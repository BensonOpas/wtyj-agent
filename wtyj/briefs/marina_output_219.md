# OUTPUT 219 — Marina actually USES the approved learnings

## What was done

New helper `state_registry.get_approved_learnings_for_prompt(channel, limit=20)` returns approved + ai-may-use-True escalation_learnings rows for a given channel, newest first, capped at 20. New helper `marina_agent._build_approved_answers_block(channel)` reads the helper output and renders an "APPROVED ANSWERS (operator-curated knowledge):" prompt block with `Q: ... A: ...` pairs. The block is gated by `client.json::features.approved_learnings_in_prompt` (default false) and returns `""` when the flag is off OR no rows match — when non-empty, it returns with leading `\n\n` so the f-string injection in `_build_system_prompt` produces clean blank-line separation, and when empty the f-string adjacent spacing collapses to identical pre-Brief-219 output. Injection point in `_build_system_prompt`: immediately after `{_customer_file_block}` (sits in the factual-context zone, not the voice/style zone). Tests cover the helper (channel/status/ai_may_use/limit) and the prompt assembly (flag off omits block; flag on with entries includes block in correct position).

## Tests

1016 passing / 0 failures (1010 baseline + 6 new).

## Unexpected findings

Round-1 test fail caught two issues. (1) The `sys.path.insert` pattern from `social/` test files violates the marina-side `test_066_project_structure::test_no_sys_path_insert_in_tests` rule that enforces marina tests rely on `wtyj/tests/conftest.py` for sys.path setup. Removed the import and used the existing module path directly. (2) The shared SQLite has pre-existing escalation_learnings rows from other tests (test_215, test_217), so `get_approved_learnings_for_prompt("whatsapp")` returned multiple rows in tests that wiped only `219_*`-prefixed conversations. Fix: helper-level tests (1-4) now use synthetic channel `test_219_chan` so the channel filter excludes everything else; integration tests (5-6) use `whatsapp` because the prompt branches by channel and they only need substring presence/absence checks on their own seeded sentinel answers.

## Deployment

Pending — commit/push/deploy in step 16.
