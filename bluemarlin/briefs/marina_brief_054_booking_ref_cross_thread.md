# BRIEF 054 — Booking ref in confirmation + cross-thread memory
**Status:** Draft | **Files:** `src/state_registry.py`, `src/email_poller.py`, `src/marina_agent.py` | **Depends on:** 053 | **Blocks:** 055

## Context
`booking_ref` (BF-YYYY-XXXXX) is generated at hold-confirmation time (email_poller.py line 806) and stored in `th["flags"]["booking_ref"]`. It is passed to marina_agent via thread_flags and appears in the THREAD CONTEXT section of the prompt. However, the prompt has **no instruction** to include it in the confirmation reply — the customer never sees their booking reference.

Additionally, if a returning customer emails in a new thread mentioning their booking ref, Marina has no memory — there is no `bookings` lookup table to resolve a ref back to booking context.

## Why This Approach
Two options were considered:
1. **Prompt-only fix** — just tell Marina to include booking_ref. Solves visibility but not cross-thread memory.
2. **Prompt + bookings table** — store completed bookings in SQLite, detect refs in new threads, inject context before the Claude call so Marina can respond knowledgeably on first reply.

Option 2 is chosen because cross-thread memory is a core requirement from the roadmap (ROADMAP_039_044.md §042). The `trip_bookings` table already has booking_ref and customer data but is optimised for capacity tracking, not for fast ref-based lookup of full booking context. A dedicated `bookings` table keyed on `booking_ref` is cleaner and avoids coupling capacity logic with customer lookup.

Detecting `BF-YYYY-XXXXX` in the inbound message body is a structured identifier extraction (a fixed-format alphanumeric code), not language understanding or intent classification. Unlike relay token extraction which operates on email subjects (structured metadata), this operates on body text — but the pattern is unambiguous and cannot match natural language. This is acceptable under Rule 2.

## Source Material

### Current booking_ref generation (email_poller.py lines 805-809)
```python
booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
th["flags"]["booking_ref"] = booking_ref
if th["flags"].get("hold_id"):
    state_registry.set_booking_ref(th["flags"]["hold_id"], booking_ref)
```

### Current thread_flags passed to marina_agent (email_poller.py lines 546-553)
```python
agent_flags = dict(th.get("flags", {}))
for _rk in ("awaiting_relay", "relay_token", "relay_question",
            "relay_customer_email", "relay_reply_subject"):
    agent_flags.pop(_rk, None)
action_context = _build_action_context(th)
result = marina_agent.process_message(
    from_email, subj, body,
    th.get("fields", {}), agent_flags, action_context,
)
```

### Current prompt THREAD CONTEXT section (marina_agent.py lines 175-177)
```python
THREAD CONTEXT (already collected this conversation):
  Fields: {json.dumps(thread_fields, ensure_ascii=False)}
  Flags: {json.dumps(thread_flags, ensure_ascii=False)}
```

## Instructions

### Step 1: state_registry.py — add bookings table and functions

Add the `bookings` table creation in `_get_conn()`, after the `manifest_events` table block:

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bookings ("
        "booking_ref TEXT PRIMARY KEY, "
        "trip_key TEXT, "
        "customer_name TEXT, "
        "customer_email TEXT, "
        "date TEXT, "
        "departure_time TEXT, "
        "guests INTEGER, "
        "special_requests TEXT, "
        "payment_link TEXT, "
        "event_link TEXT, "
        "status TEXT DEFAULT 'pending_payment', "
        "created_at TEXT NOT NULL"
        ")"
    )
```

Add two new public functions at the end of the file (before the `_get_conn().close()` init line):

```python
def save_booking(booking_ref: str, fields: dict, flags: dict,
                 customer_email: str = "") -> None:
    """Upsert a booking record after hold creation success."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO bookings "
        "(booking_ref, trip_key, customer_name, customer_email, date, "
        "departure_time, guests, special_requests, payment_link, event_link, "
        "status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            booking_ref,
            fields.get("trip_key", ""),
            fields.get("customer_name", ""),
            customer_email,
            fields.get("date", ""),
            fields.get("departure_time", ""),
            int(fields.get("guests") or 0),
            fields.get("special_requests", ""),
            flags.get("payment_link", ""),
            flags.get("event_link", ""),
            "confirmed",
            datetime.now(timezone.utc).isoformat(),
        )
    )
    conn.commit()
    conn.close()


def get_booking(booking_ref: str) -> "dict | None":
    """Return full booking dict by ref, or None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT booking_ref, trip_key, customer_name, customer_email, date, "
        "departure_time, guests, special_requests, payment_link, event_link, "
        "status, created_at "
        "FROM bookings WHERE booking_ref = ?",
        (booking_ref,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "booking_ref": row[0], "trip_key": row[1], "customer_name": row[2],
        "customer_email": row[3], "date": row[4], "departure_time": row[5],
        "guests": row[6], "special_requests": row[7], "payment_link": row[8],
        "event_link": row[9], "status": row[10], "created_at": row[11],
    }
```

### Step 2: email_poller.py — save booking after hold success

After the `log(f"Manifest CREATED/UPDATED ...")` line (currently line 917), add:

```python
                            # Save booking for cross-thread memory
                            state_registry.save_booking(
                                booking_ref, fields_now, th["flags"],
                                customer_email=from_email,
                            )
```

### Step 3: email_poller.py — detect booking ref in inbound message

Add a helper function after `_maybe_reset_stale_thread` (around line 233):

```python
def _detect_booking_ref(body: str) -> "str | None":
    """Extract a BF-YYYY-XXXXX booking reference from message body. Returns ref or None."""
    match = re.search(r'BF-\d{4}-\d{5}', body)
    return match.group() if match else None
```

In the main loop, BEFORE the marina_agent call (before line 546 `agent_flags = dict(...)`), add:

```python
                # Detect returning customer by booking ref mention
                _detected_ref = _detect_booking_ref(body)
                if _detected_ref and not th["flags"].get("booking_ref"):
                    _past_booking = state_registry.get_booking(_detected_ref)
                    if _past_booking:
                        th["flags"]["returning_booking"] = _detected_ref
                        # Pre-populate fields from past booking if thread has no data yet
                        for _rbk in ("trip_key", "date", "guests", "customer_name",
                                     "departure_time"):
                            _rbv = _past_booking.get(_rbk)
                            if _rbv and not th["fields"].get(_rbk):
                                th["fields"][_rbk] = _rbv if not isinstance(_rbv, int) else str(_rbv)
                        log(f"Returning customer: loaded booking {_detected_ref} for {from_email}")
```

### Step 4: marina_agent.py — add booking_ref instruction and returning customer context

In `_build_prompt()`, add a new section between `{action_context}` (line 136) and the `ESCALATION BEHAVIOUR:` line (line 138). Insert as a new f-string block on its own line:

```
{action_context}

BOOKING REFERENCE:
When booking_ref is present in thread_flags AND you are writing a booking
confirmation reply (booking_confirmed: true), you MUST include the booking
reference naturally in your reply. Example: "Your booking reference is
BF-2026-12345 — keep this handy for any future questions or changes!"

ESCALATION BEHAVIOUR:
```

This replaces the existing `{action_context}` and `ESCALATION BEHAVIOUR:` lines — the new text goes between them. The BOOKING REFERENCE block is static (unconditional), not wrapped in an if-statement.

Add a returning customer section. In `_build_prompt()`, build a `returning_customer_section` variable near the top (after the `fully_escalated_section` block):

```python
    returning_customer_section = ""
    if thread_flags.get("returning_booking"):
        returning_customer_section = (
            f"\nRETURNING CUSTOMER: This customer referenced booking {thread_flags['returning_booking']}. "
            f"Their booking details are pre-loaded in the Fields above. "
            f"They may want to: check status, change their date, ask a follow-up question, or report an issue. "
            f"Handle naturally based on their message. For refunds or cancellations: set requires_human to true.\n"
        )
```

Insert `{returning_customer_section}` into the prompt string, right after `{fully_escalated_section}`:

Change:
```python
{relay_mode_section}{fully_escalated_section}
```
To:
```python
{relay_mode_section}{fully_escalated_section}{returning_customer_section}
```

### Step 5: Update file headers

- `state_registry.py`: change `LAST MODIFIED: Brief 050` → `LAST MODIFIED: Brief 054`
- `email_poller.py`: change `LAST MODIFIED: Brief 053` → `LAST MODIFIED: Brief 054`
- `marina_agent.py`: change `LAST MODIFIED: Brief 048` → `LAST MODIFIED: Brief 054`

## Tests

File: `tests/test_booking_ref.py`

```python
"""Tests for Brief 054 — Booking ref in confirmation + cross-thread memory."""
import sys, os, time, re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Use a test database to avoid touching production data
import state_registry
_ORIGINAL_DB_PATH = state_registry.DB_PATH
state_registry.DB_PATH = os.path.join(os.path.dirname(__file__), 'test_054.db')

import marina_agent
import email_poller


def _cleanup_db():
    """Remove test database if it exists."""
    if os.path.exists(state_registry.DB_PATH):
        os.remove(state_registry.DB_PATH)
    wal = state_registry.DB_PATH + "-wal"
    shm = state_registry.DB_PATH + "-shm"
    if os.path.exists(wal):
        os.remove(wal)
    if os.path.exists(shm):
        os.remove(shm)


def test_save_and_get_booking():
    """Round-trip: save a booking, retrieve it, verify all fields."""
    _cleanup_db()
    fields = {
        "trip_key": "klein_curacao",
        "customer_name": "Callou",
        "date": "2026-04-15",
        "departure_time": "08:30",
        "guests": 4,
        "special_requests": "window seat",
    }
    flags = {
        "payment_link": "https://demo.pay/bluemarlin/pay123",
        "event_link": "https://calendar.google.com/event/abc",
    }
    state_registry.save_booking("BF-2026-00001", fields, flags,
                                customer_email="callou@example.com")
    result = state_registry.get_booking("BF-2026-00001")

    assert result is not None, "FAIL: booking should exist"
    assert result["booking_ref"] == "BF-2026-00001", f"FAIL: ref={result['booking_ref']}"
    assert result["trip_key"] == "klein_curacao", f"FAIL: trip_key={result['trip_key']}"
    assert result["customer_name"] == "Callou", f"FAIL: name={result['customer_name']}"
    assert result["customer_email"] == "callou@example.com", f"FAIL: email={result['customer_email']}"
    assert result["date"] == "2026-04-15", f"FAIL: date={result['date']}"
    assert result["departure_time"] == "08:30", f"FAIL: dep={result['departure_time']}"
    assert result["guests"] == 4, f"FAIL: guests={result['guests']}"
    assert result["special_requests"] == "window seat", f"FAIL: sr={result['special_requests']}"
    assert result["payment_link"] == "https://demo.pay/bluemarlin/pay123"
    assert result["event_link"] == "https://calendar.google.com/event/abc"
    assert result["status"] == "confirmed", f"FAIL: status={result['status']}"
    _cleanup_db()
    print("PASS: test_save_and_get_booking")


def test_get_booking_not_found():
    """Non-existent ref returns None."""
    _cleanup_db()
    result = state_registry.get_booking("BF-9999-99999")
    assert result is None, f"FAIL: expected None, got {result}"
    _cleanup_db()
    print("PASS: test_get_booking_not_found")


def test_save_booking_upsert():
    """Saving with same ref overwrites — upsert behavior."""
    _cleanup_db()
    fields1 = {"trip_key": "klein_curacao", "customer_name": "Alice", "guests": 2}
    flags1 = {}
    state_registry.save_booking("BF-2026-00002", fields1, flags1,
                                customer_email="alice@example.com")

    fields2 = {"trip_key": "sunset_cruise", "customer_name": "Alice Updated", "guests": 3}
    flags2 = {}
    state_registry.save_booking("BF-2026-00002", fields2, flags2,
                                customer_email="alice@example.com")

    result = state_registry.get_booking("BF-2026-00002")
    assert result["trip_key"] == "sunset_cruise", f"FAIL: trip_key not updated"
    assert result["customer_name"] == "Alice Updated", f"FAIL: name not updated"
    assert result["guests"] == 3, f"FAIL: guests not updated"
    _cleanup_db()
    print("PASS: test_save_booking_upsert")


def test_detect_booking_ref_found():
    """Detects BF-YYYY-XXXXX pattern in message body."""
    body = "Hi, my booking reference is BF-2026-12345, can I change the date?"
    ref = email_poller._detect_booking_ref(body)
    assert ref == "BF-2026-12345", f"FAIL: expected BF-2026-12345, got {ref}"
    print("PASS: test_detect_booking_ref_found")


def test_detect_booking_ref_not_found():
    """No pattern in body returns None."""
    body = "Hi, I want to book a trip to Klein Curaçao!"
    ref = email_poller._detect_booking_ref(body)
    assert ref is None, f"FAIL: expected None, got {ref}"
    print("PASS: test_detect_booking_ref_not_found")


def test_detect_booking_ref_multiple():
    """Multiple refs in body — returns first one."""
    body = "I have BF-2026-11111 and also BF-2026-22222"
    ref = email_poller._detect_booking_ref(body)
    assert ref == "BF-2026-11111", f"FAIL: expected first ref, got {ref}"
    print("PASS: test_detect_booking_ref_multiple")


def test_returning_customer_field_population():
    """When a booking is found, fields are populated on empty thread."""
    _cleanup_db()
    fields = {
        "trip_key": "snorkeling_3in1",
        "customer_name": "Calvin",
        "date": "2026-05-01",
        "departure_time": "09:00",
        "guests": 6,
    }
    flags = {}
    state_registry.save_booking("BF-2026-00003", fields, flags,
                                customer_email="calvin@example.com")

    # Simulate empty thread
    th = {"fields": {}, "flags": {}}
    body = "Hi, my ref is BF-2026-00003, can I change the date?"
    ref = email_poller._detect_booking_ref(body)
    assert ref == "BF-2026-00003"

    past = state_registry.get_booking(ref)
    assert past is not None
    # Simulate the field population logic from the brief
    for k in ("trip_key", "date", "guests", "customer_name", "departure_time"):
        v = past.get(k)
        if v and not th["fields"].get(k):
            th["fields"][k] = v if not isinstance(v, int) else str(v)
    th["flags"]["returning_booking"] = ref

    assert th["fields"]["trip_key"] == "snorkeling_3in1"
    assert th["fields"]["customer_name"] == "Calvin"
    assert th["fields"]["date"] == "2026-05-01"
    assert th["fields"]["guests"] == "6"  # converted to string
    assert th["flags"]["returning_booking"] == "BF-2026-00003"
    _cleanup_db()
    print("PASS: test_returning_customer_field_population")


def test_returning_customer_no_overwrite():
    """Returning customer lookup does NOT overwrite existing thread fields."""
    _cleanup_db()
    fields = {
        "trip_key": "klein_curacao",
        "customer_name": "Calvin",
        "date": "2026-05-01",
        "guests": 6,
    }
    flags = {}
    state_registry.save_booking("BF-2026-00004", fields, flags,
                                customer_email="calvin@example.com")

    # Thread already has some fields from current conversation
    th = {"fields": {"customer_name": "Calvin Updated", "trip_key": "sunset_cruise"}, "flags": {}}
    past = state_registry.get_booking("BF-2026-00004")
    for k in ("trip_key", "date", "guests", "customer_name", "departure_time"):
        v = past.get(k)
        if v and not th["fields"].get(k):
            th["fields"][k] = v if not isinstance(v, int) else str(v)

    # Existing fields should NOT be overwritten
    assert th["fields"]["customer_name"] == "Calvin Updated", "FAIL: existing name was overwritten"
    assert th["fields"]["trip_key"] == "sunset_cruise", "FAIL: existing trip_key was overwritten"
    # But missing fields should be populated
    assert th["fields"]["date"] == "2026-05-01", "FAIL: date not populated"
    assert th["fields"]["guests"] == "6", "FAIL: guests not populated"
    _cleanup_db()
    print("PASS: test_returning_customer_no_overwrite")


def test_prompt_contains_booking_ref_instruction():
    """Marina's prompt includes booking ref instruction text."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "test body",
        {"trip_key": "klein_curacao"}, {"booking_ref": "BF-2026-99999"},
    )
    assert "BOOKING REFERENCE:" in prompt, "FAIL: prompt missing BOOKING REFERENCE section"
    assert "booking_ref" in prompt.lower() or "BF-" in prompt, "FAIL: prompt doesn't mention booking ref"
    print("PASS: test_prompt_contains_booking_ref_instruction")


def test_prompt_contains_returning_customer_section():
    """When returning_booking is in flags, prompt includes RETURNING CUSTOMER section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "my ref is BF-2026-00001",
        {"trip_key": "klein_curacao", "customer_name": "Calvin"},
        {"returning_booking": "BF-2026-00001"},
    )
    assert "RETURNING CUSTOMER:" in prompt, "FAIL: prompt missing RETURNING CUSTOMER section"
    assert "BF-2026-00001" in prompt, "FAIL: prompt doesn't include the booking ref"
    print("PASS: test_prompt_contains_returning_customer_section")


def test_prompt_no_returning_section_without_flag():
    """Without returning_booking flag, no RETURNING CUSTOMER section."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "test body",
        {}, {},
    )
    assert "RETURNING CUSTOMER:" not in prompt, "FAIL: RETURNING CUSTOMER should not appear without flag"
    print("PASS: test_prompt_no_returning_section_without_flag")


def test_booking_ref_instruction_unconditional():
    """BOOKING REFERENCE instruction appears even with empty flags (it's static text)."""
    prompt = marina_agent._build_prompt(
        "test@example.com", "booking", "test body",
        {}, {},
    )
    assert "BOOKING REFERENCE:" in prompt, "FAIL: BOOKING REFERENCE instruction should always appear"
    print("PASS: test_booking_ref_instruction_unconditional")


if __name__ == "__main__":
    test_save_and_get_booking()
    test_get_booking_not_found()
    test_save_booking_upsert()
    test_detect_booking_ref_found()
    test_detect_booking_ref_not_found()
    test_detect_booking_ref_multiple()
    test_returning_customer_field_population()
    test_returning_customer_no_overwrite()
    test_prompt_contains_booking_ref_instruction()
    test_prompt_contains_returning_customer_section()
    test_prompt_no_returning_section_without_flag()
    test_booking_ref_instruction_unconditional()
    print(f"\n12/12 tests passed.")
```

## Success Condition
All 12 tests pass. `save_booking` and `get_booking` round-trip correctly. `_detect_booking_ref` extracts refs from message bodies. Marina's prompt includes booking_ref instruction and returning customer context when appropriate.

## Rollback
Revert all three files to their pre-054 state:
```bash
git checkout HEAD~1 -- src/state_registry.py src/email_poller.py src/marina_agent.py
```
Delete test file and output file. The bookings table is additive — it won't affect existing functionality even if left behind.
