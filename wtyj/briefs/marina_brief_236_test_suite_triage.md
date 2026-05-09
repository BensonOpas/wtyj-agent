# BRIEF 236 — Test Suite Triage

**Status:** Draft | **Files:** 5 whole-file deletions, ~17 surgical edits, 1 brief.md update | **Depends on:** none | **Blocks:** future test suite consolidation work (per-module merge)

## Context

Audit ran in this session: 1100 tests across 140 files (avg 7.9/file), suite runs in 37s. Key findings:

- **~25% of sampled tests are tautologies** — `assert "literal" in open(<source>).read()` style. They violate the explicit ban in CLAUDE.md Rule (line 41) and `.claude/commands/brief.md` line 38. They cannot fail unless someone deletes the literal string they grep for; they catch zero behavioral regressions.
- **5 zombie script files** (test_033, 034, 037, 038, 039) — pytest collects 0 tests from each but runs their module-level `assert` statements at collection time. Dead weight.
- **The "test 333 repeated every time" pattern** — every brief gets its own `test_NNN_*.py` file even when touching code paths already covered by 20+ files. 22 files exercise `_build_system_prompt`, 27 exercise `email_poller`. Each new file re-stamps the same 7 `os.environ.setdefault` lines + `_login()` / `_auth()` / `_wipe_NNN()` helpers.
- **Why nothing ever fails:** Brief 235's bug (status='pending' vs 'sent') survived 8 days in production with green tests because the Brief 227 tests inserted with `status='pending'` and queried with the `'pending'` filter — test setup and bug agreed on the wrong shape. Tests don't reproduce production data shape.

This brief is *narrow triage*: delete the obvious tautologies, kill the zombie scripts, freeze the per-brief growth pattern. Per-module consolidation (merging 27 email_poller files into 1) is **out of scope** — that's multi-session work and risky.

## Why This Approach

**Considered:** "delete all tests" (Benson floated this) — rejected. The ~60% REAL bucket (no-mock TestClient round-trips like test_192, 207, 222, 223, 233) catches my mistakes during brief execution before commit. That's real value at AI-coding-velocity; deleting it trades the safety net for slightly faster briefs.

**Considered:** ambitious per-module consolidation in this brief — rejected. Merging 27 email_poller test files into one is a high-risk operation across ~150 tests. Sloppy merges quietly drop coverage. Wrong move for one brief.

**Chose:** surgical triage. Delete tests that are objectively broken (source-string guards, zombies). Add a process rule that stops new tautology growth. Defer consolidation. Tradeoff: temporary inconsistency (some old per-brief files survive even though new convention says don't make them) — acceptable because the new convention only governs *new* code.

## Instructions

### Part A — Whole-file deletions (5 files)

Delete these files entirely. Every test in each is a source-string guard, directory-existence check, or YAML-string greppe — all banned by the test philosophy rule.

1. **`wtyj/tests/marina/test_066_project_structure.py`** — 11 tests, all `assert os.path.isdir(...)` or `assert "X" in open(<source>).read()`. Includes the `test_no_sys_path_insert_in_tests` guard (lines 71-81): also a source grepper. The convention belongs in `.claude/commands/brief.md`, not as a runtime test. Two import smoke tests (`test_imports_from_agents_marina`, `test_imports_from_shared`) are redundant with pytest collection itself — if those modules don't import, the whole suite breaks at collection time, so the explicit tests add nothing.
2. **`wtyj/tests/marina/test_148_dockerignore_directory_mount.py`** — 14 tests, all `assert "<line>" in dockerignore` or `assert "<line>" in docker-compose.yml`. The behavior these guard (correct Docker setup) is verified by deploys, not by string-greps.
3. **`wtyj/tests/marina/test_150_bluemarlin_deployment_layout.py`** — 17 tests, all path-existence + JSON-value + YAML-string greppers from the Brief 150 rebrand. Rebrand is permanent; if someone re-introduces "BlueFinn" references they'll do so deliberately and a string guard won't stop them.
4. **`wtyj/tests/marina/test_151_source_rename.py`** — 6 tests, all Dockerfile/dockerignore string greppers from the wtyj/ rename. Rename is final.
5. **`wtyj/tests/marina/test_152_image_and_container_names.py`** — 7 tests, all docker-compose.yml string greppers verifying image/container names. The names are correct; production deploys would fail visibly if they weren't.

Total tests removed by Part A: 11 + 14 + 17 + 6 + 7 = **55 tests**.

### Part B — Zombie script files (5 files)

These files have **0 pytest functions** but run module-level `assert` and `print` statements at collection time. They're old script-style files from before the project standardized on pytest functions. Delete entirely:

6. **`wtyj/tests/marina/test_033_thread_key.py`** — 0 functions, module-level asserts.
7. **`wtyj/tests/marina/test_034_verify_items.py`** — 0 functions.
8. **`wtyj/tests/marina/test_037_extended_stress.py`** — 0 functions.
9. **`wtyj/tests/marina/test_038_prompt_fixes.py`** — 0 functions, includes a "Last modified: Brief" header grep at module load.
10. **`wtyj/tests/marina/test_039_capacity_soft_holds.py`** — 0 functions.

Verify count via `grep -c "^def test_\|^class Test" <file>` before deleting (must return 0 for each).

Total tests removed by Part B: 0 (they didn't contribute any). Removes collection overhead and ~5 ghost imports.

### Part C — Surgical deletions (specific test functions)

For these files, **keep the file** but delete the listed test functions. Read each file before editing — the line numbers below are guidance, but the executor must locate the exact function definitions and delete from `def test_X` through the end of the function body (and the docstring above if any).

11. **`wtyj/tests/marina/test_035_marina_prompt.py`** — delete `test_file_header_updated` (~lines 44-48), `test_claude_md_no_stale_thread_key_issue` (~lines 51-56), `test_claude_md_no_stale_verify_issue` (~lines 59-64). All grep source files for literals.
12. **`wtyj/tests/marina/test_036_prompt_fixes.py`** — delete `test_file_header_updated` (~lines 47-51).
13. **`wtyj/tests/marina/test_049_fix_format_sheets.py`** — delete `test_old_sheet_id_removed` (~lines 18-22), `test_no_sheets_writer_import` (~lines 90-95), `test_file_header` (~lines 97-102). All read `format_sheets.py` source and grep.
14. **`wtyj/tests/marina/test_050_manifest_foundation.py`** — delete `test_state_registry_header` (~lines 250-256), `test_gws_calendar_header` (~lines 257-263).
15. **`wtyj/tests/marina/test_051_manifest_integration.py`** — delete the email_poller header grep (~lines 145-153) and `test_payment_stub_header` (~lines 155-160). The `_read_email_poller` helper at line 74 may become unused — delete it too if so.
16. **`wtyj/tests/marina/test_052_manifests_sheet_tab.py`** — delete `test_sheets_writer_header` (~lines 27-32), `test_manifests_tab_in_source` (~lines 34-41), `test_manifests_headers_defined` (~lines 43-48), `test_manifests_widths_defined` (~lines 50-55), and any other source-grep tests in the file (the file's pattern continues — verify by reading the whole file). If after deletion the file is empty or only has imports, delete the whole file.
17. **`wtyj/tests/marina/test_147_gws_key_path.py`** — delete `test_old_filename_not_referenced_in_source` (~lines 157-170).
18. **`wtyj/tests/marina/test_149_agent_persona.py`** — delete `test_dashboard_draft_email_uses_structured_persona` (~lines 268-274).
19. **`wtyj/tests/social/test_161_race_ref_multilang.py`** — delete `test_social_agent_uses_new_regex` (~lines 52-58) and `test_email_poller_uses_new_regex` (~lines 61-67). The behavioral regex tests above (test_ref_regex_rejects_all_letters_common_words, test_ref_regex_matches_mixed_letters_and_digit) STAY — they exercise the actual regex at runtime.
20. **`wtyj/tests/marina/test_162_email_thread_persistence.py`** — delete the entire "Group B: source-level structural regression guards" section: `test_source_mutating_save_paths_set_last_activity`, `test_source_semi_escalation_path_sets_last_activity`, `test_source_full_escalation_path_sets_last_activity` (~lines 139-202, including the `_EMAIL_POLLER_PATH` constant and the `# --- Group B: ...` comment block). The "count >= 9" guard and proximity-window checks are the exact pattern this brief bans: they don't fire on a real bug, they fire on refactors that change line counts. The Group A behavioral tests in the same file (testing `_cleanup_stale_data` directly with crafted state) cover the actual escalation-path invariant.
21. **`wtyj/tests/social/test_163_hold_confirmation_wording.py`** — delete the last test function that does `open(src_path).read()` and asserts strings (~lines 235-260, function `test_hold_created_branches_on_payment_timing` or similar — verify the function name when reading).
22. **`wtyj/tests/social/test_165_dashboard_quick_wins.py`** — delete `test_dashboard_delete_endpoint_exists` (~lines 60-69).
23. **`wtyj/tests/social/test_167_phone_display.py`** — delete `test_dashboard_endpoint_source_declaration` (~lines 47-53).
24. **`wtyj/tests/marina/test_168_payment_hold_reaper.py`** — delete `test_supervisord_has_hold_reaper_program` (~lines 165-169).
25. **`wtyj/tests/marina/test_171_email_dashboard.py`** — delete `test_dashboard_api_merges_email_conversations` (~lines 116-122).
26. **`wtyj/tests/marina/test_172_reconnect.py`** — delete `test_dashboard_delete_escalation_endpoint_declared` (~lines 34-41).

Total tests removed by Part C: ~28.

### Part D — Process rule update

Edit **`.claude/commands/brief.md`** at line 34 (the existing **Test philosophy:** paragraph). REPLACE the existing 8-line paragraph (lines 34-41) with this expanded version:

```markdown
**Test philosophy:** tests that check real behavior. Aim for 3-5 on a
focused brief; scale up when the brief genuinely covers multiple
behaviors. If you're going over 10 tests, stop and ask whether this
should be two briefs.

**Test file location:** new tests go into `wtyj/tests/<source-path>/test_<module>.py`
(one file per source module). Create a NEW test file ONLY when adding
a new source module. Briefs touching existing modules must extend the
existing per-module test file. Do NOT create `test_NNN_*.py` files for
every brief — that pattern caused the 1100-test bloat Brief 236 cleaned up.

**Acceptable test shapes:**
- No-mock round-trips (TestClient + real test SQLite)
- Boundary-only mocks (mock external APIs: Anthropic, IMAP, Late, Zernio
  webhook signature) — never mock internal modules
- Assertions on returned data shape or persisted state

**Banned test shapes (will be rejected by reviewers):**
- Source-string greppers: `assert "X" in open(<source_file>).read()`
- Directory/file-existence checks: `assert os.path.isdir(...)`
- File-header guards: `assert "Last modified: Brief" in header`
- Mock-the-thing-you-test: mocking the function under test or its
  same-module collaborators
- "Did the mock get called with what I told it" tests where the
  assertion is implied by the test's own setup

Good test shape: given state X, call function F, assert return value Y.
Mock-based integration tests exercising real branches are fine.
```

Do NOT touch any other line in `.claude/commands/brief.md`.

## Tests

This is a deletion brief — no NEW tests to add. The verification IS the regression suite.

1. **Pre-state baseline confirmation:** before deleting anything, run `python3 -m pytest wtyj/tests/ -q --collect-only 2>&1 | tail -3`. Confirm output reports `1100 tests collected`. If different, STOP and ask — the audit numbers are stale.
2. **Post-deletion regression:** after all deletions, run `python3 -m pytest wtyj/tests/ -q 2>&1 | tail -5`. Expected: `~1019 passed, 0 failures` (1100 baseline − 53 Part A − 28 Part C ≈ 1019). Acceptable range: **990-1030 passing, exactly 0 failures, exactly 0 errors**.
3. **Floor check:** if total drops below 950, we over-cut — re-examine which surgical deletion took out a real test. Do not commit until count is in range.
4. **Ceiling check:** if total stays above 1040, we under-cut — re-examine; some Part C deletions probably didn't land. Do not commit until count is in range.
5. **Source-grepper sweep verification:** after deletions, run `grep -rln 'open(.*\.\(py\|conf\|yml\|yaml\)).*\.read()' wtyj/tests/ --include="*.py"` and confirm output is ≤ 5 files (only test fixtures opening test fixture files, no source-greppers). If output names any of the files this brief deleted from or surgically edited, the deletion didn't land — re-examine.

## Success Condition

After commit + push:
- Test suite reports **990-1030 passed / 0 failures / 0 errors**.
- `wtyj/tests/marina/test_066_project_structure.py`, `test_148_dockerignore_directory_mount.py`, `test_150_bluemarlin_deployment_layout.py`, `test_151_source_rename.py`, `test_152_image_and_container_names.py`, `test_033_thread_key.py`, `test_034_verify_items.py`, `test_037_extended_stress.py`, `test_038_prompt_fixes.py`, `test_039_capacity_soft_holds.py` no longer exist.
- `grep -rn 'open(.*\.\(py\|conf\|yml\|yaml\)).*read()' wtyj/tests/ --include="*.py"` returns ≤ 5 lines (test fixtures only, not source greppers).
- `.claude/commands/brief.md` line 34 starts with the expanded test-philosophy paragraph including "Test file location:" and "Banned test shapes:" subsections.

## Rollback

`git revert <commit-sha>` brings the deleted files back. Tests are not part of the runtime image — no production impact, no deploy needed for rollback. The expanded `brief.md` rule is also reverted by the same revert.

If the deletion accidentally drops a test that was actually catching something, the way you'll find out is via a future regression that would have been caught — at which point we add the missing coverage *to the proper per-module test file*, not by reviving the deleted source-grep file.

## Notes for executor

- **No deploy required.** Tests are excluded from the Docker image (verified via `.dockerignore` excludes `wtyj/tests/`). No container rebuild, no production behavior change. Commit + push is sufficient. Skip the `ssh root@108.61.192.52 ...` deploy step entirely; document this in `marina_output_236.md`.
- **No `marina_explanation_236.md` required for code logic** — there is no source-code change to explain. The code-explainer agent should be invoked normally per workflow (it'll see only test deletions + brief.md edit), but the resulting file will be brief.
- **Read every file before deleting parts of it.** The line ranges in Part C are guidance — the executor must locate the actual `def test_X` boundaries by reading. If a Part C edit removes the last function in a file, leaving only imports/docstring/helpers, **delete the whole file** (note this in the output).
- **Do not delete tests outside the listed set even if they look tautological.** Scope discipline. Anything else gets a future brief.
- **Brief-reviewer and output-reviewer must run** per workflow.
