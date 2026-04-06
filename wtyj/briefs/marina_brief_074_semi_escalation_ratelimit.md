# BRIEF 074 — WhatsApp: Semi-Escalation Promotion + Rate Limit Bump
**Status:** Draft | **Files:** agents/social/social_agent.py, tests/social/test_071_whatsapp_escalation.py, tests/social/test_072_whatsapp_multi_trip.py, tests/social/test_074_semi_ratelimit.py | **Depends on:** 073 | **Blocks:** —

## Context

Two issues surfaced from the first live WhatsApp conversation (Calvin Adamus, 2026-03-12):

**1. Semi-escalation orphaned relay.** Calvin asked about 9pH water. Marina semi-escalated ("I'm checking with the crew"), setting `awaiting_relay=True`, `relay_token`, `relay_question` in flags and logging to Sheets. But WhatsApp has no relay-back mechanism — in email, the operator replies to `[RELAY-xxx]` subject which email_poller detects and forwards. WhatsApp has no equivalent (noted in Brief 071: "No cross-channel relay bridge — relay state stored for future brief"). Result: Calvin's 9pH question was logged to Sheets but will never be answered through WhatsApp. The relay flags sit orphaned in state. Meanwhile Calvin continued booking normally because there's no `awaiting_relay` guard (same as email — by design). Marina promised "I'll get back to you shortly" but can't deliver.

**2. Rate limit too tight.** `_MAX_REPLIES_PER_HOUR = 15`. Calvin's conversation: 10 booking exchanges + 5 post-booking chat = 15 replies in ~16 minutes, then rate-limited. His last 3 messages ("another one pls", "Hi", "U there?") got no response. WhatsApp is real-time rapid-fire — a single booking can take 10-15 exchanges. 15/hr leaves no buffer for post-booking conversation.

## Why This Approach

**Semi-escalation → full escalation:** Without a relay bridge, semi-escalation makes a promise Marina can't keep. Converting to full escalation is honest: the operator is notified (Sheets log includes the relay question), the customer gets a holding reply, and the `fully_escalated` flag prevents the booking flow from continuing mid-escalation. The trade-off: the customer can't complete a booking until the stale reset (24h) clears the flag — but the operator, seeing the Sheets escalation, can contact the customer directly via WhatsApp and resolve it faster. When the relay bridge is built (Phase 4), semi-escalation can be restored on WhatsApp.

Alternative rejected: just removing relay flags without setting `fully_escalated`. This leaves the booking flow running while an unanswered question hangs — exactly what happened with Calvin (9pH water question forgotten, booking completed as if nothing happened).

**Rate limit 15 → 25:** A full booking conversation takes 10-15 exchanges (inquiry, clarifications, departure selection, summary, reschedule, confirmation). Post-booking chat (how do you know me, jokes, etc.) adds 5-8 more. 25/hr covers a complete booking + reasonable post-booking + buffer. Still prevents infinite loops. Email keeps its own limit (10/thread/hr) — different medium, different pace.

## Source Material

### social_agent.py current semi-escalation (Step 7.5, lines 467-498)
```python
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
```

### Current rate limit constant (line 33)
```python
_MAX_REPLIES_PER_HOUR = 15
```

### test_071 semi-escalation tests that assert relay flags (tests 3, 4, 5)
- Test 3 (line 98-119): asserts `awaiting_relay is True`, `relay_token` length 12, `relay_question` value
- Test 4 (line 124-158): asserts `hold_id` removed, `awaiting_relay is True`, `slot_checked is False`
- Test 5 (line 163-190): asserts `awaiting_booking_confirmation is False`, `awaiting_relay is True`

### test_072 anti-loop tests that hard-code 15
- `test_anti_loop_blocks_after_limit` (line 223): `range(15)` — creates 15 recent reply_times, asserts empty reply
- `test_anti_loop_allows_after_window` (line 240): `range(15)` — creates 15 old timestamps (2hr ago), asserts call proceeds
- `test_anti_loop_blocks_fully_escalated` (line 330): `range(15)` — creates 15 recent reply_times with fully_escalated, asserts empty reply

### uuid import (line 9)
```python
import uuid
```
Only used for `relay_token = uuid.uuid4().hex[:12]` in semi-escalation. No other usage.

## Instructions

### Step 1 — social_agent.py: Bump rate limit
Change line 33:
```python
_MAX_REPLIES_PER_HOUR = 25
```

### Step 2 — social_agent.py: Remove uuid import
Remove `import uuid` from line 9 (no longer needed after semi-escalation change).

### Step 3 — social_agent.py: Convert semi-escalation to full escalation
Replace the entire Step 7.5 block (lines 466-498) with:
```python
    # Step 7.5: Semi-escalation → promote to full escalation (no relay bridge on WhatsApp)
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
        flags["fully_escalated"] = True
        reply_text = result["reply"]
        _cname = fields.get("customer_name", "Unknown")
        _relay_q = result.get("relay_question", "(no question captured)")
        sheets_writer.log_escalation({
            "email": phone,
            "subject": "WhatsApp",
            "customer_name": _cname,
            "intent": "semi_to_full_escalation",
            "fields_collected": fields,
            "internal_note": f"Relay question (no relay bridge): {_relay_q}",
            "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
        })
        bm_logger.log("whatsapp_semi_to_full", phone=phone,
                      relay_question=_relay_q)
        _skip_booking = True
```

### Step 4 — social_agent.py: Update file header
Change `Last modified: Brief 073` → `Last modified: Brief 074`.

### Step 5 — test_071: Update semi-escalation assertions
In `test_semi_escalation_sets_relay_state` (test 3):
- Change assertion `state["flags"].get("awaiting_relay") is True` → `state["flags"].get("fully_escalated") is True`
- Remove assertion for `relay_token` length == 12
- Remove assertion for `relay_question` value
- Add assertion: `"awaiting_relay" not in state["flags"]`
- Add assertion: `"relay_token" not in state["flags"]`

In `test_semi_escalation_cancels_soft_hold` (test 4):
- Change assertion `state["flags"].get("awaiting_relay") is True` → `state["flags"].get("fully_escalated") is True`

In `test_semi_escalation_overrides_post_validate` (test 5):
- Change assertion `state["flags"].get("awaiting_relay") is True` → `state["flags"].get("fully_escalated") is True`

### Step 6 — test_072: Update anti-loop test data
In all three anti-loop tests, change `range(15)` → `range(25)`:
- `test_anti_loop_blocks_after_limit` (line 223): `range(15)` → `range(25)`
- `test_anti_loop_allows_after_window` (line 240): `range(15)` → `range(25)`
- `test_anti_loop_blocks_fully_escalated` (line 330): `range(15)` → `range(25)`
Also update the comment on line 222 from `# 15 timestamps` to `# 25 timestamps`.

### Step 7 — Create test_074_semi_ratelimit.py
New test file with 6 tests:

**Test 1: Semi-escalation promotes to full escalation.**
Set up: clean phone, no prior state.
Mock process_message to return `semi_escalation=True`, `relay_question="test question"`, `reply="I'll check with the team!"`.
Assert: `fully_escalated is True`, `awaiting_relay not in flags`, `relay_token not in flags`, `relay_question not in flags`. Reply == Claude's holding reply.

**Test 2: Semi-escalation with hold cancels hold and sets fully_escalated.**
Set up: phone with active soft hold (same pattern as test_071 test 4).
Mock process_message to return `semi_escalation=True`.
Assert: `hold_id not in flags`, `fully_escalated is True`, `slot_checked is False`. Mock `remove_from_manifest` called.

**Test 3: Semi-escalation logs correctly to Sheets.**
Mock both process_message and sheets_writer.log_escalation.
Process_message returns `semi_escalation=True`, `relay_question="Is 9pH water available?"`.
Assert: Sheets called with `intent="semi_to_full_escalation"`, internal_note contains "Relay question (no relay bridge): Is 9pH water available?".

**Test 4: Post-semi-escalation message goes through fully-escalated guard.**
Set up: phone with `fully_escalated=True` (from a previous semi→full promotion).
Mock process_message to return a normal reply.
Assert: marina_agent called once, reply returned, booking flow NOT triggered (no booking_ref in state).

**Test 5: Rate limit at 25 — blocks at threshold.**
Set up: phone with 25 reply_times within the last hour.
Assert: reply == "", process_message not called.

**Test 6: Rate limit at 25 — allows at 24.**
Set up: phone with 24 reply_times within the last hour.
Mock process_message with normal reply.
Assert: reply returned, process_message called once.

## Tests

```
Test 1: semi_escalation=True → flags["fully_escalated"] is True, "awaiting_relay" not in flags
Test 2: semi_escalation with hold → hold_id removed, fully_escalated is True, remove_from_manifest called
Test 3: Sheets intent == "semi_to_full_escalation", internal_note contains "Relay question (no relay bridge)"
Test 4: fully_escalated phone → marina_agent called, booking_ref not in flags
Test 5: 25 reply_times → reply == "", process_message.call_count == 0
Test 6: 24 reply_times → reply != "", process_message.call_count == 1
```

Regression: all 8 tests in test_071 pass (3 updated), all 11 in test_072 pass (3 updated), all 79 prior social tests pass.

## Success Condition

6/6 new tests pass, 79/79 regression tests pass (with updated assertions), no orphaned relay flags set on WhatsApp semi-escalation.

## Rollback

Revert social_agent.py to Brief 073 version, revert test_071 and test_072 assertion changes, delete test_074 file.
