# BRIEF 073 — WhatsApp Hardening: Stale Reset + Cleanup + Edge Case Tests

**Status:** Draft | **Files:** `agents/social/social_agent.py`, `shared/state_registry.py`, `agents/social/webhook_server.py`, `tests/social/test_073_whatsapp_hardening.py` | **Depends on:** Brief 072 | **Blocks:** —

## Context

WhatsApp booking is feature-complete (Briefs 069–072, 69 tests). Three production gaps remain:

1. **Stale conversation reset** — `whatsapp_booking_state` has no expiry. A customer who messaged last week inherits stale fields/flags when they message again. email_poller solved this in Brief 053 with `_maybe_reset_stale_thread`. WhatsApp needs the same: a 24h inactivity gap should reset booking state (archive if hold_created, clear fields/flags, clear escalation state).

2. **Stale data cleanup** — `whatsapp_threads` and `whatsapp_processed` tables grow indefinitely. email_poller has `_cleanup_stale_data()` (Brief 065). WhatsApp needs equivalent periodic cleanup.

3. **Untested code paths** — Four code paths in social_agent.py have zero test coverage: change detection (cancel hold when customer changes details mid-confirmation), manifest creation failure, hold race condition (capacity grabbed between check and insert), and empty reply early exit.

## Why This Approach

The stale conversation reset mirrors Brief 053's proven pattern — detect inactivity gap, archive if needed, reset for clean state. The 24h threshold matches `wa_get_history`'s existing 24h window, making the model consistent: after 24h of silence, both conversation history AND booking state start fresh.

Cleanup runs hourly via a module-level timestamp guard in webhook_server (same pattern as email_poller's per-cycle cleanup). Not a cron job — runs inline with message processing.

Edge case tests fill the four remaining coverage gaps rather than adding new functionality. All four paths are already implemented; they just lack verification.

Rejected: separate cleanup cron/timer — adds operational complexity for a function that takes <50ms. Note: FastAPI background tasks may run concurrently, so two simultaneous webhooks could both trigger cleanup. This is harmless (double DELETE is idempotent under SQLite WAL) but differs from email_poller's single-threaded model.

## Source Material

### state_registry.py — `wa_get_booking_state` (current)
```python
def wa_get_booking_state(phone: str) -> dict:
    conn = _get_conn()
    row = conn.execute(
        "SELECT fields_json, flags_json, completed_bookings_json "
        "FROM whatsapp_booking_state WHERE phone = ?",
        (phone,)
    ).fetchone()
    conn.close()
    if not row:
        return {"fields": {}, "flags": {}, "completed_bookings": []}
    return {
        "fields": json.loads(row[0] or "{}"),
        "flags": json.loads(row[1] or "{}"),
        "completed_bookings": json.loads(row[2] or "[]"),
    }
```

### whatsapp_booking_state table schema
```sql
CREATE TABLE IF NOT EXISTS whatsapp_booking_state (
    phone TEXT PRIMARY KEY,
    fields_json TEXT DEFAULT '{}',
    flags_json TEXT DEFAULT '{}',
    completed_bookings_json TEXT DEFAULT '[]',
    last_activity TEXT NOT NULL,
    created_at TEXT NOT NULL
)
```

### email_poller.py — `_maybe_reset_stale_thread` (Brief 053 pattern)
- Detects new email (no In-Reply-To) on thread older than 24h
- Archives booking if hold_created
- Resets fields (keeps customer identity) and all booking flags

### email_poller.py — `_cleanup_stale_data` (Brief 065 pattern)
- Threads >30d: archived to JSONL, removed from state
- Processed hashes >5000: pruned
- sender_rates: expired entries cleaned

### social_agent.py — Untested code paths
- **Change detection** (lines 332-346): `_was_awaiting` true, `awaiting_booking_confirmation` cleared, `booking_confirmed` false → cancel hold
- **Manifest failure** (lines 501-521): `create_or_update_manifest()` returns `{ok: false}` → cancel hold, use reply_hold_failed, log to Sheets
- **Hold race** (lines 396-406): `check_availability()` returns available, `create_soft_hold()` returns None → unavailable message
- **Empty reply** (lines 288-289): marina_agent returns `reply: ""` → return empty immediately

### social_agent.py — Constants for stale reset
```python
_BOOKING_FLAGS_TO_RESET = {
    "hold_created", "booking_confirmed", "booking_ref", "hold_id",
    "payment_id", "payment_link", "payment_status",
    "event_id", "event_link",
    "slot_checked", "slot_available", "spots_remaining", "trip_capacity",
    "awaiting_booking_confirmation",
    "hold_trip_key", "hold_date", "hold_departure_time",
}
_PERSISTENT_FIELDS = {"customer_name", "phone"}
```

## Instructions

### Step 1 — Modify `wa_get_booking_state` in `state_registry.py`

Add `last_activity` to the SELECT query and return dict:

```python
def wa_get_booking_state(phone: str) -> dict:
    """Get booking state for a phone number. Returns {fields, flags, completed_bookings, last_activity}."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT fields_json, flags_json, completed_bookings_json, last_activity "
        "FROM whatsapp_booking_state WHERE phone = ?",
        (phone,)
    ).fetchone()
    conn.close()
    if not row:
        return {"fields": {}, "flags": {}, "completed_bookings": [], "last_activity": None}
    return {
        "fields": json.loads(row[0] or "{}"),
        "flags": json.loads(row[1] or "{}"),
        "completed_bookings": json.loads(row[2] or "[]"),
        "last_activity": row[3],
    }
```

### Step 2 — Add `wa_cleanup_stale_data` in `state_registry.py`

Add after `wa_save_booking_state`:

```python
def wa_cleanup_stale_data() -> dict:
    """Clean up old WhatsApp data. Returns counts of cleaned rows."""
    conn = _get_conn()
    now = datetime.now(timezone.utc)
    # Conversation messages >30 days
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    cur = conn.execute("DELETE FROM whatsapp_threads WHERE created_at < ?", (cutoff_30d,))
    threads_cleaned = cur.rowcount
    # Processed message IDs >7 days
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    cur = conn.execute("DELETE FROM whatsapp_processed WHERE created_at < ?", (cutoff_7d,))
    processed_cleaned = cur.rowcount
    conn.commit()
    conn.close()
    return {"threads_cleaned": threads_cleaned, "processed_cleaned": processed_cleaned}
```

### Step 3 — Update `state_registry.py` file header

Change `Last modified: Brief 069` to `Last modified: Brief 073`.

### Step 4 — Add stale conversation reset to `social_agent.py`

Add `_STALE_CONVERSATION_SECONDS = 86400` constant after `_REPLY_WINDOW_SECONDS`:

```python
_STALE_CONVERSATION_SECONDS = 86400  # 24 hours — matches wa_get_history window
```

Add `_maybe_reset_stale_conversation` function after `_post_validate`:

```python
def _maybe_reset_stale_conversation(last_activity, fields, flags, completed_bookings):
    """Reset booking state if >24h since last activity. Returns True if reset happened."""
    if not last_activity:
        return False
    try:
        last = datetime.fromisoformat(last_activity)
        now = datetime.now(timezone.utc)
        if (now - last).total_seconds() < _STALE_CONVERSATION_SECONDS:
            return False
    except (ValueError, TypeError):
        return False

    # Archive current booking if one exists
    if flags.get("hold_created"):
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

    # Reset fields — keep customer identity
    preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
    fields.clear()
    fields.update(preserved)

    # Reset all booking + escalation + rate-limit flags
    for fk in _BOOKING_FLAGS_TO_RESET:
        flags.pop(fk, None)
    for fk in ("fully_escalated", "awaiting_relay", "relay_token",
               "relay_question", "reply_times", "returning_booking"):
        flags.pop(fk, None)

    return True
```

### Step 5 — Call stale reset in `handle_incoming_whatsapp_message`

Insert AFTER the state load lines (after `completed_bookings = ...`) but BEFORE the anti-loop guard:

```python
    last_activity = state.get("last_activity")

    # Stale conversation reset — 24h inactivity gap means new conversation
    if _maybe_reset_stale_conversation(last_activity, fields, flags, completed_bookings):
        bm_logger.log("whatsapp_stale_reset", phone=phone)
```

### Step 6 — Add periodic cleanup to `webhook_server.py`

Add `import time` to imports. Add module-level timestamp:

```python
_last_cleanup_ts = 0
```

Add cleanup function:

```python
def _maybe_run_cleanup():
    """Run stale data cleanup at most once per hour."""
    global _last_cleanup_ts
    now = time.time()
    if now - _last_cleanup_ts < 3600:
        return
    _last_cleanup_ts = now
    result = state_registry.wa_cleanup_stale_data()
    if result["threads_cleaned"] or result["processed_cleaned"]:
        log("whatsapp_cleanup", **result)
```

Call `_maybe_run_cleanup()` at the start of `_process_whatsapp_event`, before the `try` block:

```python
def _process_whatsapp_event(payload: dict):
    """Background task: parse messages, dedup, call agent, send reply."""
    _maybe_run_cleanup()
    try:
        ...
```

### Step 7 — Update file headers

- `social_agent.py`: Change `Last modified: Brief 072` to `Last modified: Brief 073`
- `webhook_server.py`: Change `Last modified: Brief 069` to `Last modified: Brief 073`

### Step 8 — Create test file

Create `tests/social/test_073_whatsapp_hardening.py` with these tests:

**Test 1: `test_stale_conversation_resets_fields`**
- Set `whatsapp_booking_state` with `last_activity` = 48 hours ago, fields with trip_key/date/guests/customer_name
- Mock marina_agent to return intents=["inquiry"], reply="Hi!"
- Call handle_incoming_whatsapp_message
- Assert: persisted fields only has customer_name (persistent), trip_key/date/guests cleared
- Assert: reply is "Hi!" (not blocked by stale state)

**Test 2: `test_stale_conversation_archives_booking`**
- Set `whatsapp_booking_state` with `last_activity` = 48 hours ago, flags with hold_created=True, booking_ref="BF-2026-55001", fields with trip_key="west_coast_beach"
- Mock marina_agent to return intents=["inquiry"], reply="Hello!"
- Assert: completed_bookings has 1 entry with booking_ref="BF-2026-55001"
- Assert: flags has no hold_created, no booking_ref

**Test 3: `test_stale_conversation_clears_escalation`**
- Set `last_activity` = 48 hours ago, flags with fully_escalated=True, awaiting_relay=True, relay_token="abc"
- Mock marina_agent to return intents=["inquiry"], reply="Hi there!"
- Assert: flags has no fully_escalated, no awaiting_relay, no relay_token

**Test 4: `test_fresh_conversation_no_reset`**
- Set `last_activity` = 1 hour ago, fields with trip_key/date/guests
- Mock marina_agent to return intents=["inquiry"], reply="Sure!", fields={}
- Assert: persisted fields still has trip_key, date, guests (not reset)

**Test 5: `test_wa_get_booking_state_returns_last_activity`**
- Call `wa_save_booking_state(phone, {}, {})` then `wa_get_booking_state(phone)`
- Assert: result has "last_activity" key, value is not None, is a valid ISO timestamp

**Test 6: `test_wa_cleanup_stale_data`**
- Insert old rows into `whatsapp_threads` (created_at 60 days ago) and `whatsapp_processed` (created_at 14 days ago)
- Call `wa_cleanup_stale_data()`
- Assert: old rows deleted, result counts match
- Insert recent rows and verify they survive cleanup

**Test 7: `test_change_detection_cancels_hold`**
- Pre-set awaiting_booking_confirmation=True, hold_id (create real soft hold), hold_trip_key/hold_date/hold_departure_time
- Mock marina_agent to return intents=["booking"], flags={"awaiting_booking_confirmation": False} (customer changed details — Python pops this, then _was_awaiting triggers change detection)
- Mock gws_calendar.remove_from_manifest
- Assert: hold cancelled (state_registry.cancel_hold called), slot_checked=False, slot_available=False, hold_id removed
- Assert: remove_from_manifest called with correct args

**Test 8: `test_manifest_failure_cancels_hold`**
- Pre-set booking_confirmed=True + all required booking fields + hold with hold_id
- Mock marina_agent to return intents=["booking"], flags={"booking_confirmed": True}, reply="Congrats!", reply_hold_failed="Sorry, couldn't book"
- Mock gws_calendar.create_or_update_manifest to return {"ok": False, "error": "calendar API error"}
- Mock sheets_writer.log_hold_failed
- Assert: reply contains "Sorry, couldn't book" (reply_hold_failed used)
- Assert: hold cancelled, slot flags reset
- Assert: sheets_writer.log_hold_failed called

**Test 9: `test_hold_race_condition`**
- Pre-set booking fields (all 4 required), mock marina_agent to return booking intent + all fields (triggers post-validate → summary → awaiting_booking_confirmation)
- Mock gws_calendar.check_availability to return {"available": True, "spots_remaining": 10, "capacity": 25}
- Mock state_registry.create_soft_hold to return None (race — capacity grabbed)
- Assert: reply contains "fully booked"
- Assert: awaiting_booking_confirmation is False (cleared)
- Assert: no hold_id in flags

**Test 10: `test_empty_reply_returns_empty`**
- Pre-set fields with trip_key="sunset_cruise", customer_name="Test"
- Mock marina_agent to return reply=""
- Call handle_incoming_whatsapp_message
- Assert: returns ""
- Assert: persisted state unchanged — read back from DB via `wa_get_booking_state`, verify fields still has trip_key="sunset_cruise" (the early return at line 289 skips `wa_save_booking_state`, so DB state is untouched)

All tests use `@patch("agents.social.social_agent.marina_agent.process_message")` and unique phone numbers prefixed with `TEST_073_`. Tests that exercise booking paths mock all required external dependencies (gws_calendar, sheets_writer, state_registry functions as needed).

## Tests

See Step 8 above. Key assertions:
- Test 1: `state["fields"].get("trip_key") is None` and `state["fields"]["customer_name"] == "Test User"`
- Test 2: `state["completed_bookings"][0]["booking_ref"] == "BF-2026-55001"`
- Test 3: `"fully_escalated" not in state["flags"]`
- Test 5: `"last_activity" in result` and `result["last_activity"] is not None`
- Test 7: `state["flags"].get("slot_checked") is False` and `"hold_id" not in state["flags"]`
- Test 8: `"Sorry, couldn't book" in reply`
- Test 9: `"fully booked" in reply`
- Test 10: `reply == ""` and persisted `fields["trip_key"] == "sunset_cruise"` (DB unchanged)

## Success Condition

All 10 new tests pass. All 69 existing social tests pass (regression). Stale conversations reset after 24h, old data cleaned up hourly, and all four previously-untested edge cases verified.

## Rollback

```
git checkout HEAD -- agents/social/social_agent.py shared/state_registry.py agents/social/webhook_server.py
rm tests/social/test_073_whatsapp_hardening.py
```
