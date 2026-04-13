# BRIEF 191 — Source code agnostic sweep: remove all hardcoded client-specific values
**Status:** Draft | **Files:** `sheets_writer.py`, `payment_stub.py`, `social_agent.py`, `email_poller.py`, `state_registry.py`, `bm_logger.py`, `webhook_server.py`, `dm_agent.py`, `marina_agent.py`, `api.py`, `clients/bluemarlin/config/client.json`, 4 test files | **Depends on:** — | **Blocks:** —

## Context

A system-wide audit found 15 hardcoded client-specific values that would cause cross-client data bleed, wrong branding, or wrong defaults when onboarding non-BlueMarlin clients. This brief fixes all of them in one sweep. No new features — just making the source code truly agnostic.

## Why This Approach

One sweep brief instead of 15 individual quick-fixes because: (a) the changes are all the same KIND of fix (remove hardcode, use config or empty default), (b) testing them individually would run the full regression 15 times, and (c) they share the same rollback strategy (`git revert`).

### Rejected alternatives

1. **Fix each one as a separate commit.** Rejected: 15 commits for 15 one-line changes is churn. One clean commit with a descriptive message.
2. **Leave the "Marina" fallbacks as-is since config override works.** Rejected: the default reveals architectural assumptions. New clients without `agent_name` get "Marina" which is BlueMarlin's name, not a generic. "CSA" (Customer Support Agent) is the correct generic default.

## Instructions

### Group A — Critical data-bleed fixes

**A1. `sheets_writer.py:26`** — Remove hardcoded BlueMarlin spreadsheet ID.

Replace: `return '1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I'`
With: `return ''`

Also add an early-return guard at the top of `_append()` (line 29): `if not _get_spreadsheet_id(): return` — so clients without a spreadsheet configured produce no noisy gws CLI errors. No client's data silently lands in BlueMarlin's sheet.

**A2. `payment_stub.py:38`** — Remove "bluemarlin" from demo payment URL.

Replace: `link = f"https://demo.pay/bluemarlin/{payment_id}"`
With: `link = f"https://demo.pay/{payment_id}"`

**A3. `social_agent.py:817`** — Same fix.

Replace: `pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"`
With: `pay_link = f"https://demo.pay/{pay['payment_id']}"`

**A4. `email_poller.py:1134`** — Same fix.

Replace: `pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"`
With: `pay_link = f"https://demo.pay/{pay['payment_id']}"`

**A5. `state_registry.py:766-767`** — Remove hardcoded `clients/bluemarlin/` path fallback.

Replace the candidates block in `_get_email_state_path` (line 760):

Current (lines 764-772):
```python
    candidates = [
        "/app/config/email_thread_state.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                     "clients", "bluemarlin", "config", "email_thread_state.json"),
    ]
```

New:
```python
    _cfg = os.environ.get("CLIENT_CONFIG_PATH", "")
    candidates = [
        "/app/config/email_thread_state.json",
    ]
    if _cfg:
        candidates.insert(0, os.path.join(os.path.dirname(_cfg), "email_thread_state.json"))
```

This uses the same `CLIENT_CONFIG_PATH` env var that conftest.py sets for tests and docker-compose sets for production. No client name hardcoded.

**A6. `email_poller.py:365-368`** — Guard empty `demo_support_email`. The previous session removed the hardcoded `butlerbensonagent@gmail.com` fallback, leaving `or ""`. But downstream code calls `smtp_send(demo_support_email, ...)` which will throw on empty address. Add a guard at the SMTP call sites.

At `email_poller.py:1244` and `email_poller.py:1272` (the two places that call `smtp_send(demo_support_email, ...)`), wrap each in `if demo_support_email:`. The notification is already created in the database via `create_pending_notification` — the email dispatch is optional (dashboard always shows it). If no support_email is configured, skip the email silently.

### Group B — Branding fixes

**B1. `bm_logger.py:9`** — Rename log file.

Replace: `LOG_PATH = os.path.normpath(os.path.join(_BASE_DIR, "..", "logs", "bluemarlin.log"))`
With: `LOG_PATH = os.path.normpath(os.path.join(_BASE_DIR, "..", "logs", "agent.log"))`

**B2. `webhook_server.py:33`** — Rename FastAPI title.

Replace: `app = FastAPI(title="BlueMarlin Social Webhook", docs_url=None, redoc_url=None, lifespan=lifespan)`
With: `app = FastAPI(title="WTYJ Agent", docs_url=None, redoc_url=None, lifespan=lifespan)`

**B3. `webhook_server.py:39`** — Remove dead CORS origin.

Remove `"https://bluemarlindashboard.replit.app",` from the `allow_origins` list. This URL is superseded by `wetakeyourjob.com` (the merged Replit project). The regex `*.replit.app` already covers any Replit domain as a catch-all.

### Group C — Agent name defaults ("Marina" → "CSA")

Change all 6 occurrences of `"Marina"` as the fallback default for `agent_name` to `"CSA"`:

- `dm_agent.py:25` — `business.get("agent_name", "Marina")` → `business.get("agent_name", "CSA")`
- `dm_agent.py:101` — same pattern → `"CSA"`
- `marina_agent.py:452` — `business.get('agent_name', 'Marina')` → `business.get('agent_name', 'CSA')`
- `marina_agent.py:740` — `config_loader.get_business().get("agent_name", "Marina")` → `...get("agent_name", "CSA")`
- `api.py:1028` — `config_loader.get_business().get("agent_name", "Marina")` → `...get("agent_name", "CSA")`
- `api.py:1049` — `business.get("agent_name", "Marina")` → `business.get("agent_name", "CSA")`

### Group D — Client config update

**D1.** BlueMarlin's `client.json` already has `"agent_name": "Marina"` at line 18 — no change needed. The default change from "Marina" to "CSA" only affects clients WITHOUT `agent_name` in their config. BlueMarlin is unaffected.

### Group E — Test updates

**No test changes needed.** The three tests that assert "Marina" (test_069, test_119, test_176) all either use the real BlueMarlin client.json via conftest.py (which has `agent_name: "Marina"` at line 18), or check mocked API output / function parameters that already contain "Marina" explicitly. None rely on the source-code fallback default. test_049 tests `format_sheets._get_spreadsheet_id()` which reads from config (not sheets_writer.py's fallback), so it's unaffected by A1.

### Step — Do NOT touch

- `"role": "marina"` in email_poller.py (6 places) + state_registry.py (2 places) — internal data identifiers, migration needed
- `api.py:27` Google OAuth redirect URI — multi-client OAuth routing is a separate concern
- Language hints in marina_agent.py — generic, read from client config
- DM fallback reply string — documented CLAUDE.md Rule 3 exception
- `$` currency symbol in prompts — formatting, actual pricing from config

## Tests

No test changes needed — existing tests either use BlueMarlin's real config (which has `agent_name: "Marina"`) or check mocked output that already contains the expected values. The regression suite (891 baseline) should pass at 891 / 0 unchanged.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` reports **891 passed / 0 failed** (same baseline — no new tests, just test updates). `grep -r "bluemarlin" wtyj/agents/ wtyj/shared/ wtyj/dashboard/ --include="*.py" | grep -v backup | grep -v import | grep -v "#"` returns zero results (no hardcoded "bluemarlin" remains in live source outside of imports and comments).

## Rollback

`git revert <commit>`. Restores all hardcoded values. BlueMarlin's `client.json` would need `agent_name` removed to match the reverted fallback (or left in — it's harmless as an explicit value even with the "Marina" default restored).
