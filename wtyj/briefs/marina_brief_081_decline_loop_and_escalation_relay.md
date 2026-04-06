# BRIEF 081 — Fix Booking Decline Loop + Escalation Relay-Back
**Status:** Approved | **Files:** `agents/social/social_agent.py`, `agents/marina/email_poller.py`, `tests/social/test_077_relay_bridge.py` | **Depends on:** 080 | **Blocks:** —

## Context
Two bugs found during live WhatsApp E2E testing on 2026-03-13:

**Bug A — Booking decline loop.** When `awaiting_booking_confirmation=True` and the customer says "no", Claude sets `awaiting_booking_confirmation: false` but keeps intent as "booking". Post-validate then sees: booking intent + all fields present + not awaiting + not confirmed → rebuilds the exact same booking summary → sets `awaiting_booking_confirmation: true` again. Customer gets the same summary on loop until they say "leave me alone" (triggers full escalation). Observed 3x in the same conversation.

**Bug B — Escalation replies don't relay back.** When a WhatsApp customer triggers full escalation (`requires_human=True`), social_agent creates a `[ESCALATION]` notification — no relay token. The email_poller has explicit drop code: `if "[ESCALATION]" in subj → "Dropped escalation reply — one-way flow"`. When the operator replies, the answer never reaches the customer's WhatsApp. Semi-escalation (`[RELAY-xxx]`) works correctly; full escalation doesn't.

## Why This Approach

**Bug A:** Two-layer fix — prompt + Python guard. The action_context prompt only has 3 options (confirm/change/unclear) with no "decline" option. Adding option (d) tells Claude to use a non-booking intent when the customer declines. The Python guard checks whether Claude returned any new booking fields — if `_was_awaiting` was True and Claude returned NO booking fields (decline), post-validate is skipped; if Claude returned new fields (change details), post-validate runs and builds a new summary. This preserves the change-details flow while breaking the decline loop. Covers both files (social_agent + email_poller) since the pattern is identical.

The alternative of a blanket `and not _was_awaiting` guard was considered but rejected — it would block post-validate when the customer changes details (e.g., "make it 6 guests"), preventing the new summary from being generated.

**Bug B:** Add relay tokens to WhatsApp full escalation notifications. The `[RELAY-xxx]` token goes into the escalation email subject alongside `[ESCALATION]`. The existing relay handler in email_poller already processes `[RELAY-xxx]` replies and sends them back to WhatsApp — no new relay code needed. The escalation drop condition gets narrowed to only drop emails with `[ESCALATION]` but WITHOUT `[RELAY-` (preserving the drop for email-channel escalations that don't need relay-back). After the relay fires, `fully_escalated` gets cleared so the bot resumes normal operation.

The alternative of building a separate escalation-reply handler was rejected — the relay handler already does exactly what's needed.

## Source Material

### `_build_action_context()` — social_agent.py lines 87-101 (current)
```python
def _build_action_context(flags):
    """Build action_context string for the Claude prompt based on flags."""
    if flags.get("awaiting_booking_confirmation"):
        return (
            "ACTION: A booking summary was sent. The customer is replying. "
            "Determine if they are: (a) confirming — set booking_confirmed: true, "
            "awaiting_booking_confirmation: false, write a warm celebratory reply "
            "with the exact string [PAYMENT_LINK] where the payment link goes. "
            "Also write reply_hold_failed — an apologetic message if the slot turns "
            "out to be unavailable, without [PAYMENT_LINK]; "
            "(b) changing something — extract new fields, set "
            "awaiting_booking_confirmation: false; (c) unclear — ask "
            "for clarification. Do NOT generate a new booking summary."
        )
    return ""
```

### `_build_action_context()` — email_poller.py lines 411-426 (current)
```python
def _build_action_context(th):
    """Build action_context string for the Claude prompt based on thread state."""
    flags = th.get("flags", {})
    if flags.get("awaiting_booking_confirmation"):
        return (
            "ACTION: A booking summary was sent. The customer is replying. "
            "Determine if they are: (a) confirming — set booking_confirmed: true, "
            "awaiting_booking_confirmation: false, write a warm celebratory reply "
            "with the exact string [PAYMENT_LINK] where the payment link goes. "
            "Also write reply_hold_failed — an apologetic message if the slot turns "
            "out to be unavailable, without [PAYMENT_LINK]; "
            "(b) changing something — extract new fields, set "
            "awaiting_booking_confirmation: false; (c) unclear — ask "
            "for clarification. Do NOT generate a new booking summary."
        )
    return ""
```

### Post-validate guard — social_agent.py line 399
```python
    if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
```

### Post-validate guard — email_poller.py line 842
```python
                if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
```

### Escalation drop — email_poller.py lines 609-613
```python
                # Drop operator replies to [ESCALATION] alerts — escalation is one-way
                if from_email.lower() == demo_support_email.lower() and "[ESCALATION]" in subj:
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    log(f"Dropped escalation reply from {from_email} — one-way flow")
                    continue
```

### Full escalation notification — social_agent.py lines 546-572
```python
        # Build escalation alert for operator
        _esc_ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
        _esc_intents = ", ".join(result.get("intents") or ["unknown"])
        # ...
        _esc_subject = (
            f"[ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_intents}")
        # ...
        state_registry.create_pending_notification(
            'escalation', 'whatsapp', phone, _cname,
            _esc_subject, _esc_body)
```

### WhatsApp relay handler — email_poller.py lines 639-656
```python
                            _wa_agent_flags = dict(_wa_flags)
                            for _rk in ("awaiting_relay", "relay_token",
                                        "relay_question", "reply_times"):
                                _wa_agent_flags.pop(_rk, None)
                            # ... reformulate via marina_agent ... send to WhatsApp ...
                            _wa_flags.pop("awaiting_relay", None)
                            _wa_flags.pop("relay_token", None)
                            _wa_flags.pop("relay_question", None)
                            state_registry.wa_save_booking_state(
                                _wa_phone, _wa_fields, _wa_flags,
                                _wa_state.get("completed_bookings", []))
```

## Instructions

### Part A — Fix booking decline loop

#### Step A1: Update `_build_action_context()` in `agents/social/social_agent.py`

Replace the return string (lines 91-99) with:
```python
        return (
            "ACTION: A booking summary was sent. The customer is replying. "
            "Determine if they are: (a) confirming — set booking_confirmed: true, "
            "awaiting_booking_confirmation: false, write a warm celebratory reply "
            "with the exact string [PAYMENT_LINK] where the payment link goes. "
            "Also write reply_hold_failed — an apologetic message if the slot turns "
            "out to be unavailable, without [PAYMENT_LINK]; "
            "(b) changing something — extract new fields, set "
            "awaiting_booking_confirmation: false; "
            "(c) unclear — ask for clarification; "
            "(d) declining or saying no — set awaiting_booking_confirmation: false, "
            "use intent 'inquiry' (not 'booking'), acknowledge gracefully and ask "
            "if they'd like to look at something else. "
            "Do NOT generate a new booking summary."
        )
```

#### Step A2: Update `_build_action_context()` in `agents/marina/email_poller.py`

Same change — replace lines 416-424 with the identical string from Step A1.

#### Step A3: Add Python guard in `agents/social/social_agent.py`

At line 399, replace:
```python
    if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        _pv_override, _pv_set_awaiting = _post_validate(fields, flags, result, _pv_trip)
```
with:
```python
    _run_pv = any(i in _BOOKING_INTENTS for i in result.get("intents", []))
    # Guard: if customer was responding to a booking summary and didn't change
    # any booking fields, skip post-validate to prevent decline loop
    if _run_pv and _was_awaiting and not flags.get("booking_confirmed"):
        _new_f = result.get("fields", {}) or {}
        if not any(_new_f.get(k) for k in ("experience", "date", "guests", "trip_key", "departure_time")):
            _run_pv = False
    if _run_pv:
        _pv_override, _pv_set_awaiting = _post_validate(fields, flags, result, _pv_trip)
```

#### Step A4: Add Python guard in `agents/marina/email_poller.py`

At line 842, replace:
```python
                if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
                    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_trip)
```
with:
```python
                _run_pv = any(i in _BOOKING_INTENTS for i in result.get("intents", []))
                # Guard: if customer was responding to a booking summary and didn't change
                # any booking fields, skip post-validate to prevent decline loop
                if _run_pv and _was_awaiting and not th["flags"].get("booking_confirmed"):
                    _new_f = result.get("fields", {}) or {}
                    if not any(_new_f.get(k) for k in ("experience", "date", "guests", "trip_key", "departure_time")):
                        _run_pv = False
                if _run_pv:
                    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_trip)
```

### Part B — Fix escalation relay-back

#### Step B1: Add relay token to full escalation in `agents/social/social_agent.py`

In the full escalation handler (Step 7.6), after line 532 (`flags["awaiting_booking_confirmation"] = False`), add relay flags:
```python
        # Generate relay token for WhatsApp escalations — allows operator reply-back
        _esc_relay_token = uuid.uuid4().hex[:12]
        flags["awaiting_relay"] = True
        flags["relay_token"] = _esc_relay_token
```

#### Step B2: Update escalation subject to include relay token

Change the `_esc_subject` construction (lines 557-559) from:
```python
        _esc_subject = (
            f"[ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_intents}")
```
to:
```python
        _esc_subject = (
            f"[RELAY-{_esc_relay_token}] [ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_intents}")
```

#### Step B3: Pass relay token to `create_pending_notification`

Change the notification creation (lines 570-572) from:
```python
        state_registry.create_pending_notification(
            'escalation', 'whatsapp', phone, _cname,
            _esc_subject, _esc_body)
```
to:
```python
        state_registry.create_pending_notification(
            'escalation', 'whatsapp', phone, _cname,
            _esc_subject, _esc_body, relay_token=_esc_relay_token)
```

#### Step B4: Add relay instructions to escalation email body

In the escalation body construction (lines 560-568), add relay instructions. After the last line of `_esc_body` (`f"{result.get('internal_note', '')}"`), append:
```python
            f"\n\nINSTRUCTIONS: Reply to this email with your answer.\n"
            f"Marina will relay it to the customer in her own words."
```

#### Step B5: Narrow the escalation drop condition in `agents/marina/email_poller.py`

Change lines 609-613 from:
```python
                # Drop operator replies to [ESCALATION] alerts — escalation is one-way
                if from_email.lower() == demo_support_email.lower() and "[ESCALATION]" in subj:
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    log(f"Dropped escalation reply from {from_email} — one-way flow")
                    continue
```
to:
```python
                # Drop operator replies to [ESCALATION] alerts without relay token — one-way flow
                if (from_email.lower() == demo_support_email.lower()
                        and "[ESCALATION]" in subj and "[RELAY-" not in subj):
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    log(f"Dropped escalation reply from {from_email} — no relay token, one-way flow")
                    continue
```

#### Step B6: Clear `fully_escalated` after relay fires

In the WhatsApp relay handler (email_poller.py), after the existing flag cleanup (lines 653-655), add one line to clear `fully_escalated`:

After:
```python
                            _wa_flags.pop("awaiting_relay", None)
                            _wa_flags.pop("relay_token", None)
                            _wa_flags.pop("relay_question", None)
```

Add:
```python
                            _wa_flags.pop("fully_escalated", None)
```

## Tests

### Test file: `tests/social/test_077_relay_bridge.py`

#### Update existing test 6: `test_full_escalation_inserts_notification`

Change the assertion on line 193 from:
```python
    assert match[0]["relay_token"] is None
```
to:
```python
    assert match[0]["relay_token"] is not None
    assert len(match[0]["relay_token"]) == 12
```

#### Add three new tests after `test_get_relay_by_token_ignores_replied`:

```python
# --- Test 2c: Full escalation creates relay token ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_full_escalation_creates_relay_token(mock_process, mock_sheets):
    """Full escalation notification has relay token for WhatsApp reply-back."""
    phone = "TEST_081_FULLRELAY_001"
    _cleanup_phone(phone)
    mock_process.return_value = _base_result(
        intents=["complaint"],
        reply="I'm sorry to hear that, let me get someone to help!",
        requires_human=True,
        internal_note="Customer unhappy",
    )
    msg = {"from": phone, "text": "I want a refund", "from_name": "Test"}
    handle_incoming_whatsapp_message(msg)
    # Check flags
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("fully_escalated") is True
    assert state["flags"].get("awaiting_relay") is True
    assert state["flags"].get("relay_token") is not None
    assert len(state["flags"]["relay_token"]) == 12
    # Check notification has relay token in subject
    pending = state_registry.get_pending_notifications()
    match = [p for p in pending if p["customer_id"] == phone]
    assert len(match) == 1
    assert match[0]["relay_token"] == state["flags"]["relay_token"]
    assert "[RELAY-" in match[0]["subject"]
    assert "[ESCALATION]" in match[0]["subject"]
    assert "INSTRUCTIONS: Reply to this email" in match[0]["body"]
    _cleanup_phone(phone)
```

```python
# --- Test 2d: Booking decline does not re-send summary ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_booking_decline_no_loop(mock_process, mock_sheets):
    """Customer saying 'no' to booking summary should not get summary again."""
    phone = "TEST_081_DECLINE_001"
    _cleanup_phone(phone)
    # Set up state: awaiting booking confirmation with all fields
    fields = {
        "trip_key": "sunset_cruise", "experience": "Sunset Cruise",
        "date": "2026-03-21", "guests": "4", "departure_time": "17:30",
        "customer_name": "Test Decline",
    }
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True}
    state_registry.wa_save_booking_state(phone, fields, flags)
    # Claude responds to "no" with decline — intent: inquiry, not booking
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="No problem! Would you like to look at other trips?",
        flags={"awaiting_booking_confirmation": False},
    )
    msg = {"from": phone, "text": "no thanks", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "No problem" in reply
    assert "Just to confirm" not in reply  # Must NOT contain booking summary
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is not True
    _cleanup_phone(phone)
```

```python
# --- Test 2e: Booking decline with booking intent still doesn't loop ---

@patch("agents.social.social_agent.sheets_writer.log_escalation")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_booking_decline_with_booking_intent_no_loop(mock_process, mock_sheets):
    """Even if Claude returns booking intent for a decline, guard prevents loop."""
    phone = "TEST_081_DECLINE_002"
    _cleanup_phone(phone)
    fields = {
        "trip_key": "sunset_cruise", "experience": "Sunset Cruise",
        "date": "2026-03-21", "guests": "4", "departure_time": "17:30",
        "customer_name": "Test Decline2",
    }
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True}
    state_registry.wa_save_booking_state(phone, fields, flags)
    # Claude returns booking intent but no new fields — decline scenario
    mock_process.return_value = _base_result(
        intents=["booking"],
        reply="Understood, no booking needed.",
        fields={},
        flags={"awaiting_booking_confirmation": False},
    )
    msg = {"from": phone, "text": "no", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "Understood" in reply
    assert "Just to confirm" not in reply  # Must NOT re-send booking summary
    _cleanup_phone(phone)
```

Run:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/test_077_relay_bridge.py -v
```

Expected: 12/12 pass (9 existing + 3 new).

Full regression:
```bash
python3 -m pytest tests/social/ -v
```

Expected: 104/104 pass (101 existing + 3 new).

## Success Condition
All 104 social tests pass (101 existing + 3 new). Booking decline no longer loops — including when Claude returns booking intent without new fields. Full escalation notifications have `[RELAY-xxx]` in subject. Operator replies to WhatsApp escalation emails are relayed back.

## Rollback
Revert changes to social_agent.py and email_poller.py. Remove new tests from test_077.
