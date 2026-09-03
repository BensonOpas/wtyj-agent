# wtyj/shared/tenant_guard.py
# Brief 200 — Tenant isolation: account_id allowlist guard.
#
# Two call sites:
#   - inbound: webhook_server._process_zernio_event() right after parse_zernio_webhook
#   - outbound: senders.zernio.ZernioSender.send() right before send_dm_reply
#
# Both call sites pass the account_id parsed/being-targeted and ask whether
# the current tenant is allowed to handle it. Decision is driven by
# client.json's top-level "channel_account_allowlist" block.

import os

from shared import config_loader
from shared import bm_logger


def _get_allowlist_config() -> dict:
    """Return a validated allowlist or a fail-closed invalid sentinel.

    Legacy tenants may still opt out by omitting the block. Deployments that
    set ``TENANT_ACCOUNT_ALLOWLIST_REQUIRED=true`` must present the matching
    tenant config and a valid strict list, including during cold start.
    """
    required = os.environ.get(
        "TENANT_ACCOUNT_ALLOWLIST_REQUIRED", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    raw = config_loader.get_raw()
    expected_tenant = (
        os.environ.get("TENANT_ID", "")
        or os.environ.get("TENANT_SLUG", "")
    ).strip().lower()

    def invalid(reason: str) -> dict:
        bm_logger.log(
            "tenant_guard_config_invalid",
            reason=reason,
            strict_required=required,
        )
        return {"mode": "strict", "zernio_accounts": [], "_invalid": True}

    if not isinstance(raw, dict) or not raw:
        return invalid("config_unavailable") if required else {}
    if required:
        top_level_slug = str(raw.get("slug") or "").strip().lower()
        business = raw.get("business")
        business_slug = (
            str(business.get("slug") or "").strip().lower()
            if isinstance(business, dict)
            else ""
        )
        if top_level_slug and business_slug and top_level_slug != business_slug:
            return invalid("tenant_identity_conflict")
        actual_tenant = top_level_slug or business_slug
        if not expected_tenant or actual_tenant != expected_tenant:
            return invalid("tenant_identity_mismatch")

    if "channel_account_allowlist" not in raw:
        return invalid("allowlist_missing") if required else {}
    cfg = raw.get("channel_account_allowlist")
    if not isinstance(cfg, dict):
        return invalid("allowlist_not_object")
    mode = cfg.get("mode")
    accounts = cfg.get("zernio_accounts")
    if mode not in {"strict", "permissive"}:
        return invalid("allowlist_mode_invalid")
    if required and mode != "strict":
        return invalid("strict_mode_required")
    if not isinstance(accounts, list) or any(
        not isinstance(value, str) or not value.strip() for value in accounts
    ):
        return invalid("allowlist_accounts_invalid")
    return {
        "mode": mode,
        "zernio_accounts": [value.strip() for value in accounts],
    }


def account_access_state(account_id: str, direction: str) -> bool | None:
    """Return the authoritative account decision, or ``None`` if unavailable.

    Webhook endpoints need to distinguish a known foreign account (which should
    be acknowledged and ignored) from a strict tenant whose mounted identity or
    allowlist cannot currently be read (which must remain retryable).  Ordinary
    callers should continue to use :func:`is_account_allowed` for a fail-closed
    boolean decision.

    direction: "inbound" or "outbound" — used in the log entry only.

    Returns ``True`` when the event/send should proceed, ``False`` for a known
    strict-mode mismatch, and ``None`` when strict configuration is invalid or
    unavailable. Modes:
      - block absent: legacy behaviour unless the deployment requires strict
        enforcement
      - mode "permissive": logs WARN on unknown account_id but returns True
      - mode "strict": logs BLOCK on unknown account_id and returns False
    """
    cfg = _get_allowlist_config()
    if not cfg:
        return True
    if cfg.get("_invalid") is True:
        return None
    mode = cfg.get("mode", "strict")
    allowed = set(cfg.get("zernio_accounts", []))
    if account_id and account_id in allowed:
        return True
    bm_logger.log(
        "tenant_guard_account_unknown",
        direction=direction,
        account_id=(account_id[:24] if account_id else ""),
        mode=mode,
        allowlist_size=len(allowed),
    )
    if mode == "strict":
        return False
    return True


def is_account_allowed(account_id: str, direction: str) -> bool:
    """Return a fail-closed boolean account-ownership decision."""
    return account_access_state(account_id, direction) is True
