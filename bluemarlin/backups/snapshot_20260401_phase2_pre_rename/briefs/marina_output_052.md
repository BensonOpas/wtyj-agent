# OUTPUT 052 — Sheets: Manifests summary tab

## What was done

### Step 1 — Added `log_manifest_update()` to sheets_writer.py
New function after `log_hold_failed()`, before `log_escalation()`. Builds an 11-column row: Timestamp, trip_key, date, departure_time, total_guests, capacity, confirmed_count, pending_count, revenue (formatted as `$X,XXX USD`), calendar_link, booking_ref. Appends to the `Manifests` tab via `_append()`. Header updated to Brief 052.

### Step 2 — Added Manifests tab config to format_sheets.py
`MANIFESTS_HEADERS` (11 columns) and `MANIFESTS_WIDTHS` (11 values) defined after `ESCALATIONS_WIDTHS`. Manifests entry added to `TABS` list as the 5th tab. Header updated to Brief 052.

### Step 3 — Called `log_manifest_update()` from email_poller.py
In Step 5 success path, immediately after `sheets_writer.log_hold_created()`, added a block that:
1. Calls `state_registry.get_slot_passengers()` for the current slot
2. Computes confirmed/pending counts, total guests, total revenue (approximation: `total_guests * price_adult_usd`)
3. Gets capacity from `config_loader.get_trip()`
4. Calls `sheets_writer.log_manifest_update()` with all aggregated data

Header updated to Brief 052.

### Step 4 — File headers updated
All three files: sheets_writer.py, format_sheets.py, email_poller.py — headers say Brief 052.

## Test results

```
Running Brief 052 tests...
  T1: log_manifest_update exists PASS
  T2: log_manifest_update is callable PASS
  T3: log_manifest_update param is 'data' PASS
  T4: sheets_writer header says Brief 052 PASS
  T5: 'Manifests' tab name in log_manifest_update PASS
  T6: MANIFESTS_HEADERS defined PASS
  T7: MANIFESTS_WIDTHS defined PASS
  T8: MANIFESTS_HEADERS has 11 columns PASS
  T9: MANIFESTS_WIDTHS has 11 values PASS
  T10: 'Manifests' in TABS list PASS
  T11: Manifests tab headers match PASS
  T12: Manifests tab widths match PASS
  T13: format_sheets header says Brief 052 PASS
  T14: First header is 'Timestamp' PASS
  T15: Headers contain 'Revenue' PASS
  T16: Headers contain 'Calendar Link' PASS
  T17: log_manifest_update in email_poller PASS
  T18: get_slot_passengers in email_poller PASS
  T19: log_manifest_update after log_hold_created PASS
  T20: email_poller header says Brief 052 PASS
  T21: 'capacity' in manifest log call PASS
  T22: 'total_revenue' in manifest log call PASS
  T23: _append called with 'Manifests' tab PASS
  T24: row has 11 columns PASS
  T25: revenue formatted as '$1,440 USD' PASS
  T26: booking_ref 'BF-2026-50123' in last column PASS
  T27: trip_key 'klein_curacao' in column 1 PASS
  T28: capacity '30' in column 5 PASS

28/28 tests passed.
All tests passed.
```

## Unexpected
Nothing unexpected. Brief reviewer initially flagged 3 issues (revenue approximation undocumented, no behavioral tests, manual tab creation undocumented) — all fixed before execution.

## Known limitations
- Revenue is an approximation: `total_guests * price_adult_usd`. Bookings with children will show slightly inflated revenue. Accurate per-booking pricing would require a `price_paid` column in `trip_bookings`.
- The "Manifests" tab must be created manually in Google Sheets before the first booking is logged (same pattern as Escalations tab).
