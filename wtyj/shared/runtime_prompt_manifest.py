"""Runtime prompt manifest for Nr3 Prompt Conflict Checker.

The manifest indexes real prompt builders used by the live tenant runtime.
It is exposed only through the authenticated dashboard API.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from agents.marina import marina_agent
from agents.social import dm_agent
from dashboard import escalation_summary
from shared import agent_identity, config_loader
from shared.dashboard_prompts import build_suggest_reply_system_prompt

_SECRET_KEY_RE = re.compile(
    r"(?i)(password|access[_-]?key|api[_-]?key|token|secret|webhook[_-]?secret|client[_-]?secret)"
)
_JSON_SECRET_RE = re.compile(
    r'("?(?:password|access[_-]?key|api[_-]?key|token|secret|webhook[_-]?secret|client[_-]?secret)"?\s*[:=]\s*)("[^"]*"|[^,\n\r}]+)',
    re.IGNORECASE,
)


def _sanitize(text: str) -> str:
    """Redact secrets without removing the surrounding prompt context."""
    if not text:
        return ""
    redacted_lines: list[str] = []
    for line in str(text).splitlines():
        if _SECRET_KEY_RE.search(line):
            line = _JSON_SECRET_RE.sub(r"\1[REDACTED]", line)
            if _SECRET_KEY_RE.search(line):
                prefix = line.split(":", 1)[0] if ":" in line else line.split("=", 1)[0]
                line = f"{prefix}: [REDACTED]"
        redacted_lines.append(line)
    return "\n".join(redacted_lines)


def _source(
    *,
    source_id: str,
    name: str,
    location: str,
    used_in: list[str],
    prompt_kind: str,
    text: str,
    priority: str,
    status: str = "indexed",
    partial_reason: str = "",
) -> dict[str, Any]:
    return {
        "id": source_id,
        "name": name,
        "source_location": location,
        "used_in": used_in,
        "prompt_kind": prompt_kind,
        "priority": priority,
        "status": status,
        "partial_reason": partial_reason,
        "text": _sanitize(text),
    }


def _trip_lines() -> list[str]:
    lines: list[str] = []
    for key, data in config_loader.get_services().items():
        name = data.get("display_name", key)
        price = data.get("price_pp", "")
        lines.append(f"- {name}: ${price}/person" if price else f"- {name}")
    return lines


def build_runtime_prompt_manifest() -> dict[str, Any]:
    """Return runtime prompt sources for the current tenant container."""
    business = config_loader.get_business()
    company_name = business.get("name", "the business")
    try:
        from shared import icp_overrides
        override_envelope = icp_overrides.fetch_overrides()
    except Exception:
        override_envelope = None
    agent_name = agent_identity.effective_agent_name(override_envelope)
    signature = config_loader.get_agent_signature()
    persona_block = marina_agent._build_agent_persona_block(override_envelope)

    sources: list[dict[str, Any]] = []
    sources.append(_source(
        source_id="runtime.marina.whatsapp.system",
        name="Live Marina WhatsApp system prompt",
        location="wtyj/agents/marina/marina_agent.py::_build_system_prompt(channel='whatsapp')",
        used_in=["whatsapp"],
        prompt_kind="system",
        priority="platform_safety",
        text=marina_agent._build_system_prompt({}, channel="whatsapp"),
    ))
    sources.append(_source(
        source_id="runtime.marina.email.system",
        name="Live Marina email system prompt",
        location="wtyj/agents/marina/marina_agent.py::_build_system_prompt(channel='email')",
        used_in=["email"],
        prompt_kind="system",
        priority="platform_safety",
        text=marina_agent._build_system_prompt({}, channel="email"),
    ))
    sources.append(_source(
        source_id="runtime.fallback.whatsapp",
        name="Live Marina WhatsApp fallback reply",
        location="wtyj/agents/marina/marina_agent.py::_build_contextual_fallback_reply(channel='whatsapp')",
        used_in=["whatsapp"],
        prompt_kind="fallback",
        priority="platform_safety",
        text=marina_agent._build_contextual_fallback_reply(
            thread_fields={},
            channel="whatsapp",
            signature=signature,
            svc_label="service",
            party_label="guests",
        ),
    ))
    sources.append(_source(
        source_id="runtime.fallback.email",
        name="Live Marina email fallback reply",
        location="wtyj/agents/marina/marina_agent.py::_build_contextual_fallback_reply(channel='email')",
        used_in=["email"],
        prompt_kind="fallback",
        priority="platform_safety",
        text=marina_agent._build_contextual_fallback_reply(
            thread_fields={},
            channel="email",
            signature=signature,
            svc_label="service",
            party_label="guests",
        ),
    ))
    sources.append(_source(
        source_id="runtime.dashboard.suggest_reply.system",
        name="Dashboard suggest-reply system prompt",
        location="wtyj/dashboard/api.py::suggest_reply",
        used_in=["dashboard_suggest_reply"],
        prompt_kind="system",
        priority="tone_style",
        text=build_suggest_reply_system_prompt(
            agent_name=agent_name,
            company_name=company_name,
            persona_block=persona_block,
            trip_lines=_trip_lines(),
            signature=signature,
        ),
    ))
    sources.append(_source(
        source_id="runtime.escalation_summary.system",
        name="Escalation summary system prompt",
        location="wtyj/dashboard/escalation_summary.py::_build_system_prompt",
        used_in=["escalation_summary"],
        prompt_kind="system",
        priority="tenant_hard_restrictions",
        text=escalation_summary._build_system_prompt(),
    ))
    for channel, label in (("instagram_dm", "Instagram DM"), ("facebook_dm", "Facebook DM")):
        sources.append(_source(
            source_id=f"runtime.dm_agent.{channel}.system",
            name=f"DM agent {label} system prompt",
            location=f"wtyj/agents/social/dm_agent.py::_build_dm_system_prompt(channel='{channel}')",
            used_in=[channel],
            prompt_kind="system",
            priority="channel_formatting",
            text=dm_agent._build_dm_system_prompt(channel),
        ))

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tenant": {
            "business_name": company_name,
            "agent_name": agent_name,
        },
        "sources": sources,
        "partial": False,
        "limitations": [],
    }

