# OUTPUT 245 — Phase 1a Unboks QA/customer simulator

## What was done

Shipped Phase 1a of the unboks QA/customer simulator per issue #9 — a safe tooling foundation that loads a library of realistic customer scenarios, validates them in dry-run mode, and emits console + JSON + markdown reports. **Zero production code touched.** Per Benson decision 2026-05-10, scope reduced from "50 scenarios" (issue #9 spec) to "10 seed scenarios" because Phase 2 (live-exec verifier) doesn't exist yet — writing 50 scenarios now risks rot if the verifier API changes their expected-shape. Phase 1b (Brief 246+) expands to the full 50 once Phase 2 design is firmer. Per-step shipped:

1. **`tools/unboks-qa/scenarios.json`** (NEW, 215 lines) — exactly 10 well-formed seed scenarios spanning all 6 categories (2 booking + 2 FAQ + 2 escalation + 1 reply_thread + 1 dashboard_action + 2 edge_case including 1 Spanish multilingual). Every message starts with the literal `[QA TEST]` prefix; every `expected.mustNotContain` includes both Brief 244 identity rules (`butlerbensonagent@gmail.com` + `—`).
2. **`tools/unboks-qa/run_qa.py`** (NEW, 285 lines) — Python 3 stdlib-only argparse runner with 4 modes: default (dry-run + reports), `--filter <category|testId>`, `--validate-only`, `--live` (placeholder, exits code 2 with "Phase 2 only" message). Structurally decoupled from `wtyj/agents/` and `wtyj/dashboard/` — no imports → cannot trigger production behavior even by accident.
3. **`tools/unboks-qa/README.md`** (NEW, 137 lines) — operator-facing usage doc covering safety rules, the 4 CLI flags, exit codes, scenario-shape spec for adding new ones, Phase 1b roadmap (expand to 50), Phase 2 roadmap (live-injection endpoint, Marina mock harness, dashboard verifier, cleanup mode).
4. **`.gitignore`** — appended `tools/unboks-qa/reports/` so per-run report directories stay local.
5. **`wtyj/tests/tools/test_unboks_qa.py`** (NEW, 5 tests) — scenarios.json shape (10 entries), `[QA TEST]` prefix on every message, identity rules in every `mustNotContain`, real-CLI subprocess invocation produces report dir + parses results.json + asserts "Phase 1a" in summary.md, `--validate-only` flag exits 0 + does NOT create report dir.

**Brief-reviewer:** PASS round 1 zero issues. Reviewer verified all `path:line` anchors (`tools/unboks-cli/tasks.py:1-30`, `wtyj/tests/marina/live_test_harness.py:1-50`, `clients/unboks/config/client.json:9-15` languages list), confirmed scope discipline (10 seed vs 50; data-file tests vs source-string greppers), confirmed no Rule 1-5 violations (no second Claude call, no Python NLU, no static reply strings, no hardcoded business values, no production code touched).

**Sanity-tested end-to-end:** ran `python3 tools/unboks-qa/run_qa.py` from repo root before regression — wrote `reports/2026-05-10T09-39-36Z/{summary.md,results.json,failed.txt}`, console output matched expected format, exit code 0. Cleaned up the smoke-test report dir before commit.

## Tests

1055 passing / 0 failures (1050 baseline + 5 new = 1055). New test file `wtyj/tests/tools/test_unboks_qa.py` runs 5/5.

## Deployment

This brief is purely tooling — no production code touched. CI deploy will still run on push (per pipeline) but the deploy is functionally a no-op for the production containers (the new files live under `tools/` which is not built into the container image). All 4 containers expected to remain healthy. Brief 238 tenant guard / Brief 239 rich body / Brief 240 Zernio route / Brief 241 dispatcher / Brief 242 confirm endpoint / Brief 243 deep-link buttons / Brief 244 identity-leak fixes all preserved (none of those code paths touched).

## Out-of-scope (deferred per brief Step 6)

- **Phase 1b — expand `scenarios.json` to 50 scenarios** per issue #9's category breakdown (15 booking / 10 FAQ / 10 escalation / 5 reply-thread / 5 dashboard / 5 edge case). No runner changes needed; Phase 1a's runner already handles arbitrary scenario counts.
- **Phase 2 blockers documented in README.md:**
  - Live message-injection endpoint (does not exist as of Brief 245).
  - Mock harness for `marina_agent.process_message` so reply assertions can run without contacting customers.
  - Dashboard action verifier (no programmatic way today to assert "archive button worked").
  - Cleanup mode implementation (deletes `[QA TEST]` conversations from state_registry).
- TypeScript port for frontend integration (zero TS in repo today; would add toolchain weight for one tool).
- Multi-tenant scenarios (this brief is unboks-only per issue #9).
