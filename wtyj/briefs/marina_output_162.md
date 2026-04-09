# OUTPUT 162 — Email thread persistence bug (8 paths) + defensive cleanup guards

## What was done

Fixed 8 code paths in `wtyj/agents/marina/email_poller.py` that persisted the email thread state via `save_json(THREAD_STATE_PATH, state)` without first setting `th["last_activity"] = now`. Because `_cleanup_stale_data` used `th.get("last_activity") or 0` and compared against `cutoff = now - 30*86400`, any thread with missing/zero `last_activity` was treated as 30+ days old and archived immediately on the next poll — destroying the `awaiting_relay` + `relay_token` flags needed to route operator replies back to customers.

### Core fix — 8 sites

Added `th["last_activity"] = now  # Brief 162: prevent premature archive` (or `customer_th["last_activity"] = now` for the relay success path) immediately before each `threads[thread_key] = th` assignment at these sites:

| # | Path | Line (pre-fix) | What triggers it |
|---|------|----------------|------------------|
| 1 | duplicate customer content | 555 | customer sent the exact same body twice |
| 2 | anti-loop guard | 577 | thread exceeded MAX_REPLIES_PER_THREAD |
| 3 | email relay reply SUCCESS | 670 | operator replied to a semi-escalation (uses `customer_th`) |
| 4 | fully_escalated holding reply | 702 | new email on an already-escalated thread |
| 5 | semi_escalation (the Calvin bug) | 949 | Marina determined the question needs crew confirmation |
| 6 | requires_human / full escalation | 1017 | complaint / refund / cancellation |
| 7 | booking_flow_off escalation | 1059 | features.booking_flow=false and booking intent |
| 8 | manifest creation failed | 1146 | gws_calendar failure after 2 retries |

The happy-path reply at line 1262 (now ~1270) was already correct and remains unchanged — it's the reference pattern all 8 fixes now match.

### Defensive fix — `_cleanup_stale_data` hardening

Rewrote the archive decision loop to include two new protective guards:

```python
for tk, th in threads.items():
    last = th.get("last_activity") or 0
    flags = th.get("flags", {})
    # Brief 162: skip if any protection flag is set
    if flags.get("hold_created"):
        continue
    if flags.get("awaiting_relay"):
        continue
    # Brief 162: missing or zero last_activity => unknown, don't archive
    if not last:
        continue
    if last < cutoff:
        to_delete.append(tk)
```

The `hold_created` exemption is unchanged. The two new guards are:
- **skip-if-awaiting_relay** — protects pending relay state even if `last_activity` is somehow stale. Directly prevents the Calvin regression.
- **skip-if-missing-last_activity** — treats unknown timing as "don't touch" rather than "ancient, archive immediately". Defense in depth against future missed assignments.

### Tests — 12 new tests in `wtyj/tests/marina/test_162_email_thread_persistence.py`

**Group A — `_cleanup_stale_data` behavior (7 tests):**
- `test_cleanup_archives_truly_stale_thread` — sanity: 31-day-old thread with no flags → archived
- `test_cleanup_keeps_fresh_thread` — baseline: fresh thread → kept
- `test_cleanup_skips_thread_with_missing_last_activity` — defensive guard
- `test_cleanup_skips_thread_with_zero_last_activity` — defensive guard edge case
- `test_cleanup_protects_awaiting_relay_even_if_stale` — Calvin scenario guard
- `test_cleanup_protects_hold_created_even_if_stale` — pre-existing guard still works
- `test_cleanup_archives_stale_plain_thread_after_fix` — regression: defensive guards don't accidentally protect plain stale threads

**Group B — source-level regression guards (3 tests):**
- `test_source_mutating_save_paths_set_last_activity` — count-based: expects `>= 9` assignments in source (1 pre-existing + 8 fixes)
- `test_source_semi_escalation_path_sets_last_activity` — proximity check for the Calvin path (semi_escalation)
- `test_source_full_escalation_path_sets_last_activity` — proximity check for the requires_human path

**Group C — Calvin regression scenarios (2 tests):**
- `test_cleanup_protects_awaiting_relay_with_stale_last_activity` — load-bearing Calvin test with 45-day-old `last_activity`
- `test_cleanup_protects_relay_thread_missing_last_activity` — belt-and-suspenders with both guards

## Test results

```
$ python3 -m pytest wtyj/tests/marina/test_162_email_thread_persistence.py -v
============================= 12 passed in 0.32s ==============================

$ python3 -m pytest wtyj/tests/ -q --tb=line
746 passed, 6 warnings in 4.07s
```

**746 passing / 0 failures.** Baseline was 734 from Brief 161 — Brief 162 adds 12 tests. Math checks: 734 + 12 = 746. ✓

## Live evidence from the bug report

Logs from 2026-04-08 ~00:45 UTC that surfaced this bug in production:

```
Processed UNSEEN from Calvin Adamus <calvin@gaimin.io> | hi , booking
Intents: ['inquiry', 'booking'] | Fields: {'date': '2026-04-13', 'guests': 4,
  'customer_name': 'Calvin', 'email': 'calvin@gaimin.io',
  'special_requests': 'Father in wheelchair, son is 5 years old'}
Semi-escalation: relay alert sent to butlerbensonagent@gmail.com for calvin@gaimin.io
Sent pending relay notification id=64 for calvin@gaimin.io
Archived 1 stale threads (>30d)                                           ← THE BUG
Processed UNSEEN from Benson Agent <butlerbensonagent@gmail.com> | Re: [RELAY-158cf2b73100] NO-REF - Calvin
ThreadKey: subj:butlerbensonagent@gmail.com:[relay-158cf2b73100] no-ref - calvin
RELAY: no pending relay for token=158cf2b73100 — skipping (may be already replied)
```

Post-fix, the "Archived 1 stale threads" line should NOT appear following a semi-escalation or full-escalation event because:
1. The thread now has `last_activity = now` set by the fix
2. Even if (1) somehow failed, the `awaiting_relay=True` flag would short-circuit the archive decision

## Deployment

- Backend pushed: commit `686c44b`
- VPS deployed: `docker compose down && build && up -d` on `wtyj-bluemarlin`
- Health check: `{"status":"ok"}` on port 8001
- Both containers running (`wtyj-bluemarlin` + `wtyj-adamus`)
- Adamus rebuild skipped per brief reasoning (email_poller doesn't run on Adamus due to empty EMAIL_ADDRESS)

## Cleanup

Marked stale pending notification `id=64` (Calvin's Brief 161-era relay that couldn't complete) as `replied` in `state_registry.pending_notifications` so it doesn't sit forever as a half-done relay:

```bash
docker exec wtyj-bluemarlin python3 -c '
import sqlite3
db = sqlite3.connect("/app/data/state_registry.db")
c = db.cursor()
c.execute("UPDATE pending_notifications SET status=? WHERE id=?", ("replied", 64))
db.commit()
'
# → "Marked notification id=64 as replied (stale relay from pre-fix test)"
```

## Unexpected findings during execution

### 1. Round-1 brief-reviewer caught 3 missed paths

Initial investigation found 4 fix sites (semi_escalation, requires_human, booking_flow_off, manifest_failed). The brief-reviewer agent flagged 3 more that had the identical bug pattern but were missed:
- Line 577 — anti-loop guard
- Line 670 — email relay reply SUCCESS (uses `customer_th`, not `th`)
- Line 702 — fully_escalated holding reply

Without the reviewer catch, these three paths would have continued dropping threads silently. The relay success path (line 670) is particularly important because it CLEARS `awaiting_relay=False` after processing the operator's reply — so after this path runs, the defensive guard won't protect the thread. The primary `last_activity = now` fix is load-bearing there, not the defensive guard.

### 2. Line 555 added as the 8th fix for consistency

The duplicate-content path at line 555 isn't strictly a bug (it only fires on threads that already have a `last_customer_hash`, which means they already went through happy-path processing at least once and thus already had `last_activity` set). But for consistency — every `threads[thread_key] = th` write should follow the same pattern — the fix was added here too. Low-risk, zero downside, catches any future race where a fresh thread somehow hits this branch.

### 3. Round-1 brief-reviewer also caught 3 test quality issues

- Test #8 was structurally impossible as originally specified (a "check every save_json has last_activity nearby" test would produce false positives for lines 513, 632, 636 which legitimately don't mutate the thread). Rewrote as a count-based structural test + a proximity test on specific known-fixed paths.
- Test #9 was vacuous: the setup had `last_activity = now` which would pass cleanup under both old and new code without exercising any guard. Rewrote with `last_activity = now - 45*86400` so the `awaiting_relay` guard is what saves the thread.
- Original indentation description hardcoded "20 spaces / 24 spaces" which was wrong. Replaced with "match surrounding indentation" language + a walk-upward-from-save_json pattern.

### 4. Round-2 brief-reviewer caught 3 text consistency issues

After the round-1 patches, round-2 review flagged:
- Success Condition still said "4 save_json calls" — updated to "8 fix sites"
- Root Cause said "Seven such paths exist" while Step 1 listed 8 — clarified "7 primary + 1 defensive for consistency = 8 total"
- Tests section listed test names that didn't match the actual test functions in Step 3 — realigned names

All addressed before execution. None of the round-2 issues affected the fix logic (which was correct from round-1 patches) — they were all text/consistency bugs in the brief itself that would have confused the executor.

### 5. The defensive guard is independently valuable

Even after the 8 primary fixes, the `_cleanup_stale_data` hardening is worth keeping because:
- It catches any FUTURE early-return path that forgets `last_activity` without requiring the author to remember the convention
- The `awaiting_relay` exemption is a semantic invariant ("pending relay state must never be destroyed by cleanup") that should be enforced at the cleanup layer regardless of what the mutation paths do
- The `not last` guard makes the cleanup behavior match intuition (missing data = unknown, not ancient)

Belt and suspenders. Both fixes stay.

## Files modified

| File | Change |
|------|--------|
| `wtyj/agents/marina/email_poller.py` | 8 `last_activity = now` assignments + defensive guards in `_cleanup_stale_data` |
| `wtyj/tests/marina/test_162_email_thread_persistence.py` | **NEW** — 12 tests |
| `wtyj/briefs/marina_brief_162_email_thread_persistence_bug.md` | **NEW** — this brief |

## Commit

Backend: `686c44b` on `main`, pushed to origin.

## Known limitations / not in scope

- Live end-to-end Calvin replay not yet performed in this session. The unit tests simulate the cleanup behavior perfectly but a real "send from Gmail, wait for semi-escalation, reply from Gmail, verify Marina relays the answer" flow would be a useful confirmation. Can be done next session if the user wants.
- The `email_thread_state.json` on the VPS still has the 4 butlerbensonagent test threads from Brief 161 E2E — they'll age out naturally in 30 days. Not worth manually cleaning.
- The defensive `awaiting_relay` guard means the Calvin-era stale notification id=64 would have been recoverable if the thread had been preserved. But the thread was already archived before the fix, so we can't retroactively relay that particular reply.

## Brief 162 is complete and deployed
