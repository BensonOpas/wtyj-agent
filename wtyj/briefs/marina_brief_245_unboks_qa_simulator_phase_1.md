# BRIEF 245 — Phase 1a Unboks QA/customer simulator (foundation + 10 seed scenarios + dry-run runner)

**Status:** Draft | **Files:** tools/unboks-qa/scenarios.json (NEW), tools/unboks-qa/run_qa.py (NEW), tools/unboks-qa/README.md (NEW), wtyj/tests/tools/test_unboks_qa.py (NEW), .gitignore (modified) | **Depends on:** Brief 244 (`a7cef3b`) | **Blocks:** Brief 246+ (Phase 1b — expand to 50 scenarios), Phase 2 live-injection tool

## Context

Issue #9 (Calvin/Jr2 request) — **Phase 1a foundation** of a realistic QA/customer simulator for the unboks tenant. Phase 1a ships the runner + reports + README + 10 seed scenarios spanning all 6 categories; Brief 246+ expands the scenario library to the full 50 once the runner shape is verified working. **Per Benson 2026-05-10:** scenario authoring deferred to a follow-up brief because Phase 2 (live-execution verifier) doesn't exist yet — writing 50 scenarios in dry-run mode now risks scenario rot if the verifier API changes their required shape. Goal: a safe tooling foundation that loads a library of realistic customer scenarios, runs them in dry-run mode (no real customer contact, no production-data mutation), and emits console + JSON + markdown reports identifying which acceptance checks pass / fail / are pending Phase 2 live execution.

Phase 1 explicitly does NOT solve the live-injection problem. Per issue text: "If no safe message-injection endpoint exists, the runner should: stay in dry-run, generate reports based on expected checks, include TODOs for Phase 2 live/dev/staging execution, clearly report the missing endpoint or missing mock harness."

**Why this brief now:** Briefs 238-244 shipped 7 production behavior changes against the unboks tenant in 24 hours (tenant guard, alert quality, Zernio route, appointment dispatcher, operator confirm endpoint, dashboard deep-links, identity-leak fixes). Each change was tested at the unit/integration boundary, but there's no scenario-based regression check that walks the live unboks customer flows end-to-end. A dry-run scenario library is the foundation for Phase 2's eventual live exec without re-deriving "what should we test?" from scratch each time.

**Repo convention check:** Python is the existing language (Python 3.12 on VPS, Python 3.14 on Mac; all `wtyj/scripts/*.py`, `tools/unboks-cli/tasks.py`, all test modules are Python). Issue text says "If repo conventions prefer Python instead of TypeScript, choose the existing repo convention and report why." — choosing Python.

**Existing patterns to mirror (verified read-only):**
- `tools/unboks-cli/tasks.py:1-30` — argparse-based CLI structure with token caching, foreground-only commands. Same pattern for `run_qa.py` (no auth needed for dry-run).
- `wtyj/tests/marina/live_test_harness.py:1-50` — older BlueMarlin live-test harness using IMAP injection. Cousin pattern but BlueMarlin-only, no scenario library, no dry-run mode. Not a duplicate of this brief; reference for shape only.

## Why This Approach

**Considered:** Building a full live-execution harness in Phase 1 (scenarios + injector + verifier + cleanup, all in one). **Rejected:** issue #9 explicitly scopes Phase 1 to foundation + dry-run + reports. Live injection requires a safe message-injection endpoint that doesn't currently exist (would have to be either a real WhatsApp/email send to a QA mailbox, OR a new dashboard endpoint that simulates an inbound webhook). Both are Phase 2 work. Building them now would balloon scope and risk shipping a tool that contacts real customers.

**Considered:** Shipping all 50 scenarios in this brief per issue #9's "minimum initial pack" ask. **Rejected per Benson 2026-05-10:** Phase 2 (live-exec verifier) doesn't exist yet, so the 50 scenarios would sit dormant for the period between Phase 1 and Phase 2 shipping. Authoring them now risks rot — when Phase 2's verifier API solidifies, the expected-fields shape may change and 40+ scenarios need rewriting. **Phase 1a ships 10 seed scenarios** spanning all 6 categories (proves the runner + report shape works end-to-end with realistic data); **Brief 246+ (Phase 1b)** expands to the full 50 once Phase 2's verifier shape is firmer. Same total deliverable; smaller upfront sunk-cost on dormant assets.

**Considered:** TypeScript runner per the issue's example. **Rejected:** repo has zero TypeScript today (frontend lives in a separate repo `unboks-org/unboks-dashboard-api`); adding a TS toolchain (tsc, package.json, node_modules) for one tool is heavy. Python keeps the tool runnable from the same venv operators already use for `tasks.py`.

**Considered:** Putting the tool under `wtyj/scripts/` like `e2e_canary_test.sh`. **Rejected:** `wtyj/scripts/` is shell scripts for deployment plumbing; the QA simulator is a multi-file Python tool with its own scenario library and report directory. `tools/unboks-qa/` matches the precedent set by `tools/unboks-cli/` for CLI utilities and `tools/control-panel/` for the dashboard bundle.

**Tradeoff — scenario file format JSON vs YAML:** issue example shows JSON. Picked JSON. Pro: no extra dependency (PyYAML not in stdlib). Con: harder to write multi-line messy customer messages with embedded quotes. Acceptable; we'll use JSON's `\n` for line breaks. If scenarios become unwieldy later, a future brief migrates to YAML.

**Tradeoff — dry-run "verifier" depth:** in Phase 1 the verifier doesn't actually call Marina or hit any production endpoint. It loads the scenario, validates its shape, checks structural rules (every customer message starts with `[QA TEST]`, every customer-facing-reply scenario has identity rules in `expected.mustNotContain`), and records the scenario as either `PASS_DRYRUN` (passes structural checks) or `FAIL_DRYRUN` (structural check failed) or `PENDING_PHASE_2` (live execution required). This is honest scope: the Phase-1 runner verifies the SCENARIO LIBRARY is well-formed; Phase 2 verifies the SYSTEM matches scenario expectations.

## Instructions

### Step 1 — Create the scenario library

Create `tools/unboks-qa/scenarios.json` with **exactly 10 seed scenarios**, one or two from each category to validate the runner end-to-end (Brief 246+ Phase 1b expands to the full 50):
- 2 appointment/booking
- 2 FAQ/repetitive questions
- 2 complaints/escalations
- 1 reply/threading test
- 1 dashboard action test
- 2 edge cases (1 multilingual + 1 spam/irrelevant)

**Required JSON shape per scenario** (based on issue #9 example):

```json
{
  "testId": "EMAIL-BOOKING-001",
  "category": "booking",
  "channel": "email",
  "persona": "confused_customer",
  "senderEmail": "calvinadamus@gmail.com",
  "messages": [
    "[QA TEST] Hi, I want to make an appointment tomorrow. Can you help?"
  ],
  "expected": {
    "shouldEscalate": false,
    "shouldAskClarifyingQuestion": true,
    "shouldCreateAppointment": false,
    "mustNotContain": [
      "butlerbensonagent@gmail.com",
      "—"
    ]
  },
  "phase2Notes": "Requires live message injection to verify Marina's clarifying question shape."
}
```

**Field constraints (enforced by the runner — Step 2):**
- `testId`: unique string, ALL CAPS, dash-separated, format `<CHANNEL>-<CATEGORY>-<NNN>`.
- `category`: one of `booking`, `faq`, `escalation`, `reply_thread`, `dashboard_action`, `edge_case`.
- `channel`: one of `email`, `whatsapp`, `instagram`, `facebook`, `messenger`. (No `telegram` — not implemented.)
- `persona`: free-text label (`confused_customer`, `angry_customer`, `regular_repeat_customer`, etc.) — used for human reading; not enforced.
- `senderEmail`: required when `channel == "email"`. Default for unboks QA: `calvinadamus@gmail.com`. Other channels can omit.
- `messages`: array of 1+ strings; **EVERY string MUST start with the literal prefix `[QA TEST]`** so a leak into production is unambiguously identifiable.
- `expected`: object with at least one of: `shouldEscalate` (bool), `shouldCreateAppointment` (bool), `shouldAskClarifyingQuestion` (bool), `shouldRefuse` (bool), `shouldRedirect` (bool), `mustNotContain` (array of strings), `mustContain` (array of strings).
- `expected.mustNotContain` MUST include both `"butlerbensonagent@gmail.com"` and `"—"` (em-dash) for any scenario whose channel produces a customer-facing reply (i.e. ALL channels — these are the identity rules from Brief 244 + issue #9).
- `phase2Notes`: optional string explaining what live execution would need to verify (recorded in reports as TODOs).

**Scenario writing guidelines for the 10 seed scenarios:**
- Realistic, messy, human-sounding text (not robotic / not over-polite). Include typos, lowercase starts, sentence fragments where natural.
- Multilingual edge case: 1 scenario in Spanish OR Dutch (per `clients/unboks/config/client.json:9-15` languages list) — proves Marina's multilingual handling.
- Booking: 1 happy-path booking request + 1 missing-info booking request.
- FAQ: 1 pricing question + 1 opening-hours question.
- Escalation: 1 angry complaint + 1 explicit-human-request.
- Reply-thread: 1 customer reply inside an existing email thread.
- Dashboard action: 1 scenario whose expectation references operator dashboard work (archive/delete) — this is mostly Phase-2 territory but the seed scenario documents the expected shape.
- Edge cases: 1 spam/irrelevant message + 1 multilingual.

Each scenario writes inline at execution time — total file ~150-200 lines of JSON for 10 scenarios.

### Step 2 — Create the runner

Create `tools/unboks-qa/run_qa.py` with the following surface:

```
Usage:
    run_qa.py                       # dry-run all scenarios, write reports
    run_qa.py --filter <category>   # dry-run scenarios in one category
    run_qa.py --filter <testId>     # dry-run a single scenario by id
    run_qa.py --validate-only       # only validate scenario JSON shape; no report
    run_qa.py --live                # NOT IMPLEMENTED in Phase 1; runner exits non-zero with "Phase 2 only" message
```

**Default behavior (no flags):**
1. Load `tools/unboks-qa/scenarios.json`. Validate the JSON parses.
2. For each scenario, run structural validation (Step 1 field constraints). Each scenario gets a status:
   - `PASS_DRYRUN` — structural validation passed; identity-rule checks present where required.
   - `FAIL_DRYRUN` — structural validation failed (missing required field, bad category, message missing `[QA TEST]` prefix, etc.). Records a `failureReason` string.
   - `PENDING_PHASE_2` — every PASS_DRYRUN scenario is ALSO marked PENDING for the live-exec checks (`shouldEscalate`, `shouldCreateAppointment`, etc.). The dry-run runner can't verify these; reports them as Phase-2 TODOs.
3. Write reports to `tools/unboks-qa/reports/<UTC_ISO_TIMESTAMP>/` (e.g. `reports/2026-05-10T14-22-08Z/`):
   - `summary.md` — markdown report per issue #9 format.
   - `results.json` — full JSON dump (every scenario + status + failureReason + phase2TODOs).
   - `failed.txt` — one line per failed scenario (testId + failureReason). Empty file if none.
4. Print console summary: total / passed / failed / pending-phase-2 counts + "report written to: <path>" line.
5. Exit code 0 if no FAIL_DRYRUN; exit code 1 if any FAIL_DRYRUN.

**`--filter` flag:** matches against `category` first; if no category match, falls back to `testId` exact match.

**`--validate-only` flag:** runs structural validation only, prints any FAIL_DRYRUN scenarios to stderr, exits 0/1. No report directory created.

**`--live` flag:** prints
```
Phase 2 not implemented yet. Live execution requires a safe
message-injection endpoint that does not exist as of Brief 245.
Re-run without --live for dry-run mode.
```
and exits with code 2 (distinct from validation failure).

**Markdown report template (matches issue #9 format):**

```markdown
# Unboks QA Agent Report

Date: <UTC ISO timestamp>
Environment: dry-run (Phase 1 — no live execution)
Tenant: unboks
QA customer email: calvinadamus@gmail.com
Total tests: <N>
Passed (dry-run structural): <N>
Failed (dry-run structural): <N>
Pending Phase 2 (live exec needed): <N>

Critical failures: <count of FAIL_DRYRUN with category in [escalation, dashboard_action]>
High failures: <count of FAIL_DRYRUN with category in [booking, reply_thread]>
Medium failures: <count of FAIL_DRYRUN with category == faq>
Low failures: <count of FAIL_DRYRUN with category == edge_case>

## Critical Failures
<for each FAIL_DRYRUN: testId / category / failureReason / "see results.json for full scenario">

## Pending Phase 2 (live execution required)
<aggregated list of phase2Notes across all PASS_DRYRUN scenarios — what Phase 2's runner needs to verify>

## Passed Areas (dry-run structural)
- inbox: <N scenarios>
- escalation: <N scenarios>
- appointment: <N scenarios>
- reply: <N scenarios>
- archive/delete/learning: <N scenarios>
- Marina identity rules: <count of scenarios with mustNotContain identity checks>

## Phase 2 missing infrastructure
- Live message-injection endpoint (does not exist as of Brief 245).
- Mock harness for Marina.process_message that records expected vs actual reply.
- Dashboard action verifier (currently no programmatic way to assert "archive button worked").
```

**Implementation constraints:**
- Pure Python 3.12 stdlib (no new dependencies). `argparse` + `json` + `pathlib` + `datetime` only.
- No imports from `wtyj/agents/` or `wtyj/dashboard/` — runner stays decoupled from production code. (This rule means the runner can't accidentally trigger production behavior; honesty about Phase 1 scope.)
- Single file, ~250-350 lines of Python. Keep functions ≤ 30 lines each.

### Step 3 — Create the README

Create `tools/unboks-qa/README.md` covering:

- **What this tool does:** loads scenarios, runs dry-run validation, generates reports.
- **What it does NOT do (yet):** live message injection, real production checks, cleanup.
- **Usage:**
  - `python3 tools/unboks-qa/run_qa.py` — full dry-run with reports.
  - `python3 tools/unboks-qa/run_qa.py --filter booking` — single category.
  - `python3 tools/unboks-qa/run_qa.py --validate-only` — JSON shape check only.
- **Safety flags / rules:**
  - Default is dry-run. No real customers contacted.
  - All scenario messages prefixed `[QA TEST]` so any accidental production leak is identifiable.
  - `--live` flag is a placeholder; Phase 2 only.
- **Where reports go:** `tools/unboks-qa/reports/<timestamp>/`. Add to `.gitignore` if not already covered.
- **How to add a new scenario:** append to `scenarios.json` following the schema in Step 1; run `--validate-only` to confirm structural validity.
- **Phase 1b roadmap:**
  - Expand `scenarios.json` from 10 seed scenarios to the full 50 per issue #9's category breakdown (15 booking / 10 FAQ / 10 escalation / 5 reply-thread / 5 dashboard / 5 edge case).
  - No runner changes needed; Phase 1a's runner already handles arbitrary scenario counts.
- **Phase 2 roadmap (placeholder):**
  - Add safe message-injection endpoint to dashboard backend (e.g., `POST /dashboard/api/qa/inject` with auth + rate limit + `[QA TEST]` enforcement).
  - Build mock harness for `marina_agent.process_message` invocation.
  - Implement dashboard action verifier (probably via existing dashboard API).
  - Cleanup mode: removes QA conversations from DB after runs.
- **How cleanup mode will work later (Phase 2):**
  - Cleanup mode would delete every conversation in `state_registry` whose latest message starts with `[QA TEST]`.
  - Triggered explicitly via `--cleanup` flag (never automatic).

### Step 4 — Add `tools/unboks-qa/reports/` to `.gitignore`

Append to the existing root `.gitignore` (verify it exists first):

```
# tools/unboks-qa: ephemeral run reports (regenerated each run)
tools/unboks-qa/reports/
```

### Step 5 — Add tests

Create `wtyj/tests/tools/test_unboks_qa.py` with **5 tests**:

1. **`test_scenarios_json_loads_and_has_10_entries`** — opens `tools/unboks-qa/scenarios.json`, parses JSON, asserts list of 10 entries (Brief 246+ Phase 1b expands; this assertion bumps then).
2. **`test_every_scenario_has_qa_test_prefix_in_messages`** — iterates all scenarios, asserts every message starts with `[QA TEST]`.
3. **`test_every_scenario_has_identity_rules_in_must_not_contain`** — iterates all scenarios, asserts each `expected.mustNotContain` includes both `"butlerbensonagent@gmail.com"` and `"—"` (the Brief 244 identity rules).
4. **`test_runner_dry_run_produces_reports`** — invokes `python3 tools/unboks-qa/run_qa.py` via `subprocess.run`, asserts exit code 0, asserts `reports/<latest>/summary.md` and `results.json` exist and parse correctly.
5. **`test_runner_validate_only_passes_for_well_formed_scenarios`** — invokes `python3 tools/unboks-qa/run_qa.py --validate-only`, asserts exit code 0.

Test file location: `wtyj/tests/tools/test_unboks_qa.py`. Create the `tools/` subdirectory if it doesn't exist (it doesn't — verified via `ls wtyj/tests/`). Add `__init__.py` if the rest of `wtyj/tests/` uses them — verified: existing subdirs (`marina/`, `social/`, `shared/`) all have or are usable without `__init__.py` because pytest auto-discovers. Skip `__init__.py`.

**Test-shape notes:**
- Tests #1-#3 read the scenario file directly — these are NOT source-string-grepper tautologies because the file is *data* (the unit under test) not source code. Asserting "the data is well-formed" is the correct test shape for a data file.
- Test #4 invokes the runner as a subprocess (no module import) — exercises the real CLI surface, real argparse, real report writing.
- Test #5 same shape with the `--validate-only` flag.

After test write, run `python3 -m pytest wtyj/tests/tools/test_unboks_qa.py -q` to confirm all 5 pass.

### Step 6 — Out of scope (documented for future briefs)

- Live message-injection endpoint.
- Marina mock harness for offline reply verification.
- Dashboard action verifier (archive/delete/learning approval programmatic checks).
- Cleanup mode implementation.
- Multi-tenant scenarios (this brief is unboks-only per issue #9).
- TypeScript port for frontend integration.
- Continuous QA cron / nightly run — Phase 2 only.

## Tests

5 new tests in `wtyj/tests/tools/test_unboks_qa.py` (NEW FILE).

Expected after-test count: **1055 passing / 0 failures** (1050 baseline + 5 new = 1055).

## Success Condition

After this brief lands:
1. `tools/unboks-qa/scenarios.json` exists with exactly 10 well-formed seed scenarios spanning all 6 categories per Step 1 (Brief 246+ expands to 50).
2. `tools/unboks-qa/run_qa.py` is executable (chmod +x or just `python3` invocation) and supports the 4 flags (default, `--filter`, `--validate-only`, `--live`).
3. Running `python3 tools/unboks-qa/run_qa.py` writes a report directory containing `summary.md` + `results.json` + `failed.txt` and exits 0 (assuming all 50 scenarios pass structural validation).
4. Running `python3 tools/unboks-qa/run_qa.py --live` exits with code 2 and the "Phase 2 only" message.
5. README documents usage, safety, and Phase 2 roadmap.
6. `tools/unboks-qa/reports/` is gitignored.
7. 5 new tests pass; full regression at 1055.
8. No production code touched. Briefs 238-244 production behavior preserved.

## Rollback

Revert the brief commit:
```
git revert <brief-245-commit-sha>
git push origin main
```

This removes the `tools/unboks-qa/` directory and the test file. CI re-deploys identical production behavior. No data migration needed (no production code touched). Any reports generated locally before rollback can be deleted manually (`rm -rf tools/unboks-qa/reports/`).
