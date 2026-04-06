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


def get_business() -> dict:
    try:
        return _load().get("business", {})
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
