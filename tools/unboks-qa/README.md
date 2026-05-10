# Unboks QA / customer simulator

**Phase 1a foundation.** Loads a library of realistic customer scenarios for the unboks tenant, validates them in dry-run mode, and emits console + JSON + markdown reports. **Does NOT contact real customers, does NOT mutate production data, does NOT call Marina or any production endpoint.**

Phase 2 (live execution against a safe message-injection endpoint) is a separate brief.

## What this tool does

- Loads `scenarios.json` (10 seed scenarios spanning all 6 categories in Phase 1a; full 50 in Phase 1b).
- Validates each scenario's structural shape: required fields, valid category/channel enums, `[QA TEST]` prefix on every customer message, identity rules in `expected.mustNotContain`.
- Writes reports to `tools/unboks-qa/reports/<UTC ISO timestamp>/`:
  - `summary.md` — operator-facing markdown report.
  - `results.json` — full machine-readable results.
  - `failed.txt` — one line per failed scenario (empty if none).
- Prints a console summary with totals.

## What it does NOT do (yet)

- Live message injection (no QA mailbox sender, no webhook simulator).
- Real Marina invocation (no `marina_agent.process_message` call).
- Dashboard action verification (no programmatic "did the archive button work?" check).
- Cleanup mode (no DB row deletion).

These are Phase 2 scope.

## Usage

From the repo root (`/Users/benson/Projects/bluemarlin-agent` on Mac, `/root` on VPS):

```bash
# Full dry-run with reports
python3 tools/unboks-qa/run_qa.py

# Filter by category
python3 tools/unboks-qa/run_qa.py --filter booking

# Filter by single testId
python3 tools/unboks-qa/run_qa.py --filter EMAIL-BOOKING-001

# JSON shape validation only (no report directory)
python3 tools/unboks-qa/run_qa.py --validate-only

# Live execution placeholder (NOT implemented in Phase 1a)
python3 tools/unboks-qa/run_qa.py --live
```

Exit codes:
- `0` — all scenarios passed structural validation.
- `1` — at least one scenario failed structural validation.
- `2` — `--live` was used (Phase 2 placeholder; not implemented).

## Safety flags / rules

- Default is dry-run. No real customer is contacted by Phase 1a's code.
- Every scenario message starts with the literal `[QA TEST]` prefix so any accidental production leak is immediately identifiable in logs.
- `--live` flag is a placeholder; Phase 2 only. Today it prints a message and exits with code 2.
- The runner imports nothing from `wtyj/agents/` or `wtyj/dashboard/` — it is structurally incapable of triggering production behavior in Phase 1a.

## Where reports go

`tools/unboks-qa/reports/<UTC ISO timestamp>/` (gitignored — regenerated each run).

Each report directory contains three files: `summary.md`, `results.json`, `failed.txt`.

## How to add a new scenario

1. Append a new object to `tools/unboks-qa/scenarios.json` matching the shape:
   ```json
   {
     "testId": "CHANNEL-CATEGORY-NNN",
     "category": "booking|faq|escalation|reply_thread|dashboard_action|edge_case",
     "channel": "email|whatsapp|instagram|facebook|messenger",
     "persona": "free-text label",
     "senderEmail": "calvinadamus@gmail.com",
     "messages": ["[QA TEST] message text..."],
     "expected": {
       "shouldEscalate": false,
       "mustNotContain": ["butlerbensonagent@gmail.com", "—"]
     },
     "phase2Notes": "what live execution would verify"
   }
   ```
2. Every message string MUST start with `[QA TEST]`.
3. Every scenario MUST include both identity rules in `expected.mustNotContain`: `butlerbensonagent@gmail.com` (Brief 244 internal sender leak) and `—` (Brief 244 em-dash ban).
4. Run `python3 tools/unboks-qa/run_qa.py --validate-only` to confirm structural validity.

## Phase 1b roadmap

Brief 246+ (Phase 1b) expands `scenarios.json` from the 10 seed scenarios to the full 50 per issue #9's category breakdown:

- 15 appointment/booking
- 10 FAQ/repetitive questions
- 10 complaints/escalations
- 5 reply/threading tests
- 5 dashboard action tests
- 5 edge cases

No runner changes needed for Phase 1b — Phase 1a's runner already handles arbitrary scenario counts.

## Phase 2 roadmap (placeholder)

Future work to make the runner actually exercise production:

- **Add safe message-injection endpoint to the dashboard backend.** Likely shape: `POST /dashboard/api/qa/inject` with auth + rate limit + `[QA TEST]` prefix enforcement. Endpoint accepts `{channel, senderEmail, body}`, simulates an inbound webhook, returns the synthesized customer + conversation ids.
- **Build a mock harness for `marina_agent.process_message`** that records the prompt sent to Claude (or the actual reply) so each scenario's `expected` block can be asserted against real output without touching customers.
- **Implement dashboard action verifier.** Probably wraps the existing dashboard API endpoints (`POST /dashboard/api/conversations/{id}/archive`, etc.) so the runner can do "trigger inject → click archive → assert state".
- **Cleanup mode.** Trigger via `--cleanup` flag (never automatic). Deletes every conversation in `state_registry` whose latest message starts with `[QA TEST]`. Phase 2 only because it requires confidence that nothing else uses the prefix.

## How cleanup mode will work later (Phase 2)

```bash
# Phase 2 only — does not work in Phase 1a:
python3 tools/unboks-qa/run_qa.py --cleanup
```

Will iterate `state_registry.conversations` (or equivalent), find rows whose latest message starts with `[QA TEST]`, delete those rows + any associated `pending_notifications`, `appointments`, `alert_deliveries` rows. Will NOT delete real customer conversations. Will print a confirmation count before deletion.

## Implementation

- Python 3.12 stdlib only (no extra dependencies).
- Single-file runner (`run_qa.py`, ~300 lines).
- Tests at `wtyj/tests/tools/test_unboks_qa.py`.
- No imports from `wtyj/agents/` or `wtyj/dashboard/` — structural decoupling guarantees the Phase 1a runner cannot trigger production behavior.
