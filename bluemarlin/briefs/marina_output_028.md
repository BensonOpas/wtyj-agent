# OUTPUT_028 — Booking Reference + Sheets Data Rework

## Files modified
- `bluemarlin/src/sheets_writer.py`
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_028.md` (this file)

---

## Changes made

### sheets_writer.py

**log_hold_created** — replaced with 15-column Bookings row:
Timestamp, Booking Ref, Customer Name, Email, Trip, Trip Key, Date, Guests,
Departure Time, Phone, Special Requests, Total (USD), Payment Status,
Calendar Link, Payment Link.

**log_hold_failed** — replaced with matching 15-column structure:
Same columns as log_hold_created; booking_ref blank, payment_status = 'FAILED',
payment_link column used for error message.

**log_escalation** — new function writing to Escalations tab (6 columns):
Timestamp, Customer Name, Email, Intent, Fields Collected (JSON), Internal Note.
Also writes to All Events tab with event_type 'escalation'.

**log_complaint** — removed entirely (not called anywhere post-Brief 024).

File header: LAST MODIFIED Brief 013 → Brief 028

### email_poller.py

**booking_ref generation** — added in hold success block after res.get("ok") is True,
before sheets_writer.log_hold_created call:
```python
booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
th["flags"]["booking_ref"] = booking_ref
```

**sheets_writer.log_hold_created call** — updated to pass dict with 15 fields:
booking_ref, email, subject, customer_name, experience, trip_key, date, guests,
departure_time, phone, special_requests, total_price (guests * price_usd),
html_link, payment_link, payment_status.

**human_required Sheets call** — replaced:
```python
# Before
sheets_writer.log_event("human_required", {"email": from_email, "subject": subj})

# After
sheets_writer.log_escalation({
    "email": from_email,
    "subject": subj,
    "customer_name": th["fields"].get("customer_name", ""),
    "intent": (result.get("intents") or ["unknown"])[0],
    "fields_collected": th["fields"],
    "internal_note": result.get("internal_note", ""),
})
```

`import time` was already present (line 19). No additional imports needed.

File header: LAST MODIFIED Brief 027 → Brief 028

---

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | sheets_writer imports cleanly | PASS |
| 2 | email_poller imports cleanly | PASS |
| 3 | log_complaint not in source | PASS |
| 4 | log_escalation present + Escalations in source | PASS |
| 5 | booking_ref generated and stored in flags (starts with BF-) | PASS (BF-2026-47677) |
| 6 | log_hold_created receives booking_ref starting with BF- | PASS |
| 7 | log_hold_created receives total_price > 0 | PASS (240) |
| 8 | log_escalation called on requires_human with email + intent | PASS |
| 9 | log_escalation row has 6 elements, row[3] is intent | PASS |
| 10 | Bookings row has 15 columns, row[1] starts with BF- | PASS |

---

## Notes

- The Escalations tab must be created manually in the Google Sheet before live use.
  The _append call will fail silently if the tab does not exist.
- SPREADSHEET_ID: 1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE
- total_price = int(guests or 0) * price_usd (price_usd from config_loader.get_trip())
- booking_ref format: BF-YYYY-XXXXX (last 5 digits of Unix timestamp, zero-padded)
