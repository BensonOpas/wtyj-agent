# OUTPUT_012 — email_poller.py — expand structured logging

## Files modified
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_012.md` (this file)

## Changes made

### Change 7 — file header
- `LAST MODIFIED` updated from `Brief 009` to `Brief 012`

### Change 1 — off_topic_received
Added immediately after `log(f"Out-of-scope -> sent SAFE reply to: {from_email}")`:
```python
bm_logger.log(
    "off_topic_received",
    email=from_email,
    subject=subj,
    body_snippet=body[:200]
)
```

### Change 2 — complaint_received
Added immediately after `log(f"Complaint -> sent empathetic reply to: {from_email}")`:
```python
bm_logger.log(
    "complaint_received",
    email=from_email,
    subject=subj,
    body_snippet=body[:200]
)
```

### Change 3 — missing_fields_requested
Added immediately after `log(f"Booking intent -> requested missing fields (all at once): {missing}")`:
```python
bm_logger.log(
    "missing_fields_requested",
    email=from_email,
    subject=subj,
    missing=missing,
    fields_so_far=list(merged.keys())
)
```

### Change 4 — booking_attempted
Added immediately before `res = create_calendar_hold(fields_now)`:
```python
bm_logger.log(
    "booking_attempted",
    email=from_email,
    subject=subj,
    experience=fields_now.get("experience"),
    date=fields_now.get("date"),
    guests=fields_now.get("guests"),
    customer_name=fields_now.get("customer_name"),
    phone=fields_now.get("phone"),
    special_requests=fields_now.get("special_requests")
)
```

### Change 5 — hold_created (expanded)
Replaced the existing 4-field `bm_logger.log("hold_created", ...)` call with a
full 12-field call including `html_link`, `payment_link`, `experience`, `date`,
`guests`, `customer_name`, `phone`, and `special_requests`.

### Change 6 — hold_failed
Added immediately after `log(f"Hold create FAILED for {from_email}: {res.get('error')}")`:
```python
bm_logger.log(
    "hold_failed",
    email=from_email,
    subject=subj,
    error=res.get("error"),
    experience=fields_now.get("experience"),
    date=fields_now.get("date"),
    guests=fields_now.get("guests")
)
```

## Dependencies added
None.

## Assumptions
- `bm_logger.log(event, **fields)` accepts arbitrary keyword arguments and writes
  JSONL — confirmed by reading bm_logger.py; no signature changes needed
- `body[:200]` is the agreed maximum snippet length to avoid storing sensitive PII
- `body` in scope at all dispatch points is the stripped quote-removed body, which
  is the correct source for body_snippet
- `fields_now` is already in scope at the `booking_attempted` insertion point
  (assigned two lines above as `fields_now = th.get("fields", {}) or {}`)
- `merged` is in scope at the `missing_fields_requested` insertion point
- The `# ---- BM-014 ----` comment block was preserved; only the call body changed

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — bm_logger calls present in source for all 6 events
PASS — off_topic_received found
PASS — complaint_received found
PASS — missing_fields_requested found
PASS — booking_attempted found
PASS — hold_created found
PASS — hold_failed found
ALL EVENTS PRESENT

# Test 3 — bm_logger.log call count increased
bm_logger.log() call count: 6
PASS

# Test 4 — body_snippet uses 200 char slice not full body
PASS — body_snippet correctly sliced

# Test 5 — special_requests present in hold_created log call
PASS — special_requests and hold_created both present in file
```

All 5 tests pass.

## Flags and uncertainties
- `missing` is a Python list — bm_logger serialises it to JSON as an array, which
  is the correct format for the Brief 013 Google Sheets dashboard to consume
- `fields_so_far` is also a list of key names — same serialisation applies
- `phone` is logged in `booking_attempted`; this is intentional per the brief spec
  but callers of the log file should be aware of PII in the JSONL output

## SYSTEM_STATE update block
```
Brief 012 — email_poller.py — structured logging expanded from 1 to 6 events:
  off_topic_received, complaint_received, missing_fields_requested,
  booking_attempted, hold_created (expanded), hold_failed.
  All events written to bluemarlin/logs/bluemarlin.log in JSONL format.
  Callers: no impact on runtime behaviour; logging only.
```

## Dependency impact
```
Files that import email_poller: none (top-level runner)
What callers should expect differently: N/A

Files that import bm_logger: email_poller.py
What callers should expect differently: bm_logger.log() call count increased from
  1 to 6. No API changes. Log file will now contain entries for all 6 event types.
```

## Regression check block
```
# BRIEF_012 — email_poller.py — all 6 bm_logger event names present in source
# Tests: email_poller.py (source inspection)
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    c = f.read()
for e in ['off_topic_received','complaint_received','missing_fields_requested',
          'booking_attempted','hold_created','hold_failed']:
    assert e in c, f'MISSING: {e}'
assert c.count('bm_logger.log(') >= 6
assert 'body[:200]' in c
assert 'special_requests' in c
print('Brief 012 regression OK')
"
```
