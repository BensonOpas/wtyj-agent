# BRIEF 217 — Escalation alert delivery (email + WhatsApp)
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/social/test_217_alert_delivery.py` | **Depends on:** Brief 213 (escalation control surface), Brief 214 (/guidance), Brief 210 (smtp_send) | **Blocks:** SR's Settings → Escalation Alerts panel + the operator getting pinged when an escalation fires

## Context

Today, when a customer triggers an escalation (Marina hits `[ESCALATE]`, complaint, refund request, "I want a human"), the row lands in `pending_notifications` and shows up in the dashboard's Escalations tab. **Nothing actively notifies the operator.** They have to be looking at the dashboard, or check it on a polling habit, to know an escalation is waiting. This is fine for testing — useless for real product where escalations matter most outside business hours.

SR's product contract Section 11 (the May 6 22:31 task) describes the contract:

```
GET /api/{client}/dashboard/api/settings/escalation-alerts
Response: {
  "channels": {
    "email":    {"enabled": true,  "destination": "default"},
    "whatsapp": {"enabled": true,  "destination": "+351963618003"},
    "telegram": {"enabled": false, "destination": ""},
    "messenger":{"enabled": false, "destination": ""}
  }
}

PUT /api/{client}/dashboard/api/settings/escalation-alerts
(same body shape)

When a new escalation fires:
  1. Load alert settings.
  2. Send to every enabled destination.
  3. Email always enabled by default.
  4. WhatsApp sends to the configured private number, NOT the
     business WhatsApp.
  5. Telegram + Messenger if configured.
  6. Store delivery status for audit/debug.

Alert message format:
  New escalation in Unboks
  Customer: {customerName}
  Channel: {channel}
  Mode: {soft or hard}
  Summary: {summary}
  Action: Open dashboard to review.

If WhatsApp alert fails, do not block the escalation.
Log the failure. Return delivery status.
Do not silently fail. Do not assume the business WhatsApp number
is the alert recipient.
```

We have providers for email (`smtp_send` from Brief 210) and WhatsApp (`send_whatsapp_message` via Zernio). We do NOT have Telegram or Messenger providers wired today — those would need new integrations (Telegram bot token + python-telegram-bot or HTTP API; Messenger via separate Zernio account routing). v1 ships email + WhatsApp; Telegram and Messenger return 501-style "not configured" messages in the response delivery_status array so the frontend can show them as inert in the UI.

## Why This Approach

- **Schema: two new tables, both per-tenant.**
  - `alert_settings` — single row per tenant containing the channel config. Use the column-per-channel pattern (`email_enabled`, `email_destination`, `whatsapp_enabled`, `whatsapp_destination`, ...) rather than a JSON blob, because (a) it's a tiny fixed shape (4 channels × 2 fields), (b) SQL queries are cleaner, (c) future additions (telegram, messenger) are 2 more ALTER ADD COLUMNs each. Default email row is created lazily on first GET so existing tenants don't need a migration script.
  - `alert_deliveries` — append-only audit log. One row per delivery attempt: `{id, escalation_id, channel, destination, status, error, sent_at}`. Operator can query failures via the dashboard later.
- **Hook into `state_registry.create_pending_notification` (line ~1183) — but ONLY for `notification_type='escalation'` rows.** That helper is also called with `notification_type='relay'` (e.g., `social_agent.py:260`, `dm_agent` paths) — those are Marina's "ask the team a question" relay flow, NOT operator escalations. Firing alerts on relay rows would spam the operator's WhatsApp every time Marina asks a relay question. Gate the dispatcher call: `if notification_type == 'escalation' and _alert_dispatcher: _alert_dispatcher(...)`.
- **Place AFTER the existing `INSERT INTO pending_notifications` + `set_conversation_status` calls** so the alert row references a real DB id and the conversation is in the right status. Wrap the alert dispatch in a try/except — alert failure must NEVER block the escalation row from being persisted (operator can't recover from a missing escalation; they CAN recover from a missing alert by checking the dashboard).
- **Import topology — dispatcher registration timing.** `dashboard/api.py` registers `_fire_escalation_alerts` via `state_registry.set_alert_dispatcher` at module-import time. Verified import chain: `agents/social/webhook_server.py` imports `dashboard.api` at module load (via `from dashboard.api import router as dashboard_router`); `email_poller` is started as a thread inside webhook_server's startup lifespan, so by the time email_poller's for-uid loop fires, `dashboard.api` has already loaded and the dispatcher is registered. All five `create_pending_notification` call sites — `dm_agent.py:225`, `social_agent.py:260,276`, `email_poller.py:678,691,979,1048,1089,1163` — run inside that same process. Test files that import `agents.social.webhook_server.app` (the existing pattern in `test_213`/`test_214`/`test_215`) trigger the same registration chain. Tests that ONLY import `from shared import state_registry` will see `_alert_dispatcher = None` and silently skip dispatch — this is intentional (state_registry helper unit tests should not require alerts).
- **Default email destination is `business.support_email` from `client.json`.** Per SR's contract: "Email is always enabled by default." On first GET, if no `alert_settings` row exists for the tenant, return a synthesized default row using `support_email` as the email destination. PUT writes the row. This avoids needing a per-tenant bootstrap step.
- **`"default"` sentinel resolution.** SR's contract example shows `"email": {"enabled": true, "destination": "default"}`. Brief 217 treats `"default"` as a sentinel meaning "use the resolved support_email from client.json." GET responses return the RESOLVED email (e.g., `"butlerbensonagent@gmail.com"`), NOT the literal string `"default"`. The frontend's input field is pre-populated with the resolved value. PUTting the literal `"default"` string back is also accepted — the dispatcher resolves it at send time. This way operators see the real destination in the UI and can override it with a different address if they want.
- **WhatsApp alert destination is a different number from the business WhatsApp.** Per SR's contract: "WhatsApp sends to the configured private number, not necessarily the business WhatsApp number." Operator types their personal/private phone in the Settings UI. Backend stores it in `alert_settings.whatsapp_destination`. Sender path: `send_whatsapp_message(operator_phone, alert_text)` — same function the customer-reply path uses, just routed to a different recipient.
- **Best-effort dispatch with audit logs.** Each enabled channel is attempted independently. If email fails, WhatsApp still goes out. Each attempt writes one `alert_deliveries` row with status (`sent`, `failed`, `skipped` for unconfigured channels). The new pending_notification row is committed to the DB BEFORE alert dispatch — so a crash mid-dispatch doesn't lose the escalation.
- **Alert message format mirrors SR's spec verbatim.** Build with the escalation row's fields + the tenant's `client.json` business name. Truncate `summary` (subject) to 200 chars to keep WhatsApp messages under their length cap. Don't include the customer's full message body (privacy + length).
- **Telegram and Messenger return 501-equivalent rows in the audit log.** Status = "skipped", error = "provider not configured". Frontend reads this and shows the toggle as disabled (greyed out) with a "ask Unboks team to wire this" tooltip. Adding a provider later means: implement the send function, replace "skipped" with "sent"/"failed". No schema change.
- **Rejected: per-channel webhook URLs (operator-defined).** Tempting (one shape covers any channel) but yanks the operator into "configure your own integration" territory which contradicts SR's "Unboks runs your inbox" positioning. Keep the channel set bounded.
- **Rejected: store the audit log on `pending_notifications` as a JSON column.** That couples the escalation row to delivery-status fields it shouldn't carry. Separate `alert_deliveries` table = clean audit trail + queryable.
- **Rejected: synchronous send blocking the escalation insert.** Send WhatsApp via Zernio = network call, can be slow, sometimes 5-10s. Blocking `create_pending_notification` for that long would slow down `dm_agent.handle_incoming_dm` (the customer-message path that calls it). Decision: send synchronously inside try/except so customer-path latency stays bounded. Fallback to async dispatch if WhatsApp send latency becomes a real problem (future brief).

## Instructions

### Step 1 — Schema in `wtyj/shared/state_registry.py:_get_conn()`

Add two `CREATE TABLE IF NOT EXISTS` blocks adjacent to the existing escalation_learnings CREATE at `state_registry.py:316`:

```python
# Brief 217: per-tenant alert settings (email + whatsapp + telegram + messenger).
# One row per tenant; fields stored as columns for cleaner queries.
conn.execute(
    "CREATE TABLE IF NOT EXISTS alert_settings ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "email_enabled INTEGER NOT NULL DEFAULT 1, "
    "email_destination TEXT NOT NULL DEFAULT '', "
    "whatsapp_enabled INTEGER NOT NULL DEFAULT 0, "
    "whatsapp_destination TEXT NOT NULL DEFAULT '', "
    "telegram_enabled INTEGER NOT NULL DEFAULT 0, "
    "telegram_destination TEXT NOT NULL DEFAULT '', "
    "messenger_enabled INTEGER NOT NULL DEFAULT 0, "
    "messenger_destination TEXT NOT NULL DEFAULT '', "
    "updated_at TEXT NOT NULL DEFAULT ''"
    ")"
)

# Brief 217: append-only audit log of alert delivery attempts.
conn.execute(
    "CREATE TABLE IF NOT EXISTS alert_deliveries ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "escalation_id INTEGER, "
    "channel TEXT NOT NULL, "
    "destination TEXT NOT NULL DEFAULT '', "
    "status TEXT NOT NULL, "
    "error TEXT, "
    "sent_at TEXT NOT NULL"
    ")"
)
```

### Step 2 — State_registry helpers

Insert near the existing escalation helpers (after `get_active_escalation_mode` around `state_registry.py:1233`):

```python
# ── Brief 217: Alert settings + delivery audit ──

def get_alert_settings(default_email_destination: str = "") -> dict:
    """Brief 217: return the alert config in SR's frontend shape. If no
    row exists yet, synthesize a default with email enabled + the given
    default destination (typically business.support_email from
    client.json). Caller passes the default; we don't reach into config
    from here to keep state_registry agnostic."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT email_enabled, email_destination, whatsapp_enabled, "
        "whatsapp_destination, telegram_enabled, telegram_destination, "
        "messenger_enabled, messenger_destination FROM alert_settings "
        "ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return {
            "channels": {
                "email":     {"enabled": True,  "destination": default_email_destination or "default"},
                "whatsapp":  {"enabled": False, "destination": ""},
                "telegram":  {"enabled": False, "destination": ""},
                "messenger": {"enabled": False, "destination": ""},
            }
        }
    return {
        "channels": {
            "email":     {"enabled": bool(row[0]), "destination": row[1] or "default"},
            "whatsapp":  {"enabled": bool(row[2]), "destination": row[3] or ""},
            "telegram":  {"enabled": bool(row[4]), "destination": row[5] or ""},
            "messenger": {"enabled": bool(row[6]), "destination": row[7] or ""},
        }
    }


def save_alert_settings(channels: dict) -> None:
    """Brief 217: upsert the single alert_settings row. `channels` is the
    dict shape SR's frontend posts: {email: {enabled, destination}, ...}.
    Uses INSERT OR REPLACE on a fixed id=1 row so the operation is atomic
    (no DELETE-then-INSERT race window where a partial failure leaves the
    table empty and operator's settings vanish into the synthesized default)."""
    now = datetime.now(timezone.utc).isoformat()
    em = channels.get("email", {})
    wa = channels.get("whatsapp", {})
    tg = channels.get("telegram", {})
    ms = channels.get("messenger", {})
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO alert_settings "
        "(id, email_enabled, email_destination, whatsapp_enabled, whatsapp_destination, "
        "telegram_enabled, telegram_destination, messenger_enabled, messenger_destination, "
        "updated_at) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1 if em.get("enabled") else 0, em.get("destination", ""),
         1 if wa.get("enabled") else 0, wa.get("destination", ""),
         1 if tg.get("enabled") else 0, tg.get("destination", ""),
         1 if ms.get("enabled") else 0, ms.get("destination", ""),
         now))
    conn.commit()
    conn.close()


def record_alert_delivery(escalation_id, channel: str, destination: str,
                           status: str, error: str = None) -> int:
    """Brief 217: append a row to alert_deliveries. status one of
    'sent', 'failed', 'skipped'. Returns row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO alert_deliveries "
        "(escalation_id, channel, destination, status, error, sent_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (escalation_id, channel, destination or "", status, error, now))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id
```

### Step 3 — Alert dispatcher in `wtyj/dashboard/api.py`

Add a new module-level helper near the other escalation handlers, just above the `# ── Escalations ──` section divider (around `api.py:1144`):

```python
# Brief 217: alert dispatcher. Called from create_pending_notification's
# hook to fire alerts to enabled channels. Best-effort — failure on one
# channel does NOT raise; each attempt is recorded in alert_deliveries.

def _fire_escalation_alerts(escalation_id: int, customer_name: str,
                             channel: str, summary: str,
                             mode: str = None) -> None:
    """Brief 217: build the alert message, dispatch to enabled channels,
    record delivery status per attempt. Never raises — alerts are
    best-effort, the escalation row is the durable artifact."""
    try:
        biz = config_loader.get_business() or {}
        client_name = biz.get("name", "Unboks")
        default_email = biz.get("support_email", "") or biz.get("email", "")
    except Exception:
        client_name = "Unboks"
        default_email = ""

    settings = state_registry.get_alert_settings(default_email_destination=default_email)
    channels_cfg = settings.get("channels", {})

    # Build the alert text per SR's contract.
    safe_summary = (summary or "")[:200]
    mode_text = mode if mode in ("soft", "hard") else "(unset)"
    alert_text = (
        f"New escalation in {client_name}\n\n"
        f"Customer: {customer_name or '(unknown)'}\n"
        f"Channel: {channel or '(unknown)'}\n"
        f"Mode: {mode_text}\n"
        f"Summary: {safe_summary}\n"
        f"Action: Open dashboard to review."
    )

    # Email branch
    em = channels_cfg.get("email", {})
    if em.get("enabled"):
        dest = em.get("destination", "")
        if dest in ("", "default"):
            dest = default_email
        if dest:
            try:
                smtp_send(dest, f"New escalation: {customer_name or 'customer'}", alert_text)
                state_registry.record_alert_delivery(escalation_id, "email", dest, "sent")
            except Exception as exc:
                state_registry.record_alert_delivery(escalation_id, "email", dest, "failed", str(exc)[:200])
        else:
            state_registry.record_alert_delivery(escalation_id, "email", "", "skipped", "no email destination configured")

    # WhatsApp branch
    wa = channels_cfg.get("whatsapp", {})
    if wa.get("enabled"):
        dest = wa.get("destination", "")
        if dest:
            try:
                ok = send_whatsapp_message(dest, alert_text)
                if ok:
                    state_registry.record_alert_delivery(escalation_id, "whatsapp", dest, "sent")
                else:
                    state_registry.record_alert_delivery(escalation_id, "whatsapp", dest, "failed", "send_whatsapp_message returned False")
            except Exception as exc:
                state_registry.record_alert_delivery(escalation_id, "whatsapp", dest, "failed", str(exc)[:200])
        else:
            state_registry.record_alert_delivery(escalation_id, "whatsapp", "", "skipped", "no whatsapp destination configured")

    # Telegram + Messenger v1: provider not wired
    if channels_cfg.get("telegram", {}).get("enabled"):
        state_registry.record_alert_delivery(
            escalation_id, "telegram",
            channels_cfg["telegram"].get("destination", ""),
            "skipped", "telegram provider not configured")
    if channels_cfg.get("messenger", {}).get("enabled"):
        state_registry.record_alert_delivery(
            escalation_id, "messenger",
            channels_cfg["messenger"].get("destination", ""),
            "skipped", "messenger provider not configured")
```

### Step 4 — Hook into `create_pending_notification`

In `wtyj/shared/state_registry.py:create_pending_notification` (around `state_registry.py:1183`), after the `set_conversation_status(...)` call at the bottom but BEFORE `return row_id`, add a try/except that calls the dispatcher. **Critical:** gate the call on `notification_type == "escalation"` — relay rows must NOT trigger alerts (Marina's "ask the team" flow uses the same helper but should not ping the operator like a customer-driven escalation does).

The dispatcher lives in `dashboard/api.py` (where smtp_send and send_whatsapp_message are already imported), but `state_registry` shouldn't import from `dashboard.api` (would create a cycle: dashboard.api imports state_registry; state_registry can't import back). Instead, register the dispatcher as a module-level callback that dashboard.api wires at import time.

Cleanest approach: add a module-level pluggable hook in state_registry:

```python
# Near the top of state_registry.py, after the imports:
_alert_dispatcher = None  # Brief 217: optional callback set by dashboard.api

def set_alert_dispatcher(fn):
    """Brief 217: dashboard.api registers _fire_escalation_alerts here at
    import time. Decoupled callback so state_registry doesn't import
    dashboard (which would create a circular import). When None,
    create_pending_notification skips alerts (e.g., in tests that don't
    boot the dashboard router)."""
    global _alert_dispatcher
    _alert_dispatcher = fn
```

Then at the end of `create_pending_notification`:

```python
# Brief 217: best-effort alert dispatch. Wrapped in try/except so a
# dispatcher failure NEVER blocks the escalation row from being saved.
# Gated on notification_type == 'escalation' — relay rows (Marina asks
# the team a question) reuse this helper but should NOT trigger alerts;
# they're not the operator-facing "human needed now" event SR's contract
# is targeting.
if notification_type == "escalation" and _alert_dispatcher is not None:
    try:
        _alert_dispatcher(row_id, customer_name, channel, subject, mode=None)
    except Exception:
        pass  # alerts are best-effort

return row_id
```

(Note: `mode=None` for now — at create time, the mode column hasn't been set yet. Brief 213 sets mode via `/escalations/:id/mode`, AFTER the row exists. So new escalations always alert with mode="(unset)" until the operator picks soft/hard. Acceptable for v1 — the alert is just the "you have an escalation" ping; mode shows up when operator opens the dashboard.)

In `dashboard/api.py`, register the dispatcher **immediately after** the `_fire_escalation_alerts` function definition added in Step 3 (around `api.py:1144`, NOT at the top of the module — the function must be defined before the registration line runs, otherwise NameError at module import → app fails to boot):

```python
# Brief 217: register the alert dispatcher with state_registry. Placed
# directly after the function definition above so the name resolves at
# module-load time. webhook_server imports dashboard.api at startup,
# which evaluates this line, which wires the callback into state_registry.
state_registry.set_alert_dispatcher(_fire_escalation_alerts)
```

### Step 5 — Endpoints in `wtyj/dashboard/api.py`

Insert near the existing `/settings/dry-run` endpoints (around `api.py:734`):

```python
class AlertChannelConfig(BaseModel):
    enabled: bool = False
    destination: str = ""


class AlertSettingsRequest(BaseModel):
    channels: dict[str, AlertChannelConfig]


@router.get("/settings/escalation-alerts", dependencies=[Depends(_check_auth)])
async def get_alert_settings_endpoint():
    biz = config_loader.get_business() or {}
    default_email = biz.get("support_email", "") or biz.get("email", "")
    return state_registry.get_alert_settings(default_email_destination=default_email)


@router.put("/settings/escalation-alerts", dependencies=[Depends(_check_auth)])
async def put_alert_settings_endpoint(req: AlertSettingsRequest):
    # Convert the typed model into the plain dict the helper expects
    channels_dict = {k: v.dict() for k, v in req.channels.items()}
    state_registry.save_alert_settings(channels_dict)
    biz = config_loader.get_business() or {}
    default_email = biz.get("support_email", "") or biz.get("email", "")
    return state_registry.get_alert_settings(default_email_destination=default_email)
```

## Tests (9)

In `wtyj/tests/social/test_217_alert_delivery.py`. Use TestClient + real state_registry + cleanup helpers. **Test file MUST import `from agents.social.webhook_server import app` at module top** to trigger `dashboard.api`'s import-time registration of `_fire_escalation_alerts` with `state_registry.set_alert_dispatcher`. Tests that import only `from shared import state_registry` would silently skip the dispatcher (False-positive risk noted in Why-this-approach). Mock `smtp_send` and `send_whatsapp_message` so tests don't actually send.

1. **`test_get_alert_settings_synthesizes_default_when_no_row`** — clean DB (delete any existing row), GET `/settings/escalation-alerts`, assert response shape matches contract: email enabled, others disabled.
2. **`test_put_alert_settings_persists`** — PUT with `{channels: {email: {enabled: true, destination: "ops@example.com"}, whatsapp: {enabled: true, destination: "+5991234"}, ...}}`, then GET, assert values persisted.
3. **`test_create_pending_notification_fires_email_alert`** — set alert_settings to email-only enabled, mock `smtp_send`, call `state_registry.create_pending_notification(...)`, assert smtp_send was called once with the expected message body, alert_deliveries has one row with status="sent".
4. **`test_create_pending_notification_fires_whatsapp_alert_to_configured_destination`** — set alert_settings to whatsapp enabled with `+15551234`, mock `send_whatsapp_message` to return True, call `create_pending_notification`, assert `send_whatsapp_message` was called with `"+15551234"` (NOT the business whatsapp), alert_deliveries row has status="sent".
5. **`test_alert_dispatch_failure_does_not_block_escalation_creation`** — mock `smtp_send` to raise, call `create_pending_notification`, assert the pending_notifications row was still created, alert_deliveries has one row with status="failed".
6. **`test_telegram_enabled_records_skipped_with_provider_not_configured`** — enable telegram in alert_settings, fire an escalation, assert alert_deliveries has telegram row with status="skipped" and error mentions "telegram provider not configured".
7. **`test_messenger_enabled_records_skipped`** — same as 6 for messenger.
8. **`test_email_enabled_with_no_destination_records_skipped`** — set email enabled but destination="", and ensure default_email is also empty (`support_email` not in client.json), assert alert_deliveries email row is "skipped" with error about no destination.
9. **`test_relay_notification_does_NOT_fire_alerts`** — set alert_settings to email enabled, mock smtp_send. Call `state_registry.create_pending_notification(notification_type="relay", ...)` (NOT "escalation"). Assert smtp_send was NOT called and no alert_deliveries row was written for this row. Critical regression guard against the reviewer-caught issue where every relay row would spam the operator's WhatsApp.

Baseline: 989 passing (988 from Brief 218 + 1 from the post-218 `[FIX] /guidance` hotfix at commit `2e36547`). Target: 998 passing / 0 failures.

## Success Condition

After deploy:
1. SR opens Settings → Escalation Alerts in the dashboard.
2. Operator types their personal phone number for WhatsApp alerts and clicks Save.
3. Backend `PUT /settings/escalation-alerts` succeeds.
4. Customer triggers an escalation (e.g., types "I want to speak to a human" on WhatsApp).
5. Within seconds, the operator's personal phone receives a WhatsApp message:
   ```
   New escalation in Unboks
   Customer: Calvin Adamus
   Channel: whatsapp
   Mode: (unset)
   Summary: [ESCALATION] I want to speak to a human
   Action: Open dashboard to review.
   ```
6. The hello@unboks.org Gmail also receives the same alert text.
7. Live verification:
   ```bash
   ssh root@108.61.192.52 'docker exec wtyj-unboks python3 -c "
   from shared import state_registry
   rows = state_registry._get_conn().execute(
     \"SELECT channel, status, error FROM alert_deliveries ORDER BY id DESC LIMIT 5\"
   ).fetchall()
   for r in rows: print(r)
   "'
   ```
   Recent rows should show `('whatsapp', 'sent', None)`, `('email', 'sent', None)`.

## Rollback

`git revert <commit>`, push, canary redeploys. The two new tables stay in place (SQLite ALTER TABLE DROP is destructive); they simply become unread. The dispatcher hook in state_registry returns to None — alerts stop firing on new escalations. No data loss. The escalation flow itself is unchanged: the row is still inserted, dashboard still shows it; only the active-notification side is disabled.

If the dispatcher introduces a regression that causes `create_pending_notification` to slow down (WhatsApp send latency stacking), revert is the same one-line git revert. Operator can manually re-poll the dashboard while we debug.
