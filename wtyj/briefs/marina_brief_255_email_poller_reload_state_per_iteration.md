# BRIEF 255 — Email poller reloads email_thread_state.json at top of each poll iteration
**Status:** Draft | **Files:** `wtyj/agents/marina/email_poller.py`, `wtyj/tests/marina/test_162_email_thread_persistence.py` | **Depends on:** Brief 254 | **Blocks:** issue #23 verification, j2-26 retest

## Context

Calvin's live verification of Brief 254 (issue #23) HARD FAILED at 2026-05-11T16:20:09Z. Then j2-26 wipe verified `email_thread_state.json` empty on disk at 16:29:24, but Calvin's clean-slate test at 16:40 HARD FAILED with 4 conversations and persistent Escalation badges — older test threads "reappeared" after the reset.

Investigation (Read-only inspection of the live container's state + source review):
- Container `wtyj-unboks` started 2026-05-11T16:03:50Z, never restarted through any of: Brief 254 deploy, j2-26 wipe, Calvin's tests.
- j2-26 wipe at 16:29:24 verified `email_thread_state.json` content `{"threads": {}, "sender_rates": {}, "message_id_index": {}}` and 9 → 0 threads on disk.
- DB tables stayed wiped (verified at 16:53: `customer_interactions: 1`, `customers: 1`, `pending_notifications: 1`, all the new clean-slate row — DB ops are atomic with disk).
- `email_thread_state.json` at 16:53 had **10 threads back**: all 9 pre-wipe (`subj:calvin@gaimin.io:remember`, `subj:calvinadamus@gmail.com:rude`, `subj:calvin@adamus.com:sun`, etc., 7 of them still with `flags.fully_escalated: true`) plus the new `subj:calvin@gaimin.io:clean slate escalation test`.

Root cause confirmed in source at `wtyj/agents/marina/email_poller.py:430`:

```python
def main():
    ...
    state = load_json(THREAD_STATE_PATH, {"threads": {}, "message_id_index": {}})
    state.setdefault("message_id_index", {})
    ...
    while True:
        try:
            now = time.time()
            ...
            _cleanup_stale_data(state, int(time.time()))
            ...
            for uid in uids:
                ...
                save_json(THREAD_STATE_PATH, state)   # line 506 and others
```

`state` is loaded **once at process start**. The `while True:` loop mutates `state` in memory and writes the full snapshot to disk via `save_json(THREAD_STATE_PATH, state)` at lines 506, 1095, and elsewhere. **Any disk write from outside the poller process is silently overwritten on the next poller save.** External writers that hit this bug today:
- `email_clear_fully_escalated_flag` at `wtyj/shared/state_registry.py:2139` (Brief 254 — runs in the dashboard API process).
- `email_set_archived` / `email_mark_deleted` (Brief 249 — dashboard API process).
- The j2-26 wipe (operator-side `python3 /tmp/w.py` against the live file).

For the j2-26 wipe specifically: at 16:35:17 Calvin's clean-slate inbound triggered the poll iteration. Poller mutated its in-memory `state` (still holding the 9 pre-wipe threads) by adding the new thread, then called `save_json(state)` → wrote 10 threads back to disk, undoing the wipe.

For Brief 254: the helper at `state_registry.py:2161-2188` reads disk, edits flags, atomic-writes back. The poller's `state` never sees the change. Next inbound → `save_json` overwrites the cleared flag with the cached stale `True`.

Brief 254's docstring at `state_registry.py:2196-2199` even hints at this class of bug for the WA path: *"a concurrent message thread that already loaded flags before this call may overwrite the clear via wa_save_booking_state — low severity, see brief."* For the email_poller it is **not** "low severity" — the poller runs a continuous loop with state cached for the process lifetime, so external writes are GUARANTEED to be overwritten, not just at risk.

Out-of-scope confirmation (verified via grep):
- `wtyj/shared/state_registry.py:2811` reads `email_thread_state.json` fresh on every call (`json.load(f)` inside a `with open(...)`). No cache.
- `wtyj/dashboard/api.py` does not read `email_thread_state.json` directly.
- The email_poller is the only process with an in-memory cache. Single fix point.

## Why This Approach

Three options considered:

1. **Reload `state` at the top of each iteration (chosen)** — extra `load_json` per `POLL_INTERVAL` cycle (default 10s). One small JSON read (~few KB for unboks today). Eliminates the divergence at the source: disk is the single truth. ~5-line change.

2. **mtime check before reload** — load only when `os.stat(path).st_mtime` exceeds the last-seen value. Marginal I/O saving. Adds race-condition surface around `.tmp` + `os.replace` atomic writes (mtime is set on rename; in rare cases the rename can be missed by a stat between calls). Same net effect for typical workloads. Over-engineering for the size of `email_thread_state.json` we expect (<1 MB even for very active tenants).

3. **Signal/IPC invalidation from every external writer** — Brief 254's helper, dashboard's archive/delete, wipes, future writers all send a SIGUSR1 or write a sentinel that the poller `os.stat()`s. Brittle: each new writer is a future regression vector. The bug becomes "did the new caller remember to invalidate the cache?" rather than the simpler "disk is truth". Rejected.

Trade-off accepted (option 1): an in-flight iteration's `_cleanup_stale_data` mutations that haven't been `save_json`'d by end-of-iteration are dropped on the next iteration's reload. Acceptable — `_cleanup_stale_data` is idempotent (re-runs every iteration anyway). The cleanup will repeat on the next iteration against fresh disk state.

Other concurrency concern (still present after Brief 255, acknowledged but not addressed here): if the dashboard writes to disk between a poller reload and a poller save in the SAME iteration, the dashboard write loses. With `POLL_INTERVAL=10s` and saves only on inbound, this window is small. A proper fix would require file-locking or compare-and-swap — out of scope for this brief.

## Instructions

1. **Edit `wtyj/agents/marina/email_poller.py`.**

   Keep the existing pre-loop initial load at lines 430-431 (it stays useful for startup-side early-error paths and for the initial `_cleanup_stale_data` if we ever moved it back outside the loop). Add a per-iteration reload INSIDE the `while True:` block, immediately after `now = time.time()` (currently line 439) and BEFORE the IMAP reconnect logic (currently line 442):

   ```python
   while True:
       try:
           now = time.time()

           # Brief 255: reload state from disk each iteration so external
           # writers (Brief 254's email_clear_fully_escalated_flag, dashboard
           # archive/delete endpoints, operator wipes) are respected. Before
           # Brief 255 state was loaded once at process startup and any
           # external disk write was silently overwritten on the next
           # save_json from this loop -- see issue #23 / #26 for the symptom
           # chain (orphan fully_escalated flags resurrected, j2-26 wipe
           # undone within 6 minutes).
           state = load_json(THREAD_STATE_PATH, {"threads": {}, "message_id_index": {}})
           state.setdefault("message_id_index", {})

           # Brief 182: reconnect if needed (first run, error recovery, or token refresh)
           if im is None or ...
   ```

2. **No changes** to `save_json`, `load_json`, `_cleanup_stale_data`, or any of the existing save sites. The reload-at-top pattern is additive; existing behavior is unchanged for code that already runs.

## Tests

Append the following 3 tests to `wtyj/tests/marina/test_162_email_thread_persistence.py` — that's the canonical per-module file for `email_poller.py` (its docstring is *"Tests for Brief 162 — email_poller thread persistence bug"* and it imports `from agents.marina import email_poller`), per Brief 236's per-module-extension rule.

1. **test_brief_255_main_loop_reloads_state_each_iteration (BEHAVIORAL — the regression guard)** — Run `email_poller.main()` with heavy IO mocks for exactly 2 iterations. Setup:
   - `tmp_path / "ets.json"` seeded with `{"threads": {"subj:a@b.com:original": {"flags": {"fully_escalated": True}}}, "message_id_index": {}}`.
   - `monkeypatch.setattr(email_poller, "THREAD_STATE_PATH", str(state_path))`.
   - `monkeypatch.setattr(email_poller, "EMAIL_ADDR", "test@example.com")` and `os.environ["EMAIL_PASSWORD"] = "x"` (so the email-disabled early-return at line 416 does not fire).
   - `monkeypatch.setattr(email_poller, "imap_connect", lambda: fake_im)` where `fake_im` is a `MagicMock` with `uid.return_value = ("OK", [None])` (no UNSEEN), `select.return_value = None`, `noop.return_value = ("OK", None)`, `logout.return_value = None`.
   - Capture per-iteration in-memory state: `monkeypatch.setattr(email_poller, "_cleanup_stale_data", lambda state, now: captured.append(json.dumps(state.get("threads", {}), sort_keys=True)))`.
   - Between iteration 1 and iteration 2: external writer overwrites the file with `{"threads": {}, "message_id_index": {}}` — simulate by triggering this write inside the captured-state hook when `len(captured) == 1`.
   - Break out of the loop on the 2nd `time.sleep` call by raising a custom sentinel exception `_StopLoop`; `try/except _StopLoop` around `main()`.
   - Assert: `"subj:a@b.com:original" in captured[0]` (iteration 1 saw the seeded state) AND `captured[1] == "{}"` (iteration 2 reloaded the externally-emptied disk state, NOT the cached prior state).
   - **Regression guard semantics**: if a future commit deletes the in-loop `state = load_json(...)` line, iteration 2's captured state still contains `"subj:a@b.com:original"` (cached) and the test FAILS. This is the test the brief-reviewer asked for.

2. **test_brief_255_load_json_returns_default_when_file_missing** — pass a path that does not exist. `email_poller.load_json(path, default)` returns the default `{"threads": {}, "message_id_index": {}}` without raising. Regression guard against the per-iteration reload introducing a new failure mode if the file is deleted between iterations (e.g., mid-operator-wipe).

3. **test_brief_255_load_json_returns_default_when_file_corrupt** — write malformed JSON (`"{not valid"`) to a tmp file. `email_poller.load_json(path, default)` returns the default without raising. Confirms the `except: return default` branch in `load_json` (`email_poller.py:120`) is the safety net for any transient mid-write state in which the reload could otherwise crash the poller.

Test file imports the existing module (`from agents.marina import email_poller` is already in the file at the top). MagicMock available via `from unittest.mock import MagicMock`.

## Success Condition

After Brief 255 source commit + push + canary + production deploy + `wtyj-unboks` container restart + re-execution of the j2-26 wipe script:
- `email_thread_state.json` stays empty (`threads: 0`) for at least 60s of continuous polling with zero inbound emails.
- Calvin sends a fresh clean-slate test email → exactly **1 thread** appears in `email_thread_state.json`, NOT 10.
- Dashboard Email channel shows exactly 1 conversation (the new clean-slate test), no orphan Escalation badges on it (because no prior `fully_escalated:true` flag exists in disk state).
- Brief 254's `email_clear_fully_escalated_flag` cleanup, run on a future delete/resolve, now persists across poller iterations.

## Rollback

Canonical rollback path per `wtyj/briefs/infra.md:188` — retags `wtyj-agent:previous` → `wtyj-agent:latest` and restarts all four production containers (BlueMarlin, Adamus, Consulta Despertares, unboks), all of which share the `wtyj-agent` image:

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

If the rollback target image (`:previous`) is itself problematic, fall back to a git revert + re-deploy:

```
git revert <Brief 255 source SHA>
git push origin main
# CI pipeline picks up the revert, runs canary, deploys to production
```

Pure additive code change. No schema migration. No data destruction. Revert restores the prior (load-once) behavior; the known orphan-flag bug returns until the next code-side fix.
