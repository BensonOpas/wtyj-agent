# bluemarlin/shared/config_loader.py
# Last modified: Brief 134
# Purpose: Read-only client.json interface. Reloads changed files. Never raises.

import json
import os
import threading

# Brief 150 — client.json may live in different places:
# - Inside the Docker container: /app/config/client.json (mounted by docker-compose)
# - Mac dev (post-Brief-150): clients/bluemarlin/config/client.json (or clients/<name>/config/...)
# - Container default (Dockerfile COPY target): resolves to /app/shared/../config/client.json = /app/config/client.json
#
# Precedence: CLIENT_CONFIG_PATH env var (explicit) wins. Otherwise use the module-relative
# default, which works inside the container. Mac dev tests set CLIENT_CONFIG_PATH in conftest.py.
_DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "client.json")
_CONFIG_PATH = os.environ.get("CLIENT_CONFIG_PATH", _DEFAULT_CONFIG_PATH)
_cache: dict = {}
_cache_signature: tuple | None = None
_cache_lock = threading.RLock()


def _config_signature() -> tuple:
    """Return an identity that changes for edits and atomic replacements."""
    stat = os.stat(_CONFIG_PATH)
    return (
        os.path.abspath(_CONFIG_PATH),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
    )


def _invalidate_cache() -> None:
    global _cache, _cache_signature
    with _cache_lock:
        _cache = {}
        _cache_signature = None


def _required_isolation_shape_valid(loaded: dict) -> bool:
    """Validate security-critical config for strict-isolation deployments."""
    required = os.environ.get(
        "TENANT_ACCOUNT_ALLOWLIST_REQUIRED", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not required:
        return True
    expected_tenant = (
        os.environ.get("TENANT_ID", "")
        or os.environ.get("TENANT_SLUG", "")
    ).strip().lower()
    if not expected_tenant or str(loaded.get("slug") or "").strip().lower() != expected_tenant:
        return False
    allowlist = loaded.get("channel_account_allowlist")
    if not isinstance(allowlist, dict) or allowlist.get("mode") != "strict":
        return False
    accounts = allowlist.get("zernio_accounts")
    return isinstance(accounts, list) and all(
        isinstance(value, str) and bool(value.strip()) for value in accounts
    )


def _strict_isolation_required() -> bool:
    return os.environ.get(
        "TENANT_ACCOUNT_ALLOWLIST_REQUIRED", ""
    ).strip().lower() in {"1", "true", "yes", "on"}


def _failed_config_read() -> dict:
    """Return legacy last-good state, but invalidate strict tenant state."""
    global _cache, _cache_signature
    if _strict_isolation_required():
        _cache = {}
        _cache_signature = None
    return _cache


def _load() -> dict:
    """Load the latest complete client config, preserving the last good read.

    Nr 3 updates mounted ``client.json`` files with an atomic replace.  The old
    cache kept the first version for the lifetime of the process, so a newly
    persisted strict account allowlist required a container restart.  Stat the
    file on every access and reload only when its identity changes.  A
    legacy deployments retain their last complete read during a malformed
    replacement. Strict-isolation deployments instead invalidate immediately
    once a malformed or identity-mismatched document is stable, so an old
    account allowlist cannot remain authorized indefinitely.
    """
    global _cache, _cache_signature
    with _cache_lock:
        try:
            signature_before = _config_signature()
        except OSError:
            return _failed_config_read()
        if _cache and signature_before == _cache_signature:
            return _cache

        # An atomic replace can land between stat() and open().  Retry once if
        # the identity changed while reading so we never cache the superseded
        # inode as though it were current.
        for _attempt in range(2):
            try:
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                signature_after = _config_signature()
            except (OSError, ValueError, TypeError):
                # If an atomic replacement raced the read, retry its new
                # inode once. A stable malformed document is authoritative
                # failure for strict tenants and must revoke the warm cache.
                try:
                    signature_after = _config_signature()
                except OSError:
                    return _failed_config_read()
                if signature_after != signature_before and _attempt == 0:
                    signature_before = signature_after
                    continue
                return _failed_config_read()
            if not isinstance(loaded, dict):
                return _failed_config_read()
            if not _required_isolation_shape_valid(loaded):
                return _failed_config_read()
            if signature_after != signature_before:
                if _attempt == 0:
                    signature_before = signature_after
                    continue
                # Two consecutive moving inodes are a detected transient;
                # retain the last complete document and retry next access.
                return _cache
            _cache = loaded
            _cache_signature = signature_after
            return _cache
        return _cache


def _first_text(*values) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _business_with_top_level_fallbacks(raw: dict) -> dict:
    """Return business settings with fallbacks for Nr 3 minimal tenants.

    Older tenants store identity under ``business``. Nr 3's automatic
    tenant creation writes a smaller client.json with top-level fields
    such as ``name``, ``email`` and ``whatsapp``. Dashboard settings
    should show the tenant's own values in both shapes.
    """
    business = dict(raw.get("business", {}) or {})
    fallbacks = {
        "name": _first_text(
            business.get("name"),
            raw.get("business_name"),
            raw.get("name"),
            raw.get("slug"),
        ),
        "email": _first_text(business.get("email"), raw.get("email")),
        "support_email": _first_text(
            business.get("support_email"),
            raw.get("support_email"),
            raw.get("email"),
        ),
        "phone": _first_text(
            business.get("phone"),
            raw.get("phone"),
            raw.get("whatsapp"),
        ),
        "whatsapp": _first_text(business.get("whatsapp"), raw.get("whatsapp")),
        "website": _first_text(business.get("website"), raw.get("website")),
        "slug": _first_text(business.get("slug"), raw.get("slug")),
        "agent_name": _first_text(
            business.get("agent_name"),
            raw.get("agent_name"),
        ),
    }
    for key, value in fallbacks.items():
        if value and not _first_text(business.get(key)):
            business[key] = value
    return business


def get_business() -> dict:
    try:
        return _business_with_top_level_fallbacks(_load())
    except Exception:
        return {}


def get_services() -> dict:
    try:
        return _load().get("services", {})
    except Exception:
        return {}


def get_service(service_key: str) -> dict:
    try:
        return _load().get("services", {}).get(service_key, {})
    except Exception:
        return {}


def get_faq() -> dict:
    try:
        return _load().get("faq", {})
    except Exception:
        return {}


def get_faq_answer(question_key: str) -> str:
    try:
        return _load().get("faq", {}).get(question_key, "")
    except Exception:
        return ""


def get_booking_rules() -> dict:
    try:
        return _load().get("booking_rules", {})
    except Exception:
        return {}


def get_payment() -> dict:
    try:
        return _load().get("payment", {})
    except Exception:
        return {}


def get_service_aliases() -> dict:
    try:
        return _load().get("service_aliases", {})
    except Exception:
        return {}


def get_resources() -> dict:
    try:
        return _load().get("resources", {})
    except Exception:
        return {}


def get_agent_signature() -> str:
    try:
        return _load().get("business", {}).get("agent_signature", "The Team")
    except Exception:
        return "The Team"


def get_common_sense_knowledge() -> dict:
    try:
        return _load().get("common_sense_knowledge", {})
    except Exception:
        return {}


def get_raw() -> dict:
    """Return the full parsed client.json. Used for dynamic prompt injection."""
    try:
        return dict(_load())
    except Exception:
        return {}


# Brief 216: write-through edits from the dashboard's Your Info page.

import fcntl as _fcntl
import stat as _stat
import tempfile as _tempfile

_YOUR_INFO_WHITELIST = (
    "name", "email", "support_email", "phone", "whatsapp",
    "website", "location", "languages", "operating_days", "agent_name",
)


def _update_config(mutator) -> bool:
    """Serialize every client.json read/modify/replace through one sidecar lock.

    Nr3's host worker uses the same ``<client.json>.lock`` protocol. Reading
    only after acquiring the lock prevents an unrelated dashboard edit from
    restoring a stale provider allowlist.
    """
    directory = os.path.dirname(_CONFIG_PATH) or "."
    lock_path = _CONFIG_PATH + ".lock"
    lock_fd = None
    tmp_path = None
    try:
        lock_fd = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        if not _stat.S_ISREG(os.fstat(lock_fd).st_mode):
            return False
        os.fchmod(lock_fd, 0o600)
        _fcntl.flock(lock_fd, _fcntl.LOCK_EX)
        with open(_CONFIG_PATH, "r", encoding="utf-8") as stream:
            current = json.load(stream)
        if not isinstance(current, dict) or not _required_isolation_shape_valid(current):
            return False
        mutator(current)
        if not _required_isolation_shape_valid(current):
            return False
        with _tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=directory,
            prefix=".client.",
            suffix=".tmp",
        ) as stream:
            json.dump(current, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            tmp_path = stream.name
        os.replace(tmp_path, _CONFIG_PATH)
        tmp_path = None
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        if lock_fd is not None:
            try:
                _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(lock_fd)
    _invalidate_cache()
    return True


def update_business_field(key: str, value) -> bool:
    """Brief 216: write a single business.<key> value through to
    client.json on disk, atomically (tempfile + rename) so a crash
    mid-write can't leave the file truncated. Invalidates the module
    cache so subsequent reads see the new value. Whitelist enforced
    here AND at the endpoint layer (defense in depth — Pydantic strips
    unknown fields but the helper is also callable from internal code).
    Returns True on success, False on whitelist miss or disk error."""
    if key not in _YOUR_INFO_WHITELIST:
        return False
    def mutate(current: dict) -> None:
        business = dict(current.get("business", {}) or {})
        business[key] = value
        current["business"] = business

    return _update_config(mutate)


def update_response_timing(value: dict) -> bool:
    """Persist tenant response timing under top-level response_timing."""
    if not isinstance(value, dict):
        return False
    return _update_config(
        lambda current: current.__setitem__("response_timing", dict(value))
    )


def update_ali_customer_dossier_enabled(enabled: bool) -> bool:
    """Persist the Ali tenant's reversible customer-dossier feature switch.

    This intentionally exposes one exact flag rather than a generic feature
    editor. The authenticated, tenant-scoped dashboard endpoint performs the
    readiness check before calling this helper.
    """
    if not isinstance(enabled, bool):
        return False
    def mutate(current: dict) -> None:
        features = current.get("features")
        features = dict(features) if isinstance(features, dict) else {}
        features["ali_customer_dossier_enabled"] = enabled
        current["features"] = features

    return _update_config(mutate)


def get_agent_personality() -> dict:
    """Return tenant Agent Personality settings from client.json.

    The Nr2 dashboard stores this as a tenant-owned configuration block.
    Missing or malformed values intentionally normalize to an empty object so
    the Settings page can render for new tenants.
    """
    raw = _load()
    value = raw.get("agent_personality")
    return dict(value) if isinstance(value, dict) else {}


def update_agent_personality(value: dict) -> bool:
    """Persist tenant Agent Personality settings under top-level
    agent_personality."""
    if not isinstance(value, dict):
        return False
    return _update_config(
        lambda current: current.__setitem__("agent_personality", dict(value))
    )


def get_product_settings() -> dict:
    """Return tenant product/order settings from client.json."""
    raw = _load()
    value = raw.get("product_settings")
    return dict(value) if isinstance(value, dict) else {}


def update_product_settings(value: dict) -> bool:
    """Persist tenant product/order settings under top-level product_settings."""
    if not isinstance(value, dict):
        return False
    return _update_config(
        lambda current: current.__setitem__("product_settings", dict(value))
    )


def your_info_whitelist() -> tuple:
    """Brief 216: expose the whitelist so the GET endpoint returns only
    the editable fields and the PUT endpoint validates inputs."""
    return _YOUR_INFO_WHITELIST
