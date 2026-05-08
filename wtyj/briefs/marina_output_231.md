# OUTPUT 231 — Fix email-poller crash on ISO-string `last_activity`

## What was done
Patched the loop body in `_cleanup_stale_data` at `wtyj/agents/marina/email_poller.py` to accept both numeric epoch and ISO 8601 string `last_activity` values. ISO strings get parsed via `datetime.fromisoformat(...).timestamp()`; numeric values pass through; malformed strings fall through to "don't archive" per Brief 162's defensive principle. No other code changes — datetime import was already present.

## Tests
1078 passing / 0 failures (baseline 1073 + 5 new).

## Unexpected findings
test_066's "no sys.path.insert in tests" structural guard rejected the sys.path bootstrap line copied from older test files. Removed; conftest.py handles path setup for marina/ tests. Lesson re-confirmed from Brief 219 — marina/ tests don't need (and aren't allowed) the sys.path.insert pattern that social/ tests use.

## Deployment
Source committed and pushed; deploy still to fire. After deploy, the unboks email_poller.log should stop emitting `Error: '<' not supported between instances of 'str' and 'int'` — verify with `docker exec wtyj-unboks tail -f /app/logs/email_poller.log`.
