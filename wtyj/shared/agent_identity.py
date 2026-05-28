"""Canonical tenant AI agent identity helpers.

The dashboard, Marina prompt builders, and ICP bridge all need the same
effective customer-facing agent name. Keep the precedence and validation here
so UI labels do not drift from the live reply path.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from shared import config_loader


DEFAULT_AGENT_NAME = "Marina"
MAX_AGENT_NAME_LENGTH = 40

_URL_RE = re.compile(r"(https?://|www\.|[a-z0-9-]+\.[a-z]{2,})", re.IGNORECASE)
_BANNED_PHRASES = (
    "human support",
    "doctor",
    "dr.",
    "dr ",
    "lawyer",
    "attorney",
    "advocate",
    "therapist",
    "psychologist",
    "psychiatrist",
    "official meta support",
    "meta support",
    "facebook support",
    "whatsapp support",
    "openai",
    "anthropic",
    "claude",
    "system",
    "admin",
    "root",
)


def clean_agent_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def validate_agent_name(value: Any) -> tuple[bool, str, str]:
    """Return (ok, cleaned_value, error_message)."""
    name = clean_agent_name(value)
    if not name:
        return False, "", "AI Agent name is required."
    if len(name) > MAX_AGENT_NAME_LENGTH:
        return False, name, "AI Agent name must be 40 characters or less."
    if _URL_RE.search(name):
        return False, name, "AI Agent name cannot contain a URL or domain."
    lowered = name.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lowered:
            return False, name, "That name could mislead customers or imply a protected role."
    for char in name:
        category = unicodedata.category(char)
        if category.startswith("S"):
            return False, name, "AI Agent name cannot contain emojis or symbols."
        if category.startswith("C"):
            return False, name, "AI Agent name contains an invalid character."
        if not (char.isalpha() or char.isspace() or char in ".-'"):
            return False, name, "Use letters, spaces, apostrophes, hyphens, or periods only."
    return True, name, ""


def _admin_override_from_envelope(envelope: dict | None) -> dict | None:
    if not isinstance(envelope, dict):
        return None
    settings = envelope.get("ai_agent_settings")
    if not isinstance(settings, dict):
        return None
    raw = settings.get("agent_identity") or settings.get("agent_name")
    if not isinstance(raw, dict):
        return None
    value = clean_agent_name(raw.get("name"))
    if not value:
        return None
    return {
        "name": value,
        "source": raw.get("source") or "icp_override",
        "updated_at": raw.get("updated_at"),
        "updated_by": raw.get("updated_by"),
    }


def get_agent_identity(envelope: dict | None = None) -> dict[str, Any]:
    """Resolve default, tenant, admin override, and effective agent name."""
    business = config_loader.get_business() or {}
    tenant_name = clean_agent_name(business.get("agent_name"))
    admin = _admin_override_from_envelope(envelope)
    if admin:
        effective = admin["name"]
        source = "admin_override"
    elif tenant_name:
        effective = tenant_name
        source = "tenant"
    else:
        effective = DEFAULT_AGENT_NAME
        source = "default"
    return {
        "defaultName": DEFAULT_AGENT_NAME,
        "tenantName": tenant_name or None,
        "adminOverrideName": admin["name"] if admin else None,
        "effectiveName": effective,
        "source": source,
        "adminOverride": admin,
    }


def effective_agent_name(envelope: dict | None = None) -> str:
    return get_agent_identity(envelope)["effectiveName"]

