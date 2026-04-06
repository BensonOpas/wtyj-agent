# BRIEF 071 — WhatsApp Escalation: Semi + Full + Fully-Escalated Guard

**Status:** Draft | **Files:** `agents/social/social_agent.py`, `tests/social/test_071_whatsapp_escalation.py` | **Depends on:** Brief 070 | **Blocks:** Brief 072

## Context

`social_agent.py` has the full booking orchestrator (Brief 070) but no escalation handling. `email_poller.py` has three escalation paths: semi-escalation (relay question to operator, holding reply to customer), full escalation (`requires_human`, holding reply + flag + operator alert), and a fully-escalated guard (holding replies for already-escalated threads, booking flow skipped). WhatsApp needs the same three paths. Additionally, relay flags (`awaiting_relay`, `relay_token`, `relay_question`) must be filtered from the flags sent to `marina_agent.process_message()` when processing normal customer messages — otherwise the RELAY MODE prompt injection fires for non-relay messages.

## Why This Approach

Same duplication-to-social-agent strategy as Brief 070 — extraction to `shared/` deferred to Phase 4. No cross-channel relay bridge (operator replies to relay email → answer auto-delivered to WhatsApp customer) in this brief because that requires `email_poller` to import `whatsapp_client`, creating a cross-module dependency better handled in Phase 2. Instead, relay state is stored in `whatsapp_booking_state` flags (existing SQLite table), and the operator sees relay questions via the Sheets Escalation tab. The operator can contact the customer directly on WhatsApp for now. The relay bridge can be added in a future brief by having `email_poller` check for WhatsApp relay tokens in `state_registry`.

## Source Material

### email_poller.py — Semi-escalation handler (lines 880–937)
```python
if result.get("semi_escalation"):
    relay_question = result.get("relay_question", "(no question captured)")
    # Cancel any soft hold created during Step 3b
    if th["flags"].get("hold_id"):
        state_registry.cancel_hold(th["flags"]["hold_id"])
        _h_trip = th["flags"].pop("hold_trip_key", "")
        _h_date = th["flags"].pop("hold_date", "")
        _h_dep = th["flags"].pop("hold_departure_time", "")
        th["flags"].pop("hold_id", None)
        if _h_trip and _h_date and _h_dep:
            gws_calendar.remove_from_manifest(_h_trip, _h_date, _h_dep)
    th["flags"]["slot_checked"] = False
    th["flags"]["slot_available"] = False
    relay_token = uuid.uuid4().hex[:12]
    th["flags"]["awaiting_relay"] = True
    th["flags"]["relay_token"] = relay_token
    th["flags"]["relay_question"] = relay_question
    th["flags"]["relay_customer_email"] = from_email        # email-only
    th["flags"]["relay_reply_subject"] = "Re: " + subj     # email-only
    # ... sends alert email to operator, sends Claude's reply to customer ...
    # NOTE: email_poller does NOT call sheets_writer.log_escalation for semi-escalation
    # (only bm_logger). The WhatsApp version adds Sheets logging as new behavior.
    bm_logger.log("semi_escalation", ...)
    continue
```

### email_poller.py — Full escalation handler (lines 939–998)
```python
if result.get("requires_human"):
    # Send Claude's reply to customer
    th["flags"]["fully_escalated"] = True
    bm_logger.log("human_required", ...)
    # Build escalation alert with chat log, fields, internal note
    sheets_writer.log_escalation({
        "email": from_email, "subject": subj,
        "customer_name": th["fields"].get("customer_name", ""),
        "intent": (result.get("intents") or ["unknown"])[0],
        "fields_collected": th["fields"],
        "internal_note": result.get("internal_note", ""),
        "messages_json": json.dumps(th.get("messages", []), ensure_ascii=False),
    })
    continue
```

### email_poller.py — Fully escalated guard (lines 676–699)
```python
if th["flags"].get("fully_escalated"):
    _esc_flags = dict(th.get("flags", {}))
    for _rk in ("awaiting_relay", "relay_token", "relay_question",
                "relay_customer_email", "relay_reply_subject"):
        _esc_flags.pop(_rk, None)
    result = marina_agent.process_message(
        from_email, subj, body, th.get("fields", {}), _esc_flags)
    smtp_send(from_email, "Re: " + subj, result["reply"], ...)
    continue  # skips entire booking flow
```

### email_poller.py — Relay flag filtering (lines 731–735)
```python
agent_flags = dict(th.get("flags", {}))
for _rk in ("awaiting_relay", "relay_token", "relay_question",
            "relay_customer_email", "relay_reply_subject"):
    agent_flags.pop(_rk, None)
```

### marina_agent.py — Result fields for escalation
```json
{
  "semi_escalation": true,
  "relay_question": "<exact question to relay>",
  "requires_human": true
}
```

### sheets_writer.log_escalation() signature (lines 141–162)
```python
def log_escalation(data: dict):
    # Expects: customer_name, email, intent, fields_collected (dict→JSON), internal_note, messages_json
```

### WhatsApp relay flags (subset of email — no relay_customer_email/relay_reply_subject)
WhatsApp doesn't need `relay_customer_email` (customer is identified by phone, the state key) or `relay_reply_subject` (no email subject). Only 3 relay flags: `awaiting_relay`, `relay_token`, `relay_question`.

## Instructions

### Step 1 — Modify `agents/social/social_agent.py`

**1a. Add imports** — After `import time`, add `import uuid` and `import json`:

```python
import time
import json
import uuid
from datetime import datetime, timezone, timedelta
```

**1b. Add fully-escalated guard** — Insert AFTER the `from_id = ...` line and BEFORE the `# Step 1: Build action context` comment. This is an early return that skips the entire booking flow:

```python
    # Fully escalated guard — still calls marina_agent (one Claude call), skip booking flow
    if flags.get("fully_escalated"):
        _esc_flags = dict(flags)
        for _rk in ("awaiting_relay", "relay_token", "relay_question"):
            _esc_flags.pop(_rk, None)
        esc_result = marina_agent.process_message(
            from_email=from_id, subject="", body=text,
            thread_fields=fields, thread_flags=_esc_flags,
            channel="whatsapp", messages=history,
        )
        esc_reply = esc_result.get("reply", "")
        bm_logger.log("whatsapp_escalated_reply", phone=phone,
                      reply_length=len(esc_reply))
        return esc_reply
```

**1c. Add relay flag filtering** — BEFORE Step 2 (the `marina_agent.process_message` call), add filtering. Then change `thread_flags=flags` to `thread_flags=agent_flags` in the marina_agent call:

```python
    # Filter relay flags before marina_agent call — prevents RELAY MODE prompt injection
    agent_flags = dict(flags)
    for _rk in ("awaiting_relay", "relay_token", "relay_question"):
        agent_flags.pop(_rk, None)

    # Step 2: Call marina_agent with channel="whatsapp"
    result = marina_agent.process_message(
        from_email=from_id,
        subject="",
        body=text,
        thread_fields=fields,
        thread_flags=agent_flags,   # ← was: flags
        action_context=action_context,
        channel="whatsapp",
        messages=history,
    )
```

**1d. Add escalation handlers** — Insert AFTER Step 7 (the availability/soft-hold section ending with the last `bm_logger.log("whatsapp_slot_unavailable", ...)` block) and BEFORE Step 8 (`# Step 8: Booking confirmation flow`).

Add `_skip_booking = False` before the handlers:

```python
    _skip_booking = False

    # Step 7.5: Semi-escalation — relay question to operator, holding reply to customer
    if result.get("semi_escalation"):
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
        relay_token = uuid.uuid4().hex[:12]
        flags["awaiting_relay"] = True
        flags["relay_token"] = relay_token
        flags["relay_question"] = result.get("relay_question", "(no question captured)")
        reply_text = result["reply"]  # Claude's warm holding reply, not post-validation override
        _cname = fields.get("customer_name", "Unknown")
        sheets_writer.log_escalation({
            "email": phone,
            "subject": "WhatsApp",
            "customer_name": _cname,
            "intent": "semi_escalation",
            "fields_collected": fields,
            "internal_note": f"Relay question: {flags['relay_question']}",
            "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
        })
        bm_logger.log("whatsapp_semi_escalation", phone=phone,
                      relay_question=flags["relay_question"],
                      relay_token=relay_token)
        _skip_booking = True

    # Step 7.6: Full escalation — requires_human, holding reply to customer
    if not _skip_booking and result.get("requires_human"):
        # Cancel any soft hold (same pattern as semi-escalation — capacity leak prevention)
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
        flags["fully_escalated"] = True
        flags["awaiting_booking_confirmation"] = False
        reply_text = result["reply"]  # Claude's warm holding reply
        _cname = fields.get("customer_name", "Unknown")
        sheets_writer.log_escalation({
            "email": phone,
            "subject": "WhatsApp",
            "customer_name": _cname,
            "intent": (result.get("intents") or ["unknown"])[0],
            "fields_collected": fields,
            "internal_note": result.get("internal_note", ""),
            "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
        })
        bm_logger.log("whatsapp_full_escalation", phone=phone,
                      intents=result.get("intents", []))
        _skip_booking = True
```

**1e. Guard Step 8** — Change the Step 8 opening condition from:

```python
    # Step 8: Booking confirmation flow
    if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
```

to:

```python
    # Step 8: Booking confirmation flow (skip if escalated)
    if not _skip_booking and any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
```

**1f. Update file header** — Change `# Last modified: Brief 070` to `# Last modified: Brief 071` and update the purpose line to: `# Purpose: WhatsApp booking orchestrator with escalation — calls marina_agent, validates, holds, confirms, escalates`

### Step 2 — Create `tests/social/test_071_whatsapp_escalation.py`

8 tests. Same imports, cleanup pattern, and mock structure as `test_070_whatsapp_booking.py`.

**Test 1: `test_fully_escalated_guard_returns_holding_reply`**
- Pre-set state: `flags = {"fully_escalated": True}` via `wa_save_booking_state`
- Mock `marina_agent.process_message` to return `{"intents": ["inquiry"], "reply": "Our team is looking into this!", ...}`
- Call `handle_incoming_whatsapp_message`
- Assert: reply == "Our team is looking into this!"
- Assert: `marina_agent.process_message` was called exactly once

**Test 2: `test_fully_escalated_guard_filters_relay_flags`**
- Pre-set state: `flags = {"fully_escalated": True, "awaiting_relay": True, "relay_token": "abc123", "relay_question": "weight limit?"}`
- Mock `marina_agent.process_message`
- Call `handle_incoming_whatsapp_message`
- Assert: the `thread_flags` kwarg passed to `marina_agent.process_message` does NOT contain `awaiting_relay`, `relay_token`, or `relay_question`
- Assert: it DOES contain `fully_escalated: True`

**Test 3: `test_semi_escalation_sets_relay_state`**
- No pre-set state (fresh phone)
- Mock `sheets_writer.log_escalation` (semi-escalation calls it)
- Mock `marina_agent.process_message` to return:
  ```python
  {"intents": ["inquiry"], "fields": {}, "confidence": "high",
   "reply": "Let me check with the team on that!",
   "clarifications_needed": [], "requires_human": False,
   "flags": {}, "internal_note": "Weight limit question",
   "semi_escalation": True,
   "relay_question": "What is the weight limit for jet skis?"}
  ```
- Call `handle_incoming_whatsapp_message`
- Assert: reply == "Let me check with the team on that!"
- Assert: state flags contain `awaiting_relay: True`, `relay_token` (non-empty string, 12 hex chars), `relay_question: "What is the weight limit for jet skis?"`

**Test 4: `test_semi_escalation_cancels_soft_hold`**
- Pre-set state: fields with valid booking data (`trip_key: west_coast_beach`, `experience: West Coast Beach Trip`, `date: 2026-03-18`, `guests: 2`, `departure_time: 09:00`), flags with `awaiting_booking_confirmation: True`, `slot_checked: True`, `slot_available: True`, `hold_id` (create a real soft hold via `state_registry.create_soft_hold`), `hold_trip_key: west_coast_beach`, `hold_date: 2026-03-18`, `hold_departure_time: 09:00`
- Mock `sheets_writer.log_escalation` (semi-escalation calls it)
- Mock `gws_calendar.remove_from_manifest` (called during hold cancellation when hold_trip_key/date/time are present)
- Mock `marina_agent.process_message` to return `semi_escalation: True, relay_question: "Can I bring my own snorkel?", reply: "Let me check on that!", intents: ["inquiry"]`
- Call `handle_incoming_whatsapp_message`
- Assert: state flags `hold_id` is gone, `slot_checked: False`, `slot_available: False`, `awaiting_booking_confirmation: False`
- Assert: `awaiting_relay: True`
- Assert: `gws_calendar.remove_from_manifest` was called once with `("west_coast_beach", "2026-03-18", "09:00")`

**Test 5: `test_semi_escalation_overrides_post_validate`**
- No pre-set state
- Mock `sheets_writer.log_escalation` (semi-escalation calls it)
- Mock `marina_agent.process_message` to return `semi_escalation: True` WITH valid booking fields (trip_key: `west_coast_beach`, date: `2026-03-18`, guests: `2`, experience: `West Coast Beach Trip`) AND `intents: ["booking"]` (so post-validate fires and generates a booking summary before semi-escalation overrides it)
- Mock `gws_calendar.check_availability` to return `{"available": True, "spots_remaining": 23, "capacity": 25}` (post-validate sets awaiting, so availability check runs)
- Mock `gws_calendar.remove_from_manifest` (semi-escalation cancels the hold created in Step 7)
- Mock `marina_agent.process_message` `relay_question: "Also what's the weight limit?"`, `reply: "Let me check with the team on that!"`
- Call `handle_incoming_whatsapp_message`
- Assert: reply is Claude's holding reply "Let me check with the team on that!" (NOT the booking summary with "$240")
- Assert: `awaiting_booking_confirmation: False` (semi-escalation cleared it)
- Assert: `awaiting_relay: True`

**Test 6: `test_full_escalation_sets_flag_and_logs`**
- No pre-set state
- Mock `marina_agent.process_message` to return:
  ```python
  {"intents": ["complaint"], "fields": {}, "confidence": "high",
   "reply": "I'm sorry about that. I've passed this to our team.",
   "clarifications_needed": [], "requires_human": True,
   "flags": {}, "internal_note": "Complaint about cancelled trip"}
  ```
- Mock `sheets_writer.log_escalation`
- Call `handle_incoming_whatsapp_message`
- Assert: reply == "I'm sorry about that. I've passed this to our team."
- Assert: state flags `fully_escalated: True`
- Assert: `sheets_writer.log_escalation` called once with `intent: "complaint"`, `email: phone`

**Test 7: `test_full_escalation_skips_booking_confirmation`**
- No pre-set state
- Mock `marina_agent.process_message` to return `requires_human: True` WITH booking fields (trip_key: `west_coast_beach`, date: `2026-03-18`, guests: `2`, experience: `West Coast Beach Trip`) and `intents: ["booking"]`
- Mock `gws_calendar.check_availability` to return `{"available": True, "spots_remaining": 23, "capacity": 25}` (post-validate sets awaiting, so availability check runs and creates a soft hold — but full escalation cancels it)
- Mock `sheets_writer.log_escalation`
- Call `handle_incoming_whatsapp_message`
- Assert: no `booking_ref` in state flags (booking confirmation skipped)
- Assert: `fully_escalated: True`
- Assert: `hold_id` NOT in state flags (full escalation cancelled the hold)
- Assert: `slot_checked: False` (full escalation reset it)

**Test 8: `test_relay_flags_filtered_for_normal_message`**
- Pre-set state: `flags = {"awaiting_relay": True, "relay_token": "abc123def456", "relay_question": "weight limit?"}`
- Mock `marina_agent.process_message` to return normal inquiry reply
- Call `handle_incoming_whatsapp_message`
- Assert: `marina_agent.process_message` was called
- Assert: the `thread_flags` kwarg does NOT contain `awaiting_relay`, `relay_token`, `relay_question`
- Assert: reply is the normal inquiry reply

## Success Condition

All 8 new tests pass. All 50 existing tests (Brief 067–070) pass without modification. Semi-escalation, full escalation, and fully-escalated guard work correctly in the WhatsApp booking orchestrator.

## Rollback

```bash
git checkout HEAD -- agents/social/social_agent.py
rm tests/social/test_071_whatsapp_escalation.py
```
