# OUTPUT 154 — Pre-Existing Latent Issues Cleanup

## What was done

### Investigations (Issues 5 + 6) — both came back NORMAL, no fix needed

**Issue 5 — `archived_threads.jsonl` 27-day staleness:**

```
File stat: 63344 bytes, last modified 2026-03-10 21:59
Total archives: 42
Last entry: archived_at: 1773179965 (= 2026-03-10 18:39)
            thread_key: subj:ops.bluemarlindemo@gmail.com:big group trip
```

Verdict: **normal behavior**. The archive logic at `email_poller.py:118-132` (`_cleanup_stale_data`) only writes to `archived_threads.jsonl` when there are threads older than `THREAD_RETENTION_DAYS` (30 days) without an active hold. The function runs every poll loop (every 30 seconds, verified by fresh heartbeat). Since Mar 10, no threads have aged into the archive window — meaning either no customers contacted BlueMarlin in that time, or the threads that did exist all completed (got holds) and so are excluded from archiving. Both are plausible. No bug, no follow-up brief.

**Issue 6 — `email_thread_state.json` 2-day staleness:**

```
File stat: 292481 bytes, last modified 2026-04-04 23:53
Heartbeat: 11 seconds old (poller alive)
email_poller.log: 3 "Email poller started" lines, no "Processed UNSEEN" or "Replied" lines
```

Verdict: **normal behavior**. The poller is running (heartbeat is 11 seconds old). The state file is only written when state changes — i.e., when an email is processed. The log shows zero email processing in the visible window. Quiet inbox for 2 days = no state writes = stale file timestamp. This is correct behavior. No bug, no follow-up brief.

### Cleanup actions

**Issue 7 — Stale 0-byte `state_registry.db` deleted:**

```
$ ssh root@... "rm /root/clients/bluemarlin/config/state_registry.db"
Before: -rw-r--r-- 1 root root 0 Mar 10 18:56
After:  GONE
Real DB at /root/clients/bluemarlin/data/state_registry.db: 303104 bytes (untouched)
```

The security hook did NOT block this — verified the regex requires `-r` flag, which plain `rm /path/to/file` doesn't have. Brief's pre-execution hook analysis was correct.

**Issue 8 — `client.json.template` moved to platform-level:**

```
git mv clients/bluemarlin/config/client.json.template wtyj/templates/client.json.template
```

Added `wtyj/templates/` to `.dockerignore` so the template doesn't ship in the Docker image (it's source-tree reference material, not runtime code).

Verified zero runtime references via grep before the move (no `.py`, `.yml`, or `.json` file references the old path).

### Code changes

**Issue 9 — `whatsapp_client.py` lazy env var read:**

Replaced module-level constants:
```python
_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
```

with helper functions:
```python
def _access_token() -> str:
    return os.environ.get("WHATSAPP_ACCESS_TOKEN", "")

def _phone_number_id() -> str:
    return os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
```

Updated the 2 call sites in `send_text_message()` to use the helpers. Same lazy-read pattern Brief 147 used to fix `gws_calendar.py`.

### Test fixture updates

**Issue 9 — date updates:**

Replaced all 5 occurrences of `2026-04-03` in `test_047_reschedule_booking_flow.py` with `2027-12-17`. Replaced the 1 occurrence in `test_048_human_speech_optimization.py` similarly.

First attempt used `2027-12-15` but that's a Wednesday, and the 3-in-1 Snorkeling Trip is "Fridays only" — the validation rejected the date with "doesn't run on Wednesdays" instead of producing the booking summary. Switched to `2027-12-17` (a Friday — confirmed by the error message itself which suggested "Friday 17 December" as an alternative). Both test files now pass.

**IMPORTANT:** the assertion strings (`"Want me to go ahead and book this"`) were NOT changed. The reviewer round 1 caught a false premise where I assumed Brief 141 had updated this wording across both booking summary builders. In fact, Brief 141 only updated `social_agent._build_booking_summary` (used by WhatsApp/DM path); `email_poller._build_booking_summary` (used by these tests) still produces the old wording verbatim. The tests' assertions are correct as-written.

### New mandatory regression test

Added `test_whatsapp_client_reads_env_var_lazily` in `test_068_pipeline.py`:
```python
def test_whatsapp_client_reads_env_var_lazily(monkeypatch):
    from agents.social import whatsapp_client
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "fresh-token-from-test")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "fresh-phone-id-from-test")
    assert whatsapp_client._access_token() == "fresh-token-from-test"
    assert whatsapp_client._phone_number_id() == "fresh-phone-id-from-test"
```

This test will fail if the lazy-read pattern is ever reverted, locking in the fix.

## Test results

### Targeted tests (the 7 previously-failing + the new regression test)

All 8 pass — verified with isolated run:

```
40 passed in 0.47s
```

(40 includes the 8 newly-fixed/added tests plus the other tests in those files that were already passing.)

### Full regression

Before Brief 154: 730 passed / 7 pre-existing failures = 737 total
After Brief 154: **738 passed / 0 failures** (730 - 7 stale + 7 fixed + 1 new = 738)

**First time in months the suite is fully clean.** Zero pre-existing failures. The test suite now provides honest signal again.

```
738 passed, 6 warnings in 3.99s
```

## Deployment

No VPS deploy needed. Brief 154's source-code changes (whatsapp_client.py refactor) are backwards-compatible — call sites changed but the behavior is identical when env vars are set normally. Test updates and template move are doc/test only. The VPS already had the 0-byte file deleted as part of Step 3.

The commit pushed automatically via the security hook fix from earlier in the session — no manual `git push` needed.

## Unexpected / problems encountered

1. **Reviewer round 1 caught a critical false premise.** I had assumed Brief 141 unified the wording across both booking summary builders. In fact, Brief 141 only changed `social_agent.py:86`. The `email_poller.py:412` builder still produces the old wording verbatim. My initial brief draft would have replaced correct test assertions with wrong substrings, breaking 6 tests against actually-correct production code. The reviewer caught this, I verified directly in source, and removed all wording changes from the brief. Only date updates remained.

2. **Wrong occurrence counts in the first draft.** I said test_047 had 4 date occurrences (actually 5) and 3 wording occurrences (actually 2). The reviewer caught this. Re-grepped precisely before patching.

3. **First date attempt `2027-12-15` was a Wednesday.** The 3-in-1 Snorkeling Trip is "Fridays only" so the validation rejected the date with "doesn't run on Wednesdays" instead of producing the booking summary. Switched to `2027-12-17` (Friday) and the tests pass. Lesson: when picking future dates for tests that exercise day-of-week-restricted services, check the day of the week, not just "is it in the future."

4. **The wording divergence between `email_poller._build_booking_summary` and `social_agent._build_booking_summary` is a real architectural inconsistency** but Brief 154 explicitly leaves it alone. Whether to unify them is a separate decision and a separate brief. Noted in the brief's "Out of scope" section.

## Post-execution

- Committed as `6d70602` on main
- Pushed to origin
- 738 tests passing, 0 failures
- Investigations documented (no follow-up briefs needed)
