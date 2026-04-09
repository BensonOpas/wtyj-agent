# BRIEF 162 — Email thread persistence bug: escalation paths lose `last_activity` and get archived
**Status:** Draft | **Files:** email_poller.py, test_162_email_thread_persistence.py (new) | **Depends on:** Brief 161 | **Blocks:** —

## Context

Live E2E testing on 2026-04-08 surfaced a production-blocking bug in the email relay flow. A real customer (`calvin@gaimin.io`) sent an email with a question about wheelchair accessibility and a child's age. Marina correctly identified it as a semi-escalation, generated a relay notification (id=64, token=`158cf2b73100`), and emailed it to the operator (`butlerbensonagent@gmail.com`). The operator replied to the relay email with an answer.

The reply never reached the customer. The email_poller logs show:

```
Semi-escalation: relay alert sent to butlerbensonagent@gmail.com for calvin@gaimin.io
Sent pending relay notification id=64 for calvin@gaimin.io
Archived 1 stale threads (>30d)
Processed UNSEEN from Benson Agent <butlerbensonagent@gmail.com> | Re: [RELAY-158cf2b73100] NO-REF - Calvin
RELAY: no pending relay for token=158cf2b73100 — skipping (may be already replied)
```

Notice the sequence: the relay notification is sent, then "Archived 1 stale threads" runs, then the operator's reply arrives and the token lookup fails. The `pending_notifications` row is still present (id=64, status=sent), but the thread it belonged to has been deleted from `email_thread_state.json`.

Direct DB inspection confirms:
```
(64, 'relay', 'email', 'calvin@gaimin.io', 'Calvin', '158cf2b73100', 'sent', '[RELAY-158cf2b73100] NO-REF - Calvin')
```

And the thread state file shows only 4 threads remaining — all of which are successful booking flows from my Brief 161 E2E testing (Lucia, Pieter, Maria, Robert). Missing: Angela (complaint), Joscar (semi-escalation), Calvin (semi-escalation). **Every thread that went through an escalation path is gone.**

## Why This Approach

### Root cause

`email_poller.py` has one code path (the happy-path reply at line 1258-1264) that persists the thread correctly — it sets `th["last_activity"] = now` before `save_json`. Every other early-return `continue` path that persists state **forgets to set `last_activity`**. **Total: 8 fix sites** — 7 primary early-return paths (initial investigation found 4; brief-reviewer surfaced 3 more: lines 577, 670, 702) + 1 low-risk duplicate-content path (line 555, added for defensive consistency):

1. **Line 558-578 — anti-loop guard**: when a thread exceeds `MAX_REPLIES_PER_THREAD` in the reply window, sends a safe-stop message and persists. Mutates `reply_times`, `last_customer_hash`, `threads[thread_key] = th`, saves at line 577. **Missing `last_activity = now`**.
2. **Line 647-671 — email relay reply SUCCESS**: after the operator's reply is successfully reformulated and sent to the customer, clears `awaiting_relay=False` and pops `relay_token`. Saves the customer thread at line 670. **Missing `last_activity = now`**. Note: because this path clears `awaiting_relay`, the defensive cleanup guard (skip-if-awaiting_relay) won't protect this thread on subsequent polls — so the primary fix is load-bearing here.
3. **Line 681-704 — fully_escalated holding reply**: when a subsequent email arrives on an already-escalated thread, sends a short holding reply and persists at line 702. **Missing `last_activity = now`**.
4. **Line 889-950 — semi_escalation path**: generates relay_token, sets `awaiting_relay=True`, sends relay email, creates pending_notification. Persists thread at line 949. **Missing `last_activity = now`**. This is the exact path that caused the Calvin regression.
5. **Line 952-1018 — requires_human (full escalation) path**: sets `fully_escalated=True`, sends escalation alert, creates pending_notification. Persists thread at line 1017. **Missing `last_activity = now`**.
6. **Line 1020-1060 — booking_flow_off escalation path**: sends Marina's reply, creates pending_notification. Persists thread at line 1059. **Missing `last_activity = now`**.
7. **Line 1126-1147 — manifest creation failed path**: handles gws_calendar retry failure, sends failure reply. Persists thread at line 1146. **Missing `last_activity = now`**.
8. **Line 549-555 — duplicate customer content path** (defensive fix): technically writes `threads[thread_key] = th` but only for an existing thread whose `last_customer_hash` already matched, so in normal operation `last_activity` would already be set on that thread from its prior processing. Low risk but the fix is added for consistency so every `threads[thread_key] = th` site has the same persistence pattern. **Missing `last_activity = now`**.

**Not a fix target** (investigated, genuinely no thread mutation):
- Line 513 — sender rate limit: saves `state["sender_rates"]` only; `threads[thread_key] = th` is not called. No thread mutation.
- Lines 632, 636 — WhatsApp relay paths (channel=whatsapp): mutate `state_registry.wa_save_booking_state`, not the email thread state. The `save_json` call re-saves the email state untouched. No fix needed.

When any of these paths run, the thread is saved with `last_activity=0` (the default from `th.get("last_activity") or 0` in `_cleanup_stale_data`). On the next poll cycle (every ~10 seconds), `_cleanup_stale_data` iterates threads and compares `last_activity < cutoff` where `cutoff = now - 30*86400`. Since `0 < (now - 30*86400)` is always true, these threads are archived immediately and deleted from the live state file.

### The cascading effect on the relay reply flow

The relay reply handler at line 586-637 tries to find the original customer thread by:
1. Matching `[RELAY-<token>]` in the reply subject (line 588)
2. Iterating `state["threads"]` for a thread with `flags.awaiting_relay==True` AND `flags.relay_token==<token>` (lines 592-599)
3. Falling back to `state_registry.get_relay_by_token()` which returns the notification row from the DB (line 602)
4. If the notification row's `channel=="whatsapp"`, it uses the WhatsApp state registry to find the customer (lines 603-632)
5. If the notification row's `channel=="email"`, there's **no fallback** — it logs "no pending relay for token — skipping" and drops the reply (lines 634-637)

So the lookup is fundamentally dependent on the customer's email thread being present in `state["threads"]`. The `pending_notifications` row isn't a fallback source — it's only used for the WhatsApp path.

### The fix

**Primary fix**: add `th["last_activity"] = now` before each of the four affected `save_json` calls. One line each, four total. This is the minimum fix to stop threads from being archived prematurely.

**Defensive fix (belt and suspenders)**: harden `_cleanup_stale_data` against this category of bug so a future missed assignment doesn't silently destroy state again. Specifically:
- Skip archiving any thread with `awaiting_relay=True` (protects pending relay state even if `last_activity` is stale).
- Skip archiving any thread where `last_activity` is missing or zero — treat this as "unknown, don't touch" rather than "oldest possible, archive immediately". Threads with no `last_activity` at all should be considered fresh, not ancient.

The existing `hold_created` exemption stays unchanged.

I considered using `created_at` as a fallback field, but that requires adding a new field to every thread and backfilling existing state. Not worth the complexity when the two guards above solve the immediate issue.

## Source Material

### `_cleanup_stale_data` (email_poller.py:120-151)

```python
def _cleanup_stale_data(state, now):
    """Prune threads >30d old (no active hold) and trim processed_hashes."""
    cutoff = now - (THREAD_RETENTION_DAYS * 86400)
    threads = state.get("threads", {})
    to_delete = []
    for tk, th in threads.items():
        last = th.get("last_activity") or 0
        if last < cutoff and not th.get("flags", {}).get("hold_created"):
            to_delete.append(tk)
    if to_delete:
        with open(ARCHIVE_PATH, "a", encoding="utf-8") as f:
            for tk in to_delete:
                f.write(json.dumps({"archived_at": now, "thread_key": tk, "data": threads[tk]}, ensure_ascii=False) + "\n")
                del threads[tk]
        log(f"Archived {len(to_delete)} stale threads (>{THREAD_RETENTION_DAYS}d)")
    # ... (processed_hashes pruning and sender_rates pruning below — unchanged)
```

`THREAD_RETENTION_DAYS = 30` (line 61).

### Path 1 — semi_escalation (lines 945-950)

```python
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue
```

### Path 2 — requires_human / full escalation (lines 1013-1018)

```python
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue
```

### Path 3 — booking_flow=OFF escalation (lines 1055-1060)

```python
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue
```

### Path 4 — manifest creation failed (lines 1142-1147)

```python
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue
```

### Happy path (lines 1258-1264) — CORRECT reference

```python
                # Step 7: Persist state
                im.uid("store", uid, "+FLAGS", r"(\Seen)")
                th["reply_times"].append(now)
                th["last_customer_hash"] = customer_hash
                th["last_activity"] = now                  # ← the line missing in the 4 paths above
                threads[thread_key] = th
                save_json(THREAD_STATE_PATH, state)
```

### Live evidence from VPS logs (2026-04-08 ~00:45 UTC)

```
Processed UNSEEN from Calvin Adamus <calvin@gaimin.io> | hi , booking
Intents: ['inquiry', 'booking'] | Fields: {'date': '2026-04-13', 'guests': 4, 'customer_name': 'Calvin', 'email': 'calvin@gaimin.io', 'special_requests': 'Father in wheelchair, son is 5 years old'}
Semi-escalation: relay alert sent to butlerbensonagent@gmail.com for calvin@gaimin.io
Sent pending relay notification id=64 for calvin@gaimin.io
Archived 1 stale threads (>30d)
Processed UNSEEN from Benson Agent <butlerbensonagent@gmail.com> | Re: [RELAY-158cf2b73100] NO-REF - Calvin
ThreadKey: subj:butlerbensonagent@gmail.com:[relay-158cf2b73100] no-ref - calvin
RELAY: no pending relay for token=158cf2b73100 — skipping (may be already replied)
```

### Live evidence from state_registry.db

```
(64, 'relay', 'email', 'calvin@gaimin.io', 'Calvin', '158cf2b73100', 'sent', '[RELAY-158cf2b73100] NO-REF - Calvin')
```

The notification row is there. The thread is gone. The reply is dropped.

### Current state of email_thread_state.json

```
Total threads: 4
- subj:butlerbensonagent@gmail.com:sunset cruise booking question    (Lucia - happy path)
- subj:butlerbensonagent@gmail.com:snorkeling next tuesday            (Pieter - happy path)
- subj:butlerbensonagent@gmail.com:reserva klein curacao              (Maria - happy path)
- subj:butlerbensonagent@gmail.com:book sunset cruise now             (Robert - happy path)
```

All 4 remaining threads took the happy path at line 1258. Every thread that took an escalation path is missing.

## Instructions

### Step 1: Fix the seven early-return paths in email_poller.py (plus the one low-risk duplicate-content path for consistency)

For each of the following `save_json(THREAD_STATE_PATH, state)` call sites, insert `th["last_activity"] = now  # Brief 162: prevent premature archive` immediately above the `threads[thread_key] = th` line. **Do not hard-code indentation levels** — match the indentation of the surrounding statements in the same block exactly. The pattern to locate each fix site is: find the `save_json(THREAD_STATE_PATH, state)` call and walk upward to the nearest `threads[thread_key] = th` assignment; insert the new line directly before that assignment.

Fix sites (line numbers may drift by 1-2 as you edit — use the pattern match, not the literal number):

| # | Approx line | Path name | Target |
|---|-----|------|--------|
| 1 | 577 | anti-loop guard | Before `threads[thread_key] = th` |
| 2 | 555 | duplicate customer content | Before `threads[thread_key] = th` |
| 3 | 670 | email relay reply SUCCESS | Before `state["threads"][customer_thread_key] = customer_th` (customer_th, not th) |
| 4 | 702 | fully_escalated holding reply | Before `threads[thread_key] = th` |
| 5 | 949 | semi_escalation | Before `threads[thread_key] = th` |
| 6 | 1017 | requires_human | Before `threads[thread_key] = th` |
| 7 | 1059 | booking_flow_off escalation | Before `threads[thread_key] = th` |
| 8 | 1146 | manifest creation failed | Before `threads[thread_key] = th` |

**Special case for fix #3 (line 670)**: this path operates on `customer_th`, not `th`. The inserted line must be `customer_th["last_activity"] = now  # Brief 162: prevent premature archive`. This is also the path that clears `awaiting_relay=False`, so the defensive cleanup guard (skip-if-awaiting_relay) won't protect it — the primary fix at this site is load-bearing.

**Example of the edit for fix #5 (semi_escalation, the most important one):**

Replace:
```python
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue
```

With:
```python
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    th["last_activity"] = now  # Brief 162: prevent premature archive
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue
```

**Verification after all 8 edits**: run `grep -n 'th\["last_activity"\] = now\|customer_th\["last_activity"\] = now' wtyj/agents/marina/email_poller.py`. Expect at least 9 results: 1 pre-existing (happy path around line 1262) + 8 new from this fix. If the count is less than 9, you missed one.

### Step 2: Harden `_cleanup_stale_data` (email_poller.py:120)

Replace the `for` loop in `_cleanup_stale_data` with the defensive version that protects pending-relay threads and treats missing `last_activity` as "fresh, don't touch":

Replace:
```python
def _cleanup_stale_data(state, now):
    """Prune threads >30d old (no active hold) and trim processed_hashes."""
    cutoff = now - (THREAD_RETENTION_DAYS * 86400)
    threads = state.get("threads", {})
    to_delete = []
    for tk, th in threads.items():
        last = th.get("last_activity") or 0
        if last < cutoff and not th.get("flags", {}).get("hold_created"):
            to_delete.append(tk)
```

With:
```python
def _cleanup_stale_data(state, now):
    """Prune threads >30d old (no active hold, no pending relay) and trim processed_hashes.

    Brief 162: defensive guards against the class of bug where an early-return
    code path forgets to set last_activity. A missing or zero last_activity
    is now treated as "don't know, don't archive" rather than "ancient, archive
    immediately". Also never archive a thread with awaiting_relay=True — that
    would destroy the relay token lookup and silently drop the operator's reply.
    """
    cutoff = now - (THREAD_RETENTION_DAYS * 86400)
    threads = state.get("threads", {})
    to_delete = []
    for tk, th in threads.items():
        last = th.get("last_activity") or 0
        flags = th.get("flags", {})
        # Skip if any protection flag is set
        if flags.get("hold_created"):
            continue
        if flags.get("awaiting_relay"):
            continue
        # Missing or zero last_activity => unknown, don't archive
        if not last:
            continue
        if last < cutoff:
            to_delete.append(tk)
```

The rest of the function (the archive-file writing, log line, processed_hashes pruning, sender_rates pruning) stays exactly as it was.

### Step 3: Write tests — `wtyj/tests/marina/test_162_email_thread_persistence.py`

Create a new test file covering:

**Group A — `_cleanup_stale_data` behavior:**

1. `test_cleanup_archives_truly_stale_thread` — thread with `last_activity = now - 31*86400` is archived. Regression coverage for the happy case still working.
2. `test_cleanup_keeps_fresh_thread` — thread with `last_activity = now` is kept. Baseline sanity.
3. `test_cleanup_skips_thread_with_missing_last_activity` — thread with no `last_activity` field at all is NOT archived. This is the direct defense against the Brief 162 bug class.
4. `test_cleanup_skips_thread_with_zero_last_activity` — thread with explicit `last_activity=0` is NOT archived.
5. `test_cleanup_protects_awaiting_relay_even_if_stale` — thread with `awaiting_relay=True` AND very old `last_activity` is NOT archived. Protects the Calvin scenario.
6. `test_cleanup_protects_hold_created_even_if_stale` — existing exemption still works.
7. `test_cleanup_archives_stale_plain_thread` — regular stale thread without any protection flags IS archived.

**Group B — source-level structural test for the 7 known-mutating paths:**

8. `test_source_mutating_save_paths_set_last_activity` — read email_poller.py source and assert that a minimum number of `th["last_activity"] = now` OR `customer_th["last_activity"] = now` assignments exist in the file. After the fix there should be at least 9 such assignments (1 pre-existing at the happy path around line 1262, plus 8 new ones from Brief 162). The test is a structural count, not a per-path proximity check — the proximity check idea from round-1 review was rejected because lines 513, 632, and 636 are legitimate `save_json` calls that don't mutate the thread, so a "every save_json must have a nearby last_activity" assertion would produce false positives. A count-based test catches regressions where someone adds a new early-return path but forgets the `last_activity` line: the count would stay flat, and a second assertion on a specific known-fixed path (e.g. the semi_escalation site) would fail.

```python
def test_source_mutating_save_paths_set_last_activity():
    """Brief 162: regression guard. Count last_activity assignments in email_poller.py.
    Baseline: 1 pre-existing (happy path) + 8 new (Brief 162 fixes) = 9 total minimum."""
    src = open(os.path.join(os.path.dirname(__file__), '..', '..',
                            'agents', 'marina', 'email_poller.py')).read()
    # Both th["last_activity"] = now and customer_th["last_activity"] = now are valid
    count = src.count('["last_activity"] = now')
    assert count >= 9, (
        f"Expected >= 9 last_activity assignments in email_poller.py after Brief 162 "
        f"(1 happy path + 8 fixes), got {count}. If you added a new early-return "
        f"path that persists state, you must also set last_activity before save_json."
    )

def test_source_semi_escalation_path_sets_last_activity():
    """Brief 162: specifically verify the semi_escalation path (the Calvin bug site).
    Find the 'Semi-escalation: relay alert sent' log line and confirm last_activity
    is set within the 50 lines before it."""
    src = open(os.path.join(os.path.dirname(__file__), '..', '..',
                            'agents', 'marina', 'email_poller.py')).read()
    lines = src.split('\n')
    # Find the semi-escalation path's save_json call
    save_idx = None
    for i, line in enumerate(lines):
        if 'Semi-escalation: relay alert sent' in line:
            # Walk forward to find the next save_json(THREAD_STATE_PATH
            for j in range(i, min(i + 60, len(lines))):
                if 'save_json(THREAD_STATE_PATH' in lines[j]:
                    save_idx = j
                    break
            break
    assert save_idx is not None, "Could not locate semi_escalation save_json call"
    # Search the 20 lines before save_idx for last_activity assignment
    window = '\n'.join(lines[max(0, save_idx - 20):save_idx])
    assert '["last_activity"] = now' in window, (
        f"semi_escalation path at line ~{save_idx} is missing last_activity assignment. "
        f"Window checked:\n{window}"
    )
```

**Group C — Calvin regression scenario (end-to-end state simulation):**

9. `test_cleanup_protects_awaiting_relay_with_stale_last_activity` — this is the load-bearing Calvin test. Set up a thread with `awaiting_relay=True, relay_token="158cf2b73100"` AND `last_activity = now - 45*86400` (45 days old, past the cutoff). Call `_cleanup_stale_data(state, now)`. Assert the thread is still present, proving the `awaiting_relay` guard overrides the cutoff. This is the test that would have caught the Calvin bug in the hypothetical timeline where `last_activity` was being set correctly but cleanup was still pruning relay threads.

10. `test_cleanup_protects_relay_thread_missing_last_activity` — set up a thread with `awaiting_relay=True, relay_token="158cf2b73100"` and NO `last_activity` field at all. Call `_cleanup_stale_data(state, now)`. Assert the thread is still present. This covers the interaction of both defensive guards (skip-if-awaiting-relay AND skip-if-no-last_activity) — belt and suspenders.

### Step 4: Verify state files manually on VPS before fix

On the VPS, the thread state file is at `/root/clients/bluemarlin/config/email_thread_state.json`. Check the current contents before the fix lands to establish a baseline. This is documentation only, not a code step.

### Step 5: Run tests locally

```bash
cd /Users/benson/Projects/bluemarlin-agent
python3 -m pytest wtyj/tests/marina/test_162_email_thread_persistence.py -v --tb=short
python3 -m pytest wtyj/tests/ -q --tb=line  # full regression
```

Both must pass cleanly. The full suite baseline is 734 passing from Brief 161. Brief 162 adds 10 new tests so the target is 744 passing.

### Step 6: Commit, deploy, and verify live

Standard deploy flow:

```bash
git add -A
git commit -m "Brief 162 fix: email_poller early-return paths set last_activity + defensive cleanup guards"
git push origin main

ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d"
ssh root@108.61.192.52 "docker ps --format 'table {{.Names}}\t{{.Status}}' && curl -s http://localhost:8001/health"
```

Skip Adamus container rebuild: Adamus's `email_poller.main()` exits cleanly at startup because `EMAIL_ADDRESS` is empty and `azure_refresh_token.txt` is absent (the OAuth bootstrap for sophia@wetakeyourjob.com is still pending per `memory/project_open_work.md`). The email_poller never executes on Adamus, so this bug fix has zero functional impact there. The shared `wtyj-agent` image will pick up the new source on Adamus's next natural rebuild — no need to force it for Brief 162.

### Step 7: Live E2E verification

After deploy, replay the Calvin scenario end to end with a new relay token:

1. Send a fresh test email from Gmail (butlerbensonagent@gmail.com) to hello@wetakeyourjob.com with a question that would trigger semi-escalation (e.g. a nut allergy cross-contamination question). Use a clean subject without `[RELAY-` or `[ESCALATION]` markers.
2. Wait ~30 seconds for the poller to process the email.
3. Verify the semi-escalation notification arrives in butlerbensonagent's inbox with `[RELAY-<token>]` subject.
4. Check the VPS log: `ssh root@108.61.192.52 "docker exec wtyj-bluemarlin tail -5 /app/logs/email_poller.log"` — should NOT say "Archived 1 stale threads" immediately after. The relay thread should survive.
5. Reply to the escalation email from the Gmail inbox with an answer.
6. Wait ~30 seconds.
7. Verify the email_poller log shows `RELAY: email relay sent to <customer>` or similar success message (NOT `no pending relay for token — skipping`).
8. Verify a new email arrives in butlerbensonagent's inbox with Marina's reformulated answer (the customer email address IS butlerbensonagent because the test uses the support email as the "customer" — that's fine for verification).

If all 8 steps pass, the fix is verified live.

### Cleanup

Mark the stale pending notification id=64 as `replied` in the state_registry so it doesn't sit forever as a half-completed relay:

```bash
ssh root@108.61.192.52 "docker exec wtyj-bluemarlin python3 -c '
import sqlite3
db = sqlite3.connect(\"/app/data/state_registry.db\")
c = db.cursor()
c.execute(\"UPDATE pending_notifications SET status=? WHERE id=?\", (\"replied\", 64))
db.commit()
print(\"Marked notification id=64 as replied\")
db.close()
'"
```

Also clean up the 4 butlerbensonagent E2E threads from Brief 161 testing if you prefer a clean state file (optional — they will age out naturally in 30 days).

## Tests

Specific must-pass tests from the new file:

- `test_cleanup_skips_thread_with_missing_last_activity` — directly tests the defensive guard (Group A #3)
- `test_cleanup_protects_awaiting_relay_even_if_stale` — directly tests the Calvin scenario guard (Group A #5)
- `test_source_mutating_save_paths_set_last_activity` — count-based regression guard (Group B #8)
- `test_source_semi_escalation_path_sets_last_activity` — proximity check for the Calvin path (Group B, new)
- `test_cleanup_protects_awaiting_relay_with_stale_last_activity` — load-bearing Calvin regression test with stale last_activity (Group C #9)
- `test_cleanup_protects_relay_thread_missing_last_activity` — belt-and-suspenders (Group C #10)

Must-not-regress:

- All 734 existing tests still pass
- `test_stale_48h_thread_resets` in test_stale_thread.py still passes (different function, `_maybe_reset_stale_thread`, unrelated)

## Success Condition

1. All **8** fix sites in `email_poller.py` have `th["last_activity"] = now` (or `customer_th["last_activity"] = now` for fix #3) inserted immediately before their respective `threads[thread_key] = th` / `state["threads"][customer_thread_key] = customer_th` assignment. Verify with `grep -c '\["last_activity"\] = now' wtyj/agents/marina/email_poller.py` — expected count >= 9 (1 pre-existing happy path + 8 new).
2. `_cleanup_stale_data` has the defensive guards: skip-if-hold_created (pre-existing), skip-if-awaiting_relay (new), skip-if-no-last_activity (new).
3. `python3 -m pytest wtyj/tests/ -q` passes cleanly. Baseline is 734 from Brief 161; Brief 162 adds ~10 new tests so the target is 744 passing (small variance OK).
4. Live E2E Calvin scenario replay: semi-escalation thread survives the cleanup call, operator's reply is successfully relayed back to the customer (no `no pending relay for token — skipping` log entry).
5. VPS logs no longer show `Archived 1 stale threads` immediately following a semi-escalation or full-escalation event.
6. Both containers healthy post-deploy (`curl -s http://localhost:8001/health` returns `{"status":"ok"}`).

## Rollback

Single commit. `git revert <commit>` restores the exact previous behavior (threads get archived on next poll, relay replies get dropped — but at least the state file stays small). Redeploy via the standard flow. No data migration, no config change, no infra change.

The more aggressive rollback if the defensive guards cause unexpected behavior (unlikely — they only ADD protection, never remove it): partial revert of just `_cleanup_stale_data` while keeping the 4 `last_activity` assignments. The 4 assignments are the load-bearing fix; the cleanup hardening is defense in depth.
