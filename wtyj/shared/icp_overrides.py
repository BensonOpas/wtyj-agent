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
    endpoint, React UI, marina_agent) tell the difference between
    'bridge is fine and the tenant has no overrides' and 'bridge is
    unreachable'.

    J3-N2-02: sot_entries + ai_agent_settings keys ALWAYS present
    (default empty / None) so prompt-builders can use d['sot_entries']
    directly without KeyError-guarding."""
    return {
        "available": False,
        "reason": reason,
        "tenant_id": tenant_id,
        "feature_toggles": {},
        "channel_connections": {},
        "display_metadata": {},
        "sot_entries": [],
        "ai_agent_settings": {"tone": None, "escalation_rules": None, "agent_name": None},
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
    """Test hook. Drops the entire in-process cache. J3-N2-04: also
    resets the observability state so a --fresh CLI run shows clean
    counters."""
    _cache.clear()
    _reset_observability()


# J3-N2-04: in-process observability state. Module-level dict captured
# at the end of every fetch_overrides() call. Visible to any code path
# running in the SAME process (the agent's process). A separate CLI
# invocation via `docker exec python3 ...` is its OWN process with its
# own _observability dict - the CLI's view is honest about per-process
# scope; the HTTP /icp-overrides-debug endpoint (running in the agent's
# process) shows the agent's live state.
_observability: dict = {
    "last_fetch_at": None,
    "last_fetch_duration_ms": None,
    "last_outcome": None,
    "last_tenant_id": None,
    "last_bridge_available": None,
    "last_sot_count": None,
    "last_tone_source": None,
    "last_escalation_source": None,
    "total_fetches": 0,
    "total_failures": 0,
    "total_cache_hits": 0,
}


def get_observability_state() -> dict:
    """J3-N2-04: snapshot of in-process fetch state. Returns a COPY so
    callers cannot mutate the module dict accidentally."""
    return dict(_observability)


def _reset_observability() -> None:
    """Test hook."""
    _observability.update({
        "last_fetch_at": None,
        "last_fetch_duration_ms": None,
        "last_outcome": None,
        "last_tenant_id": None,
        "last_bridge_available": None,
        "last_sot_count": None,
        "last_tone_source": None,
        "last_escalation_source": None,
        "total_fetches": 0,
        "total_failures": 0,
        "total_cache_hits": 0,
    })


def _record_observability(envelope: dict, outcome: str,
                            duration_ms: int, tenant_id, fetch_start_iso: str,
                            was_cache_hit: bool = False) -> None:
    """Update the in-process observability dict + emit one structured
    log line per call. No token, no full response body in the log."""
    _observability["last_fetch_at"] = fetch_start_iso
    _observability["last_fetch_duration_ms"] = duration_ms
    _observability["last_outcome"] = outcome
    _observability["last_tenant_id"] = tenant_id
    _observability["last_bridge_available"] = bool(envelope.get("available"))
    sot = envelope.get("sot_entries") or []
    _observability["last_sot_count"] = (
        len(sot) if isinstance(sot, list) else 0)
    ai = envelope.get("ai_agent_settings") or {}
    tone = ai.get("tone") if isinstance(ai, dict) else None
    rules = ai.get("escalation_rules") if isinstance(ai, dict) else None
    _observability["last_tone_source"] = (
        tone.get("source") if isinstance(tone, dict) else None)
    _observability["last_escalation_source"] = (
        rules.get("source") if isinstance(rules, dict) else None)
    _observability["total_fetches"] += 1
    if was_cache_hit:
        _observability["total_cache_hits"] += 1
    elif outcome != "success":
        _observability["total_failures"] += 1
    _log.info(
        "icp_overrides fetch tenant=%s outcome=%s duration_ms=%d "
        "available=%s sot_count=%s tone_source=%s escalation_source=%s "
        "cache_hit=%s",
        tenant_id or "(none)", outcome, duration_ms,
        bool(envelope.get("available")),
        _observability["last_sot_count"],
        _observability["last_tone_source"] or "(none)",
        _observability["last_escalation_source"] or "(none)",
        was_cache_hit,
    )


def fetch_overrides() -> dict:
    """Single entry point for Nr 2 callers.

    Returns one of:
    - {"available": True, "tenant_id": "...", "feature_toggles": {...},
       "display_metadata": {...}, "sot_entries": [...],
       "ai_agent_settings": {...}}  on a successful bridge read
    - {"available": False, "reason": "...", ...}  on any failure

    NEVER raises. NEVER sends a cross-tenant request. NEVER includes
    the token in the returned dict.

    J3-N2-04: every call updates module-level _observability state and
    emits one structured log line. See get_observability_state()."""
    import datetime as _dt
    fetch_start = time.time()
    fetch_start_iso = (
        _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
        .isoformat(timespec="microseconds"))

    def _record(env, outcome, was_cache_hit=False):
        duration_ms = int((time.time() - fetch_start) * 1000)
        _record_observability(env, outcome, duration_ms,
                                env.get("tenant_id"), fetch_start_iso,
                                was_cache_hit=was_cache_hit)
        return env

    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return _record(
            _empty_envelope(tenant_id, "no tenant identity configured"),
            "no_tenant")

    # Cache check
    cached = _cache_get(tenant_id)
    if cached is not None:
        return _record(cached, "cache_hit", was_cache_hit=True)

    base_url = os.environ.get("NR3_INTERNAL_OVERRIDES_URL", "").strip()
    token = os.environ.get("NR3_INTERNAL_API_TOKEN", "").strip()
    if not base_url:
        env = _empty_envelope(tenant_id, "NR3_INTERNAL_OVERRIDES_URL unset")
        _cache_put(tenant_id, env)
        return _record(env, "url_unset")
    if not token:
        env = _empty_envelope(tenant_id, "NR3_INTERNAL_API_TOKEN unset")
        _cache_put(tenant_id, env)
        return _record(env, "token_unset")

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
        return _record(env, "network_error")

    if resp.status_code == 401:
        _log.warning("icp_overrides bridge returned 401 - check token")
        env = _empty_envelope(tenant_id, "401 unauthorized")
        _cache_put(tenant_id, env)
        return _record(env, "401")
    if resp.status_code == 403:
        _log.warning("icp_overrides bridge returned 403 - identity mismatch")
        env = _empty_envelope(tenant_id, "403 identity mismatch")
        _cache_put(tenant_id, env)
        return _record(env, "403")
    if resp.status_code == 404:
        _log.warning("icp_overrides bridge returned 404 - tenant unknown")
        env = _empty_envelope(tenant_id, "404 tenant unknown")
        _cache_put(tenant_id, env)
        return _record(env, "404")
    if resp.status_code != 200:
        _log.warning("icp_overrides bridge returned unexpected status %d",
                      resp.status_code)
        env = _empty_envelope(tenant_id, f"unexpected status {resp.status_code}")
        _cache_put(tenant_id, env)
        return _record(env, "unexpected_status")

    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        _log.warning("icp_overrides bridge returned non-JSON body")
        env = _empty_envelope(tenant_id, "non-json body")
        _cache_put(tenant_id, env)
        return _record(env, "non_json")

    # Sanity-check shape. The bridge returns {tenant_id, feature_toggles,
    # display_metadata}. If anything is missing or has the wrong type,
    # fall back to empty rather than propagating bad data into Nr 2.
    if not isinstance(body, dict):
        env = _empty_envelope(tenant_id, "body not a dict")
        _cache_put(tenant_id, env)
        return _record(env, "body_not_dict")
    body_tenant = body.get("tenant_id")
    if body_tenant != tenant_id:
        # Bridge MUST echo our tenant_id back. If not, treat as
        # corrupted/cross-tenant and refuse.
        _log.warning(
            "icp_overrides bridge tenant mismatch: requested %r, got %r",
            tenant_id, body_tenant)
        env = _empty_envelope(tenant_id, "tenant_id mismatch in body")
        _cache_put(tenant_id, env)
        return _record(env, "tenant_mismatch")
    feature_toggles = body.get("feature_toggles")
    channel_connections = body.get("channel_connections")
    display_metadata = body.get("display_metadata")
    sot_entries = body.get("sot_entries")
    ai_agent_settings = body.get("ai_agent_settings")
    if not isinstance(feature_toggles, dict):
        feature_toggles = {}
    if not isinstance(channel_connections, dict):
        channel_connections = {}
    if not isinstance(display_metadata, dict):
        display_metadata = {}
    # J3-N2-02: sot_entries should be a list; AI settings should be a
    # dict with tone + escalation_rules keys. Coerce defensively.
    if not isinstance(sot_entries, list):
        sot_entries = []
    if not isinstance(ai_agent_settings, dict):
        ai_agent_settings = {"tone": None, "escalation_rules": None, "agent_name": None}
    else:
        # Ensure both nested keys exist (None when not configured)
        ai_agent_settings = {
            "tone": ai_agent_settings.get("tone"),
            "escalation_rules": ai_agent_settings.get("escalation_rules"),
            "agent_name": ai_agent_settings.get("agent_name"),
        }

    envelope = {
        "available": True,
        "tenant_id": tenant_id,
        "feature_toggles": feature_toggles,
        "channel_connections": channel_connections,
        "display_metadata": display_metadata,
        "sot_entries": sot_entries,
        "ai_agent_settings": ai_agent_settings,
    }
    _cache_put(tenant_id, envelope)
    return _record(envelope, "success")
