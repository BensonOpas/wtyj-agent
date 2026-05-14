"""J3-N2-01: read-only client for Nr 3's ICP override bridge.

Calls Nr 3's GET /internal/tenants/{tenant_id}/overrides (J3-BE-17)
and returns the effective_state envelope: {feature_toggles,
display_metadata}. Read-only, never raises, fails gracefully when the
bridge is unavailable so Nr 2 keeps working even when Nr 3 is down.

Tenant identity for the bridge call comes from one of:
  1. TENANT_ID env var (explicit override; tests use this)
  2. business.slug from client.json (the canonical Nr 2 tenant id)

The bridge token (NR3_INTERNAL_API_TOKEN) is read from the Nr 2
PROCESS environment - it must NEVER reach the React frontend. The
endpoint exposed by this module (/api/icp-overrides in dashboard/api.py)
returns ONLY the resolved envelope, never the token.

Caching: results are cached in-process for ICP_OVERRIDES_TTL_SECONDS
(default 60s). Repeated calls within the window return the cached
envelope without a network round-trip.

Failure modes (all return empty {} and log a warning, never raise):
- env vars unset / blank
- network timeout / connection refused
- 401 / 403 / 404 / 5xx
- non-JSON response body
- response shape unexpected
"""
import json
import logging
import os
import time
from typing import Optional

import requests

from shared.config_loader import get_business


_log = logging.getLogger(__name__)


# How long an envelope stays cached before re-fetching. Set short by
# default - operators expect override flips to land within a minute.
ICP_OVERRIDES_TTL_SECONDS = int(os.environ.get("ICP_OVERRIDES_TTL_SECONDS", "60"))

# Outbound HTTP timeout. Short so a slow/dead Nr 3 doesn't stall Nr 2
# request handling.
_HTTP_TIMEOUT_SECONDS = 3.0


# Module-level cache: (tenant_id) -> (fetched_at_unix, envelope_dict)
_cache: dict = {}


def _resolve_tenant_id() -> Optional[str]:
    """Returns the tenant identity to send in X-Tenant-Identity / the
    path. Tries TENANT_ID env var first, then business.slug from
    client.json. Returns None if neither is set."""
    explicit = os.environ.get("TENANT_ID", "").strip()
    if explicit:
        return explicit
    business = get_business()
    slug = business.get("slug") if isinstance(business, dict) else None
    if isinstance(slug, str) and slug.strip():
        return slug.strip()
    return None


def _empty_envelope(tenant_id: Optional[str], reason: str) -> dict:
    """Returned when the bridge is unreachable for any reason. The
    'available': False flag lets callers (the /api/icp-overrides
    endpoint, React UI) tell the difference between 'bridge is fine
    and the tenant has no overrides' and 'bridge is unreachable'."""
    return {
        "available": False,
        "reason": reason,
        "tenant_id": tenant_id,
        "feature_toggles": {},
        "display_metadata": {},
    }


def _cache_get(tenant_id: str) -> Optional[dict]:
    entry = _cache.get(tenant_id)
    if entry is None:
        return None
    fetched_at, envelope = entry
    if time.time() - fetched_at > ICP_OVERRIDES_TTL_SECONDS:
        return None
    return envelope


def _cache_put(tenant_id: str, envelope: dict) -> None:
    _cache[tenant_id] = (time.time(), envelope)


def clear_cache() -> None:
    """Test hook. Drops the entire in-process cache."""
    _cache.clear()


def fetch_overrides() -> dict:
    """Single entry point for Nr 2 callers.

    Returns one of:
    - {"available": True, "tenant_id": "...", "feature_toggles": {...},
       "display_metadata": {...}}  on a successful bridge read
    - {"available": False, "reason": "...", "tenant_id": "...",
       "feature_toggles": {}, "display_metadata": {}}  on any failure

    NEVER raises. NEVER sends a cross-tenant request (the tenant_id is
    always resolved locally - the caller cannot influence which tenant
    is queried). NEVER includes the token in the returned dict.
    """
    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return _empty_envelope(tenant_id, "no tenant identity configured")

    # Cache check
    cached = _cache_get(tenant_id)
    if cached is not None:
        return cached

    base_url = os.environ.get("NR3_INTERNAL_OVERRIDES_URL", "").strip()
    token = os.environ.get("NR3_INTERNAL_API_TOKEN", "").strip()
    if not base_url:
        env = _empty_envelope(tenant_id, "NR3_INTERNAL_OVERRIDES_URL unset")
        _cache_put(tenant_id, env)
        return env
    if not token:
        env = _empty_envelope(tenant_id, "NR3_INTERNAL_API_TOKEN unset")
        _cache_put(tenant_id, env)
        return env

    # Compose URL. base_url may or may not end with a slash; rstrip then
    # append the canonical path. Tenant identity is sent in BOTH the path
    # AND the X-Tenant-Identity header (the bridge enforces equality).
    url = base_url.rstrip("/") + "/internal/tenants/" + tenant_id + "/overrides"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Identity": tenant_id,
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=_HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        _log.warning("icp_overrides bridge unreachable: %s",
                      type(exc).__name__)
        env = _empty_envelope(tenant_id, "bridge unreachable")
        _cache_put(tenant_id, env)
        return env

    if resp.status_code == 401:
        _log.warning("icp_overrides bridge returned 401 - check token")
        env = _empty_envelope(tenant_id, "401 unauthorized")
        _cache_put(tenant_id, env)
        return env
    if resp.status_code == 403:
        _log.warning("icp_overrides bridge returned 403 - identity mismatch")
        env = _empty_envelope(tenant_id, "403 identity mismatch")
        _cache_put(tenant_id, env)
        return env
    if resp.status_code == 404:
        _log.warning("icp_overrides bridge returned 404 - tenant unknown")
        env = _empty_envelope(tenant_id, "404 tenant unknown")
        _cache_put(tenant_id, env)
        return env
    if resp.status_code != 200:
        _log.warning("icp_overrides bridge returned unexpected status %d",
                      resp.status_code)
        env = _empty_envelope(tenant_id, f"unexpected status {resp.status_code}")
        _cache_put(tenant_id, env)
        return env

    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        _log.warning("icp_overrides bridge returned non-JSON body")
        env = _empty_envelope(tenant_id, "non-json body")
        _cache_put(tenant_id, env)
        return env

    # Sanity-check shape. The bridge returns {tenant_id, feature_toggles,
    # display_metadata}. If anything is missing or has the wrong type,
    # fall back to empty rather than propagating bad data into Nr 2.
    if not isinstance(body, dict):
        env = _empty_envelope(tenant_id, "body not a dict")
        _cache_put(tenant_id, env)
        return env
    body_tenant = body.get("tenant_id")
    if body_tenant != tenant_id:
        # Bridge MUST echo our tenant_id back. If not, treat as
        # corrupted/cross-tenant and refuse.
        _log.warning(
            "icp_overrides bridge tenant mismatch: requested %r, got %r",
            tenant_id, body_tenant)
        env = _empty_envelope(tenant_id, "tenant_id mismatch in body")
        _cache_put(tenant_id, env)
        return env
    feature_toggles = body.get("feature_toggles")
    display_metadata = body.get("display_metadata")
    if not isinstance(feature_toggles, dict):
        feature_toggles = {}
    if not isinstance(display_metadata, dict):
        display_metadata = {}

    envelope = {
        "available": True,
        "tenant_id": tenant_id,
        "feature_toggles": feature_toggles,
        "display_metadata": display_metadata,
    }
    _cache_put(tenant_id, envelope)
    return envelope
