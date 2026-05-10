# BRIEF 238 — Tenant isolation: account-id allowlist guard + BlueMarlin credential strip

**Status:** Draft | **Files:** `clients/{bluemarlin,adamus,unboks}/config/client.json` (each gets a new top-level `channel_account_allowlist` block — local repo edits), `/root/clients/consultadespertares/config/client.json` (VPS-only — Consulta Despertares is not version-controlled in this repo, patched in-place via SSH in Step 1b), `wtyj/shared/tenant_guard.py` (NEW), `wtyj/agents/social/webhook_server.py` (wire inbound check after `parse_zernio_webhook` in `_process_zernio_event`), `wtyj/agents/social/senders/zernio.py` (wire outbound check before `send_dm_reply`), `/root/clients/bluemarlin/config/platform.env` (VPS-only, strip channel credentials — script in Step 5), `wtyj/briefs/infra.md` (APPEND short note about Brief 238), `wtyj/tests/test_238_tenant_isolation.py` (NEW) | **Depends on:** Brief 199 (which moved channel credentials to unboks but left the values populated in BlueMarlin's env), and the entire Briefs 200-237 stretch (against which the patches in this brief are written — webhook_server.py and surrounding files have been restructured several times since Brief 199). | **Blocks:** Any future tenant onboarding that shares a Zernio profile with an existing tenant, until the allowlist mechanism exists.

## Context

Brief 199 moved the WhatsApp/Zernio/Meta/Late credentials to the unboks tenant on the VPS so prospects messaging Calvin's number `+599 968 81585` would route to a Calvin/Unboks-aware agent instead of BlueMarlin's Marina. The brief stated "BlueMarlin retains zero channel credentials and runs as a code-only demo." That intent was not actually achieved — the move was a copy. Both `LATE_API_KEY`, `ZERNIO_WEBHOOK_SECRET`, `WHATSAPP_*`, and `EMAIL_ADDRESS` remain populated in `/root/clients/bluemarlin/config/platform.env`. Verification:

```
ssh root@108.61.192.52 'for k in LATE_API_KEY ZERNIO_WEBHOOK_SECRET WHATSAPP_ACCESS_TOKEN; do
  bm=$(grep "^$k=" /root/clients/bluemarlin/config/platform.env);
  ub=$(grep "^$k=" /root/clients/unboks/config/platform.env);
  if [ "$bm" = "$ub" ]; then echo "$k: SAME"; else echo "$k: DIFFERENT"; fi;
done'
LATE_API_KEY: SAME
ZERNIO_WEBHOOK_SECRET: DIFFERENT
WHATSAPP_ACCESS_TOKEN: DIFFERENT
```

`LATE_API_KEY` is identical between BlueMarlin and unboks → both containers are authenticated as the same Zernio account/profile. `ZERNIO_WEBHOOK_SECRET` differs because Zernio assigns a separate signing secret per webhook subscription, and there are two subscriptions registered in Late: one pointing at `/webhooks/zernio` (which falls through nginx `location /` to BlueMarlin:8001) and one at `/unboks/webhooks/zernio` (routed to unboks:8004). Each container verifies its own subscription's signature successfully and processes the message.

**Real evidence from production logs** for conversation `69efec187aca03948969` (Calvin's WhatsApp number) on 2026-05-09 / 2026-05-10:

| Time (UTC)         | BlueMarlin (`/root/clients/bluemarlin/logs/agent.log`)                          | Unboks (`/root/clients/unboks/logs/agent.log`)                |
|--------------------|---------------------------------------------------------------------------------|---------------------------------------------------------------|
| 23:05:53           |                                                                                 | `dm_reply_generated` channel=whatsapp                         |
| 23:05:55 (+2s)     | `whatsapp_agent_reply` intents=`["booking"]` reply_length=113                   |                                                               |
| 00:16:34           | `whatsapp_agent_reply` intents=`["reschedule"]` reply_length=100                |                                                               |
| 00:16:41 (+7s)     |                                                                                 | `dm_reply_generated`                                          |
| 00:17:10           |                                                                                 | `dm_reply_generated`                                          |
| 00:17:12 (+2s)     | `whatsapp_agent_reply` intents=`["inquiry"]` reply_length=103                   |                                                               |

Both containers process the same Zernio webhook within seconds. The customer received two replies for every inbound message — Marina's booking-flow response and Calvin's DM-agent response — because both containers passed HMAC verification (different secrets, both correct), both ran their respective agent path, and both sent via `client.inbox.send_inbox_message(...)` against the same Zernio profile.

Other conversations on the same logs hit only one container (`69fd0426ec1983eefca54fe8` BlueMarlin only, `69ff774f4aabac2e12e2` unboks only), so the bug is not a generic fan-out — it's specific to which Zernio account a given conversation is connected to AND which webhook subscriptions Zernio fires for that account.

**Fix 1 (already done by SR, outside this brief):** SR deleted the duplicate Zernio webhook subscription pointing at BlueMarlin in the Late dashboard. After that change, only the unboks subscription remains, so future inbound events for Calvin's number reach only the unboks container at the HTTP layer. That stops the immediate double-reply, but it leaves three latent risks:

1. **No guard against a future webhook subscription being re-added by mistake.** If anyone re-creates the BlueMarlin `/webhooks/zernio` subscription in Late (during testing, debugging, recovery), the bug returns silently and the customer sees double replies again.
2. **BlueMarlin's container is still capable of sending Zernio replies.** It still has `LATE_API_KEY` and a valid `ZERNIO_WEBHOOK_SECRET` in its env. Stripping these is the only way to make the env-layer guarantee "BlueMarlin physically cannot authenticate to Zernio" hold.
3. **No defensive boundary at the application layer.** All isolation today depends on Late's webhook routing being correct. There is no `if this account is mine, process it; otherwise refuse` check anywhere in the Python codebase. SR's spec called this out explicitly: "If tenant routing is ambiguous, do not send any customer-facing reply. Create an internal escalation/log instead."

This brief addresses 1 + 2 + 3 by adding two complementary defenses: (a) strip BlueMarlin's now-unused credentials so even an accidental webhook re-subscription cannot pass HMAC and even an accidental code path cannot authenticate to Zernio; (b) add an `account_id` allowlist check at the inbound edge (after parse, before processing) and at the outbound edge (before sending), driven by per-tenant config in `client.json`.

**Out of scope (deferred, noted here):**
- **Central webhook router/gateway** (Zernio → router → resolve tenant → forward to one container). That's an architectural change requiring a new service, new deploy story, new failure modes. SR's spec listed it as the long-term target. This brief locks down the existing per-tenant webhook model so that target can be approached incrementally rather than as a forklift migration.
- **Per-tenant Late accounts (separate `LATE_API_KEY`s).** Late currently hosts both BlueMarlin's Twilio number and Calvin's WhatsApp number under one profile (`69b868672cde65a782026248` per `infra.md`). Splitting requires a new Late plan or workspace, possibly new billing, and re-connecting accounts. Out of scope here; this brief makes the shared-key world safe by validating account_id at process boundaries.

## Why This Approach

Three options were considered for closing the application-layer gap:

**A — Strip BlueMarlin credentials only (no allowlist).** Simpler. Achieves the immediate "BlueMarlin can't send Zernio replies" guarantee. Rejected as the *sole* fix because it leaves no application-layer defense against the symmetric mistake (e.g. a new tenant container is added, accidentally given another tenant's `LATE_API_KEY`, and silently starts cross-replying). Also fails SR's "outbound tenant must match inbound tenant" requirement — without an allowlist there's nothing to match against.

**B — Allowlist only (don't strip credentials).** Cleaner architecturally. Rejected as the *sole* fix because the allowlist is enforced inside the Python process — if the process boots with stale or missing config, there's nothing to block a misrouted reply. Stripping the credentials provides a stronger guarantee at the env layer (no key, no API call possible, full stop) that doesn't depend on Python-level correctness.

**C — Both, in order: allowlist first (mechanism), then credential strip (defense in depth) (chosen).** Implements the allowlist mechanism first so the test suite covers the new boundary, then strips BlueMarlin's credentials so a future regression on the allowlist path can't leak through to the customer. Tradeoff: more change in one brief than option A or B alone, but all changes are mechanical and verifiable.

**On the outbound guard specifically (honest framing).** The outbound check at `ZernioSender.send` is largely *symmetric instrumentation* with the inbound check, not an independent filter. Both call sites validate the same `account_id` value because that value is parsed once at the inbound edge and threaded through to the sender unchanged. Today the practical extra catch from the outbound guard, on top of the inbound guard plus credential strip, is: (i) a synthetic test or manual REPL call inside a tenant container that constructs a `ZernioSender.send` invocation directly with someone else's `account_id` (extremely rare in practice — and once `LATE_API_KEY` is empty, `_get_client()` returns `None` and the send fails anyway); (ii) a future change that re-introduces `LATE_API_KEY` on a tenant without re-introducing the webhook subscription, leaving the outbound guard as the last line of defense. SR's spec explicitly required outbound validation, so this brief includes it for symmetry and observability (`tenant_guard_account_unknown direction=outbound` log entries) — not because it catches a class of bug the inbound guard alone can't.

Allowlist *enforcement mode* design — two settings considered:
- `strict` (default for tenants with no live channels): any inbound event whose `account_id` is not in the allowlist is dropped before processing; any outbound send to a non-allowlisted account_id returns False without calling Zernio's API; both record an internal log entry.
- `permissive` (default for the active tenant `unboks` initially): allowlist mismatches log a WARN-level entry but the event still processes / the send still goes out. Used during the bedding-in period so we can populate the allowlist from real production logs without risking a missed reply on a real customer.

Reason for permissive default on unboks: the actual Zernio `account_id` for Calvin's WhatsApp number is not yet known to us (it doesn't appear in current logs because `webhook_server.py:296` truncates the `zernio_dm_received` log line to conversation_id + platform + sender). Once unboks runs in permissive mode for ~1 day with the new WARN logging, SR copies the surfaced account_ids into `clients/unboks/config/client.json` and flips mode to `strict`. That follow-up is a 2-line config edit, not a brief.

## Instructions

### Step 1a — Add `channel_account_allowlist` block to local repo configs

Three local files: `clients/bluemarlin/config/client.json`, `clients/adamus/config/client.json`, `clients/unboks/config/client.json`.

For BlueMarlin and Adamus (no live channels — BlueMarlin's are stripped in Step 5; Adamus has none), add as the last top-level key (after `common_sense_knowledge`):

```json
"channel_account_allowlist": {
  "mode": "strict",
  "zernio_accounts": [],
  "notes": "This tenant has no live inbound channels. Strict mode + empty list means any Zernio webhook arriving here is treated as misrouted and rejected before processing."
}
```

For unboks (live for Calvin's WhatsApp number), add:

```json
"channel_account_allowlist": {
  "mode": "permissive",
  "zernio_accounts": [],
  "notes": "Permissive mode logs WARN on unknown account_ids but still processes. Bedding-in period: collect real account_ids from production logs over ~1 day, populate zernio_accounts, then switch mode to strict. The known Zernio profile is 69b868672cde65a782026248 (Default Profile) per infra.md; account_ids are per-account-within-profile and need to be observed empirically."
}
```

Use the Edit tool for each file — do not rewrite the whole config. Insert the new block after the closing `}` of `common_sense_knowledge` and before the file's final `}`. Add a comma after `common_sense_knowledge`'s closing `}` (it was previously the last block).

### Step 1b — Add `channel_account_allowlist` block to Consulta Despertares on the VPS

Consulta Despertares's `client.json` lives only at `/root/clients/consultadespertares/config/client.json` on the VPS — it's not version-controlled in this repo. Patch it in place via SSH using a tiny Python one-liner that loads the JSON, inserts the strict-mode block, and writes back atomically:

```bash
ssh root@108.61.192.52 "python3 - <<'PY'
import json, os, shutil
p = '/root/clients/consultadespertares/config/client.json'
shutil.copy(p, p + '.bak.brief238')
with open(p) as f:
    cfg = json.load(f)
cfg['channel_account_allowlist'] = {
    'mode': 'strict',
    'zernio_accounts': [],
    'notes': 'This tenant has no live inbound channels. Strict mode + empty list means any Zernio webhook arriving here is treated as misrouted and rejected before processing.'
}
tmp = p + '.tmp'
with open(tmp, 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
os.replace(tmp, p)
print('Consulta config patched. Backup at', p + '.bak.brief238')
PY"
```

The `.bak.brief238` backup enables a one-line rollback (`cp <bak> <orig>`).

### Step 2 — Create `wtyj/shared/tenant_guard.py` (NEW)

```python
# wtyj/shared/tenant_guard.py
# Brief 238 — Tenant isolation: account_id allowlist guard.
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
```

Notes:
- `config_loader.get_raw()` is the existing helper used throughout the codebase (see `webhook_server.py:321`). Returns the in-memory client.json dict, which is mutable but we don't mutate.
- `account_id[:24]` truncation in the log mirrors the truncation pattern at `webhook_server.py:296` — Zernio account IDs are typically 24 hex chars. Logging the full ID would also be fine but consistent with existing redaction behaviour wins.
- No exception is raised on a missing/empty `account_id`. An empty string is treated as "not in allowlist" → handled by mode (permissive: log + allow, strict: log + block). This matches the parser's behaviour in `zernio_dm_client.py:32-96` which never raises and may return an empty `account_id` if the payload is malformed.

### Step 3 — Wire the inbound check in `wtyj/agents/social/webhook_server.py`

In `_process_zernio_event` (currently starting at line 275), after `parse_zernio_webhook` returns a non-None `msg` and after the dedup check passes (line 287 — `state_registry.wa_mark_as_processed(message_id)`), insert the guard. Place it before the empty-text skip at line 290 because we want to record the unknown-account event regardless of whether it has text.

Insert immediately after `state_registry.wa_mark_as_processed(message_id)`:

```python
        # Brief 238 — tenant isolation: refuse webhooks for accounts not
        # allowlisted in this tenant's client.json. Strict mode aborts here;
        # permissive mode just logs and keeps going.
        from shared.tenant_guard import is_account_allowed
        if not is_account_allowed(msg.get("account_id", ""), direction="inbound"):
            return
```

(The local import keeps the existing top-of-file import block undisturbed and matches the guard's "lazy" call profile — only invoked on actual webhook events.)

The dedup `wa_mark_as_processed` runs *before* the guard so a misrouted event is still marked seen — preventing the same message from being re-processed if the allowlist is widened later in the day. Acceptable: `wa_processed` is shared across the dedup window only, and a misrouted event reaching this point is already an anomaly worth not re-running.

### Step 4 — Wire the outbound check in `wtyj/agents/social/senders/zernio.py`

Replace the `ZernioSender.send` body (currently 2 lines at lines 13-15) with:

```python
    @classmethod
    def send(cls, conversation_id: str, account_id: str, text: str) -> bool:
        # Brief 238 — tenant isolation: refuse outbound sends to accounts
        # not allowlisted in this tenant's client.json. Strict mode blocks
        # the call entirely; permissive mode logs and proceeds.
        from shared.tenant_guard import is_account_allowed
        if not is_account_allowed(account_id, direction="outbound"):
            return False
        return send_dm_reply(conversation_id, account_id, text)
```

The guard runs *before* `send_dm_reply` so a blocked send never touches Zernio's API. Returns `False` on block, which is the existing failure-shape of `ZernioSender.send` and propagates correctly through the dispatcher in `senders/__init__.py:22-31`.

### Step 5 — Strip BlueMarlin's channel credentials on the VPS

Idempotent shell script — write at `/tmp/strip_bluemarlin_channels.sh` locally, scp to VPS, execute, delete. Mirrors Brief 199's shape so SR can compare side-by-side.

```bash
#!/bin/bash
# Brief 238 — Strip channel credentials from BlueMarlin's platform.env.
# After Brief 199 these values were copied (not moved) to unboks/. Now we
# remove them from BlueMarlin so the container can no longer authenticate
# to Zernio/Meta/Late and cannot pass HMAC verification on Zernio webhooks.
# Idempotent: safe to re-run. Backup created with timestamp.

set -e
SRC=/root/clients/bluemarlin/config/platform.env
BAK="$SRC.bak.brief238.$(date +%Y%m%d-%H%M%S)"
cp "$SRC" "$BAK"

KEYS="WHATSAPP_ACCESS_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_VERIFY_TOKEN WHATSAPP_BUSINESS_ACCOUNT_ID META_APP_ID META_APP_SECRET LATE_API_KEY ZERNIO_WEBHOOK_SECRET EMAIL_ADDRESS"
for KEY in $KEYS; do
  if grep -qE "^$KEY=" "$SRC"; then
    sed -i "s|^$KEY=.*|$KEY=|" "$SRC"
  fi
done

chmod 600 "$SRC"
echo "Strip complete. Backup: $BAK"
echo "Current state of channel keys in BlueMarlin platform.env:"
grep -E "^($(echo $KEYS | tr ' ' '|'))=" "$SRC"
```

Steps from local Mac:
- `scp /tmp/strip_bluemarlin_channels.sh root@108.61.192.52:/root/strip_bluemarlin_channels.sh`
- `ssh root@108.61.192.52 "chmod +x /root/strip_bluemarlin_channels.sh && /root/strip_bluemarlin_channels.sh && rm /root/strip_bluemarlin_channels.sh"`
- `rm /tmp/strip_bluemarlin_channels.sh`

Note `EMAIL_ADDRESS` is included in the strip list. Per `infra.md`'s env var inventory, BlueMarlin's `EMAIL_ADDRESS` was `hello@wetakeyourjob.com` — but that mailbox is now Brief 199's responsibility under the unboks tenant per current intent. If BlueMarlin ever needs an email channel back, that's a future brief that re-provisions per-tenant.

### Step 6 — Restart all four tenant containers

```bash
ssh root@108.61.192.52 "cd /root/clients/bluemarlin && docker compose down && docker compose up -d && \
                       cd /root/clients/adamus && docker compose down && docker compose up -d && \
                       cd /root/clients/consultadespertares && docker compose down && docker compose up -d && \
                       cd /root/clients/unboks && docker compose down && docker compose up -d"
```

`down + up -d` (not `restart`) on each so the new client.json keys get re-read from the volume mount. Image is unchanged.

### Step 7 — Verify

Health on every container:

```bash
ssh root@108.61.192.52 "for p in 8001 8002 8003 8004; do printf 'port %s: ' \$p; curl -sf -m 3 http://localhost:\$p/health; echo; done"
```

Expected: all four return `{"status":"ok"}`.

BlueMarlin channel envs are empty (the right-hand side of `=` is the empty string):

```bash
ssh root@108.61.192.52 "for k in LATE_API_KEY ZERNIO_WEBHOOK_SECRET WHATSAPP_ACCESS_TOKEN; do
  v=\$(grep \"^\$k=\" /root/clients/bluemarlin/config/platform.env | cut -d= -f2-)
  if [ -z \"\$v\" ]; then echo \"\$k: empty\"; else echo \"\$k: NOT empty (FAIL)\"; fi
done"
```

Expected:
```
LATE_API_KEY: empty
ZERNIO_WEBHOOK_SECRET: empty
WHATSAPP_ACCESS_TOKEN: empty
```

Unboks channel envs are still set (sanity check Step 5 didn't accidentally affect unboks):

```bash
ssh root@108.61.192.52 "for k in LATE_API_KEY ZERNIO_WEBHOOK_SECRET WHATSAPP_ACCESS_TOKEN; do
  v=\$(grep \"^\$k=\" /root/clients/unboks/config/platform.env | cut -d= -f2-)
  if [ -n \"\$v\" ]; then echo \"\$k: set\"; else echo \"\$k: empty (FAIL)\"; fi
done"
```

Expected:
```
LATE_API_KEY: set
ZERNIO_WEBHOOK_SECRET: set
WHATSAPP_ACCESS_TOKEN: set
```

### Step 8 — Append a Brief 238 note to `wtyj/briefs/infra.md`

Find the Brief 199 paragraph (search for "2026-05-03 update (Brief 199)") and append a new paragraph immediately after it:

> **2026-05-10 update (Brief 238):** added a `channel_account_allowlist` block to every tenant's `client.json` and a `wtyj/shared/tenant_guard.py` module that validates inbound webhook `account_id`s and outbound send targets against the per-tenant allowlist. BlueMarlin/Adamus/Consulta Despertares default to `mode: "strict"` with empty lists (any Zernio webhook reaching them is treated as misrouted and dropped). Unboks defaults to `mode: "permissive"` until Calvin's actual Zernio account_id is observed in WARN logs and added to its allowlist. The cred copy from Brief 199 was also reversed: BlueMarlin's `LATE_API_KEY`, `ZERNIO_WEBHOOK_SECRET`, `WHATSAPP_*`, and `EMAIL_ADDRESS` are now empty, so even if a future webhook subscription is re-added in Late by mistake, BlueMarlin rejects HMAC and cannot authenticate to Zernio.

## Tests

Seven new behavioral tests at `wtyj/tests/test_238_tenant_isolation.py`. All target real branches in `tenant_guard.is_account_allowed` and the two call sites that wrap it.

```python
"""Brief 238 — Tenant isolation guard tests.

Cover the four guard branches (absent, permissive-allowed, permissive-unknown,
strict-unknown, strict-allowed) plus the integration of the guard at the
inbound webhook handler (DM branch and WhatsApp branch separately) and
outbound sender call sites.
"""
from unittest.mock import patch, MagicMock


def _stub_config(allowlist_block):
    """Return a get_raw() stub returning a config with the given allowlist
    block (or no block at all when allowlist_block is None)."""
    cfg = {}
    if allowlist_block is not None:
        cfg["channel_account_allowlist"] = allowlist_block
    return MagicMock(return_value=cfg)


def test_guard_returns_true_when_block_absent():
    """No allowlist block in client.json → no enforcement, no log entry."""
    from shared import tenant_guard
    with patch("shared.tenant_guard.config_loader.get_raw",
               _stub_config(None)), \
         patch("shared.tenant_guard.bm_logger.log") as mock_log:
        assert tenant_guard.is_account_allowed("any_account_id",
                                               direction="inbound") is True
        mock_log.assert_not_called()


def test_guard_strict_blocks_unknown_account_and_logs():
    """Strict mode + account not in list → returns False, logs unknown event."""
    from shared import tenant_guard
    with patch("shared.tenant_guard.config_loader.get_raw",
               _stub_config({"mode": "strict",
                             "zernio_accounts": ["aaa111"]})), \
         patch("shared.tenant_guard.bm_logger.log") as mock_log:
        assert tenant_guard.is_account_allowed("bbb222",
                                               direction="inbound") is False
        mock_log.assert_called_once()
        args, kwargs = mock_log.call_args
        assert args[0] == "tenant_guard_account_unknown"
        assert kwargs["mode"] == "strict"
        assert kwargs["direction"] == "inbound"


def test_guard_permissive_allows_unknown_account_but_logs():
    """Permissive mode + account not in list → returns True, still logs."""
    from shared import tenant_guard
    with patch("shared.tenant_guard.config_loader.get_raw",
               _stub_config({"mode": "permissive",
                             "zernio_accounts": []})), \
         patch("shared.tenant_guard.bm_logger.log") as mock_log:
        assert tenant_guard.is_account_allowed("ccc333",
                                               direction="outbound") is True
        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["mode"] == "permissive"


def test_guard_strict_allows_listed_account_with_no_log():
    """Strict mode + account is in list → returns True, no log entry."""
    from shared import tenant_guard
    with patch("shared.tenant_guard.config_loader.get_raw",
               _stub_config({"mode": "strict",
                             "zernio_accounts": ["aaa111", "bbb222"]})), \
         patch("shared.tenant_guard.bm_logger.log") as mock_log:
        assert tenant_guard.is_account_allowed("aaa111",
                                               direction="inbound") is True
        mock_log.assert_not_called()


def test_inbound_dm_handler_skipped_on_strict_mismatch():
    """webhook_server._process_zernio_event with platform=instagram and a
    strict-mismatch account must NOT call handle_incoming_dm.

    Use the DM (non-WhatsApp) branch because that's where downstream handlers
    are directly observable; the WhatsApp branch only buffers, which is
    covered by the next test.

    Both tenant_guard and webhook_server import config_loader as a module
    (`from shared import config_loader`), so both reference the same
    `shared.config_loader.get_raw` callable. A single patch on that path
    serves both call sites — return a dict containing BOTH the allowlist
    block (read by tenant_guard) and the features block (read by
    webhook_server's booking_flow lookup)."""
    from agents.social import webhook_server
    payload = {"event": "message.received", "data": {
        "id": "msgB238a", "conversationId": "convB238a",
        "accountId": "not_allowlisted", "platform": "instagram",
        "text": "hi", "sender": {"name": "Test"}}}
    fake_cfg = {
        "channel_account_allowlist": {
            "mode": "strict", "zernio_accounts": ["only_this_one"]},
        "features": {"booking_flow": False},
    }
    parsed = {"conversation_id": "convB238a", "platform": "instagram",
              "channel": "instagram_dm", "sender_name": "Test", "sender_id": "s1",
              "text": "hi", "message_id": "msgB238a", "account_id": "not_allowlisted"}
    with patch("agents.social.webhook_server.parse_zernio_webhook", return_value=parsed), \
         patch("agents.social.webhook_server.state_registry.wa_has_been_processed",
               return_value=False), \
         patch("agents.social.webhook_server.state_registry.wa_mark_as_processed"), \
         patch("agents.social.webhook_server.send_typing_indicator"), \
         patch("shared.config_loader.get_raw", return_value=fake_cfg), \
         patch("agents.social.webhook_server.handle_incoming_dm") as mock_dm:
        webhook_server._process_zernio_event(payload)
        mock_dm.assert_not_called()


def test_inbound_whatsapp_buffer_skipped_on_strict_mismatch():
    """webhook_server._process_zernio_event with platform=whatsapp and a
    strict-mismatch account must NOT call _buffer_message.

    The WhatsApp-via-Zernio branch routes through _buffer_message (debounce);
    the guard must prevent that call when the account is not allowlisted."""
    from agents.social import webhook_server
    payload = {"event": "message.received", "data": {
        "id": "msgB238b", "conversationId": "convB238b",
        "accountId": "not_allowlisted", "platform": "whatsapp",
        "text": "hi", "sender": {"name": "Test"}}}
    fake_cfg = {"channel_account_allowlist": {
        "mode": "strict", "zernio_accounts": ["only_this_one"]}}
    parsed = {"conversation_id": "convB238b", "platform": "whatsapp",
              "channel": "whatsapp", "sender_name": "Test", "sender_id": "s1",
              "text": "hi", "message_id": "msgB238b", "account_id": "not_allowlisted"}
    with patch("agents.social.webhook_server.parse_zernio_webhook", return_value=parsed), \
         patch("agents.social.webhook_server.state_registry.wa_has_been_processed",
               return_value=False), \
         patch("agents.social.webhook_server.state_registry.wa_mark_as_processed"), \
         patch("agents.social.webhook_server.send_typing_indicator"), \
         patch("shared.config_loader.get_raw", return_value=fake_cfg), \
         patch("agents.social.webhook_server._buffer_message") as mock_buffer:
        webhook_server._process_zernio_event(payload)
        mock_buffer.assert_not_called()


def test_outbound_sender_blocks_strict_mismatch_before_zernio_call():
    """ZernioSender.send with a strict-mismatch account must NOT call
    send_dm_reply (the actual Zernio API wrapper)."""
    from agents.social.senders.zernio import ZernioSender
    fake_cfg = {"channel_account_allowlist": {
        "mode": "strict", "zernio_accounts": ["only_this_one"]}}
    with patch("shared.config_loader.get_raw", return_value=fake_cfg), \
         patch("agents.social.senders.zernio.send_dm_reply") as mock_send:
        result = ZernioSender.send("convX", "wrong_account", "hello")
        assert result is False
        mock_send.assert_not_called()
```

Seven tests. Four exercise the four branches of `is_account_allowed` directly (absent / strict-block / permissive-warn / strict-allow). Two integration tests verify the inbound guard short-circuits both downstream paths it can short-circuit (DM handler call AND the WhatsApp debounce buffer call). One integration test verifies the outbound guard short-circuits the Zernio API wrapper. No source-level string guards.

**Regression baseline:** **1015 passing / 0 failures** (per Brief 237 system_state — confirmed by running `python3 -m pytest wtyj/tests/ -q` 2026-05-10). After this brief: **1022 passing / 0 failures** (1015 + 7 new).

## Success Condition

After execution:

1. `python3 -m pytest wtyj/tests/test_238_tenant_isolation.py -q` passes 7/7.
2. `python3 -m pytest wtyj/tests/ -q` reports 1022 passing / 0 failures.
3. For each of `bluemarlin`, `adamus`, `unboks` — `python3 -c "import json; print(json.load(open('clients/<tenant>/config/client.json')).get('channel_account_allowlist', {}).get('mode'))"` prints either `strict` (bluemarlin, adamus) or `permissive` (unboks). Same check on the VPS for Consulta: `ssh root@VPS "python3 -c \"import json; print(json.load(open('/root/clients/consultadespertares/config/client.json')).get('channel_account_allowlist', {}).get('mode'))\""` prints `strict`.
4. The verification script in Step 7 prints `LATE_API_KEY: empty / ZERNIO_WEBHOOK_SECRET: empty / WHATSAPP_ACCESS_TOKEN: empty` for BlueMarlin and `set / set / set` for unboks.
5. `for slug in bluemarlin adamus consultadespertares unboks; do curl -sf "https://api.wetakeyourjob.com/$slug/health"; echo; done` returns `{"status":"ok"}` four times.
6. After the next inbound WhatsApp from Calvin's number reaches the unboks tenant, `docker logs wtyj-unboks --since 5m | grep tenant_guard_account_unknown` shows a WARN-level entry with `direction=inbound, mode=permissive` and a real `account_id` value — that account_id is what SR should later add to `clients/unboks/config/client.json` and flip mode to strict. (Capture the surfaced `account_id` in the OUTPUT for the follow-up.)

## Rollback

Step 5 creates a timestamped backup (`platform.env.bak.brief238.YYYYMMDD-HHMMSS`) before any change. Step 1b creates `client.json.bak.brief238` for Consulta. To roll back the credential strip:

```bash
ssh root@108.61.192.52 "ls -t /root/clients/bluemarlin/config/platform.env.bak.brief238.* | head -1 | xargs -I {} cp {} /root/clients/bluemarlin/config/platform.env"
ssh root@108.61.192.52 "cp /root/clients/consultadespertares/config/client.json.bak.brief238 /root/clients/consultadespertares/config/client.json"
ssh root@108.61.192.52 "cd /root/clients/bluemarlin && docker compose restart && cd /root/clients/consultadespertares && docker compose restart"
```

To roll back the code + repo client.json changes: `git revert <this brief's source commit>` and push. The pipeline auto-deploys the revert.

If only the inbound check is misbehaving in production (e.g. permissive mode is too noisy or strict mode is too aggressive), edit the affected tenant's `client.json` `channel_account_allowlist.mode` to `"permissive"` (or remove the block entirely to disable enforcement) and `docker compose restart` that tenant. No code revert needed for a config-level rollback.
