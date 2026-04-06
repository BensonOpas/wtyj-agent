# BRIEF 072 — WhatsApp: Multi-Trip Reset, Returning Customer, Anti-Loop

**Status:** Draft | **Files:** `agents/social/social_agent.py`, `tests/social/test_072_whatsapp_multi_trip.py` | **Depends on:** Brief 071 | **Blocks:** Brief 073

## Context

social_agent.py has full booking + escalation support but is missing three production-critical features that email_poller.py has:

1. **Multi-trip reset** — When a WhatsApp customer completes a booking (`hold_created=True`) and then starts a new one, the old booking data pollutes the new intake. `_BOOKING_FLAGS_TO_RESET` and `_PERSISTENT_FIELDS` constants exist (lines 21–30) but are never used. `completed_bookings` is fetched from SQLite (line 176) but never modified.

2. **Returning customer** — No awareness of past bookings. `get_bookings_by_email(phone)` and `get_booking(ref)` exist in state_registry but are never called from social_agent. marina_agent.py already has prompt sections for `returning_booking`, `unknown_ref`, and `_past_customer_bookings` flags — they just need to be set.

3. **Anti-loop** — No rate limiting. A customer (or bot) sending rapid messages gets unlimited Claude API calls. email_poller has 10/hr per thread + 20/hr per sender; WhatsApp needs equivalent protection.

## Why This Approach

All three features are proven patterns from email_poller.py (Briefs 055, 054/064, 065). Porting them rather than redesigning avoids new edge cases. The WhatsApp-specific adaptations:

- **Multi-trip:** Same `_maybe_reset_for_new_booking()` function, adapted to work with flat `fields`/`flags` dicts instead of `th` dict. Reset triggers AFTER the marina_agent call but BEFORE field merge — same ordering as email_poller (lines 761–766).
- **Returning customer:** Phone number replaces email as the lookup key. `save_booking()` already stores `customer_email=phone` (social_agent.py line 486), so `get_bookings_by_email(phone)` works directly. Booking ref detection via `BF-\d{4}-\d{5}` regex applies to message text.
- **Anti-loop:** Reply timestamps stored in `flags["reply_times"]` (persisted via `wa_save_booking_state` JSON). Limit: 15/hr — higher than email's 10/hr per-thread because WhatsApp is conversational, but still protective. When hit, return empty string (webhook_server already skips empty replies at line 67). No hardcoded stop message (avoids Rule 3 violation).

Rejected alternative for anti-loop: sending a canned "slow down" message. This would violate Rule 3 and doesn't match WhatsApp UX — silent rate limiting is standard for messaging APIs.

## Source Material

### email_poller.py — `_maybe_reset_for_new_booking()` (lines 322–356)
```python
def _maybe_reset_for_new_booking(th: dict) -> bool:
    if not th.get("flags", {}).get("hold_created"):
        return False
    max_bookings = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
    completed = th.get("completed_bookings", [])
    if len(completed) >= max_bookings:
        return False
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
    preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
    th["fields"] = preserved
    for flag_key in _BOOKING_FLAGS_TO_RESET:
        th["flags"].pop(flag_key, None)
    return True
```

### email_poller.py — Multi-trip trigger (lines 761–766)
```python
if (any(i in _BOOKING_INTENTS for i in result.get("intents", []))
        and th["flags"].get("hold_created")):
    _did_reset = _maybe_reset_for_new_booking(th)
    if _did_reset:
        log(f"Multi-trip reset for {from_email}: booking #{len(th.get('completed_bookings', []))} archived")
```

### email_poller.py — Completed bookings injection (lines 736–750)
```python
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
    _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
    if len(_completed) >= _max_bk and th["flags"].get("hold_created"):
        agent_flags["_max_bookings_reached"] = True
```

### email_poller.py — Returning customer (lines 701–729)
```python
# Booking ref detection
_detected_ref = _detect_booking_ref(body)
if _detected_ref and not th["flags"].get("booking_ref"):
    _past_booking = state_registry.get_booking(_detected_ref)
    if _past_booking:
        th["flags"]["returning_booking"] = _detected_ref
        for _rbk in ("trip_key", "date", "guests", "customer_name", "departure_time"):
            _rbv = _past_booking.get(_rbk)
            if _rbv and not th["fields"].get(_rbk):
                th["fields"][_rbk] = _rbv if not isinstance(_rbv, int) else str(_rbv)
    else:
        th["flags"]["unknown_ref"] = _detected_ref

# Email-based returning customer lookup
if not _detected_ref and not th.get("completed_bookings"):
    _email_bookings = state_registry.get_bookings_by_email(from_email)
    if _email_bookings:
        _eb_lines = []
        for eb in _email_bookings[:3]:
            _eb_lines.append(
                f"  - {eb['trip_key']} on {eb['date']} for {eb['guests']} guests "
                f"(ref: {eb['booking_ref']})")
        th["flags"]["_past_customer_bookings"] = "\n".join(_eb_lines)
```

### email_poller.py — `_detect_booking_ref()` (lines 295–298)
```python
def _detect_booking_ref(body: str) -> "str | None":
    match = re.search(r'BF-\d{4}-\d{5}', body)
    return match.group() if match else None
```

### email_poller.py — Anti-loop (lines 47–48, 586–606)
- `MAX_REPLIES_PER_THREAD = 10` / `REPLY_WINDOW_SECONDS = 3600`
- Filters `reply_times` to 1hr window, blocks if count >= limit

### client.json — max_bookings_per_thread
```json
"max_bookings_per_thread": 3
```

### state_registry.py — Relevant functions
- `get_bookings_by_email(customer_email)` — returns list of booking dicts, newest first
- `get_booking(booking_ref)` — returns booking dict or None
- `wa_save_booking_state(phone, fields, flags, completed_bookings)` — already accepts completed_bookings param

### webhook_server.py — Empty reply guard (line 67)
```python
if reply_text:
    send_text_message(to=msg["from"], text=reply_text)
```

## Instructions

### Step 1 — Add anti-loop guard (top of `handle_incoming_whatsapp_message`)

Add `import re` to imports at top of file.

Add constant after `_PERSISTENT_FIELDS`:
```python
_MAX_REPLIES_PER_HOUR = 15
_REPLY_WINDOW_SECONDS = 3600
```

Insert anti-loop guard at the start of `handle_incoming_whatsapp_message`, AFTER `state = ...` / `fields = ...` / `flags = ...` lines (after line 176) but BEFORE the history fetch (line 179):

```python
# Anti-loop guard — rate limit per phone
_reply_times = flags.get("reply_times", [])
_now_ts = int(time.time())
_reply_times = [t for t in _reply_times if _now_ts - t <= _REPLY_WINDOW_SECONDS]
flags["reply_times"] = _reply_times
if len(_reply_times) >= _MAX_REPLIES_PER_HOUR:
    bm_logger.log("whatsapp_rate_limited", phone=phone,
                  count=len(_reply_times))
    state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
    return ""
```

### Step 2 — Add returning customer detection (BEFORE marina_agent call)

Insert AFTER the relay flag filtering block (after line 205) but BEFORE the marina_agent call (line 208):

```python
# Returning customer — booking ref detection
_detected_ref = None
_ref_match = re.search(r'BF-\d{4}-\d{5}', text)
if _ref_match:
    _detected_ref = _ref_match.group()
    if not flags.get("booking_ref"):
        _past_booking = state_registry.get_booking(_detected_ref)
        if _past_booking:
            flags["returning_booking"] = _detected_ref
            agent_flags["returning_booking"] = _detected_ref  # also on agent_flags (already copied)
            for _rbk in ("trip_key", "date", "guests", "customer_name", "departure_time"):
                _rbv = _past_booking.get(_rbk)
                if _rbv and not fields.get(_rbk):
                    fields[_rbk] = _rbv if not isinstance(_rbv, int) else str(_rbv)
            bm_logger.log("whatsapp_returning_customer", phone=phone, booking_ref=_detected_ref)
        else:
            flags["unknown_ref"] = _detected_ref
            agent_flags["unknown_ref"] = _detected_ref  # also on agent_flags (already copied)
            bm_logger.log("whatsapp_unknown_ref", phone=phone, ref=_detected_ref)

# Returning customer — phone-based lookup (cross-thread memory)
if not _detected_ref and not completed_bookings:
    _phone_bookings = state_registry.get_bookings_by_email(phone)
    if _phone_bookings:
        _eb_lines = []
        for _eb in _phone_bookings[:3]:
            _eb_lines.append(
                f"  - {_eb['trip_key']} on {_eb['date']} for {_eb['guests']} guests "
                f"(ref: {_eb['booking_ref']})")
        agent_flags["_past_customer_bookings"] = "\n".join(_eb_lines)
        bm_logger.log("whatsapp_returning_by_phone", phone=phone,
                      past_count=len(_phone_bookings))
```

Note: `returning_booking` and `unknown_ref` must be set on BOTH `flags` (for persistence) AND `agent_flags` (for the marina_agent call). Since `agent_flags = dict(flags)` is created before this block, changes to `flags` alone won't be visible to marina_agent. `_past_customer_bookings` goes into `agent_flags` directly (one-shot, not persisted — same as email_poller pattern).

### Step 3 — Add completed bookings injection (BEFORE marina_agent call)

Insert right after the returning customer block, before the marina_agent call:

```python
# Completed bookings context for multi-trip conversations
if completed_bookings:
    _cb_lines = []
    for _cb in completed_bookings:
        _cb_lines.append(
            f"  - {_cb.get('experience', _cb.get('trip_key', '?'))} on "
            f"{_cb.get('date', '?')} for {_cb.get('guests', '?')} guests "
            f"(ref: {_cb.get('booking_ref', 'N/A')})")
    agent_flags["_completed_bookings_summary"] = "\n".join(_cb_lines)
    _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
    if len(completed_bookings) >= _max_bk and flags.get("hold_created"):
        agent_flags["_max_bookings_reached"] = True
```

### Step 4 — Add multi-trip reset (AFTER marina_agent call, BEFORE field merge)

Insert AFTER the marina_agent call (after `reply = result.get("reply", "")`) but BEFORE the field merge block (Step 3 in the current code — "Merge fields"):

```python
# Multi-trip: if booking intent + previous booking completed, archive and reset
if (any(i in _BOOKING_INTENTS for i in result.get("intents", []))
        and flags.get("hold_created")):
    _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
    if len(completed_bookings) < _max_bk:
        archived = {
            "booking_ref": flags.get("booking_ref", ""),
            "trip_key": fields.get("trip_key", ""),
            "experience": fields.get("experience", ""),
            "date": fields.get("date", ""),
            "guests": fields.get("guests", ""),
            "departure_time": fields.get("departure_time", ""),
            "payment_link": flags.get("payment_link", ""),
        }
        completed_bookings.append(archived)
        preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
        fields.clear()
        fields.update(preserved)
        for _fk in _BOOKING_FLAGS_TO_RESET:
            flags.pop(_fk, None)
        bm_logger.log("whatsapp_multi_trip_reset", phone=phone,
                      booking_number=len(completed_bookings))
```

### Step 5 — Clear one-shot flags after marina_agent call

Insert right after the multi-trip reset block:

```python
# Clear one-shot flags after Claude has seen them
flags.pop("unknown_ref", None)
```

### Step 6 — Record reply timestamp (at end of function)

Insert right BEFORE the final `state_registry.wa_save_booking_state()` call:

```python
# Record reply timestamp for anti-loop tracking
if reply_text:
    _reply_times = flags.get("reply_times", [])
    _reply_times.append(int(time.time()))
    flags["reply_times"] = _reply_times
```

### Step 7 — Filter reply_times from agent_flags

The `reply_times` list is internal state that shouldn't leak into the marina_agent prompt. Add `reply_times` to the relay flag filtering block (Step 2 existing code). Change:

```python
agent_flags = dict(flags)
for _rk in ("awaiting_relay", "relay_token", "relay_question"):
    agent_flags.pop(_rk, None)
```

To:

```python
agent_flags = dict(flags)
for _rk in ("awaiting_relay", "relay_token", "relay_question", "reply_times"):
    agent_flags.pop(_rk, None)
```

Also filter `reply_times` from the fully-escalated guard's `_esc_flags` (same pattern):

```python
for _rk in ("awaiting_relay", "relay_token", "relay_question", "reply_times"):
    _esc_flags.pop(_rk, None)
```

### Step 7b — Add reply_times recording + state persistence to fully-escalated guard

The fully-escalated guard (lines 184–197) returns early, bypassing the reply_times recording and state persistence at the end of the function. Without this fix, anti-loop never triggers on fully-escalated threads.

Insert BEFORE the `return esc_reply` line in the fully-escalated guard:

```python
        # Record reply timestamp + persist (early return bypasses end-of-function persistence)
        if esc_reply:
            _reply_times = flags.get("reply_times", [])
            _reply_times.append(int(time.time()))
            flags["reply_times"] = _reply_times
        state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
```

### Step 8 — Update file header

Change `Last modified: Brief 071` to `Last modified: Brief 072`.

### Step 9 — Create test file

Create `tests/social/test_072_whatsapp_multi_trip.py` with these tests:

**Test 1: `test_multi_trip_reset_archives_booking`**
- Pre-set fields (trip_key="west_coast_beach", experience="West Coast Beach Trip", date="2026-03-18", guests="2", departure_time="09:00", customer_name="Test User") and flags (hold_created=True, booking_ref="BF-2026-99001", payment_link="https://demo.pay/test")
- Mock marina_agent to return intents=["booking"], fields={"trip_key": "klein_curacao"} (only partial — triggers multi-trip reset but post-validate's `all()` check will fail since date/guests are cleared by reset, preventing downstream calendar/sheets calls)
- Call handle_incoming_whatsapp_message
- Assert: `completed_bookings` has 1 entry with booking_ref="BF-2026-99001", trip_key="west_coast_beach"
- Assert: `fields` has customer_name="Test User" (persistent), no trip_key/date/guests from old booking
- Assert: `flags` has no hold_created, booking_ref, payment_link

**Test 2: `test_multi_trip_max_bookings_no_reset`**
- Pre-set completed_bookings with 3 entries (max), flags with hold_created=True, fields with customer_name
- Mock marina_agent to return intents=["booking"], reply="Some reply", fields={} (empty — no new fields to trigger downstream)
- Assert: completed_bookings still has 3 entries (no archive happened), hold_created still True

**Test 3: `test_returning_customer_by_ref`**
- Create a real booking in SQLite via `state_registry.save_booking("BF-2026-88001", {"trip_key": "sunset_cruise", "customer_name": "Jane"}, {}, customer_email="TEST_072_RET_001")`
- Mock marina_agent to return intents=["inquiry"], reply="Happy to help!"
- Send message text containing "BF-2026-88001"
- Assert: persisted state flags have `returning_booking` = "BF-2026-88001"
- Assert: persisted state fields pre-populated from past booking (trip_key="sunset_cruise", customer_name="Jane")
- Cleanup: delete from bookings table where booking_ref="BF-2026-88001"

**Test 4: `test_returning_customer_unknown_ref`**
- Mock marina_agent to return intents=["inquiry"], reply="Let me check."
- Send message text containing "BF-2026-00000" (no matching booking)
- Check: marina_agent was called with `unknown_ref` = "BF-2026-00000" in thread_flags
- Assert: persisted state does NOT have `unknown_ref` (cleared as one-shot after call)

**Test 5: `test_returning_customer_by_phone`**
- Create a booking with `customer_email="test_072_ret_003"` (lowercase, matching save_booking normalization) via `state_registry.save_booking("BF-2026-88005", {"trip_key": "jet_ski", "guests": 1}, {}, customer_email="TEST_072_RET_003")`
- Mock marina_agent to return intents=["inquiry"], reply="Welcome back!"
- Send a message from phone="TEST_072_RET_003" (no ref in text, no completed_bookings)
- Check that marina_agent was called with `_past_customer_bookings` in thread_flags
- Assert: the summary line includes "jet_ski" and "BF-2026-88005"
- Cleanup: delete from bookings table where booking_ref="BF-2026-88005"

**Test 6: `test_anti_loop_blocks_after_limit`**
- Pre-set flags with `reply_times` = list of 15 timestamps all within the last hour
- Call handle_incoming_whatsapp_message
- Assert: returns empty string
- Assert: marina_agent.process_message was NOT called

**Test 7: `test_anti_loop_allows_after_window`**
- Pre-set flags with `reply_times` = list of 15 timestamps all from 2 hours ago (outside window)
- Mock marina_agent to return intents=["inquiry"], reply="Here to help!"
- Call handle_incoming_whatsapp_message
- Assert: returns "Here to help!"
- Assert: marina_agent.process_message WAS called (call_count == 1)

**Test 8: `test_reply_times_recorded`**
- Mock marina_agent to return intents=["inquiry"], reply="Hello!"
- Call handle_incoming_whatsapp_message with a fresh phone (no pre-existing state)
- Check persisted state: flags should have `reply_times` with 1 entry, value within last 5 seconds

**Test 9: `test_reply_times_not_in_agent_flags`**
- Pre-set flags with reply_times=[int(time.time())] (1 recent timestamp)
- Mock marina_agent to return intents=["inquiry"], reply="Sure!"
- Inspect the thread_flags kwarg passed to marina_agent.process_message
- Assert: `reply_times` not in the flags passed to marina_agent

**Test 10: `test_completed_bookings_summary_in_agent_flags`**
- Pre-set completed_bookings with 1 entry: {"booking_ref": "BF-2026-77001", "trip_key": "klein_curacao", "experience": "Klein Curaçao", "date": "2026-03-15", "guests": "4"}
- Mock marina_agent to return intents=["inquiry"], reply="What can I help with?"
- Inspect the thread_flags kwarg passed to marina_agent.process_message
- Assert: `_completed_bookings_summary` is in the flags, contains "BF-2026-77001" and "klein_curacao"

**Test 11: `test_anti_loop_blocks_fully_escalated`**
- Pre-set flags with `fully_escalated=True` and `reply_times` = list of 15 timestamps all within the last hour
- Call handle_incoming_whatsapp_message
- Assert: returns empty string
- Assert: marina_agent.process_message was NOT called (anti-loop fires before fully-escalated guard)

All tests use the same pattern as test_071: `_cleanup_phone()`, `_base_result()`, `@patch` decorators for marina_agent.process_message. Each test uses a unique phone number prefixed with `TEST_072_`.

## Tests

See Step 9 above. Each test asserts specific values:
- Test 1: `completed_bookings[0]["booking_ref"] == "BF-2026-99001"`
- Test 2: `len(completed_bookings) == 3` (unchanged)
- Test 3: `flags["returning_booking"] == "BF-2026-88001"`
- Test 4: `"unknown_ref" not in state["flags"]` (cleared)
- Test 6: `reply == ""` and `mock_process.call_count == 0`
- Test 7: `reply != ""` and `mock_process.call_count == 1`

## Success Condition

All 11 new tests pass. All 58 existing social tests pass (regression). Multi-trip, returning customer, and anti-loop behaviors match email_poller semantics.

## Rollback

`git checkout HEAD -- agents/social/social_agent.py && rm tests/social/test_072_whatsapp_multi_trip.py`
