# OUTPUT 189 — Email poller split: extract adapter layer

## What was done

Created `wtyj/agents/marina/email_adapter.py` (~170 lines) containing 12 functions and 11 constants extracted from `email_poller.py`: IMAP connection (`imap_connect`, `oauth_token`, `get_refresh_token`), SMTP sending (`smtp_send`), email parsing (`extract_text`, `strip_quotes`, `_decode_subj`, `normalize_subject`, `_is_new_email`, `resolve_thread_key`), and utilities (`log`, `sha`). All moved functions are re-exported from `email_poller.py` via a single import block, so the 15+ existing test files that import from `email_poller` continue to work unchanged. Updated 2 tests in `test_065_production_hardening.py` to also patch `email_adapter.REFRESH_TOKEN_PATH` alongside `email_poller.REFRESH_TOKEN_PATH` (same mock-target migration pattern from Brief 187). Removed `sys.path.insert` from the new test file per `test_066` project structure rules.

## Tests

889 passing / 0 failures (886 baseline + 3 new).

## Unexpected findings

Two existing tests (`test_065::test_oauth_saves_refresh_token` and `test_065::test_oauth_raises_on_missing_access_token`) broke because they set `email_poller.REFRESH_TOKEN_PATH = temp_path` — but `get_refresh_token()` now reads from `email_adapter.REFRESH_TOKEN_PATH`, which wasn't patched. Same root cause as Brief 187: Python's `from X import Y` copies the reference to Y; reassigning Y in the importing module's namespace doesn't affect the source module's namespace. Fixed by also patching `email_adapter.REFRESH_TOKEN_PATH`.

## Deployment

Pending — deploy after commit + push.
