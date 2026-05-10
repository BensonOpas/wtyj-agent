# BRIEF 240 — Operator WhatsApp alerts via Zernio + delivery-status truth

**Status:** Draft | **Files:** `wtyj/shared/state_registry.py` (3 new ALTER columns on `alert_settings`; new `get_resolved_operator_whatsapp_route` + `set_resolved_operator_whatsapp_route` helpers; switch `save_alert_settings` from `INSERT OR REPLACE` → `INSERT ... ON CONFLICT DO UPDATE` so the bootstrapped route columns survive a Settings save), `wtyj/dashboard/api.py` (rewrite the WhatsApp branch of `_fire_escalation_alerts` to use Zernio's `send_dm_reply` directly via the resolved route — no Meta fallback for operator alerts; add `whatsappZernioResolved: bool` to the `GET /settings/escalation-alerts` response), `wtyj/agents/social/webhook_server.py` (auto-resolve hook in `_process_zernio_event` — when an inbound Zernio WhatsApp message's normalized sender_id matches the configured `whatsapp_destination`, persist the conversation_id + account_id), `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND with 4 new behavioral tests) | **Depends on:** Brief 217 (alert dispatcher), Brief 226 (alternative email destination + INSERT OR REPLACE pattern), Brief 235 (escalation_dispatcher), Brief 238 (tenant isolation guard — auto-resolve runs AFTER the guard so misrouted webhooks cannot bootstrap a route), Brief 239 (rich alert body — `_fire_escalation_alerts` now passes `summary_dict` + `is_update`, both must thread through to the new Zernio path) | **Blocks:** Calvin actually receiving WA operator alerts at `+351963618003`. Settings UI showing "send a WA from this number to bootstrap" copy when route is unresolved.

## Context

Audit on issue #2 (https://github.com/BensonOpas/wtyj-agent/issues/2#issuecomment-4414611403) found:

- `alert_settings.whatsapp_enabled=1, whatsapp_destination='+351963618003'` for unboks. Settings save works.
- `alert_deliveries` for unboks escalations 15-20: WA rows alternate `failed`→`sent`. File log `/app/clients/unboks/logs/agent.log` shows the actual provider error path:
  - **Pre-2026-05-10:** every WA send to `+351963618003` returned HTTP 400 from Meta with body `"API access deactivated. To reactivate, go to the My Apps page to unarchive it." code=200 OAuthException`. The legacy Meta WhatsApp Business app (per Brief 143's migration to Zernio) was archived.
  - **From 2026-05-10 00:16 onward:** sends return `200` with a real `wamid` (e.g. `wamid.HBgMMzUxOTYzNjE4MDAzFQIAERgSMEFERDQxMTNBQTlBRTgxMEQxAA==`). Someone unarchived the Meta app between those timestamps.
- **Calvin still doesn't receive the alerts** because Meta accepts the API call but silently drops at delivery. `+351963618003` has never sent an inbound to the unboks Meta WhatsApp Business number → outside the 24-hour customer service window → free-form text not delivered. Only pre-approved templates (HSM) reach numbers outside the CSW; none configured. Meta returns 200+wamid regardless; the failure surfaces only via the asynchronous `statuses` webhook (which we don't currently consume for outbound).

**Architectural mismatch:** unboks customer chat goes through Zernio (post-Brief-143); operator alerts go through legacy Meta Cloud API because `wtyj/agents/social/whatsapp_client.py:111 send_whatsapp_message(customer_id, text)` routes phone-string args (`+351963618003` is 13 chars, not a 24-char Zernio hex conv_id) to `send_text_message` → Meta. Operator phone numbers are by definition not customers, so they're always outside any CSW → Meta free-form sends will never deliver, regardless of Meta app archive state.

**Calvin/Jr2 picked option A+C from the audit:**
- **A** — switch operator WA alert delivery to Zernio (same provider as unboks customer chat, no CSW issue). Bootstrap by having Calvin send one inbound WA from `+351963618003` to the unboks WA Business number; backend captures the Zernio `conversation_id` + `account_id` and stores them as the resolved operator route.
- **C** — stop reporting fake `sent` for the Meta operator-alert path. Solved by removing the Meta path from operator alerts entirely (Part A); the false-`sent` problem is eliminated by removal, not by adding a Meta statuses webhook listener (deferred to TASK-074-or-later).

### Current resolved state of the four `alert_settings` columns under audit

| Column | Today | After this brief |
|---|---|---|
| `whatsapp_destination` | `'+351963618003'` (the displayed phone) | unchanged — still the user-facing displayed phone number |
| `whatsapp_zernio_conversation_id` | (column does not exist) | NEW — populated by auto-resolve hook on first matching inbound |
| `whatsapp_zernio_account_id` | (column does not exist) | NEW — same |
| `whatsapp_zernio_resolved_at` | (column does not exist) | NEW — ISO timestamp of the bootstrap event |

`whatsapp_destination` is the human-readable phone Calvin types into Settings. The three new columns are the machine-readable Zernio route the dispatcher actually uses. They get populated automatically when the bootstrap WA inbound arrives.

## Why This Approach

Three options were considered:

**A — Add the three Zernio-route columns to `alert_settings` (chosen).** Simplest schema change. Same row already holds the user-facing destination, so the bootstrapped route lives next to it. No new table, no JOIN. ALTER ADD COLUMN preserves all existing rows. Tradeoff: `save_alert_settings` currently uses `INSERT OR REPLACE` which would clobber the resolved columns on every Settings save — we have to switch it to `INSERT ... ON CONFLICT DO UPDATE` (column-by-column UPSERT). Acceptable; `INSERT OR REPLACE` was lazy from the start.

**B — New `operator_alert_routes` table keyed by `(channel)` or `(channel, destination)`.** Cleaner conceptually if we ever support multiple operator destinations per channel. Rejected: we have one operator per tenant per channel today and no signal that's about to change. Premature normalization.

**C — Single JSON column on `alert_settings` storing the entire route as a JSON blob.** Rejected: harder to query/index; obscures the schema; SQLite JSON is fine for ad-hoc but feels wrong for what should be three first-class columns.

For the auto-resolve hook insertion point, four options were considered:

**i — Auto-resolve in the dashboard's `PUT /settings/escalation-alerts` handler when Calvin types the phone in Settings.** Rejected: Calvin doesn't have the Zernio conversation_id at typing time. The point is to capture it from a real Zernio webhook.

**ii — Auto-resolve in the WhatsApp client / sender layer.** Rejected: too far from the inbound metadata. The conversation_id + account_id are only present at the webhook ingestion boundary.

**iii — Auto-resolve in `_process_zernio_event` AFTER the Brief 238 tenant_guard (chosen).** Runs after the guard so misrouted webhooks (e.g., a Zernio webhook that should have hit a different tenant) cannot poison the route. Runs before the empty-text skip so even a one-character "hi" from Calvin bootstraps. WhatsApp-only gating (`platform == "whatsapp"`) so Calvin DMing the Instagram or Facebook account doesn't accidentally bootstrap the WA alert route.

**iv — A separate dashboard endpoint `POST /settings/escalation-alerts/whatsapp/bootstrap` that Calvin manually triggers.** Rejected: more steps for Calvin, no upside. The auto-resolve hook is observably correct (Calvin can verify in Settings that `whatsappZernioResolved: true` after sending).

For Part C delivery-status truth, two paths were considered:

**1 — Add a Meta `statuses` webhook listener that updates `alert_deliveries.status` to `delivery_failed` when Meta async-reports a failure.** Rejected for THIS brief: out of scope per Calvin's "do not overbuild if Zernio is now the actual operator alert path." Reserved for TASK-074-or-later if/when Meta returns to the operator-alert critical path (it shouldn't — Zernio is the canonical provider going forward).

**2 — Remove the Meta path from operator alerts entirely; document the status vocabulary in code comments (chosen).** Eliminates the false-`sent` problem at the source. The customer-reply paths in the rest of the codebase (relay reply, dashboard "Send WA" features) still use Meta and still have the same async-delivery-truth gap, but those are out of scope here.

## Instructions

### Step 1 — Schema additions in `wtyj/shared/state_registry.py`

In the `_get_conn` schema-migration block (next to the existing Brief 226 ALTER for `email_alternative_destination` at lines 460-466), add three more ALTER ADD COLUMN statements. Use the same try/except `sqlite3.OperationalError` pattern so existing tenant DBs migrate idempotently:

```python
# Brief 240: Zernio-route fields for operator WhatsApp alerts. The
# user-facing whatsapp_destination stays as the displayed phone (e.g.,
# "+351963618003"); these three columns capture the Zernio
# conversation_id + account_id needed for outbound delivery, populated
# automatically by the auto-resolve hook in webhook_server when the
# operator sends a bootstrap inbound from that number.
for _coldef in (
    "ADD COLUMN whatsapp_zernio_conversation_id TEXT",
    "ADD COLUMN whatsapp_zernio_account_id TEXT",
    "ADD COLUMN whatsapp_zernio_resolved_at TEXT",
):
    try:
        conn.execute(f"ALTER TABLE alert_settings {_coldef}")
    except sqlite3.OperationalError:
        pass  # column already exists
```

### Step 2 — Helpers in `wtyj/shared/state_registry.py`

Add two module-level functions next to `get_alert_settings` (around line 1690):

```python
def get_resolved_operator_whatsapp_route() -> dict | None:
    """Brief 240: return the Zernio route resolved for the operator
    WhatsApp alert destination, or None if not yet bootstrapped.

    Shape: {"conversation_id": str, "account_id": str, "resolved_at": str}.
    Both conversation_id and account_id must be non-empty for the route
    to count as resolved; otherwise returns None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT whatsapp_zernio_conversation_id, "
        "whatsapp_zernio_account_id, whatsapp_zernio_resolved_at "
        "FROM alert_settings WHERE id = 1").fetchone()
    conn.close()
    if not row or not row[0] or not row[1]:
        return None
    return {
        "conversation_id": row[0],
        "account_id": row[1],
        "resolved_at": row[2] or "",
    }


def set_resolved_operator_whatsapp_route(conversation_id: str,
                                          account_id: str) -> None:
    """Brief 240: persist the Zernio route for operator WhatsApp alerts.
    UPSERTs into alert_settings — preserves the user-controlled
    whatsapp_destination + enabled flags + email columns. Idempotent:
    re-running with the same conv_id + account_id is a no-op state-wise
    (except for resolved_at, which refreshes)."""
    if not conversation_id or not account_id:
        return  # defensive: never persist a half-resolved route
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO alert_settings (id, whatsapp_zernio_conversation_id, "
        "whatsapp_zernio_account_id, whatsapp_zernio_resolved_at, "
        "updated_at) VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "whatsapp_zernio_conversation_id = excluded.whatsapp_zernio_conversation_id, "
        "whatsapp_zernio_account_id = excluded.whatsapp_zernio_account_id, "
        "whatsapp_zernio_resolved_at = excluded.whatsapp_zernio_resolved_at, "
        "updated_at = excluded.updated_at",
        (conversation_id, account_id, now, now))
    conn.commit()
    conn.close()
```

### Step 3 — Convert `save_alert_settings` from `INSERT OR REPLACE` to `INSERT … ON CONFLICT DO UPDATE`

Currently (state_registry.py:1747-1758) `save_alert_settings` uses `INSERT OR REPLACE` which would clobber the new Zernio-route columns whenever Calvin saves Settings. Replace with column-explicit ON CONFLICT DO UPDATE so the resolved-route columns survive:

```python
conn.execute(
    "INSERT INTO alert_settings "
    "(id, email_enabled, email_destination, whatsapp_enabled, whatsapp_destination, "
    "telegram_enabled, telegram_destination, messenger_enabled, messenger_destination, "
    "email_alternative_destination, updated_at) "
    "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET "
    "email_enabled = excluded.email_enabled, "
    "email_destination = excluded.email_destination, "
    "whatsapp_enabled = excluded.whatsapp_enabled, "
    "whatsapp_destination = excluded.whatsapp_destination, "
    "telegram_enabled = excluded.telegram_enabled, "
    "telegram_destination = excluded.telegram_destination, "
    "messenger_enabled = excluded.messenger_enabled, "
    "messenger_destination = excluded.messenger_destination, "
    "email_alternative_destination = excluded.email_alternative_destination, "
    "updated_at = excluded.updated_at",
    (1 if em.get("enabled") else 0, em.get("destination", ""),
     1 if wa.get("enabled") else 0, wa.get("destination", ""),
     1 if tg.get("enabled") else 0, tg.get("destination", ""),
     1 if ms.get("enabled") else 0, ms.get("destination", ""),
     em.get("alternativeDestination", "") or "",
     now))
```

The new Zernio-route columns are NOT in the column list, so they're left alone. Critically, when a row doesn't exist yet (first save), the INSERT creates it without those columns (NULL by default), and the auto-resolve hook fills them later.

**Edge case to verify:** with the row not existing yet, the auto-resolve hook's INSERT (Step 2's `set_resolved_operator_whatsapp_route`) creates the row with NULL for all the user-controlled fields. That's acceptable — `get_alert_settings` already handles a row with NULL/empty defaults gracefully (lines 1718-1731 of state_registry.py treat empty strings as "default"). But the more common ordering will be: Calvin sets WA destination in Settings → save_alert_settings creates the row → Calvin sends bootstrap WA → auto-resolve UPDATEs the row.

### Step 4 — Auto-resolve hook in `wtyj/agents/social/webhook_server.py`

In `_process_zernio_event`, insert the auto-resolve block AFTER the Brief 238 tenant_guard check and BEFORE the empty-text skip. Locate the anchor by searching for the Brief 238 comment:

```python
        from shared.tenant_guard import is_account_allowed
        if not is_account_allowed(msg.get("account_id", ""), direction="inbound"):
            return

        # Brief 240: auto-resolve operator WhatsApp alert route. If this
        # inbound is from the configured operator phone (whatsapp_destination
        # in alert_settings), persist the Zernio conversation_id + account_id
        # so the alert dispatcher can deliver future operator alerts via
        # Zernio (not Meta). WhatsApp-only — DMing the IG/FB account does
        # not bootstrap a WA alert route. Best-effort: never blocks the
        # inbound event from being processed normally.
        if msg.get("platform") == "whatsapp":
            try:
                _alert_settings = state_registry.get_alert_settings(
                    default_email_destination="")
                _wa_dest = (((_alert_settings or {}).get("channels") or {})
                            .get("whatsapp") or {}).get("destination") or ""
                if _wa_dest:
                    _sender_digits = _normalize_phone_digits(
                        msg.get("sender_id", ""))
                    _dest_digits = _normalize_phone_digits(_wa_dest)
                    if _sender_digits and _sender_digits == _dest_digits:
                        state_registry.set_resolved_operator_whatsapp_route(
                            msg.get("conversation_id", ""),
                            msg.get("account_id", ""))
                        log("operator_whatsapp_route_resolved",
                            sender_digits=_sender_digits,
                            conversation_id=msg.get("conversation_id", "")[:20],
                            account_id=msg.get("account_id", "")[:20])
            except Exception as _e:
                log("operator_whatsapp_route_resolve_failed",
                    error=str(_e)[:200])

        text = msg.get("text", "")
```

Notes:
- Reuses the existing `_normalize_phone_digits` helper at `webhook_server.py:301` — same comparison pattern Brief 208's `ignored_phones` uses, so format-mismatched phones (with/without `+`, with separators) match correctly.
- Hook runs even when text is empty (a "hi" or even an emoji-only inbound bootstraps just fine — the conv_id/account_id are present regardless of text).
- Uses `state_registry.get_alert_settings(default_email_destination="")` — the dashboard's helper that returns the channels dict in SR's frontend shape. Slight overhead vs reading the DB directly, but consistent with how the dispatcher already reads settings.
- Best-effort try/except so a settings read failure (or any other unexpected error) never blocks the inbound message from being processed normally.

### Step 5 — Rewrite the WhatsApp branch of `_fire_escalation_alerts` in `wtyj/dashboard/api.py`

Replace the existing WhatsApp branch (lines 1708-1727 inside `_fire_escalation_alerts`, between the email branch and the telegram skip). New logic uses Zernio directly when route is resolved; never falls back to Meta:

```python
    wa = channels_cfg.get("whatsapp", {})
    if wa.get("enabled"):
        dest = wa.get("destination", "")
        if not dest:
            state_registry.record_alert_delivery(
                escalation_id, "whatsapp", "", "skipped",
                "no whatsapp destination configured")
        else:
            # Brief 240: operator WA alerts go via Zernio (same provider as
            # unboks customer chat, no Meta CSW issue). The route must be
            # bootstrapped by the operator sending one inbound WA from the
            # configured destination — webhook_server.py's auto-resolve hook
            # captures conv_id + account_id then. Until resolved, we record
            # `skipped` with the bootstrap reason (no fake `sent`).
            route = state_registry.get_resolved_operator_whatsapp_route()
            if not route:
                state_registry.record_alert_delivery(
                    escalation_id, "whatsapp", dest, "skipped",
                    "zernio_operator_destination_not_resolved")
            else:
                from agents.social.zernio_dm_client import send_dm_reply
                try:
                    ok = send_dm_reply(
                        route["conversation_id"],
                        route["account_id"],
                        alert_text)
                    if ok:
                        state_registry.record_alert_delivery(
                            escalation_id, "whatsapp", dest, "sent")
                    else:
                        state_registry.record_alert_delivery(
                            escalation_id, "whatsapp", dest, "failed",
                            "zernio_send_dm_reply_returned_false")
                except Exception as exc:
                    state_registry.record_alert_delivery(
                        escalation_id, "whatsapp", dest, "failed",
                        f"zernio_send_dm_reply_exception: {str(exc)[:200]}")
```

`alert_deliveries.destination` continues to record the user-facing phone string (`+351963618003`) so the operator-experience trail in the audit log matches what they see in Settings, even though the actual delivery route is the Zernio conversation_id+account_id.

`alert_text` is the Brief 239 rich body produced by `_build_alert_body(...)` earlier in the function — Zernio sends the same operator-friendly text the email gets. No special template needed.

**Critical: `send_whatsapp_message` is no longer called from `_fire_escalation_alerts`.** Verify no other inbound to this function still imports/uses it. (The customer-reply paths at `dashboard/api.py:2146` and `:2274` still use `send_whatsapp_message` — those are intentionally untouched per scope.)

### Step 6 — Surface the resolved-or-not flag in `GET /settings/escalation-alerts`

Modify `get_alert_settings` in state_registry.py to include the resolution flag in its return shape. The frontend can then show a "Send a WhatsApp from this number to bootstrap operator alerts" hint when `whatsappZernioResolved: false`:

```python
    # ... existing return dict ...
    return {
        "channels": {
            "email":     {
                "enabled": bool(row[0]),
                "destination": email_dest,
                "alternativeDestination": row[8] or "",
            },
            "whatsapp":  {
                "enabled": bool(row[2]),
                "destination": row[3] or "",
                # Brief 240: True when the operator has sent a bootstrap WA
                # inbound and the Zernio route is captured. False = next
                # alert will record `skipped` with bootstrap reason.
                "zernioResolved": bool(get_resolved_operator_whatsapp_route()),
            },
            "telegram":  {"enabled": bool(row[4]), "destination": row[5] or ""},
            "messenger": {"enabled": bool(row[6]), "destination": row[7] or ""},
        }
    }
```

Apply the same `zernioResolved: False` field to the `if not row` synthesized-default path so the response shape is uniform.

### Step 7 — Tests in `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND, do not rewrite)

Add 4 new tests at the bottom of the file:

```python
# ── Brief 240: operator WhatsApp alerts via Zernio + bootstrap ─────────

def test_wa_alert_unresolved_route_records_skipped_no_zernio_call(monkeypatch):
    """Brief 240: WA enabled + destination configured + Zernio route NOT yet
    resolved → alert dispatcher records 'skipped' with the bootstrap reason
    and does NOT call send_dm_reply or any Meta send function."""
    from dashboard import api as dapi
    from shared import state_registry
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"channels": {
                             "email": {"enabled": False, "destination": "", "alternativeDestination": ""},
                             "whatsapp": {"enabled": True, "destination": "+351963618003", "zernioResolved": False},
                         }})
    monkeypatch.setattr(state_registry, "get_resolved_operator_whatsapp_route",
                         lambda: None)
    captured = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: captured.append(a))
    # Sentinels: must NOT be called
    called = {"send_dm_reply": False, "send_whatsapp_message": False}
    monkeypatch.setattr("agents.social.zernio_dm_client.send_dm_reply",
                         lambda *a, **k: called.__setitem__("send_dm_reply", True) or True)
    monkeypatch.setattr(dapi, "send_whatsapp_message",
                         lambda *a, **k: called.__setitem__("send_whatsapp_message", True) or True)
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft",
        summary_dict={"reason": "x", "extractedDetails": {"intent": "scheduling"}},
        is_update=False)
    # Find the WA delivery row in captured calls
    wa_rows = [a for a in captured if len(a) >= 4 and a[1] == "whatsapp"]
    assert len(wa_rows) == 1
    eid, ch, dest, status = wa_rows[0][:4]
    assert status == "skipped"
    assert dest == "+351963618003"
    reason = wa_rows[0][4] if len(wa_rows[0]) > 4 else ""
    assert "zernio_operator_destination_not_resolved" in reason
    assert called["send_dm_reply"] is False
    assert called["send_whatsapp_message"] is False


def test_wa_alert_resolved_route_calls_zernio_records_sent(monkeypatch):
    """Brief 240: WA enabled + Zernio route resolved → alert dispatcher
    calls send_dm_reply with the route's conv_id + account_id and records
    'sent' on True."""
    from dashboard import api as dapi
    from shared import state_registry
    from agents.social import zernio_dm_client
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"channels": {
                             "email": {"enabled": False, "destination": "", "alternativeDestination": ""},
                             "whatsapp": {"enabled": True, "destination": "+351963618003", "zernioResolved": True},
                         }})
    monkeypatch.setattr(state_registry, "get_resolved_operator_whatsapp_route",
                         lambda: {"conversation_id": "convOPER123",
                                   "account_id": "acctZER999",
                                   "resolved_at": "2026-05-10T04:00:00+00:00"})
    captured_send = {}
    def fake_send(conv, acct, text):
        captured_send.update(conv=conv, acct=acct, text=text)
        return True
    monkeypatch.setattr(zernio_dm_client, "send_dm_reply", fake_send)
    captured_delivery = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: captured_delivery.append(a))
    dapi._fire_escalation_alerts(
        escalation_id=2, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft",
        summary_dict={"reason": "Calvin needs scheduling decision",
                       "operatorNeedsToDecide": "Choose a time",
                       "recommendedOptions": ["Confirm Friday 12:00"],
                       "extractedDetails": {"intent": "scheduling",
                                              "proposedTimes": ["Friday 12:00"]},
                       "latestCustomerMessage": "i wanna change to friday 12:00"},
        is_update=False)
    assert captured_send["conv"] == "convOPER123"
    assert captured_send["acct"] == "acctZER999"
    assert "Reason:" in captured_send["text"]  # rich Brief 239 body went through
    wa_rows = [a for a in captured_delivery if len(a) >= 4 and a[1] == "whatsapp"]
    assert len(wa_rows) == 1
    assert wa_rows[0][3] == "sent"
    assert wa_rows[0][2] == "+351963618003"  # destination is the user-facing phone


def test_wa_alert_zernio_failure_records_failed_with_reason(monkeypatch):
    """Brief 240: Zernio's send_dm_reply returns False → alert dispatcher
    records 'failed' with reason 'zernio_send_dm_reply_returned_false'."""
    from dashboard import api as dapi
    from shared import state_registry
    from agents.social import zernio_dm_client
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"channels": {
                             "email": {"enabled": False, "destination": "", "alternativeDestination": ""},
                             "whatsapp": {"enabled": True, "destination": "+351963618003", "zernioResolved": True},
                         }})
    monkeypatch.setattr(state_registry, "get_resolved_operator_whatsapp_route",
                         lambda: {"conversation_id": "convX",
                                   "account_id": "acctY",
                                   "resolved_at": "2026-05-10T04:00:00+00:00"})
    monkeypatch.setattr(zernio_dm_client, "send_dm_reply",
                         lambda *a, **k: False)
    captured = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: captured.append(a))
    dapi._fire_escalation_alerts(
        escalation_id=3, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft",
        summary_dict={"reason": "x", "extractedDetails": {"intent": "scheduling"}},
        is_update=False)
    wa_rows = [a for a in captured if len(a) >= 4 and a[1] == "whatsapp"]
    assert len(wa_rows) == 1
    eid, ch, dest, status = wa_rows[0][:4]
    assert status == "failed"
    reason = wa_rows[0][4] if len(wa_rows[0]) > 4 else ""
    assert "zernio_send_dm_reply_returned_false" in reason


def test_inbound_wa_from_operator_phone_resolves_zernio_route(monkeypatch):
    """Brief 240: an inbound Zernio webhook whose normalized sender_id matches
    the configured whatsapp_destination triggers
    set_resolved_operator_whatsapp_route with the conv_id + account_id from
    the parsed message. WhatsApp-only — non-WA platforms do not bootstrap."""
    from agents.social import webhook_server
    from shared import state_registry
    payload = {"event": "message.received", "data": {
        "id": "msgB240a", "conversationId": "convOPER123",
        "accountId": "acctZER999", "platform": "whatsapp",
        "text": "hi", "sender": {"name": "Calvin", "id": "+351963618003"}}}
    parsed = {"conversation_id": "convOPER123", "platform": "whatsapp",
              "channel": "whatsapp", "sender_name": "Calvin",
              "sender_id": "+351963618003", "text": "hi",
              "message_id": "msgB240a", "account_id": "acctZER999"}
    monkeypatch.setattr(webhook_server, "parse_zernio_webhook",
                         lambda p: parsed)
    monkeypatch.setattr(webhook_server.state_registry, "wa_has_been_processed",
                         lambda mid: False)
    monkeypatch.setattr(webhook_server.state_registry,
                         "wa_mark_as_processed", lambda mid: None)
    monkeypatch.setattr(webhook_server.state_registry, "get_blocked",
                         lambda cid: False)
    # Settings: WA destination matches sender
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"channels": {
                             "whatsapp": {"enabled": True, "destination": "+351963618003"},
                         }})
    # tenant_guard returns True (allowlisted)
    monkeypatch.setattr("shared.tenant_guard.config_loader.get_raw",
                         lambda: {})
    captured = {}
    def fake_set_route(conv, acct):
        captured.update(conv=conv, acct=acct)
    monkeypatch.setattr(state_registry,
                         "set_resolved_operator_whatsapp_route", fake_set_route)
    # Stub the rest of the WA processing path so we don't actually buffer
    monkeypatch.setattr(webhook_server, "_buffer_message", lambda m: None)
    monkeypatch.setattr(webhook_server, "send_typing_indicator",
                         lambda *a, **k: None)
    webhook_server._process_zernio_event(payload)
    assert captured.get("conv") == "convOPER123"
    assert captured.get("acct") == "acctZER999"
```

Four tests. All exercise real branches: unresolved-skip, resolved-Zernio-success, Zernio-failure, inbound-bootstrap. No source-string greppers; no mock-the-thing-you-test.

**Regression baseline:** 1029 passing / 0 failures (per Brief 239 system_state). After this brief: **1033 passing / 0 failures** (1029 + 4 new).

## Success Condition

After execution:

1. `python3 -m pytest wtyj/tests/social/test_217_alert_delivery.py -q` passes (existing 16 + 4 new = 20).
2. `python3 -m pytest wtyj/tests/ -q` reports 1033 passing / 0 failures.
3. `python3 -c "from shared.state_registry import get_resolved_operator_whatsapp_route; print(get_resolved_operator_whatsapp_route())"` returns `None` on a fresh test DB; returns the dict shape after `set_resolved_operator_whatsapp_route('convX', 'acctY')` followed by another get.
4. After deploy, `curl -sf https://api.unboks.org/api/unboks/dashboard/api/settings/escalation-alerts -H "Authorization: Bearer <token>"` returns `channels.whatsapp.zernioResolved: false` (until Calvin sends bootstrap WA).
5. After Calvin sends one inbound WA from `+351963618003` to the unboks WhatsApp Business number, the Zernio webhook fires → `_process_zernio_event` matches the digits → `set_resolved_operator_whatsapp_route` writes the columns → next `GET /settings/escalation-alerts` returns `zernioResolved: true`. Verifiable on VPS: `docker exec wtyj-unboks sqlite3 /app/data/state_registry.db "SELECT whatsapp_zernio_conversation_id, whatsapp_zernio_account_id, whatsapp_zernio_resolved_at FROM alert_settings WHERE id=1;"` returns three non-empty values.
6. Next escalation alert with the route resolved produces an `alert_deliveries` row with `channel='whatsapp', destination='+351963618003', status='sent'` AND Calvin actually receives the WA message at `+351963618003`. Until the route resolves, escalations record `status='skipped', error='zernio_operator_destination_not_resolved'` instead of fake `sent`.
7. CI green; all 4 containers healthy; `tenant_guard.is_account_allowed` still importable in unboks/bluemarlin (Brief 238 not regressed); existing Brief 239 tests in the same file all still pass.

## Rollback

Code-only rollback: `git revert <this brief's source commit>` and push. The pipeline auto-deploys the revert (~90s). The three new ALTER ADD COLUMN statements stay in the schema (SQLite ALTER ADD is forward-compatible — old code ignores unknown columns). The columns sit unused after a revert.

If only the WA dispatcher branch is misbehaving (e.g., Zernio rejects the bootstrap conv_id for some reason), set the alert settings WhatsApp `enabled` flag to `false` via `PUT /settings/escalation-alerts` and `docker compose restart wtyj-unboks`. Email alerts continue working unchanged. To clear a bad bootstrap and force re-resolution, run on the VPS: `docker exec wtyj-unboks sqlite3 /app/data/state_registry.db "UPDATE alert_settings SET whatsapp_zernio_conversation_id=NULL, whatsapp_zernio_account_id=NULL, whatsapp_zernio_resolved_at=NULL WHERE id=1;"` — Calvin then re-sends the bootstrap WA.
