# BRIEF 028 — Booking Reference + Sheets Data Rework

**Brief number:** 028
**Status:** Ready to execute
**Files modified:** bluemarlin/src/sheets_writer.py, bluemarlin/src/email_poller.py
**Files created:** None
**Depends on:** Brief 027 (email_poller.py), Brief 013 (sheets_writer.py)
**Blocks:** Escalation path, cancellation identity verification, post-trip complaints

---

## CONTEXT

Two problems being solved together because they are tightly coupled:

1. No permanent booking record exists. The only record of a booking is
   the Google Calendar hold and an ephemeral thread state file. If a
   customer emails weeks after their trip, or requests a cancellation,
   there is nothing to cross-reference.

2. sheets_writer.py is incomplete. Bookings tab is missing booking
   reference, trip_key, departure_time, and total_price. human_required
   events only log to All Events — no dedicated Escalations tab exists.
   Complaints tab exists but is never called by email_poller.py after
   the Brief 024 rework.

---

## SOURCE MATERIAL

Files confirmed seen this session:

sheets_writer.py — 157 lines, Brief 013. SPREADSHEET_ID:
1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE
Four functions: log_hold_created, log_hold_failed, log_complaint,
log_event. Three tabs: Bookings, Complaints, All Events.

email_poller.py main loop — lines 299–440, Brief 027.
hold creation block confirmed: sheets_writer.log_hold_created called
with: email, subject, customer_name, experience, date, guests, phone,
special_requests, html_link, payment_link.
human_required block confirmed: only calls sheets_writer.log_event
with event_type "human_required".

config_loader.py — 94 lines, Brief 022. get_trip(key) confirmed
available.

---

## PART 1 — email_poller.py

### Change 1 — Generate booking reference at hold creation

In the hold success block (after res.get("ok") is True), before
calling sheets_writer.log_hold_created, generate a booking reference:
```python
booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
th["flags"]["booking_ref"] = booking_ref
```

Note: time is already imported in email_poller.py. No additional imports needed.

booking_ref format: BF-2026-XXXXX where XXXXX is last 5 digits of
Unix timestamp. Unique enough for BlueFinn's booking volume. Not
sequential — intentional, prevents enumeration.

### Change 2 — Pass booking_ref and additional fields to
sheets_writer.log_hold_created

Update the sheets_writer.log_hold_created call to include:
```python
sheets_writer.log_hold_created({
    "booking_ref": booking_ref,
    "email": from_email,
    "subject": subj,
    "customer_name": fields_now.get("customer_name"),
    "experience": fields_now.get("experience"),
    "trip_key": fields_now.get("trip_key"),
    "date": fields_now.get("date"),
    "guests": fields_now.get("guests"),
    "departure_time": fields_now.get("departure_time"),
    "phone": fields_now.get("phone"),
    "special_requests": fields_now.get("special_requests"),
    "total_price": int(fields_now.get("guests") or 0) * price_usd,
    "html_link": th["flags"].get("event_link"),
    "payment_link": th["flags"].get("payment_link"),
    "payment_status": pay.get("status"),
})
```

price_usd is already calculated in this block — use the existing value.

### Change 3 — Replace human_required Sheets call with
log_escalation

Current:
```python
sheets_writer.log_event("human_required", {"email": from_email,
    "subject": subj})
```

Replace with:
```python
sheets_writer.log_escalation({
    "email": from_email,
    "subject": subj,
    "customer_name": th["fields"].get("customer_name", ""),
    "intent": (result.get("intents") or ["unknown"])[0],
    "fields_collected": th["fields"],
    "internal_note": result.get("internal_note", ""),
})
```

### Change 4 — Add import time

Add `import time` to email_poller.py imports if not already present.

Update file header: LAST MODIFIED Brief 027 → Brief 028

No other changes to email_poller.py.

---

## PART 2 — sheets_writer.py

### Replace log_hold_created

New column order for Bookings tab (14 columns):
1. Timestamp
2. Booking Ref
3. Customer Name
4. Email
5. Trip
6. Trip Key
7. Date
8. Guests
9. Departure Time
10. Phone
11. Special Requests
12. Total (USD)
13. Payment Status
14. Calendar Link
15. Payment Link
```python
def log_hold_created(data: dict):
    try:
        service = _get_service()
        if service is None:
            return None
        row_bookings = [
            _now(),
            data.get('booking_ref', ''),
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('experience', ''),
            data.get('trip_key', ''),
            data.get('date', ''),
            str(data.get('guests', '')),
            data.get('departure_time', ''),
            data.get('phone', ''),
            data.get('special_requests', ''),
            str(data.get('total_price', '')),
            data.get('payment_status', ''),
            data.get('html_link', ''),
            data.get('payment_link', ''),
        ]
        row_all = [
            _now(),
            'hold_created',
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        _append(service, 'Bookings', row_bookings)
        return _append(service, 'All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_hold_created error: {e}")
        return None
```

### Replace log_hold_failed

Update to consistent 15-column structure matching Bookings tab,
with FAILED status and error column:
```python
def log_hold_failed(data: dict):
    try:
        service = _get_service()
        if service is None:
            return None
        row_bookings = [
            _now(),
            '',
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('experience', ''),
            data.get('trip_key', ''),
            data.get('date', ''),
            str(data.get('guests', '')),
            '',
            '',
            '',
            '',
            'FAILED',
            '',
            data.get('error', ''),
        ]
        row_all = [
            _now(),
            'hold_failed',
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        _append(service, 'Bookings', row_bookings)
        return _append(service, 'All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_hold_failed error: {e}")
        return None
```

### Add log_escalation (new function)

Writes to Escalations tab (new tab). 6 columns:
1. Timestamp
2. Customer Name
3. Email
4. Intent
5. Fields Collected (JSON)
6. Internal Note
```python
def log_escalation(data: dict):
    try:
        service = _get_service()
        if service is None:
            return None
        row_escalations = [
            _now(),
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('intent', ''),
            json.dumps(data.get('fields_collected', {})),
            data.get('internal_note', ''),
        ]
        row_all = [
            _now(),
            'escalation',
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        _append(service, 'Escalations', row_escalations)
        return _append(service, 'All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_escalation error: {e}")
        return None
```

### Remove log_complaint

log_complaint is not called anywhere in email_poller.py after Brief
024. Remove the function entirely.

Update file header: LAST MODIFIED Brief 013 → Brief 028

---

## IMPORTANT NOTE ON GOOGLE SHEETS TABS

The Google Sheet must have these tabs created manually before the
brief is executed, or the _append calls will fail silently:
- Bookings (already exists)
- All Events (already exists)
- Escalations (NEW — must be created manually)

Claude Code cannot create Sheets tabs — this requires manual action
in the Google Sheets UI. The test suite will detect if the tab is
missing. Create the Escalations tab in the Sheet before running
tests.

Sheet URL (for reference, not for Claude Code to access):
https://docs.google.com/spreadsheets/d/1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE

---

## TESTS

**Test 1 — sheets_writer imports cleanly**
Import sheets_writer from bluemarlin/src. Assert no ImportError.

**Test 2 — email_poller imports cleanly**
Import email_poller from bluemarlin/src. Assert no ImportError.

**Test 3 — log_complaint is gone**
Read sheets_writer.py as text. Assert "log_complaint" not in source.

**Test 4 — log_escalation is present**
Read sheets_writer.py as text. Assert "log_escalation" in source.
Assert "Escalations" in source.

**Test 5 — booking_ref is generated and stored in flags**
Mock create_calendar_hold to return ok=True with a fake eventId.
Mock payment_stub.generate_payment_link. Mock sheets_writer.
Trigger the booking flow with all required fields present.
Assert th["flags"].get("booking_ref") starts with "BF-".

**Test 6 — log_hold_created receives booking_ref**
Same mock setup as Test 5. Capture the dict passed to
sheets_writer.log_hold_created. Assert "booking_ref" in the dict
and it starts with "BF-".

**Test 7 — log_hold_created receives total_price**
Same mock setup. Assert dict passed to log_hold_created contains
"total_price" as a numeric value greater than 0.

**Test 8 — log_escalation called on requires_human**
Mock sheets_writer.log_escalation. Trigger a message that returns
requires_human=True from marina_agent. Assert log_escalation was
called with a dict containing "email" and "intent".

**Test 9 — log_escalation writes correct row structure**
Call log_escalation directly with test data. Mock _append and capture
the row. Assert row has 6 elements. Assert row[3] is the intent value.

**Test 10 — Bookings row has 15 columns**
Call log_hold_created with test data. Mock _append and capture the
row. Assert len(row) == 15. Assert row[1] starts with "BF-".

---

## SUCCESS CONDITION

All 10 tests pass. Every confirmed booking generates a booking
reference stored in thread flags. Escalations write to the
Escalations tab with full context. Bookings tab has 15 structured
columns. log_complaint is removed. No data is lost compared to
current behaviour.

---

## ROLLBACK

sheets_writer.py changes are additive except for log_complaint
removal. email_poller.py changes are additive (booking_ref
generation, extra fields to existing call, one function call
replacement). If tests fail, restore both files from their
Brief 027 state. Live service is not restarted as part of this
brief — VPS pull and restart happen separately.
