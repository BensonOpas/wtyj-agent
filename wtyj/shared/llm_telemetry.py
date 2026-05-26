"""LLM provider usage and failure telemetry."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from shared import bm_logger, config_loader
from shared import tenant_context


_DEFAULT_COSTS = {
    "claude-sonnet-4-6": (0.000003, 0.000015),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_error(exc: Exception | str) -> tuple[str, str]:
    text = str(exc or "")[:500]
    lower = text.lower()
    if any(marker in lower for marker in ("credit", "billing", "quota", "insufficient", "balance")):
        return "billing_quota", text
    if "rate" in lower and "limit" in lower:
        return "rate_limit", text
    if any(marker in lower for marker in ("timeout", "timed out")):
        return "timeout", text
    if any(marker in lower for marker in ("401", "403", "auth", "api key")):
        return "auth", text
    return "provider_error", text


def estimate_cost(model: str, input_tokens: int = 0, output_tokens: int = 0) -> float:
    input_rate, output_rate = _DEFAULT_COSTS.get(model, (0.0, 0.0))
    return round((input_tokens or 0) * input_rate + (output_tokens or 0) * output_rate, 6)


def usage_from_response(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    return input_tokens, output_tokens, input_tokens + output_tokens


def log_llm_event(
    *,
    provider: str,
    model: str,
    feature_path: str,
    channel: str,
    started_at: float,
    success: bool,
    response: Any = None,
    error: Exception | str | None = None,
    fallback_used: bool = False,
    tenant_id: str | None = None,
) -> None:
    input_tokens, output_tokens, total_tokens = usage_from_response(response)
    category = ""
    message = ""
    if error:
        category, message = classify_error(error)
    latency_ms = int((time.monotonic() - started_at) * 1000)
    cost = estimate_cost(model, input_tokens, output_tokens)
    tenant = tenant_id or tenant_context.tenant_slug()
    event = {
        "tenant_id": tenant,
        "client_slug": tenant,
        "provider": provider,
        "model": model,
        "feature_path": feature_path,
        "channel": channel,
        "timestamp": utc_now(),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": cost,
        "latency_ms": latency_ms,
        "success": bool(success),
        "error_category": category,
        "error_message": message[:300],
        "fallback_used": bool(fallback_used),
    }
    try:
        from shared import state_registry
        state_registry.record_api_usage_event(event)
    except Exception as exc:
        bm_logger.log("api_usage_record_failed", error=str(exc)[:200], tenant=tenant)
    bm_logger.log("api_usage_health", **event)
    if category in {"billing_quota", "auth", "rate_limit"} or fallback_used:
        bm_logger.log("api_provider_alert", **event)


def should_alert_missing_language() -> bool:
    try:
        return not tenant_context.canonical_business().get("primary_language")
    except Exception:
        return True
