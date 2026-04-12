# BRIEF 189 — Email poller split: extract adapter layer from 1437-line monolith
**Status:** Draft | **Files:** new `wtyj/agents/marina/email_adapter.py`, `wtyj/agents/marina/email_poller.py` (removals + re-exports) | **Depends on:** — | **Blocks:** —

## Context

`email_poller.py` is 1437 lines containing EVERYTHING: IMAP connection, OAuth token refresh, SMTP sending, email parsing, subject normalization, thread resolution, booking flow orchestration, Marina calls, calendar integration, sheets logging, notification dispatch, error handling, and heartbeat — all in one file, with a 940-line `main()` function.

The integration modules already live in their own files: `gws_calendar.py`, `sheets_writer.py`, `payment_stub.py`, `state_registry.py`. What's NOT separated is the email **adapter layer** — the I/O functions that talk to the email platform (IMAP connect, OAuth, SMTP send, email body parsing, subject decoding, thread key resolution). These are currently defined at the top of `email_poller.py` (lines 106-310) alongside orchestration-level code, with no separation between "talk to the platform" and "run the business logic."

This brief extracts 12 standalone I/O/parsing functions and their associated constants into a new `email_adapter.py` file. The orchestrator (`main()` + booking/validation helpers) stays in `email_poller.py`. All extracted functions are **re-exported from `email_poller.py`** so that the 15+ existing test import sites (`from agents.marina.email_poller import ...`) continue to work with zero changes.

## Why This Approach

**Extract and re-export, not extract and update all callers.** 15+ test files import from `email_poller`. Updating them all is mechanical but risky (Brief 187 taught us that changing mock targets cascades). Re-exporting keeps backward compat at zero cost. Future briefs can migrate importers to the new module path one at a time if desired — no rush.

**Adapter layer only, not main() restructuring.** The 940-line `main()` function contains deeply interleaved orchestration + integration calls (13 `smtp_send` calls, 5 `gws_calendar` calls, 4 `create_pending_notification` calls, all inside nested conditionals). Restructuring `main()` into an orchestrator + integration split requires understanding and refactoring ~940 lines of control flow — that's a separate brief. This brief moves the **self-contained helper functions** that exist OUTSIDE `main()` and have clean boundaries.

**12 functions, ~170 lines.** Each is a self-contained function with no circular dependencies:

| Function | Lines | Concern |
|---|---|---|
| `log(msg)` | 115-116 | Print wrapper (used by adapter functions internally) |
| `_decode_subj(raw)` | 106-113 | Decode email subject headers |
| `sha(s)` | 132-133 | SHA256 hash for thread key generation |
| `normalize_subject(subj)` | 135-143 | Strip Re:/Fwd: prefixes |
| `get_refresh_token()` | 194-195 | Read OAuth refresh token from file |
| `oauth_token(scope)` | 197-220 | Request OAuth access token from Microsoft |
| `imap_connect()` | 222-227 | Establish IMAP4_SSL connection with OAuth |
| `smtp_send(...)` | 229-254 | Send email reply via SMTP with OAuth |
| `extract_text(msg)` | 256-273 | Extract plain text from email message |
| `strip_quotes(text)` | 275-283 | Remove quoted reply text |
| `resolve_thread_key(...)` | 285-303 | Determine thread key from message headers |
| `_is_new_email(msg)` | 306-310 | Check if email is new (no reply headers) |

**Constants that move with them:** `CLIENT_ID`, `TENANT_ID`, `EMAIL_ADDR`, `_MODULE_DIR`, `_CONFIG_DIR`, `REFRESH_TOKEN_PATH`, `SESSION_ID`, `IMAP_HOST`, `IMAP_PORT`, `SMTP_HOST`, `SMTP_PORT` (lines 27-39).

### Rejected alternatives

1. **Full 3-way split (adapter + orchestrator + integrations) in one brief.** Rejected: the "integrations" (Calendar, Sheets, notifications) are already in separate modules — they're just CALLED from inside `main()`. Extracting those call sites requires restructuring `main()`'s 940-line control flow. Too big and too risky for one brief. The adapter extraction alone delivers the structural improvement and completes the s34 subtask's spirit.

2. **Move functions without re-exporting from email_poller.py.** Rejected: would break 15+ test files that import from `email_poller`. Brief 187 proved that mock-target changes cascade badly. Re-exporting avoids that entirely.

3. **Create an `EmailChannel` class following the `Channel` ABC from Brief 186.** Rejected: email doesn't come through webhooks — it's polled via IMAP inside a while-loop. The `Channel.from_zernio()` interface doesn't apply. A class wrapper around the email adapter functions is possible but adds abstraction without current value. YAGNI until there's a second polling channel.

## Instructions

### Step 1 — Create `wtyj/agents/marina/email_adapter.py`

Create the new file with:
- File header comment
- Imports needed by the 12 functions (imaplib, smtplib, urllib, email.*, re, hashlib, os, base64, json)
- The 11 constants (CLIENT_ID through SMTP_PORT)
- The 12 functions in the same order they appear in email_poller.py

All functions and constants are copied verbatim — no behavioral changes, no renaming, no signature changes.

### Step 2 — Update `email_poller.py`: remove moved code, add re-exports

**Remove** the 12 function definitions and the 11 constants from email_poller.py. Keep everything else (imports of shared modules like `state_registry`, `config_loader`, `marina_agent`; orchestrator-level functions like `_cleanup_stale_data`, `_build_action_context`, `_post_validate`, `_maybe_reset_stale_thread`, etc.; `main()`; remaining constants like `POLL_INTERVAL`, `MAILBOX`, `_ERROR_ALERT_THRESHOLD`, etc.).

**Add** a re-export import block near the top (after the existing imports):

```python
# Brief 189: adapter layer extracted to email_adapter.py. Re-export for backward
# compat — existing tests and any other code that imports these from email_poller
# continue to work unchanged.
from agents.marina.email_adapter import (
    log, _decode_subj, sha, normalize_subject,
    get_refresh_token, oauth_token, imap_connect, smtp_send,
    extract_text, strip_quotes, resolve_thread_key, _is_new_email,
    # Constants (including _MODULE_DIR and _CONFIG_DIR — needed by staying
    # constants STATE_DIR, THREAD_STATE_PATH, ARCHIVE_PATH, HEARTBEAT_PATH)
    CLIENT_ID, TENANT_ID, EMAIL_ADDR, IMAP_HOST, IMAP_PORT,
    SMTP_HOST, SMTP_PORT, REFRESH_TOKEN_PATH, SESSION_ID,
    _MODULE_DIR, _CONFIG_DIR,
)
```

**Also remove** the now-unused stdlib imports that were ONLY needed by the moved functions. Specifically: if `imaplib`, `smtplib`, `base64`, `urllib.request`, `urllib.parse`, `email.header._decode_header`, `email.mime.text.MIMEText`, `email.mime.multipart.MIMEMultipart`, `email.utils.make_msgid` are not used elsewhere in email_poller.py (outside the moved functions), remove them from the import lines. Check each one — some (like `re`, `json`, `os`, `hashlib`) ARE used by remaining code and must stay.

**Verify:** `email_poller.py` should drop from ~1437 lines to ~1250 lines. All references to the moved functions within `main()` and the remaining helpers (`_maybe_reset_stale_thread` calls `_is_new_email` and `log`; `_cleanup_stale_data` calls `log`) continue to resolve via the re-export imports.

### Step 3 — Do NOT touch

- `main()` function (lines 495-1437) — stays in email_poller.py, zero restructuring
- `_cleanup_stale_data`, `load_json`, `save_json`, `_business_sender_emails` — stay in email_poller.py (orchestrator-level concerns)
- `_maybe_reset_stale_thread`, `_detect_booking_ref`, `_resolve_booking_ref`, `_maybe_reset_for_new_booking`, `_day_matches` — stay (thread/booking management)
- `_build_action_context`, `_post_validate` — stay (orchestrator helpers)
- Constants: `POLL_INTERVAL`, `MAILBOX`, `THREAD_STATE_PATH`, `STATE_DIR`, `MAX_REPLIES_PER_THREAD`, `REPLY_WINDOW_SECONDS`, `SENDER_RATE_LIMIT`, `SENDER_RATE_WINDOW`, `THREAD_RETENTION_DAYS`, `ARCHIVE_PATH`, `HEARTBEAT_PATH`, `_ERROR_ALERT_THRESHOLD`, `_ERROR_EXIT_THRESHOLD`, `_TOKEN_REFRESH_SECONDS`, `_BOOKING_INTENTS`, `_SYSTEM_EMAIL_PREFIXES`, `_FRESH_THREAD` — all stay
- No existing test files — zero test import changes
- Anything in `webhook_server.py`, `social_agent.py`, `channels/`, `senders/`, `dashboard/api.py`

## Tests

Create `wtyj/tests/marina/test_189_email_adapter.py` with 3 tests:

### Test 1 — `normalize_subject` works from `email_adapter` import

```python
from agents.marina.email_adapter import normalize_subject
assert normalize_subject("Re: Re: Fwd: Booking inquiry") == "Booking inquiry"
assert normalize_subject("") == ""
assert normalize_subject("No prefix here") == "No prefix here"
```

Behavioral test: the function produces correct output when imported from its new home.

### Test 2 — `strip_quotes` works from `email_adapter` import

```python
from agents.marina.email_adapter import strip_quotes
text = "Hello there\n\nOn Jan 1 someone wrote:\noriginal quoted text"
result = strip_quotes(text)
assert result == "Hello there"
```

Exact value assertion: the regex split at `\nOn .*wrote:\n` removes everything from that point, leaving just "Hello there".

### Test 3 — Backward compat: functions importable from `email_poller` (re-export)

```python
from agents.marina.email_poller import (
    normalize_subject, imap_connect, smtp_send, extract_text,
    strip_quotes, resolve_thread_key, sha, _is_new_email,
    IMAP_HOST, SMTP_HOST, EMAIL_ADDR,
)
# All should be the SAME objects as in email_adapter (re-export, not duplicate)
from agents.marina.email_adapter import normalize_subject as ns2, sha as sha2
assert normalize_subject is ns2, "Re-export should be the same object, not a copy"
assert sha is sha2
```

Identity check (`is`) verifies the re-export is a real import pass-through, not a duplicate definition.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` reports **889 passed / 0 failed** (886 baseline + 3 new). All 15+ existing email poller tests pass unchanged (they still import from `email_poller` which re-exports from `email_adapter`). The new `email_adapter.py` file contains ~200 lines (12 functions + 11 constants + imports + header). `email_poller.py` drops from ~1437 to ~1250 lines.

## Rollback

`git revert <commit>`. Restores the moved functions and constants to `email_poller.py`, removes `email_adapter.py` and the test file. Zero behavioral change in either direction — the functions work identically in either location.
