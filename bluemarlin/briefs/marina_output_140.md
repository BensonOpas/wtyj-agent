# OUTPUT 140 — Large Group Pre-Check

## What was done

Modified `agents/social/social_agent.py` — added a capacity pre-check at the top of Step 7. When guests exceed the service's capacity, the system escalates to the operator instead of saying "fully booked." Marina's original conversational reply is sent to the customer (not the booking summary or "fully booked" message).

## Files changed

- `agents/social/social_agent.py` — Step 7 restructured: capacity pre-check → escalation path, else → existing availability check
- `tests/social/test_140_large_group_pre_check.py` — 5 new tests

## Test results

```
5 new tests: all pass
629 total (social + marina): all pass
6 pre-existing failures: test_047 + test_048 reschedule tests (unchanged)
```

## Unexpected issues

None. Clean execution. The key insight was using `reply` (Marina's original response, line 344) instead of `reply_text` (which post-validate may have overwritten with a booking summary) or `reply_hold_failed` (which isn't available on the first booking request).
