# bluemarlin/shared/config_loader.py
# Last modified: Brief 134
# Purpose: Read-only client.json interface. Caches on first read. Never raises.

import json
import os

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


def _load() -> dict:
    global _cache
    if _cache:
        return _cache
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    except Exception:
        _cache = {}
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

import tempfile as _tempfile

_YOUR_INFO_WHITELIST = (
    "name", "email", "support_email", "phone", "whatsapp",
    "website", "location", "languages", "operating_days", "agent_name",
)


def update_business_field(key: str, value) -> bool:
    """Brief 216: write a single business.<key> value through to
    client.json on disk, atomically (tempfile + rename) so a crash
    mid-write can't leave the file truncated. Invalidates the module
    cache so subsequent reads see the new value. Whitelist enforced
    here AND at the endpoint layer (defense in depth — Pydantic strips
    unknown fields but the helper is also callable from internal code).
    Returns True on success, False on whitelist miss or disk error."""
    global _cache
    if key not in _YOUR_INFO_WHITELIST:
        return False
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            current = json.load(f)
    except Exception:
        return False
    biz = dict(current.get("business", {}) or {})
    biz[key] = value
    current["business"] = biz
    tmp_path = None
    try:
        dir_path = os.path.dirname(_CONFIG_PATH) or "."
        with _tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=dir_path, prefix=".client.", suffix=".tmp",
        ) as tf:
            json.dump(current, tf, indent=2, ensure_ascii=False)
            tmp_path = tf.name
        os.replace(tmp_path, _CONFIG_PATH)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False
    _cache = {}
    return True


def update_response_timing(value: dict) -> bool:
    """Persist tenant response timing under top-level response_timing."""
    global _cache
    if not isinstance(value, dict):
        return False
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            current = json.load(f)
    except Exception:
        return False
    current["response_timing"] = dict(value)
    tmp_path = None
    try:
        dir_path = os.path.dirname(_CONFIG_PATH) or "."
        with _tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=dir_path, prefix=".client.", suffix=".tmp",
        ) as tf:
            json.dump(current, tf, indent=2, ensure_ascii=False)
            tmp_path = tf.name
        os.replace(tmp_path, _CONFIG_PATH)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False
    _cache = {}
    return True


def your_info_whitelist() -> tuple:
    """Brief 216: expose the whitelist so the GET endpoint returns only
    the editable fields and the PUT endpoint validates inputs."""
    return _YOUR_INFO_WHITELIST
