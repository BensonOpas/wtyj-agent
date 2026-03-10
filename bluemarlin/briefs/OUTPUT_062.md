# OUTPUT 062 — Live Test Harness: Automated E2E Testing

## What Was Done

Created `tests/live_test_harness.py` — a standalone E2E test script that:
1. Injects test emails into Marina's inbox via IMAP APPEND
2. Waits for the poller to process them (polls thread state file)
3. Verifies Marina's responses with pattern-based assertions
4. Reports PASS/FAIL per check

### Key design features
- **Zero src/ imports** — copies `oauth_token`, `imap_connect`, `normalize_subject` directly into the script to avoid transitive import chain
- **IMAP APPEND injection** — places crafted RFC822 emails as UNSEEN, poller picks them up naturally
- **Dedup-safe** — each run embeds unique `[LIVETEST-{uuid}]` in body
- **Far-future dates** (2027+) to avoid conflicts with real bookings
- **Cleanup opt-in only** — requires `--cleanup` flag AND poller stopped

### 6 test scenarios
1. `simple_inquiry` — trip inquiry, no escalation
2. `booking_summary` — full booking with tone assertions (no bullets, no old phrases, correct price)
3. `day_of_week` — snorkeling on wrong day, expects Friday correction
4. `tone_quality` — checks for AI-isms (em dashes, stock phrases)
5. `unknown_ref` — fake booking ref, expects "not found" acknowledgment
6. `escalation` — complaint, expects `requires_human` flag

### CLI
```bash
python3 tests/live_test_harness.py --dry-run        # Preview emails
python3 tests/live_test_harness.py                   # Full run
python3 tests/live_test_harness.py --scenario X      # Single scenario
python3 tests/live_test_harness.py --cleanup         # Clean up (poller must be stopped)
```

## Test Results

### T1: Dry run — PASS
```
6 scenario(s) previewed.
```
All 6 scenarios print From/Subject/Body, no IMAP connection, exit 0.

### T2 + T3: Full run / single scenario
Requires VPS deployment. Not yet tested.

## Files Created
| File | Purpose |
|------|---------|
| `tests/live_test_harness.py` | Standalone E2E test harness |
