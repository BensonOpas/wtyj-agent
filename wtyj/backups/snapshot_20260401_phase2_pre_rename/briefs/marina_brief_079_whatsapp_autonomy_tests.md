# BRIEF 079 — WhatsApp Autonomy Tests: Edge Cases for Full Autonomous Operation
**Status:** Approved | **Files:** `tests/social/live_test_whatsapp_079.py` (new) | **Depends on:** 075, 078 | **Blocks:** —

## Context
Briefs 075 and 078 delivered 19 live test scenarios (98 checks) covering happy paths, stress inputs, and basic escalation. But several critical code paths in `social_agent.py` have never been exercised with real Claude calls — specifically the fully-escalated guard, stale conversation reset, slot unavailability, manifest failure, past date rejection, rate limiting, unknown booking refs, phone-based returning customer recognition, the max-bookings-per-thread cap, and customer follow-up during awaiting_relay. These gaps mean the agent is untested on the exact paths that determine whether it can run fully autonomously without human intervention.

## Why This Approach
Could add unit tests (mocked Claude), but the existing test_070–077 suite already covers the Python logic. What's missing is proof that **Claude behaves correctly** in these edge cases — empathetic reply after escalation, graceful rejection on sold-out trip, French language handling, etc. Only live Claude calls prove that. Follows the same pattern as 075 and 078: real `handle_incoming_whatsapp_message()` calls, mocked only for Google API writes and `check_availability` (for deterministic slot control). New file `live_test_whatsapp_079.py` keeps existing test files untouched.

## Source Material

### Trip data (from client.json)
- `klein_curacao`: $120/adult, daily, capacity 30, 2 departures (08:00, 08:30)
- `snorkeling_3in1`: $110/adult, Fridays only, capacity 20, 1 departure
- `west_coast_beach`: $120/adult, Wednesdays and Sundays, capacity 25, 1 departure
- `sunset_cruise`: $79/adult, Tue/Thu/Fri/Sat, capacity 20, 1 departure (17:30)
- `jet_ski`: $135/adult, daily, capacity 4, 12 departures

### Booking rules
- `max_bookings_per_thread`: 3
- Rate limit: `_MAX_REPLIES_PER_HOUR = 50`, `_REPLY_WINDOW_SECONDS = 3600`
- Stale conversation: `_STALE_CONVERSATION_SECONDS = 86400` (24 hours)

### Code paths under test (social_agent.py line references)
- Fully-escalated guard: lines 246–264
- Stale conversation reset: lines 166–203, called at 225
- Rate limit: lines 229–237
- Semi-escalation relay flags: lines 467–516
- Post-validate past date: lines 134–142
- Slot unavailable: lines 453–462
- Manifest failure: lines 592–612
- Hold race condition: lines 443–452
- Unknown booking ref: lines 290–292
- Phone-based returning customer: lines 295–305
- Multi-trip max reached: lines 317–318
- Placeholder stripping: line 674

### Test harness pattern (from 075/078)
- `send_message(phone, text)` wraps `handle_incoming_whatsapp_message()` with mocks
- Mock targets: `sheets_writer.log_escalation`, `sheets_writer.log_hold_created`, `sheets_writer.log_hold_failed`, `sheets_writer.log_manifest_update`, `gws_calendar.create_or_update_manifest`, `gws_calendar.remove_from_manifest`, `gws_calendar.check_availability`
- Default: `create_or_update_manifest` returns `{"ok": True, "eventId": "test-evt-079", "htmlLink": "https://calendar.google.com/test"}`, `check_availability` returns `{"available": True, "spots_remaining": 20, "capacity": 25}`
- `_cleanup_phone(phone)` cleans: `whatsapp_threads`, `whatsapp_booking_state`, `trip_bookings`, `bookings`, `pending_notifications`
- After `handle_incoming_whatsapp_message`, replicate webhook_server storage: `wa_store_message(phone, "user", text)` and `wa_store_message(phone, "assistant", reply)`
- Phone prefix: `LIVE_079_`

## Instructions

### Step 1 — Create `tests/social/live_test_whatsapp_079.py`

File header:
```python
# bluemarlin/tests/social/live_test_whatsapp_079.py
# Created: Brief 079
# Purpose: Live autonomy tests — edge cases for fully autonomous WhatsApp operation
```

Copy the test harness scaffolding (imports, env setup, `_cleanup_phone`, `check`, `check_contains`, `check_not_contains`, `check_contains_any`, `send_message`, `main`) from `live_test_whatsapp_078.py`. Change:
- `_PHONE_PREFIX = "LIVE_079_"`
- Update `send_message` to accept optional `mock_overrides` dict for per-scenario mock configuration (availability=False, manifest failure, hold race). Implementation: after starting default mocks, apply overrides. Example: `mock_overrides={"check_availability": {"available": False, "spots_remaining": 0, "capacity": 25}}` sets `mock_objects[6].return_value` to that dict. `mock_overrides={"create_or_update_manifest": {"ok": False, "error": "Calendar API timeout"}}` sets `mock_objects[4].return_value`. `mock_overrides={"create_soft_hold_returns_none": True}` patches `state_registry.create_soft_hold` to return `None`.

### Step 2 — Write 12 test scenarios

**Scenario U: Fully-Escalated Follow-Up (2 turns)**
- Turn 1: Send: "I had the worst experience on your boat yesterday. The crew was incredibly rude and the food was terrible. I want a full refund NOW." Verify `fully_escalated=True`.
- Turn 2: Send a normal message "Can I book a sunset cruise tomorrow?". Verify: reply is NOT empty, reply does NOT contain booking summary (`$79`, `confirm`), `fully_escalated` is still `True`, no `awaiting_booking_confirmation` flag set. The reply should be empathetic/holding ("team is looking into it" or similar).

**Scenario V: Semi-Escalation + Customer Follow-Up While Waiting (2 turns)**
- Turn 1: Send: "What's the maximum weight limit for the jet ski? I'm a bigger guy, about 130kg, and I want to make sure it's safe." This should trigger semi-escalation. Verify `awaiting_relay=True`.
- Turn 2: Send "Hey any update on my question?". Verify: reply is NOT empty (agent should respond, not silently drop), `awaiting_relay` is still `True`, reply does NOT contain booking flow content. Note: the fully_escalated guard at line 246 only catches `fully_escalated`, NOT `awaiting_relay`. So this message goes through the normal path. The test verifies Claude handles this gracefully with relay context in the flags.

**Scenario W: Slot Unavailable (1 turn)**
- Use `mock_overrides={"check_availability": {"available": False, "spots_remaining": 0, "capacity": 20}}`.
- Send: "Book the Sunset Cruise for April 10 2027 for 2 guests. Name is Sold Out Test, phone +5999999079."
- Verify: reply contains "fully booked" or "unavailable", `awaiting_booking_confirmation` is `False`, `slot_available` is `False`. No `[PAYMENT_LINK]` or `[BOOKING_REF]` in reply.

**Scenario X: Manifest Failure on Confirmation (2 turns)**
- Turn 1: Normal booking request (Sunset Cruise April 10 2027, 2 guests, name Manifest Test). Use default mocks (available). Verify booking summary sent, `awaiting_booking_confirmation=True`.
- Turn 2: Send "Yes, book it!" but use `mock_overrides={"create_or_update_manifest": {"ok": False, "error": "Calendar API timeout"}}`. Verify: reply does NOT contain `[PAYMENT_LINK]`, `hold_created` is NOT `True`. Reply should be apologetic (reply_hold_failed path). `slot_checked` should be reset to `False`.

**Scenario Y: Past Date Rejection (1 turn)**
- Send: "Book the Klein Curacao trip for March 1 2026 for 2 people. Name is Past Date Test."
- Verify: reply contains "passed" or "already passed" or "different date", `awaiting_booking_confirmation` is `False`. No booking flow triggered.

**Scenario Z: Stale Conversation Reset (2 turns)**
- Turn 1: Book sunset cruise (Sunset Cruise April 10 2027, 2 guests, name Stale Test). Verify booking summary and `awaiting_booking_confirmation=True`.
- Between turns: manually update `last_activity` in `whatsapp_booking_state` to 48 hours ago using Python (NOT raw SQL, to preserve timezone-aware ISO format):
  ```python
  from datetime import datetime, timezone, timedelta
  _stale_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
  conn = state_registry._get_conn()
  conn.execute("UPDATE whatsapp_booking_state SET last_activity = ? WHERE phone = ?", (_stale_ts, phone))
  conn.commit()
  conn.close()
  ```
  This produces a timezone-aware ISO string (e.g. `2026-03-11T14:00:00+00:00`) matching the format used by `wa_save_booking_state`, avoiding a TypeError when `_maybe_reset_stale_conversation` subtracts aware from naive datetime.
- Turn 2: Send "Hi, what trips do you have?". Verify: `awaiting_booking_confirmation` is `False` (stale reset fired), reply mentions trips (fresh conversation), fields are cleared (except possibly customer_name).

**Scenario AA: Unknown Booking Ref (1 turn)**
- Send: "Hi I booked with you, reference BF-2026-00000. I need to change my date."
- Verify: reply is NOT empty, `unknown_ref` flag is NOT in final state (it's a one-shot flag, cleared at line 361). The agent should handle gracefully — either ask for clarification or say the ref wasn't found.

**Scenario BB: Phone-Based Returning Customer (1 turn)**
- Setup: create a past booking in the `bookings` table with `customer_email=phone`:
  ```python
  _ref = "BF-2026-99902"
  _fields = {"trip_key": "klein_curacao", "experience": "Klein Curacao Trip",
             "date": "2026-03-01", "guests": "4", "customer_name": "Return Phone Test",
             "departure_time": "08:00"}
  _flags = {"booking_ref": _ref, "hold_created": True}
  state_registry.save_booking(_ref, _fields, _flags, customer_email=phone)
  ```
- Send: "Hi, I'd like to book another trip please!" (no ref cited).
- Verify: reply is NOT empty, reply mentions trips or asks what they'd like to book. Also verify the agent had returning customer context available by checking the reply acknowledges them as a returning customer OR mentions past booking details (Klein Curacao, March, 4 guests). If the reply is generic (no returning customer acknowledgment), that's still acceptable — the key assertion is that the code path at lines 295-305 ran without error and the reply is coherent.

**Scenario CC: French Language (1 turn)**
- Send: "Bonjour! Nous sommes 4 personnes et nous cherchons une excursion en bateau à Curaçao. Quelles sont vos options et les prix?"
- Verify: reply is NOT empty, reply contains at least one trip name or price indicator (`$`, `Klein`, `Sunset`, `excursion`, `bateau`).

**Scenario DD: Rate Limit Boundary (2 turns, seeded state)**
- Setup: seed 49 reply timestamps all within the last hour:
  ```python
  import time, random
  _now = int(time.time())
  _seeded_times = [_now - random.randint(60, 3500) for _ in range(49)]
  state_registry.wa_save_booking_state(phone, {}, {"reply_times": _seeded_times}, [])
  ```
  After seeding, the phone has 49 reply_times, all within the 3600-second window.
- Turn 1: Send "What trips do you have?". The code reads 49 entries, prunes (all within window, still 49), checks `49 >= 50` = False, proceeds. After reply, appends timestamp #50.
- Verify: reply is NOT empty (49th call passes the check).
- Turn 2: Send "Tell me more about Klein Curacao". The code reads 50 entries, prunes (all within window, still 50), checks `50 >= 50` = True, returns "".
- Verify: reply IS empty string (rate limited). State is still persisted (line 236-237 saves before returning).

**Scenario EE: Max Bookings Cap (3 turns, seeded state)**

Background: `max_bookings_per_thread` is 3. The multi-trip reset at line 341 only fires when `len(completed_bookings) < max`. After 3 confirmations, completed_bookings has 2 entries (the 3rd is in current flags as hold_created, not yet archived). A 4th booking request WILL reset (2 < 3), archiving the 3rd. But a 5th request hits the wall (3 < 3 = False, no reset). The `_max_bookings_reached` flag is set at lines 317-318 when `len(completed_bookings) >= max AND hold_created`. This means the effective cap is 4 bookings, not 3 — a potential bug worth documenting.

This test seeds state to avoid 8+ expensive Claude calls:

- Setup: seed phone state via `wa_save_booking_state` with:
  ```python
  fields = {"trip_key": "sunset_cruise", "experience": "Sunset Cruise",
            "date": "2027-04-10", "guests": "2", "customer_name": "Max Test",
            "departure_time": "17:30"}
  flags = {"hold_created": True, "booking_ref": "BF-2026-99903",
           "booking_confirmed": True, "event_id": "test-evt-ee",
           "payment_link": "https://demo.pay/test", "payment_status": "pending"}
  completed_bookings = [
      {"booking_ref": "BF-2026-99901", "trip_key": "klein_curacao",
       "experience": "Klein Curacao Trip", "date": "2027-04-08",
       "guests": "2", "departure_time": "08:00", "payment_link": "https://demo.pay/test1"},
      {"booking_ref": "BF-2026-99902", "trip_key": "jet_ski",
       "experience": "Jet Ski Excursion", "date": "2027-04-09",
       "guests": "2", "departure_time": "10:00", "payment_link": "https://demo.pay/test2"},
  ]
  state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
  ```
  This simulates: 2 archived bookings + 1 active (hold_created). Total: 3 bookings done.

- Turn 1: "I also want the snorkeling trip for April 16 2027 for 2 people". April 16 2027 is a Friday (snorkeling is Fridays only). This is booking #4. Multi-trip reset fires (completed=2 < 3), archives current sunset booking (completed becomes 3), resets fields, starts new booking.
- Verify: `completed_bookings` length is 3, fields contain snorkeling data or new booking info.

- Turn 2: "Yes, confirm it!". Confirm the snorkeling booking.
- Verify: `hold_created=True`, `booking_ref` starts with `BF-`.

- Turn 3: "Now book a jet ski for April 17 2027 at 10am for 2 people". April 17 2027 is a Saturday (jet ski is daily, any day works). This is booking #5. Multi-trip reset does NOT fire (completed=3, 3 < 3 = False). `_max_bookings_reached=True` is passed to Claude.
- Verify: `completed_bookings` still 3 (no archive happened), `hold_created` still True from Turn 2 (fields NOT reset — snorkeling data persists, not jet ski). Claude should acknowledge the limit gracefully.

**Scenario FF: Placeholder Safety Net (2 turns)**
- Turn 1: Book Sunset Cruise April 10 2027, 2 guests, name Placeholder Test. Verify summary.
- Turn 2: "Yes, confirm it!". Verify: reply does NOT contain literal string `[PAYMENT_LINK]`, reply does NOT contain literal string `[BOOKING_REF]`, reply DOES contain `demo.pay` (payment link replaced), reply DOES contain `BF-` (booking ref replaced).

### Step 3 — Run the tests on VPS

```bash
export $(grep -v '^#' config/bluemarlin.env | grep '=' | xargs)
python3 tests/social/live_test_whatsapp_079.py
```

Record all results.

## Tests

Each scenario has specific assertions listed in the instructions above. Summary of expected check counts per scenario:

| Scenario | Checks | Key assertion |
|----------|--------|---------------|
| U: Fully-escalated follow-up | 5 | No booking flow after escalation |
| V: Semi-escalation follow-up | 5 | Reply exists, relay flags preserved |
| W: Slot unavailable | 4 | "fully booked", no confirmation |
| X: Manifest failure | 5 | reply_hold_failed path, no hold_created |
| Y: Past date rejection | 3 | "already passed", no booking |
| Z: Stale conversation reset | 4 | Fresh state after 24h gap |
| AA: Unknown booking ref | 3 | Graceful handling, one-shot flag cleared |
| BB: Phone-based returning | 3 | Reply exists, past booking accessible |
| CC: French language | 2 | French reply with trip info |
| DD: Rate limit boundary | 4 | 50th reply works, 51st returns "" |
| EE: Max bookings | 5 | 5th booking blocked (4th succeeds, 5th hits cap) |
| FF: Placeholder safety | 4 | No raw placeholders, real links present |

**Total: ~47 checks across 12 scenarios**

## Success Condition
All 12 scenarios run on VPS with real Claude API calls. All checks pass. Results documented in `briefs/marina_output_079.md`.

## Rollback
Delete `tests/social/live_test_whatsapp_079.py`. No source files modified.
