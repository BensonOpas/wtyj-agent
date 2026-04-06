# BRIEF 077 — WhatsApp Operator Notification + Relay Bridge
**Status:** Draft | **Files:** `shared/state_registry.py`, `agents/social/social_agent.py`, `agents/marina/email_poller.py`, `tests/social/test_077_relay_bridge.py` (new), `tests/social/test_074_semi_ratelimit.py` | **Depends on:** Briefs 074, 076 | **Blocks:** nothing

## Context
When a WhatsApp customer asks an unanswerable question (semi-escalation) or requires human help (full escalation), the operator is not notified. Semi-escalation is currently promoted to full escalation (`fully_escalated = True`) because there was no relay bridge. Full escalation only logs to Sheets — no email alert. The email system has both: a two-way relay bridge (operator replies via email, Marina reformulates and sends back) and one-way escalation notifications. WhatsApp needs parity.

## Why This Approach
Three options for cross-process communication (social agent → email poller):

1. **Social agent sends email directly** — Requires SMTP access (Azure OAuth tokens, refresh logic). The email_poller owns all SMTP machinery. Duplicating it in the social agent violates single-responsibility and creates a second OAuth token consumer.
2. **Shared SQLite queue table** — Social agent writes notifications to SQLite. Email poller picks them up during its poll cycle (~30s) and sends via existing SMTP. Adds at most 30 seconds latency, which is invisible for "let me check with the team" scenarios. No new SMTP consumers. Clean separation.
3. **HTTP API between processes** — Over-engineered for the volume (5-10 escalations/day max).

**Chosen: Option 2.** Simplest, no new dependencies, operator experience is identical (reply to email). The email poller already monitors the inbox for relay replies — extending it to also check WhatsApp relays is a minor addition.

## Source Material

### Pending notifications table schema
```sql
CREATE TABLE IF NOT EXISTS pending_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_type TEXT NOT NULL,
    relay_token TEXT UNIQUE,
    channel TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    customer_name TEXT DEFAULT '',
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL
)
```

### Current WhatsApp semi-escalation (social_agent.py lines 466-494)
Sets `fully_escalated = True`, logs to Sheets with intent "semi_to_full_escalation". No relay flags. No operator notification.

### Current WhatsApp full escalation (social_agent.py lines 497-524)
Sets `fully_escalated = True`, logs to Sheets. No operator email notification.

### Email relay alert format (email_poller.py lines 902-916)
```
Subject: [RELAY-{token}] {booking_ref} - {customer_name}
Body:
Customer: {name} <{email}>
Their question: {question}

Booking context:
  Trip: {trip_key} | Date: {date} | Guests: {guests}
  Ref: {booking_ref}

INSTRUCTIONS: Reply to this email with your answer.
Marina will relay it to the customer in her own words.
```

### Email escalation alert format (email_poller.py lines 964-978)
```
Subject: [ESCALATION] {booking_ref} - {name} ({email}) - {intents}
Body:
=== CUSTOMER ===
Email: {email}
Name: {name}
Phone: {phone}

=== CHAT LOG ===
{chat_log}

=== BOOKING FIELDS ===
{fields_json}

=== MARINA'S INTERNAL NOTE ===
{internal_note}
```

### Email relay detection (email_poller.py lines 614-666)
Matches `[RELAY-{12-char-hex}]` in subject when sender is `demo_support_email`. Iterates email threads to find matching `relay_token`. Calls marina_agent to reformulate operator's answer. Sends reformulated reply to customer via SMTP. Clears relay flags.

### social_agent.py flag stripping (lines 268-271)
Already strips `awaiting_relay`, `relay_token`, `relay_question` before passing to marina_agent. No change needed.

### social_agent.py stale reset (lines 196-200)
Already clears `awaiting_relay`, `relay_token`, `relay_question` during stale conversation reset. No change needed.

### Deployment note
Both `bluemarlin` and `bluemarlin-social` systemd services must source `config/bluemarlin.env`. The email_poller will import `send_text_message` from `whatsapp_client.py`, which reads `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` at import time. These env vars must be available in the email_poller's environment.

### demo_support_email source
`config_loader.get_business().get("demo_support_email", "butlerbensonagent@gmail.com")` — same for both channels.

## Instructions

### Step 1 — Add pending_notifications table + CRUD to state_registry.py

Add the table creation inside `_get_conn()`, after the `whatsapp_booking_state` table (after line 98):

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pending_notifications ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "notification_type TEXT NOT NULL, "
        "relay_token TEXT UNIQUE, "
        "channel TEXT NOT NULL, "
        "customer_id TEXT NOT NULL, "
        "customer_name TEXT DEFAULT '', "
        "subject TEXT NOT NULL, "
        "body TEXT NOT NULL, "
        "status TEXT DEFAULT 'pending', "
        "created_at TEXT NOT NULL"
        ")"
    )
```

Add four functions before the `_get_conn().close()` line at the end of the file:

```python
def create_pending_notification(notification_type: str, channel: str,
                                 customer_id: str, customer_name: str,
                                 subject: str, body: str,
                                 relay_token: str = None) -> int:
    """Insert a pending notification for the email poller to send. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, relay_token, channel, customer_id, customer_name, "
        "subject, body, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (notification_type, relay_token, channel, customer_id, customer_name,
         subject, body, datetime.now(timezone.utc).isoformat())
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_pending_notifications(status: str = "pending") -> list:
    """Return all notifications with the given status."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications WHERE status = ? ORDER BY created_at ASC",
        (status,)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "notification_type": r[1], "relay_token": r[2],
             "channel": r[3], "customer_id": r[4], "customer_name": r[5],
             "subject": r[6], "body": r[7], "status": r[8], "created_at": r[9]}
            for r in rows]


def update_notification_status(notification_id: int, status: str) -> bool:
    """Update the status of a pending notification. Returns True if row updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE pending_notifications SET status = ? WHERE id = ?",
        (status, notification_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_relay_by_token(relay_token: str) -> "dict | None":
    """Look up a relay notification by token. Returns dict or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications WHERE relay_token = ?",
        (relay_token,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "notification_type": row[1], "relay_token": row[2],
            "channel": row[3], "customer_id": row[4], "customer_name": row[5],
            "subject": row[6], "body": row[7], "status": row[8], "created_at": row[9]}
```

Update header to `Last modified: Brief 077`.

### Step 2 — Revert semi-escalation in social_agent.py

Add `import uuid` to the imports (after `import json`, line 8).

Replace the semi-escalation block (Step 7.5, lines 466-494) with:

```python
    # Step 7.5: Semi-escalation → create relay (operator notified via email poller)
    if result.get("semi_escalation"):
        relay_question = result.get("relay_question", "(no question captured)")
        # Cancel any soft hold (capacity leak prevention)
        if flags.get("hold_id"):
            state_registry.cancel_hold(flags["hold_id"])
            _h_trip = flags.pop("hold_trip_key", "")
            _h_date = flags.pop("hold_date", "")
            _h_dep = flags.pop("hold_departure_time", "")
            flags.pop("hold_id", None)
            if _h_trip and _h_date and _h_dep:
                gws_calendar.remove_from_manifest(_h_trip, _h_date, _h_dep)
        flags["slot_checked"] = False
        flags["slot_available"] = False
        flags["awaiting_booking_confirmation"] = False
        # Set relay flags (proper relay bridge, not promote to full)
        relay_token = uuid.uuid4().hex[:12]
        flags["awaiting_relay"] = True
        flags["relay_token"] = relay_token
        flags["relay_question"] = relay_question
        reply_text = result["reply"]
        # Build relay alert for operator
        _ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
        _cname = fields.get("customer_name", "Unknown")
        _alert_subject = f"[RELAY-{relay_token}] {_ref} - {_cname}"
        _alert_body = (
            f"Customer: {_cname} (WhatsApp: {phone})\n"
            f"Their question: {relay_question}\n\n"
            f"Booking context:\n"
            f"  Trip: {fields.get('trip_key', '')} | "
            f"Date: {fields.get('date', '')} | "
            f"Guests: {fields.get('guests', '')}\n"
            f"  Ref: {_ref}\n\n"
            f"INSTRUCTIONS: Reply to this email with your answer.\n"
            f"Marina will relay it to the customer in her own words."
        )
        state_registry.create_pending_notification(
            'relay', 'whatsapp', phone, _cname,
            _alert_subject, _alert_body, relay_token=relay_token)
        sheets_writer.log_escalation({
            "email": phone,
            "subject": "WhatsApp",
            "customer_name": _cname,
            "intent": "semi_escalation",
            "fields_collected": fields,
            "internal_note": f"Relay question: {relay_question}",
            "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
        })
        bm_logger.log("whatsapp_semi_escalation", phone=phone,
                      relay_question=relay_question, relay_token=relay_token)
        _skip_booking = True
```

### Step 3 — Add full escalation notification in social_agent.py

In the full escalation block (Step 7.6, lines 497-524), add operator notification. After the existing `sheets_writer.log_escalation(...)` call (line ~521) and `bm_logger.log(...)` call (line ~523), add:

```python
        # Build escalation alert for operator
        _esc_ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
        _esc_intents = ", ".join(result.get("intents") or ["unknown"])
        _esc_history = state_registry.wa_get_history(phone, limit=20)
        _esc_chat_lines = []
        for _em in _esc_history:
            _esc_chat_lines.append(
                f"[{_em['role'].upper()} | {_em.get('created_at', '')}]")
            _esc_chat_lines.append(_em.get("text", ""))
            _esc_chat_lines.append("---")
        _esc_chat_log = "\n".join(_esc_chat_lines) or "(no messages logged)"
        _esc_subject = (
            f"[ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_intents}")
        _esc_body = (
            f"=== CUSTOMER ===\n"
            f"WhatsApp: {phone}\n"
            f"Name: {_cname}\n\n"
            f"=== CHAT LOG ===\n{_esc_chat_log}\n\n"
            f"=== BOOKING FIELDS ===\n"
            f"{json.dumps(fields, indent=2, ensure_ascii=False)}\n\n"
            f"=== MARINA'S INTERNAL NOTE ===\n"
            f"{result.get('internal_note', '')}"
        )
        state_registry.create_pending_notification(
            'escalation', 'whatsapp', phone, _cname,
            _esc_subject, _esc_body)
```

### Step 4 — Add pending notification processing to email_poller.py

Add import after the existing imports (after line 23):

```python
from agents.social.whatsapp_client import send_text_message as wa_send_text_message
```

In the `main()` function, after `im.logout()` (line 1177) and before the heartbeat write (line 1179), add:

```python
            # Process pending operator notifications (from WhatsApp)
            _pending = state_registry.get_pending_notifications()
            for _pn in _pending:
                try:
                    smtp_send(demo_support_email, _pn["subject"], _pn["body"],
                              reply_to=EMAIL_ADDR)
                    state_registry.update_notification_status(_pn["id"], "sent")
                    log(f"Sent pending {_pn['notification_type']} "
                        f"notification id={_pn['id']} for {_pn['customer_id']}")
                except Exception as _pn_err:
                    log(f"Failed to send pending notification "
                        f"id={_pn['id']}: {_pn_err}")
```

### Step 5 — Add WhatsApp relay detection to email_poller.py

In the relay detection block (lines 614-666), modify the `if customer_th is None:` branch (line 628). Replace:

```python
                    if customer_th is None:
                        log(f"RELAY: no matching customer thread for token={relay_token_in} — skipping")
                        im.uid("store", uid, "+FLAGS", r"(\Seen)")
                        save_json(THREAD_STATE_PATH, state)
                        continue
```

With:

```python
                    if customer_th is None:
                        # Check WhatsApp relay
                        _wa_relay = state_registry.get_relay_by_token(relay_token_in)
                        if _wa_relay and _wa_relay["channel"] == "whatsapp":
                            _wa_phone = _wa_relay["customer_id"]
                            _wa_state = state_registry.wa_get_booking_state(_wa_phone)
                            _wa_fields = _wa_state.get("fields", {})
                            _wa_flags = _wa_state.get("flags", {})
                            _wa_history = state_registry.wa_get_history(_wa_phone, limit=10)
                            _wa_agent_flags = dict(_wa_flags)
                            for _rk in ("awaiting_relay", "relay_token",
                                        "relay_question", "reply_times"):
                                _wa_agent_flags.pop(_rk, None)
                            relay_result = marina_agent.process_message(
                                _wa_phone, "", body,
                                _wa_fields, _wa_agent_flags,
                                channel="whatsapp", messages=_wa_history,
                            )
                            relay_reply = relay_result.get("reply", "")
                            if relay_reply:
                                wa_send_text_message(to=_wa_phone, text=relay_reply)
                                state_registry.wa_store_message(
                                    _wa_phone, "assistant", relay_reply)
                                log(f"RELAY: WhatsApp relay sent to {_wa_phone}")
                            _wa_flags.pop("awaiting_relay", None)
                            _wa_flags.pop("relay_token", None)
                            _wa_flags.pop("relay_question", None)
                            state_registry.wa_save_booking_state(
                                _wa_phone, _wa_fields, _wa_flags,
                                _wa_state.get("completed_bookings", []))
                            state_registry.update_notification_status(
                                _wa_relay["id"], "replied")
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            save_json(THREAD_STATE_PATH, state)
                            continue
                        log(f"RELAY: no matching thread for token={relay_token_in} — skipping")
                        im.uid("store", uid, "+FLAGS", r"(\Seen)")
                        save_json(THREAD_STATE_PATH, state)
                        continue
```

### Step 6 — Update email_poller.py and social_agent.py headers

```
# Last modified: Brief 077
```

### Step 7 — Update test_074 semi-escalation tests

**Test 1** (`test_semi_promotes_to_full_escalation`, line 52): Change assertions. Replace:
```python
    assert state["flags"].get("fully_escalated") is True
    assert "awaiting_relay" not in state["flags"]
    assert "relay_token" not in state["flags"]
    assert "relay_question" not in state["flags"]
```
With:
```python
    assert state["flags"].get("awaiting_relay") is True
    assert state["flags"].get("relay_token") is not None
    assert len(state["flags"]["relay_token"]) == 12
    assert "fully_escalated" not in state["flags"]
```

Also rename the function to `test_semi_creates_relay` and update the docstring to `"""Semi-escalation sets relay flags, not fully_escalated."""`. Update the section comment from `# --- Test 1: Semi-escalation promotes to full escalation ---` to `# --- Test 1: Semi-escalation creates relay ---`.

**Test 2** (`test_semi_with_hold_cancels_and_escalates`, line 78): Change the assertion. Replace:
```python
    assert state["flags"].get("fully_escalated") is True
```
With:
```python
    assert state["flags"].get("awaiting_relay") is True
```

Also rename to `test_semi_with_hold_cancels_and_creates_relay`. Update section comment to `# --- Test 2: Semi-escalation with hold cancels hold ---` (unchanged). Update docstring to `"""Semi-escalation cancels soft hold and sets relay flags."""`.

**Test 3** (`test_semi_escalation_sheets_logging`, line 111): Change the intent assertion. Replace:
```python
    assert sheets_data["intent"] == "semi_to_full_escalation"
    assert "Relay question (no relay bridge): Is 9pH water available?" in sheets_data["internal_note"]
```
With:
```python
    assert sheets_data["intent"] == "semi_escalation"
    assert "Relay question: Is 9pH water available?" in sheets_data["internal_note"]
```

**Test 4** (`test_post_semi_goes_through_escalated_guard`, line 132): This test pre-sets `fully_escalated: True`. Since semi-escalation no longer sets this flag, update the docstring from `"""After semi→full promotion, next message hits fully-escalated guard."""` to `"""After full escalation, next message hits fully-escalated guard."""`. No logic change needed — the test is still valid for full escalation.

### Step 8 — Create `tests/social/test_077_relay_bridge.py`

```python
# bluemarlin/tests/social/test_077_relay_bridge.py
# Created: Brief 077
# Purpose: Tests for WhatsApp relay bridge and operator notification
```

Standard imports + path setup + env vars (same pattern as test_074).

Additional imports:
```python
from shared import state_registry
from agents.social.social_agent import handle_incoming_whatsapp_message
```

**Cleanup helper** — same as test_074 plus pending_notifications cleanup:
```python
def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM trip_bookings WHERE customer_email = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.commit()
    conn.close()
```

**Test 1: create_pending_notification round-trip**
- Call `state_registry.create_pending_notification('relay', 'whatsapp', 'TEST_PHONE', 'Test User', '[RELAY-abc123] NO-REF - Test User', 'body text', relay_token='abc123def456')`
- Call `state_registry.get_pending_notifications()`
- Assert returned list has at least 1 entry matching customer_id='TEST_PHONE'
- Assert `notification_type == 'relay'`, `channel == 'whatsapp'`, `status == 'pending'`
- Assert `relay_token == 'abc123def456'`
- Clean up: `conn.execute("DELETE FROM pending_notifications WHERE customer_id = 'TEST_PHONE'")`

**Test 2: get_relay_by_token**
- Create a relay notification with `relay_token='aaa111bbb222'`
- Call `state_registry.get_relay_by_token('aaa111bbb222')`
- Assert result is not None
- Assert `result['channel'] == 'whatsapp'`
- Call `state_registry.get_relay_by_token('nonexistent')`
- Assert result is None
- Clean up

**Test 3: update_notification_status**
- Create a notification
- Call `state_registry.update_notification_status(row_id, 'sent')`
- Assert returns True
- Verify by calling `get_pending_notifications('sent')` — should find the row
- Verify `get_pending_notifications('pending')` — should NOT find it
- Clean up

**Test 4: Semi-escalation creates relay, not full escalation**
- Mock `marina_agent.process_message` to return `semi_escalation=True`, `relay_question="Is 9pH water available?"`, `reply="I'll check with the team!"`
- Mock `sheets_writer.log_escalation`
- `phone = "TEST_077_SEMI_001"`, `_cleanup_phone(phone)`
- Call `handle_incoming_whatsapp_message({"from": phone, "text": "Do you have 9pH water?", "from_name": "Test"})`
- Assert reply == "I'll check with the team!"
- `state = state_registry.wa_get_booking_state(phone)`
- Assert `state["flags"].get("awaiting_relay") is True`
- Assert `state["flags"].get("relay_token")` is not None and length 12
- Assert `state["flags"].get("relay_question") == "Is 9pH water available?"`
- Assert `"fully_escalated" not in state["flags"]`
- `_cleanup_phone(phone)`

**Test 5: Semi-escalation inserts pending notification**
- Same setup as Test 4, different phone: `"TEST_077_SEMI_002"`
- After calling `handle_incoming_whatsapp_message`, query `state_registry.get_pending_notifications()`
- Filter for `customer_id == phone`
- Assert exactly 1 notification found
- Assert `notification_type == 'relay'`
- Assert `channel == 'whatsapp'`
- Assert `'[RELAY-' in notification['subject']`
- Assert notification `relay_token` matches `state["flags"]["relay_token"]`
- `_cleanup_phone(phone)`

**Test 6: Full escalation inserts pending notification**
- Mock `marina_agent.process_message` to return `requires_human=True`, `reply="Let me get someone to help!"`, `intents=["complaint"]`, `internal_note="Customer unhappy"`
- Mock `sheets_writer.log_escalation`
- `phone = "TEST_077_FULL_001"`, `_cleanup_phone(phone)`
- Call `handle_incoming_whatsapp_message(...)`
- Assert reply == "Let me get someone to help!"
- `state = state_registry.wa_get_booking_state(phone)`
- Assert `state["flags"].get("fully_escalated") is True`
- Query `state_registry.get_pending_notifications()`
- Filter for `customer_id == phone`
- Assert exactly 1 notification
- Assert `notification_type == 'escalation'`
- Assert `'[ESCALATION]' in notification['subject']`
- Assert `relay_token is None` (escalation has no token)
- `_cleanup_phone(phone)`

**Test 7: Semi-escalation cancels soft hold**
- Pre-set booking state with `hold_id` from `create_soft_hold`
- Mock `marina_agent.process_message` to return `semi_escalation=True`
- Mock `sheets_writer.log_escalation`, mock `gws_calendar.remove_from_manifest`
- Call `handle_incoming_whatsapp_message(...)`
- Assert `state["flags"].get("awaiting_relay") is True`
- Assert `"hold_id" not in state["flags"]`
- Assert `state["flags"].get("slot_checked") is False`
- `_cleanup_phone(phone)`

**Test 8: Escalation alert body contains chat log**
- Mock `marina_agent.process_message` to return `requires_human=True`
- Mock `sheets_writer.log_escalation`
- Pre-populate WhatsApp history: `state_registry.wa_store_message(phone, "user", "I have a complaint")`
- Call `handle_incoming_whatsapp_message(...)`
- Query pending notification, assert `'I have a complaint' in notification['body']`
- Assert `'=== CUSTOMER ===' in notification['body']`
- Assert `'=== CHAT LOG ===' in notification['body']`
- `_cleanup_phone(phone)`

## Tests
Run:
```
cd bluemarlin && python3 -m pytest tests/social/test_077_relay_bridge.py -v
cd bluemarlin && python3 -m pytest tests/social/ -v   # full regression
```

Expected: 8/8 new tests pass, all existing social tests pass with updated semi-escalation assertions.

## Success Condition
WhatsApp semi-escalation creates a proper relay (operator email queued, relay flags set). Full escalation queues an operator notification email. Email poller sends queued notifications and detects WhatsApp relay replies. All tests pass.

## Rollback
Revert state_registry.py (remove pending_notifications table + functions). Revert social_agent.py (restore promote-to-full semi-escalation). Revert email_poller.py (remove pending notification processing + WhatsApp relay detection). Delete test_077. Revert test_074 semi-escalation assertions.
