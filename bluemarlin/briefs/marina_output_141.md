# OUTPUT 141 — Booking UX + Email Config

## What was done

Three changes:

1. **Booking summary wording** — "Want me to go ahead and book this?" → "Want me to check availability and hold a spot for you?" Sets correct expectation that we're checking, not finalizing.

2. **Booking pacing prompt** — Added BOOKING PACING section to Marina's prompt. When a customer first mentions booking, Marina now gives a brief service summary (what's included, schedule, duration) before collecting fields. Keeps it to 1-2 sentences, not a sales pitch.

3. **Email config** — Added `business.booking_email` to client.json (set to `hello@wetakeyourjob.com` for demo). DM agent uses this for booking redirect instead of `business.email`. Falls back to `business.email` if not set.

## Files changed

- `agents/social/social_agent.py` — booking summary string + action context wording
- `agents/marina/marina_agent.py` — BOOKING PACING section added to prompt
- `agents/social/dm_agent.py` — uses `booking_email` with fallback
- `config/client.json` — added `booking_email` field
- `tests/social/test_141_booking_ux.py` — 4 new tests
- `tests/social/test_070_whatsapp_booking.py` — updated 2 assertions for new wording + added soft hold mock

## Test results

```
4 new tests: all pass
633 total (social + marina): all pass
6 pre-existing failures: test_047 + test_048 reschedule tests (unchanged)
```

## Unexpected issues

test_070 had 2 assertions checking for "book this?" in the booking summary — updated to "check availability". Also the orchestrator test needed a `create_soft_hold` mock (same pattern as test_138 — the real DB insert races on capacity).
