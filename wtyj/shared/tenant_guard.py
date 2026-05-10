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

from shared import config_loader
from shared import bm_logger


def _get_allowlist_config() -> dict:
    """Read the current tenant's allowlist block. Returns {} if absent
    (backward-compat: tenants without the block opt out of enforcement
    entirely — no checks, no logs)."""
    return config_loader.get_raw().get("channel_account_allowlist", {}) or {}


def is_account_allowed(account_id: str, direction: str) -> bool:
    """Check whether the current tenant is permitted to handle this account_id.

    direction: "inbound" or "outbound" — used in the log entry only.

    Returns True when the event/send should proceed, False when it should be
    blocked. Modes:
      - block absent: legacy behaviour, no enforcement, returns True silently
      - mode "permissive": logs WARN on unknown account_id but returns True
      - mode "strict": logs BLOCK on unknown account_id and returns False
    """
    cfg = _get_allowlist_config()
    if not cfg:
        return True
    mode = cfg.get("mode", "permissive")
    allowed = set(cfg.get("zernio_accounts", []) or [])
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
