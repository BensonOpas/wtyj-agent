# OUTPUT 139 — Manifest API Error Handling

## What was done

Modified `agents/social/social_agent.py` and `agents/marina/email_poller.py` — manifest failure handling in Step 8 / Step 5 now distinguishes API errors from business logic errors.

When manifest creation fails with an API error (404, 500, 403, 401, or "Calendar ID not configured"):
- Hold is cancelled (same as before)
- `booking_confirmed` reset to False, `awaiting_booking_confirmation` set to True — customer can retry on next message
- Retry count tracked in `manifest_retry_count` flag
- After 2 consecutive API failures, a [SYSTEM] escalation is created so the operator knows the calendar is broken
- Retry count cleared on successful manifest creation

For non-API errors (business logic like missing service_key): behavior unchanged — no retry, no state reset.

Also fixed:
- Fallback wording in marina_agent.py and dm_agent.py: "Hey, give me a moment" → "Sorry, could you send that again? I missed it." (Issue 3 from plan — prompts customer to retry instead of promising to come back)
- CLAUDE.md known open issues updated to reflect new fallback wording
- test_051 source-reading test window expanded (code grew due to new error handling)

## Files changed

- `agents/social/social_agent.py` — manifest failure block rewritten with API error detection + retry state + circuit breaker
- `agents/marina/email_poller.py` — same pattern applied
- `agents/marina/marina_agent.py` — fallback wording change
- `agents/social/dm_agent.py` — fallback wording change
- `CLAUDE.md` — known open issues updated
- `tests/social/test_139_error_handling.py` — 6 new tests
- `tests/social/test_069_whatsapp_agent.py` — updated fallback assertion
- `tests/social/test_131b_dm_qa_agent.py` — updated fallback assertion
- `tests/marina/test_051_manifest_integration.py` — expanded source window

## Test results

```
6 new tests: all pass
624 total tests (social + marina): all pass
6 pre-existing failures: test_047 + test_048 reschedule tests (unchanged)
```

## Unexpected issues

1. test_051 reads email_poller source code and checks for `hold_id` pop within 1200 chars of the log line. The new error handling code pushed it further away. Fixed by expanding the window to 3000 chars.
2. The four hardcoded "fully booked" strings in Step 7 are intentionally NOT changed — `reply_hold_failed` is not available at that point in the flow (Marina didn't get the confirmation action context). Documented as accepted Rule 3 exception.
