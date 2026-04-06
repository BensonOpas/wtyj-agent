# BRIEF 154 — Pre-Existing Latent Issues Cleanup (Issues 5-9 from Systemwide Check)

**Status:** Draft
**Files:** `wtyj/agents/social/whatsapp_client.py`, `wtyj/tests/marina/test_047_reschedule_booking_flow.py`, `wtyj/tests/marina/test_048_human_speech_optimization.py`, `wtyj/templates/client.json.template` (new file location), `clients/bluemarlin/config/client.json.template` (delete), `clients/bluemarlin/config/state_registry.db` (delete on VPS — 0-byte stale), `.dockerignore` (add `templates/` exclusion if needed)
**Depends on:** Briefs 141 (booking wording), 147 (gws lazy env var pattern — same fix here for whatsapp_client), 150-152 (WTYJ rename complete)
**Blocks:** Nothing.

---

## Context

The systemwide check earlier in this session found 9 issues in BlueMarlin's deployment. Issues 1-3 were addressed via earlier work (security key removal, docker prune, infra.md sweep in Brief 153). Brief 154 picks up issues 5-9.

### Issue 5 — `archived_threads.jsonl` last modified Mar 10 (27 days stale)

The file at `/root/clients/bluemarlin/config/archived_threads.jsonl` (63344 bytes) was last modified Mar 10 21:59. That's 27 days of zero archive activity. Two possibilities:
1. Normal — BlueMarlin hasn't had any threads that triggered archiving (archives happen when a thread is fully escalated or aged out, which is uncommon)
2. Bug — the archive logic stopped running at some point

Brief 154 investigates by reading the file's tail and checking how the archive write happens in `email_poller.py`. If it turns out to be normal behavior (rare archives), document the answer in the brief output and move on. If it's a real bug, scope a follow-up brief.

### Issue 6 — `email_thread_state.json` last modified Apr 4 (2 days stale)

File at `/root/clients/bluemarlin/config/email_thread_state.json` (292481 bytes, 105 threads) last modified Apr 4 23:53. Today is Apr 6. Two days of no thread state updates. Either no email activity in 2 days (plausible — quiet weekend) or the email_poller isn't writing state correctly.

Brief 154 investigates by tailing the BlueMarlin email_poller log (now mounted persistently at `/root/clients/bluemarlin/logs/email_poller.log` since Brief 150) and checking if it shows any actual email processing in the last 48 hours. If the poller is silent, that's normal (no inbound email). If it's processing emails but not writing state, that's a real bug.

### Issue 7 — Stale 0-byte `state_registry.db` in BlueMarlin's `/app/config/`

There's a 0-byte file at `/root/clients/bluemarlin/config/state_registry.db` left over from before the Brief 148 directory mount cleanup. The REAL state registry DB is at `/root/clients/bluemarlin/data/state_registry.db` (303 KB, the one that actually has data). The 0-byte one in `/app/config/` is leftover cruft, harmless but cluttered.

Brief 154 deletes it from the host (`rm /root/clients/bluemarlin/config/state_registry.db`).

### Issue 8 — `client.json.template` lives in BlueMarlin's per-client config dir

The file `clients/bluemarlin/config/client.json.template` is a static template, not BlueMarlin-specific business data. Per Brief 148's directory mount, it gets mounted into BlueMarlin's container at `/app/config/client.json.template`. Cosmetic clutter — Adamus's container doesn't have this file (since `clients/adamus/config/` doesn't have the template), so the layout is asymmetric.

Brief 154 moves the template to `wtyj/templates/client.json.template` (a new platform-level templates dir, sibling to `wtyj/agents/`). This makes it part of the source tree as platform-level reference material rather than per-client clutter.

### Issue 9 — 7 pre-existing test failures

**Critical correction (caught by reviewer round 1):** The wording `"Want me to go ahead and book this"` is NOT stale. It IS still the wording in `email_poller.py:412` (`_build_booking_summary`). Brief 141 only changed the parallel `social_agent.py:86` builder used by the WhatsApp/DM path. The two builders diverged intentionally (or Brief 141 was incomplete — that's a separate question, NOT in scope for Brief 154). The test assertions for `email_poller`'s booking summary are correct as-written. **The tests fail ONLY because of the hardcoded past date `2026-04-03`.**

| Test | Failure cause | Fix |
|---|---|---|
| `test_047::test_reschedule_triggers_summary` | Hardcoded date `2026-04-03` is now in the past. Validation rejects past dates with "That date has already passed" instead of producing the expected booking summary. | Update date to future date |
| `test_047::test_reschedule_sets_awaiting` | Same | Same |
| `test_047::test_booking_still_triggers_summary` | Same | Same |
| `test_047::test_reschedule_summary_correct_price` | Same | Same |
| `test_047::test_reschedule_summary_trip_name` | Same | Same |
| `test_048::test_reschedule_still_triggers` | Same hardcoded `2026-04-03` | Same |
| `test_068::test_send_text_message_success` | Module-level env var read at import time. `whatsapp_client.py` lines 12-13 read `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` at import time. When the test sets the env var BEFORE importing the module (in isolation), it works. In the full suite, some earlier test imports `whatsapp_client` transitively (via webhook_server or social_agent) before the env var is set. The module caches empty values, then test_068 sets the env var too late. | Make `whatsapp_client.py` read env vars at call time, same lazy pattern Brief 147 used for `gws_calendar.py`. |

All 7 failures are real test maintenance / latent code issues, not new platform bugs. They're worth fixing rather than deleting because the underlying test intent (reschedule routes through booking flow; send_text_message uses the right URL+headers) is still valid.

**Out of scope for Brief 154:** the wording divergence between `email_poller._build_booking_summary` (uses old wording "go ahead and book this") and `social_agent._build_booking_summary` (uses Brief 141's new wording "hold a spot"). Whether this should be unified is a separate decision and a separate brief. Brief 154 leaves both builders alone.

---

## Why This Approach

**Alternative considered: delete the 7 failing tests instead of fixing them.** Rejected. The reschedule tests cover Brief 047 logic that's still load-bearing. The send_text_message test covers the WhatsApp send path which is part of Brief 143's still-active code. Deleting them would lose real coverage.

**Alternative considered: relative dates in test fixtures (e.g., `today + 30 days`).** Considered. This avoids the test going stale every time the calendar moves forward. But it makes the test less deterministic (the value changes every day), which complicates failure debugging. Going with a fixed future date that's far enough out to last (e.g., `2027-12-15`). When that goes stale in 2 years, it's a one-line fix again.

**Alternative considered: leave `client.json.template` in `clients/bluemarlin/config/` and ignore the asymmetry.** Rejected. The user explicitly asked Brief 154 to address this. Moving it to `wtyj/templates/` makes the layout symmetric.

**Alternative considered: fix `whatsapp_client.py` by adding `importlib.reload` to the test.** Rejected. The same root cause (env var read at import time) bit us in Brief 147 and we fixed it with lazy reads. Same fix here is consistent and prevents the same bug from recurring whenever a new test imports whatsapp_client.

**Tradeoff accepted:** Issues 5 and 6 (file staleness) are investigations only. If a real bug surfaces during investigation, the brief STOPS the cleanup work (Issues 7-9), documents the bug, and opens a follow-up brief. Brief 154 does not interleave investigation with fix — investigations are read-only and either come back "no bug, normal behavior" or come back "real bug, follow-up brief opened."

**Scope-creep note (caught by reviewer round 1):** Brief 154 covers 5 unrelated issues. The reviewer suggested splitting into 154a/b/c/d. Decision: keep as one brief because (a) the user explicitly asked for "5 to 9 — brief" as one ask, (b) all 5 items are pre-existing latent issues from the same systemwide check, (c) the changes are independent enough that a partial revert is feasible — git tracks each file separately and the rollback section enumerates each item. Single commit message acceptable. If a single change causes a regression, `git revert` and then re-apply the safe subset is straightforward.

---

## Source Material

### Issue 7 — VPS file to delete

```
$ ls -la /root/clients/bluemarlin/config/state_registry.db
-rw-r--r-- 1 root root 0 Mar 10 18:56 state_registry.db
```

Confirmed 0 bytes, never touched since Mar 10. The real DB lives at `/root/clients/bluemarlin/data/state_registry.db` (303104 bytes, actively written to by the email_poller and webhook_server).

### Issue 8 — `client.json.template` current location and target

Current: `clients/bluemarlin/config/client.json.template` (1664 bytes, git-tracked)
Target: `wtyj/templates/client.json.template` (new directory in source tree)

The template is loaded by no production code. It's reference material for onboarding. The brief verifies this with a grep before moving.

### Issue 9 — Test 047 / 048 stale dates (verified counts)

`2026-04-03` is now in the past. Confirmed via `grep -c`:
- `test_047_reschedule_booking_flow.py`: **5 occurrences** (lines 13, 35, 42, 71, 78)
- `test_048_human_speech_optimization.py`: **1 occurrence** (line 150)

All 6 need updating to a future date.

The assertion strings (`"Want me to go ahead and book this"`) are **NOT changed**. They reflect the actual current behavior of `email_poller._build_booking_summary` and the tests are correct as-written for that builder. (See Issue 9 note above about the deferred builder-divergence question.)

### Issue 9 — `whatsapp_client.py` env var loading (current)

```python
# wtyj/agents/social/whatsapp_client.py:12-13
_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
```

Read at module import time. If the module loads before test fixtures set the env vars, the cached values are empty. Same shape as the Brief 147 gws bug.

### Brief 141's new wording (background only — Brief 154 does NOT use this)

Per system_state.md Brief 141 entry:
> Booking summary changed from "Want me to go ahead and book this?" to "Want me to check availability and hold a spot for you?" — sets correct expectation before availability check.

**This change was applied to `social_agent._build_booking_summary` (line 86) only**, not to `email_poller._build_booking_summary` (line 412 — still uses the old wording verbatim). The two booking summary builders were independent and Brief 141 only updated one. test_047 and test_048 exercise the email_poller builder, so the OLD wording in their assertions is correct for the code they test. Brief 154 leaves both wordings alone.

---

## Instructions

### Step 1 — Investigate `archived_threads.jsonl` (Issue 5)

```bash
ssh root@108.61.192.52 "
  echo '=== File stat ==='
  stat /root/clients/bluemarlin/config/archived_threads.jsonl
  echo
  echo '=== Last 5 lines ==='
  tail -5 /root/clients/bluemarlin/config/archived_threads.jsonl
  echo
  echo '=== Archive count ==='
  wc -l /root/clients/bluemarlin/config/archived_threads.jsonl
"
```

Check the timestamps in the last 5 lines. If they're all from before Mar 10, that means archives haven't been written since then. Check `wtyj/agents/marina/email_poller.py` for the archive logic (grep for `archived_threads` or `ARCHIVE_PATH`) — find when it gets called and what conditions trigger it.

If the archive logic only runs on `_cleanup_stale_data` (triggered every poll loop, but only writes when there's something to archive), and BlueMarlin simply hasn't had aged-out threads in 27 days, that's normal behavior. Document the finding in the brief output and move on.

If the logic looks like it should have run but didn't (e.g., it depends on a config value that's wrong), open a follow-up brief.

**Decision criteria:**
- Normal (rare archives) → document in output, no fix
- Bug → open follow-up brief with the root cause

### Step 2 — Investigate `email_thread_state.json` (Issue 6)

```bash
ssh root@108.61.192.52 "
  echo '=== File stat ==='
  stat /root/clients/bluemarlin/config/email_thread_state.json
  echo
  echo '=== Recent email_poller log lines ==='
  tail -50 /root/clients/bluemarlin/logs/email_poller.log
  echo
  echo '=== Heartbeat freshness ==='
  cat /root/clients/bluemarlin/config/heartbeat.txt
  date +%s
"
```

The heartbeat file is updated by the email_poller every loop. If `heartbeat.txt` is fresh (within the last few minutes) but `email_thread_state.json` is 2 days stale, that means the poller is RUNNING but not WRITING state — which would be a real bug. If the heartbeat is also stale, the poller isn't running at all, which is a different bug (supervisord might have restarted it but the process is silent).

The most likely outcome: heartbeat is fresh, no new emails arrived in 2 days, so `email_thread_state.json` was last written when the last real email was processed. Normal behavior.

**Decision criteria:** same as Issue 5 — investigate, document, fix-or-defer.

### Step 3 — Delete stale 0-byte `state_registry.db` (Issue 7)

```bash
ssh root@108.61.192.52 "
  echo '=== Before ==='
  ls -la /root/clients/bluemarlin/config/state_registry.db
  echo
  rm /root/clients/bluemarlin/config/state_registry.db
  echo '=== After ==='
  ls -la /root/clients/bluemarlin/config/state_registry.db 2>&1 || echo 'GONE (expected)'
  echo
  echo '=== Real DB still exists ==='
  ls -la /root/clients/bluemarlin/data/state_registry.db
"
```

The security hook does NOT block this command. The hook regex (`rm\s+(-[a-zA-Z]*)?r[a-zA-Z]*f?\s+(/|~|...)`) requires an `r` flag (`-rf`, `-r`, `-Rf`, etc.) followed by a root path. Plain `rm /path/to/file` without any `-r` flag does not match — verified by reading the hook source at `~/.claude/hooks/security-gate.sh`.

Verify the REAL DB at `/root/clients/bluemarlin/data/state_registry.db` is unchanged (~303 KB). The 0-byte file at `/app/config/state_registry.db` will not appear inside the container after the next restart since it's mounted from the now-empty host path.

### Step 4 — Move `client.json.template` to `wtyj/templates/`

First verify nothing depends on its current location:

```bash
grep -rn "client\.json\.template" /Users/benson/Projects/bluemarlin-agent/wtyj /Users/benson/Projects/bluemarlin-agent/clients --include="*.py" --include="*.yml" --include="*.json"
```

Expected: zero matches in source code or yaml. If there are matches, those code paths need updating too — flag in execution.

Then perform the move:

```bash
mkdir -p /Users/benson/Projects/bluemarlin-agent/wtyj/templates
git mv clients/bluemarlin/config/client.json.template wtyj/templates/client.json.template
```

Verify `git status` shows a clean rename. The template is now a git-tracked file in the source tree, accessible to operators reading the source for reference.

Add to `.dockerignore` if not already excluded — `wtyj/templates/` is reference material, not needed at runtime in the container:

```
wtyj/templates/
```

### Step 5 — Fix `whatsapp_client.py` env var loading (Issue 9, test_068)

In `wtyj/agents/social/whatsapp_client.py` lines 12-13, replace:

```python
_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
```

with helper functions that read at call time:

```python
def _access_token() -> str:
    return os.environ.get("WHATSAPP_ACCESS_TOKEN", "")

def _phone_number_id() -> str:
    return os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
```

Then update every call site in `whatsapp_client.py` that uses `_ACCESS_TOKEN` or `_PHONE_NUMBER_ID` to call the helper instead. Find all references with:

```bash
grep -n "_ACCESS_TOKEN\|_PHONE_NUMBER_ID" wtyj/agents/social/whatsapp_client.py
```

Update each call site. Typical patterns:
- `f"https://graph.facebook.com/v22.0/{_PHONE_NUMBER_ID}/messages"` → `f"https://graph.facebook.com/v22.0/{_phone_number_id()}/messages"`
- `headers = {"Authorization": f"Bearer {_ACCESS_TOKEN}"}` → `headers = {"Authorization": f"Bearer {_access_token()}"}`

### Step 6 — Fix test_047 stale dates (Issue 9, 5 tests)

In `wtyj/tests/marina/test_047_reschedule_booking_flow.py`:

Replace ALL 5 occurrences of `2026-04-03` with `2027-12-15` (a fixed future date far enough out to survive 2+ years).

Use `Edit` with `replace_all=true` so all 5 lines (13, 35, 42, 71, 78) get updated in one shot.

**DO NOT touch the `"Want me to go ahead and book this"` assertion strings.** They are correct as-written. The reviewer round 1 caught this — see "Out of scope" note in Issue 9.

### Step 7 — Fix test_048 stale date (Issue 9, 1 test)

In `wtyj/tests/marina/test_048_human_speech_optimization.py`:

Replace ONLY the 1 occurrence of `2026-04-03` (line 150) with `2027-12-15`.

`replace_all=true` is fine here because there's only one occurrence of `2026-04-03`. Use a unique anchor in `old_string` (the surrounding line context) to be extra-safe.

**DO NOT touch the `"Want me to go ahead and book this"` assertion strings.** test_048 has 3 occurrences of that wording but only 1 is in a failing test, and the wording itself is correct. The other 2 occurrences are in tests that currently pass — leave them alone.

### Step 8 — Run tests locally

```bash
cd /Users/benson/Projects/bluemarlin-agent/wtyj
python3 -m pytest tests/marina/test_047_reschedule_booking_flow.py tests/marina/test_048_human_speech_optimization.py tests/social/test_068_pipeline.py -v
```

Expected: all 7 previously-failing tests now pass + 1 new test (`test_whatsapp_client_reads_env_var_lazily`) also passes.

Then run the full suite:

```bash
python3 -m pytest tests/ -q --tb=no
```

Expected: 731 passed / 0 failures (one new test added, seven previously-failing now passing). **Zero pre-existing failures.** This is the first time in months the suite has been fully clean.

### Step 9 — Commit and push

```bash
git add -A
git commit -m "Brief 154 — Cleanup pre-existing latent issues"
git push
```

No VPS deploy needed for the source code changes (templates move + whatsapp_client refactor + test fixes). The whatsapp_client fix is backwards-compatible — existing code that called functions still works because we just added helpers behind the scenes; the env var values are now read fresh on each call.

### Step 10 — Investigation results

Update Brief 154 output document with the findings from Issues 5 and 6. Format:

```
## Issue 5 — archived_threads.jsonl staleness investigation

Last archive entry timestamp: <found via tail>
Number of total archives: <found via wc -l>
Conclusion: <normal/bug>
[If bug:] Follow-up brief: <number>

## Issue 6 — email_thread_state.json staleness investigation

Heartbeat freshness: <fresh/stale>
Recent email_poller log activity: <quiet/active>
Conclusion: <normal/bug>
[If bug:] Follow-up brief: <number>
```

---

## Tests

The brief is mostly fixing existing tests plus adding one new regression test. The verification IS the test suite — after Brief 154, 731 tests pass with zero pre-existing failures. That's a strong success signal.

Steps 6-7 modify existing test files in place (date updates only).

**MANDATORY (not optional):** regression test for the `whatsapp_client.py` lazy env var fix. Without this test, the same import-order bug can silently come back. Add to `wtyj/tests/social/test_068_pipeline.py` as a new test function:

```python
def test_whatsapp_client_reads_env_var_lazily(monkeypatch):
    """Brief 154 — regression: whatsapp_client must read env vars at call time,
    not at import time, so tests can override them after import."""
    from agents.social import whatsapp_client
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "fresh-token-from-test")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "fresh-phone-id-from-test")
    assert whatsapp_client._access_token() == "fresh-token-from-test"
    assert whatsapp_client._phone_number_id() == "fresh-phone-id-from-test"
```

This test must pass both in isolation AND in the full suite, which is the failure mode the original bug exhibited.

This new test plus the 7 fixed-failure tests means the brief moves the test count from 730 passed / 7 failed → 731 passed / 0 failed. (One new test, seven previously-failing now passing.)

---

## Success Condition

- 7 previously-failing tests now pass
- 1 new regression test for whatsapp_client lazy env var pass
- Full regression: 731 passed, 0 failures (730 + 1 new test, 7 pre-existing failures fixed)
- `client.json.template` is at `wtyj/templates/client.json.template`, no longer in `clients/bluemarlin/config/`
- 0-byte `state_registry.db` is gone from `/root/clients/bluemarlin/config/`
- Investigations for archived_threads.jsonl and email_thread_state.json complete with findings documented in the output (whether or not real bugs are found)

---

## Rollback

Single git revert restores all source code changes. Memory (test changes, whatsapp_client refactor, template move) is fully captured by git.

The VPS file deletion (Issue 7) is the only change that's not git-tracked. Trivial to reverse: `touch /root/clients/bluemarlin/config/state_registry.db` recreates the empty file.

Investigations (Issues 5+6) are read-only — nothing to roll back.
