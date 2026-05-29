"""Tenant AI agent display-name helpers.

The customer-facing assistant name is tenant configuration, not model or
provider identity. Runtime prompts use the effective value here so Nr2 tenant
settings and Nr3 admin overrides cannot drift.
"""

from __future__ import annotations

import re
from typing import Any

from shared import config_loader


DEFAULT_AGENT_NAME = "Marina"

_URL_RE = re.compile(r"https?://|www\.|[a-z0-9-]+\.[a-z]{2,}", re.I)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]"
)
_UNSAFE_TERMS = (
    "claude",
    "anthropic",
    "openai",
    "chatgpt",
    "human support",
    "doctor",
    "dr.",
    "dr ",
    "lawyer",
    "attorney",
    "therapist",
    "psychologist",
    "official meta support",
    "meta support",
    "system",
    "admin",
)


def clean_agent_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def validate_agent_name(value: Any) -> str:
    name = clean_agent_name(value)
    if not name:
        raise ValueError("AI Agent name is required.")
    if len(name) > 40:
        raise ValueError("AI Agent name must be 40 characters or fewer.")
    if _URL_RE.search(name):
        raise ValueError("AI Agent name cannot contain a URL.")
    if _EMOJI_RE.search(name):
        raise ValueError("AI Agent name cannot contain emojis.")
    lowered = name.lower()
    if any(term in lowered for term in _UNSAFE_TERMS):
        raise ValueError("Choose a name that does not imply a human role or professional license.")
    return name


def local_agent_name() -> str:
    business = config_loader.get_business() or {}
    raw = config_loader.get_raw() or {}
    return clean_agent_name(business.get("agent_name") or raw.get("agent_name")) or DEFAULT_AGENT_NAME


def override_agent_name(envelope: dict | None) -> str:
    if not isinstance(envelope, dict):
        return ""
    ai = envelope.get("ai_agent_settings")
    if not isinstance(ai, dict):
        return ""
    override = ai.get("agent_name")
    if isinstance(override, dict):
        return clean_agent_name(override.get("name"))
    return ""


def effective_agent_name(envelope: dict | None = None) -> str:
    override = override_agent_name(envelope)
    if override:
        return override
    return local_agent_name()


def agent_name_config(envelope: dict | None = None) -> dict[str, Any]:
    tenant_value = local_agent_name()
    override = ""
    override_meta: dict[str, Any] | None = None
    if isinstance(envelope, dict):
        ai = envelope.get("ai_agent_settings")
        if isinstance(ai, dict) and isinstance(ai.get("agent_name"), dict):
            override_meta = dict(ai["agent_name"])
            override = clean_agent_name(override_meta.get("name"))
    effective = override or tenant_value or DEFAULT_AGENT_NAME
    return {
        "defaultName": DEFAULT_AGENT_NAME,
        "tenantValue": tenant_value,
        "adminOverride": override or None,
        "effectiveName": effective,
        "source": "admin_override" if override else ("tenant" if tenant_value != DEFAULT_AGENT_NAME else "default"),
        "overrideMeta": override_meta,
    }
