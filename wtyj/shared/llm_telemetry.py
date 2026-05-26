"""LLM provider usage and failure telemetry."""

from __future__ import annotations

import time
import os
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


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


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
        _evaluate_usage_alerts(state_registry, event)
    except Exception as exc:
        bm_logger.log("api_usage_record_failed", error=str(exc)[:200], tenant=tenant)
    bm_logger.log("api_usage_health", **event)
    if category in {"billing_quota", "auth", "rate_limit"} or fallback_used:
        bm_logger.log("api_provider_alert", **event)


def _record_alert(state_registry: Any, event: dict, *, severity: str, category: str, message: str, details: dict) -> None:
    alert = {
        "alert_key": f"{event.get('tenant_id')}:{event.get('provider')}:{category}",
        "tenant_id": event.get("tenant_id"),
        "provider": event.get("provider"),
        "severity": severity,
        "category": category,
        "message": message,
        "details": details,
    }
    state_registry.record_api_usage_alert(alert)
    bm_logger.log("api_provider_alert", **alert)


def _evaluate_usage_alerts(state_registry: Any, event: dict) -> None:
    """Evaluate internal provider health thresholds after a usage event.

    Anthropic does not expose a simple reliable prepaid balance endpoint in
    this runtime path, so production protection is based on provider errors
    plus tenant-local usage and cost telemetry.
    """
    tenant = event.get("tenant_id") or "unknown"
    provider = event.get("provider") or "unknown"
    category = event.get("error_category") or ""
    if category in {"billing_quota", "auth"}:
        _record_alert(
            state_registry,
            event,
            severity="critical",
            category=category,
            message="Provider returned a billing, quota, or authentication error.",
            details={"last_error": event.get("error_message", "")},
        )
    elif category == "rate_limit":
        _record_alert(
            state_registry,
            event,
            severity="warning",
            category="rate_limit",
            message="Provider rate limit was hit.",
            details={"last_error": event.get("error_message", "")},
        )

    today = state_registry.api_usage_summary(1, tenant_id=tenant, provider=provider)
    seven = state_registry.api_usage_summary(7, tenant_id=tenant, provider=provider)
    thirty = state_registry.api_usage_summary(30, tenant_id=tenant, provider=provider)
    calls = max(int(today.get("calls") or 0), 1)
    failure_rate = (int(today.get("errors") or 0) + int(today.get("fallbacks") or 0)) / calls
    failure_threshold = _float_env("API_USAGE_FAILURE_RATE_ALERT", 0.2)
    if today.get("calls") and failure_rate >= failure_threshold:
        _record_alert(
            state_registry,
            event,
            severity="critical" if failure_rate >= 0.5 else "warning",
            category="failure_rate",
            message="Provider failure or fallback rate crossed threshold.",
            details={"today_calls": today.get("calls"), "failure_rate": round(failure_rate, 3), "threshold": failure_threshold},
        )

    fallback_limit = _int_env("API_USAGE_TENANT_FALLBACK_ALERT", 3)
    if int(today.get("fallbacks") or 0) >= fallback_limit:
        _record_alert(
            state_registry,
            event,
            severity="warning",
            category="tenant_fallbacks",
            message="Tenant fallback replies crossed threshold.",
            details={"tenant": tenant, "fallbacks_today": today.get("fallbacks"), "threshold": fallback_limit},
        )

    projected_monthly = float(today.get("estimated_cost") or 0.0) * 30
    spend_limit = _float_env("API_USAGE_MONTHLY_SPEND_ALERT", 100.0)
    if projected_monthly >= spend_limit:
        _record_alert(
            state_registry,
            event,
            severity="warning",
            category="projected_spend",
            message="Projected monthly provider spend crossed threshold.",
            details={"projected_monthly_spend": round(projected_monthly, 4), "threshold": spend_limit},
        )

    min_spike_calls = _int_env("API_USAGE_SPIKE_MIN_CALLS", 20)
    spike_multiplier = _float_env("API_USAGE_SPIKE_MULTIPLIER", 3.0)
    seven_avg = max(float(seven.get("calls") or 0) / 7.0, 1.0)
    if int(today.get("calls") or 0) >= min_spike_calls and float(today.get("calls") or 0) >= seven_avg * spike_multiplier:
        _record_alert(
            state_registry,
            event,
            severity="warning",
            category="tenant_usage_spike",
            message="Tenant API usage is unusually high compared with the recent average.",
            details={"provider": provider, "today_calls": today.get("calls"), "seven_day_daily_average": round(seven_avg, 2)},
        )

    if thirty.get("active_alerts"):
        bm_logger.log("api_usage_alerts_active", tenant=tenant, active_alerts=len(thirty.get("active_alerts") or []))


def should_alert_missing_language() -> bool:
    try:
        return not tenant_context.canonical_business().get("primary_language")
    except Exception:
        return True
