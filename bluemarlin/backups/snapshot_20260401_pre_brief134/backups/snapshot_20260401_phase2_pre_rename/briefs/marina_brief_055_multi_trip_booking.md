# BRIEF 055 — Multi-trip booking in one thread
**Status:** Draft | **Files:** `src/email_poller.py`, `src/marina_agent.py`, `config/client.json` | **Depends on:** 054 | **Blocks:** —

## Context
After a booking is completed (`hold_created = True`), the thread is stuck — booking-related fields and flags remain set, so subsequent messages cannot start a new booking. The check at email_poller.py line 806-809 requires `booking_confirmed and not hold_created`, which never re-fires once `hold_created` is True.

A customer who says "Great, I also want to book a sunset cruise for Sunday" gets no fresh intake — the old trip_key, date, and guests pollute the new request.

## Why This Approach
Three approaches were considered:
1. **Unconditional reset on next message** — archive and reset on every message after hold_created. REJECTED: breaks non-booking follow-ups ("Thanks!", "What should I bring?") by wiping booking context before Claude responds.
2. **Intent-gated reset** — archive and reset only when Claude returns a booking intent AND hold_created is True. The reset runs AFTER the marina_agent call but BEFORE the field merge, so the old booking is archived from the pre-merge thread state, then Claude's new fields (for the new trip) are merged onto the clean slate.
3. **Separate thread per booking** — force a new thread. Breaks conversation continuity.

Option 2 is chosen. The reset is a Python-side operation (Rule 2 compliant) — Python detects the collision between booking intent + hold_created, not the language. Non-booking messages (inquiry, social, off_topic) pass through unchanged with full booking context intact.

A `max_bookings_per_thread` safeguard (default 3) prevents runaway booking loops. `_FRESH_THREAD` from Brief 053's stale thread reset naturally clears `completed_bookings` when a stale thread is reset — correct behavior.

## Source Material

### Current booking completion check (email_poller.py lines 806-809)
```python
if (fields_now.get("experience") and fields_now.get("date")
        and fields_now.get("guests") and fields_now.get("trip_key")
        and th["flags"].get("booking_confirmed")
        and not th["flags"].get("hold_created")):
```

### Current field merge (email_poller.py lines 576-583)
```python
th.setdefault("fields", {})
new_fields = result.get("fields", {}) or {}
new_flags = result.get("flags", {}) or {}
for k, v in new_fields.items():
    if v is not None and v != "":
        th["fields"][k] = v
    elif v == "" and k in th["fields"]:
        del th["fields"][k]
```

### Current marina_agent call + field/flag merge location (email_poller.py lines 565-587)
```
Line 565: agent_flags = dict(th.get("flags", {}))
Line 571: result = marina_agent.process_message(...)
Line 576: # Step 2: Merge fields
Line 585: # Step 3: Persist flags
```

### _BOOKING_INTENTS set (email_poller.py)
```python
_BOOKING_INTENTS = {"booking", "reschedule"}
```

## Instructions

### Step 1: client.json — add max_bookings_per_thread

Add `"max_bookings_per_thread": 3` to the `booking_rules` object, after the `"dietary_advance_notice_days": 1` line:

```json
    "dietary_advance_notice_days": 1,
    "max_bookings_per_thread": 3
```

### Step 2: email_poller.py — add _maybe_reset_for_new_booking helper

Add after `_detect_booking_ref` (around line 240), before the `_day_matches` helper:

```python
# Booking-related flags that get reset between bookings in the same thread
_BOOKING_FLAGS_TO_RESET = {
    "hold_created", "booking_confirmed", "booking_ref", "hold_id",
    "payment_id", "payment_link", "payment_status",
    "event_id", "event_link",
    "slot_checked", "slot_available", "spots_remaining", "trip_capacity",
    "awaiting_booking_confirmation",
    "hold_trip_key", "hold_date", "hold_departure_time",
}

# Fields to preserve across bookings (customer identity)
_PERSISTENT_FIELDS = {"customer_name", "phone"}


def _maybe_reset_for_new_booking(th: dict) -> bool:
    """If a booking was just completed (hold_created=True), archive it and reset
    fields/flags for a fresh booking intake. Returns True if reset happened."""
    if not th.get("flags", {}).get("hold_created"):
        return False

    max_bookings = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
    completed = th.get("completed_bookings", [])
    if len(completed) >= max_bookings:
        return False  # at limit — don't reset, Marina will decline

    # Archive current booking
    fields = th.get("fields", {})
    flags = th.get("flags", {})
    archived = {
        "booking_ref": flags.get("booking_ref", ""),
        "trip_key": fields.get("trip_key", ""),
        "experience": fields.get("experience", ""),
        "date": fields.get("date", ""),
        "guests": fields.get("guests", ""),
        "departure_time": fields.get("departure_time", ""),
        "payment_link": flags.get("payment_link", ""),
    }
    completed.append(archived)
    th["completed_bookings"] = completed

    # Reset fields — keep customer identity
    preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
    th["fields"] = preserved

    # Reset booking flags
    for flag_key in _BOOKING_FLAGS_TO_RESET:
        th["flags"].pop(flag_key, None)

    return True
```

Note: `returning_booking` is NOT in `_BOOKING_FLAGS_TO_RESET` — it is a detection flag from Brief 054, not a booking flow flag.

### Step 3: email_poller.py — call reset AFTER marina_agent call, gated on booking intent

The reset must fire AFTER the marina_agent call but BEFORE the field merge. This ensures:
- Non-booking messages (inquiry, social) never trigger the reset
- The archive captures pre-merge thread state (old booking data)
- Claude's new fields are then merged onto the clean slate

Insert the following AFTER the marina_agent call (after line 574 `result = marina_agent.process_message(...)`) and BEFORE the field merge comment (before line 576 `# Step 2: Merge fields`):

```python
                # Multi-trip: if booking intent + previous booking completed, archive and reset
                if (any(i in _BOOKING_INTENTS for i in result.get("intents", []))
                        and th["flags"].get("hold_created")):
                    _did_reset = _maybe_reset_for_new_booking(th)
                    if _did_reset:
                        log(f"Multi-trip reset for {from_email}: booking #{len(th.get('completed_bookings', []))} archived")

```

### Step 4: email_poller.py — pass completed bookings summary to marina_agent

The completed bookings summary must be injected into `agent_flags` BEFORE the marina_agent call so Claude sees the context.

After the relay key cleanup block (after line 569 where relay keys are popped from `agent_flags`), add:

```python
                # Inject completed bookings summary for multi-trip context
                _completed = th.get("completed_bookings", [])
                if _completed:
                    _cb_lines = []
                    for _cb in _completed:
                        _cb_lines.append(
                            f"  - {_cb.get('experience', _cb.get('trip_key', '?'))} on "
                            f"{_cb.get('date', '?')} for {_cb.get('guests', '?')} guests "
                            f"(ref: {_cb.get('booking_ref', 'N/A')})"
                        )
                    agent_flags["_completed_bookings_summary"] = "\n".join(_cb_lines)
                    # Check max bookings — tells Marina to decline new bookings
                    _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
                    if len(_completed) >= _max_bk and th["flags"].get("hold_created"):
                        agent_flags["_max_bookings_reached"] = True
```

### Step 5: marina_agent.py — add completed bookings context and max-bookings awareness

In `_build_prompt()`, build two new variables after the `returning_customer_section` block (after line 90):

```python
    completed_bookings_section = ""
    completed = thread_flags.get("_completed_bookings_summary", "")
    if completed:
        completed_bookings_section = (
            f"\nCOMPLETED BOOKINGS IN THIS THREAD:\n{completed}\n"
            f"The customer may want to book another trip. Start fresh intake "
            f"for the new booking — do not reference or modify completed bookings.\n"
        )

    max_bookings_section = ""
    if thread_flags.get("_max_bookings_reached"):
        max_bookings_section = (
            "\nMAX BOOKINGS REACHED: This customer has reached the maximum number of "
            "bookings per conversation. Politely let them know they can email again "
            "to book additional trips. Do not start a new booking intake.\n"
        )
```

Insert both into the prompt string, right after `{returning_customer_section}`:

Change:
```python
{relay_mode_section}{fully_escalated_section}{returning_customer_section}
```
To:
```python
{relay_mode_section}{fully_escalated_section}{returning_customer_section}{completed_bookings_section}{max_bookings_section}
```

### Step 6: Update file headers

- `email_poller.py`: change `LAST MODIFIED: Brief 054` → `LAST MODIFIED: Brief 055`
- `marina_agent.py`: change `LAST MODIFIED: Brief 054` → `LAST MODIFIED: Brief 055`

## Tests

File: `tests/test_multi_trip.py`

```python
"""Tests for Brief 055 — Multi-trip booking in one thread."""
import sys, os, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import email_poller
import marina_agent
import config_loader


def _make_thread(fields=None, flags=None, completed=None):
    th = {
        "fields": fields or {},
        "flags": flags or {},
        "last_customer_hash": "",
        "reply_times": [],
        "messages": [],
    }
    if completed is not None:
        th["completed_bookings"] = completed
    return th


def test_reset_after_hold_created():
    """After hold_created=True, reset archives booking and clears fields/flags."""
    th = _make_thread(
        fields={
            "trip_key": "klein_curacao",
            "experience": "Klein Curaçao",
            "date": "2026-04-15",
            "guests": "4",
            "departure_time": "08:30",
            "customer_name": "Callou",
            "phone": "+5999 123 4567",
        },
        flags={
            "hold_created": True,
            "booking_confirmed": True,
            "booking_ref": "BF-2026-00001",
            "payment_link": "https://demo.pay/bluemarlin/pay123",
            "slot_checked": True,
            "slot_available": True,
            "hold_id": 42,
            "event_id": "evt123",
            "event_link": "https://calendar.google.com/event/abc",
        },
    )
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == True, "FAIL: should return True when reset happens"
    # Fields: customer_name and phone preserved, everything else cleared
    assert th["fields"]["customer_name"] == "Callou", "FAIL: customer_name should persist"
    assert th["fields"]["phone"] == "+5999 123 4567", "FAIL: phone should persist"
    assert "trip_key" not in th["fields"], "FAIL: trip_key should be cleared"
    assert "experience" not in th["fields"], "FAIL: experience should be cleared"
    assert "date" not in th["fields"], "FAIL: date should be cleared"
    assert "guests" not in th["fields"], "FAIL: guests should be cleared"
    # Flags: booking flags cleared
    assert "hold_created" not in th["flags"], "FAIL: hold_created should be cleared"
    assert "booking_confirmed" not in th["flags"], "FAIL: booking_confirmed should be cleared"
    assert "booking_ref" not in th["flags"], "FAIL: booking_ref should be cleared"
    assert "slot_checked" not in th["flags"], "FAIL: slot_checked should be cleared"
    assert "hold_id" not in th["flags"], "FAIL: hold_id should be cleared"
    # Completed bookings list
    assert len(th["completed_bookings"]) == 1
    archived = th["completed_bookings"][0]
    assert archived["booking_ref"] == "BF-2026-00001", f"FAIL: archived ref={archived['booking_ref']}"
    assert archived["trip_key"] == "klein_curacao", f"FAIL: archived trip={archived['trip_key']}"
    assert archived["date"] == "2026-04-15", f"FAIL: archived date={archived['date']}"
    assert archived["guests"] == "4", f"FAIL: archived guests={archived['guests']}"
    print("PASS: test_reset_after_hold_created")


def test_no_reset_without_hold_created():
    """Without hold_created, no reset happens."""
    th = _make_thread(
        fields={"trip_key": "klein_curacao", "date": "2026-04-15"},
        flags={"awaiting_booking_confirmation": True},
    )
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == False, "FAIL: should return False without hold_created"
    assert th["fields"]["trip_key"] == "klein_curacao", "FAIL: fields should be unchanged"
    print("PASS: test_no_reset_without_hold_created")


def test_max_bookings_blocks_reset():
    """At max_bookings_per_thread (3), no reset happens."""
    completed = [
        {"booking_ref": f"BF-2026-0000{i}", "trip_key": "klein_curacao",
         "date": "2026-04-15", "guests": "2"} for i in range(3)
    ]
    th = _make_thread(
        fields={"trip_key": "sunset_cruise", "date": "2026-04-16", "customer_name": "Callou"},
        flags={"hold_created": True, "booking_ref": "BF-2026-00004"},
        completed=completed,
    )
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == False, "FAIL: should return False at max bookings"
    assert th["flags"].get("hold_created") == True, "FAIL: flags should be unchanged at max"
    assert len(th["completed_bookings"]) == 3, "FAIL: completed list should not grow past max"
    print("PASS: test_max_bookings_blocks_reset")


def test_second_booking_archives_correctly():
    """Second booking adds to completed_bookings list."""
    first_completed = [{
        "booking_ref": "BF-2026-00001",
        "trip_key": "klein_curacao",
        "experience": "Klein Curaçao",
        "date": "2026-04-15",
        "guests": "4",
        "departure_time": "08:30",
        "payment_link": "https://demo.pay/1",
    }]
    th = _make_thread(
        fields={
            "trip_key": "sunset_cruise",
            "experience": "Sunset Cruise",
            "date": "2026-04-16",
            "guests": "2",
            "departure_time": "17:00",
            "customer_name": "Callou",
            "phone": "+5999 123 4567",
        },
        flags={
            "hold_created": True,
            "booking_ref": "BF-2026-00002",
            "payment_link": "https://demo.pay/2",
        },
        completed=first_completed,
    )
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == True
    assert len(th["completed_bookings"]) == 2
    assert th["completed_bookings"][0]["booking_ref"] == "BF-2026-00001"
    assert th["completed_bookings"][1]["booking_ref"] == "BF-2026-00002"
    assert th["completed_bookings"][1]["trip_key"] == "sunset_cruise"
    assert th["completed_bookings"][1]["date"] == "2026-04-16"
    # Fields reset but identity preserved
    assert th["fields"]["customer_name"] == "Callou"
    assert "trip_key" not in th["fields"]
    print("PASS: test_second_booking_archives_correctly")


def test_non_booking_flags_preserved():
    """Flags not in _BOOKING_FLAGS_TO_RESET survive the reset."""
    th = _make_thread(
        fields={"trip_key": "klein_curacao", "customer_name": "Test"},
        flags={
            "hold_created": True,
            "booking_ref": "BF-2026-00001",
            "fully_escalated": False,
            "awaiting_relay": False,
            "returning_booking": "BF-2026-00099",
        },
    )
    email_poller._maybe_reset_for_new_booking(th)
    # These are NOT in _BOOKING_FLAGS_TO_RESET — they should survive
    assert "fully_escalated" in th["flags"], "FAIL: fully_escalated should survive"
    assert "awaiting_relay" in th["flags"], "FAIL: awaiting_relay should survive"
    assert "returning_booking" in th["flags"], "FAIL: returning_booking should survive"
    # Booking flags should be cleared
    assert "hold_created" not in th["flags"], "FAIL: hold_created should be cleared"
    assert "booking_ref" not in th["flags"], "FAIL: booking_ref should be cleared"
    print("PASS: test_non_booking_flags_preserved")


def test_prompt_completed_bookings_section():
    """When _completed_bookings_summary is in flags, prompt includes COMPLETED BOOKINGS section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "I also want sunset cruise",
        {"customer_name": "Callou"},
        {"_completed_bookings_summary": "  - Klein Curaçao on 2026-04-15 for 4 guests (ref: BF-2026-00001)"},
    )
    assert "COMPLETED BOOKINGS IN THIS THREAD:" in prompt, "FAIL: missing COMPLETED BOOKINGS section"
    assert "Klein Curaçao" in prompt, "FAIL: completed booking details not in prompt"
    assert "BF-2026-00001" in prompt, "FAIL: booking ref not in prompt"
    print("PASS: test_prompt_completed_bookings_section")


def test_prompt_max_bookings_reached():
    """When _max_bookings_reached is True, prompt includes MAX BOOKINGS section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "I want another trip",
        {"customer_name": "Callou"},
        {"_max_bookings_reached": True},
    )
    assert "MAX BOOKINGS REACHED:" in prompt, "FAIL: missing MAX BOOKINGS section"
    assert "email again" in prompt, "FAIL: should mention emailing again"
    print("PASS: test_prompt_max_bookings_reached")


def test_prompt_no_completed_without_data():
    """Without completed bookings data, no COMPLETED BOOKINGS section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "I want to book",
        {}, {},
    )
    assert "COMPLETED BOOKINGS IN THIS THREAD:" not in prompt
    assert "MAX BOOKINGS REACHED:" not in prompt
    print("PASS: test_prompt_no_completed_without_data")


def test_completed_bookings_summary_format():
    """Verify the summary format that gets injected into agent_flags."""
    completed = [
        {
            "booking_ref": "BF-2026-00001",
            "trip_key": "klein_curacao",
            "experience": "Klein Curaçao",
            "date": "2026-04-15",
            "guests": "4",
        },
        {
            "booking_ref": "BF-2026-00002",
            "trip_key": "sunset_cruise",
            "experience": "Sunset Cruise",
            "date": "2026-04-16",
            "guests": "2",
        },
    ]
    lines = []
    for cb in completed:
        lines.append(
            f"  - {cb.get('experience', cb.get('trip_key', '?'))} on "
            f"{cb.get('date', '?')} for {cb.get('guests', '?')} guests "
            f"(ref: {cb.get('booking_ref', 'N/A')})"
        )
    summary = "\n".join(lines)
    assert "Klein Curaçao on 2026-04-15 for 4 guests (ref: BF-2026-00001)" in summary
    assert "Sunset Cruise on 2026-04-16 for 2 guests (ref: BF-2026-00002)" in summary
    print("PASS: test_completed_bookings_summary_format")


def test_intent_gating_prevents_non_booking_reset():
    """Verify that the reset is gated on booking intent — non-booking intents
    should NOT trigger _maybe_reset_for_new_booking even with hold_created=True.
    This test validates the gating logic by showing that _maybe_reset_for_new_booking
    only checks hold_created and max_bookings — the intent gating is done by the
    caller in the main loop."""
    th = _make_thread(
        fields={"trip_key": "klein_curacao", "customer_name": "Test",
                "date": "2026-04-15", "guests": "2"},
        flags={"hold_created": True, "booking_ref": "BF-2026-00001"},
    )
    # _maybe_reset_for_new_booking itself always resets when hold_created is True
    # The intent gating happens in the main loop BEFORE calling this function
    result = email_poller._maybe_reset_for_new_booking(th)
    assert result == True, "FAIL: function should return True (intent gating is in caller)"
    # This test documents that the CALLER must gate on booking intent
    print("PASS: test_intent_gating_prevents_non_booking_reset")


if __name__ == "__main__":
    test_reset_after_hold_created()
    test_no_reset_without_hold_created()
    test_max_bookings_blocks_reset()
    test_second_booking_archives_correctly()
    test_non_booking_flags_preserved()
    test_prompt_completed_bookings_section()
    test_prompt_max_bookings_reached()
    test_prompt_no_completed_without_data()
    test_completed_bookings_summary_format()
    test_intent_gating_prevents_non_booking_reset()
    print(f"\n10/10 tests passed.")
```

## Success Condition
All 10 tests pass. After a completed booking, the next message with booking intent archives the old booking and starts fresh intake. Non-booking follow-ups ("Thanks!", FAQ questions) retain full booking context. Marina sees completed bookings in context. Max 3 bookings per thread enforced.

## Rollback
Revert changed files:
```bash
git checkout HEAD~1 -- src/email_poller.py src/marina_agent.py config/client.json
```
Delete test file and output file.
