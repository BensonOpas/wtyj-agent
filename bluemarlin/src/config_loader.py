# FILE: config_loader.py
# CREATED: Brief 022
# LAST MODIFIED: Brief 022
# DEPENDS ON: bluemarlin/config/client.json
# IMPORTS FROM: nothing (stdlib only)

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "client.json")
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


def get_trips() -> dict:
    try:
        return _load().get("trips", {})
    except Exception:
        return {}


def get_trip(trip_key: str) -> dict:
    try:
        return _load().get("trips", {}).get(trip_key, {})
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


def get_trip_aliases() -> dict:
    try:
        return _load().get("trip_aliases", {})
    except Exception:
        return {}


def get_fleet() -> dict:
    try:
        return _load().get("fleet", {})
    except Exception:
        return {}


def get_agent_signature() -> str:
    try:
        return _load().get("business", {}).get("agent_signature", "Marina\nBlueFinn Charters Curaçao")
    except Exception:
        return "Marina\nBlueFinn Charters Curaçao"


def get_common_sense_knowledge() -> dict:
    try:
        return _load().get("common_sense_knowledge", {})
    except Exception:
        return {}
