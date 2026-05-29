"""Tenant response timing / message batching settings.

The runtime already batches rapid WhatsApp messages. This module makes the
timing tenant-configurable while keeping a conservative default for all
tenants.
"""

from __future__ import annotations

import random
from typing import Any

from shared import config_loader


DEFAULT_PRESET = "balanced"
DEFAULT_DELAY_SECONDS = 12.0
DEFAULT_MAX_WAIT_SECONDS = 25.0
DEFAULT_MODE = "preset"
DEFAULT_CUSTOM_DELAY_SECONDS = 12.0
DEFAULT_RANDOM_MIN_SECONDS = 5.0
DEFAULT_RANDOM_MAX_SECONDS = 25.0

PRESET_DELAYS = {
    "fast": 5.0,
    "balanced": 12.0,
    "patient": 15.0,
}

MIN_DELAY_SECONDS = 5.0
MAX_DELAY_SECONDS = 300.0
MIN_MAX_WAIT_SECONDS = 5.0
MAX_MAX_WAIT_SECONDS = 300.0


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_preset(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in PRESET_DELAYS:
        return value.strip().lower()
    return DEFAULT_PRESET


def _clean_mode(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in {"preset", "custom", "random"}:
        return value.strip().lower()
    return DEFAULT_MODE


def _clamp_seconds(value: Any, default: float) -> float:
    seconds = _as_float(value, default)
    return max(MIN_DELAY_SECONDS, min(MAX_DELAY_SECONDS, seconds))


def normalize_response_timing(raw: Any | None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    mode = _clean_mode(data.get("mode"))
    preset = _clean_preset(data.get("preset"))
    delay_default = PRESET_DELAYS[preset]
    custom_delay = _clamp_seconds(
        data.get("custom_delay_seconds", data.get("delay_seconds")),
        DEFAULT_CUSTOM_DELAY_SECONDS,
    )
    random_min = _clamp_seconds(data.get("random_min_seconds"), DEFAULT_RANDOM_MIN_SECONDS)
    random_max = _clamp_seconds(data.get("random_max_seconds"), DEFAULT_RANDOM_MAX_SECONDS)
    if random_min > random_max:
        random_min, random_max = random_max, random_min

    if mode == "custom":
        delay = custom_delay
        max_wait_default = custom_delay
    elif mode == "random":
        delay = random_min
        max_wait_default = random_max
    else:
        delay = delay_default
        max_wait_default = DEFAULT_MAX_WAIT_SECONDS

    max_wait = _as_float(data.get("max_wait_seconds"), max_wait_default)
    max_wait = max(max(delay, MIN_MAX_WAIT_SECONDS), min(MAX_MAX_WAIT_SECONDS, max_wait))
    return {
        "message_batching_enabled": _as_bool(
            data.get("message_batching_enabled"),
            True,
        ),
        "mode": mode,
        "preset": preset,
        "delay_seconds": delay,
        "max_wait_seconds": max_wait,
        "custom_delay_seconds": custom_delay,
        "random_min_seconds": random_min,
        "random_max_seconds": random_max,
    }


def local_response_timing() -> dict[str, Any]:
    raw = config_loader.get_raw() or {}
    return normalize_response_timing(raw.get("response_timing"))


def override_response_timing(envelope: dict | None) -> dict[str, Any] | None:
    if not isinstance(envelope, dict):
        return None
    override = envelope.get("response_timing")
    if not isinstance(override, dict):
        return None
    settings = override.get("settings") if isinstance(override.get("settings"), dict) else override
    normalized = normalize_response_timing(settings)
    return {
        **normalized,
        "source": override.get("source") or "admin_override",
        "updated_at": override.get("updated_at"),
        "updated_by": override.get("updated_by"),
    }


def effective_response_timing(envelope: dict | None = None) -> dict[str, Any]:
    override = override_response_timing(envelope)
    local = local_response_timing()
    effective = override or {**local, "source": "tenant"}
    if not effective.get("message_batching_enabled", True):
        return {
            **effective,
            "delay_seconds": 0.1,
            "max_wait_seconds": 0.1,
        }
    return effective


def runtime_response_timing(effective: dict[str, Any]) -> dict[str, Any]:
    """Resolve the actual timing used for one pending batch.

    Random mode samples once per batch. The sampled value is copied to both the
    debounce delay and hard cap so one random response wait is used for that
    burst.
    """
    timing = normalize_response_timing(effective)
    timing["source"] = effective.get("source")
    if not timing.get("message_batching_enabled", True):
        return {
            **timing,
            "delay_seconds": 0.1,
            "max_wait_seconds": 0.1,
        }
    if timing.get("mode") == "random":
        picked = round(
            random.uniform(
                float(timing["random_min_seconds"]),
                float(timing["random_max_seconds"]),
            ),
            1,
        )
        return {
            **timing,
            "delay_seconds": picked,
            "max_wait_seconds": picked,
            "random_picked_seconds": picked,
        }
    if timing.get("mode") == "custom":
        custom = float(timing["custom_delay_seconds"])
        return {
            **timing,
            "delay_seconds": custom,
            "max_wait_seconds": custom,
        }
    return timing


def response_timing_config(envelope: dict | None = None) -> dict[str, Any]:
    local = local_response_timing()
    override = override_response_timing(envelope)
    effective = effective_response_timing(envelope)
    return {
        "default": normalize_response_timing(None),
        "tenantValue": local,
        "adminOverride": override,
        "effective": effective,
        "source": "admin_override" if override else "tenant",
        "presets": [
            {"key": "fast", "label": "Fast", "delay_seconds": PRESET_DELAYS["fast"]},
            {"key": "balanced", "label": "Balanced", "delay_seconds": PRESET_DELAYS["balanced"]},
            {"key": "patient", "label": "Patient", "delay_seconds": PRESET_DELAYS["patient"]},
        ],
    }
