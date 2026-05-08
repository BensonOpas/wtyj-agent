# OUTPUT 235 — Fix Brief 227 escalation summary in production

## What was done
Two bug fixes. (1) Status filter in `state_registry.py` corrected at both Brief 227 sites — the dedup at line 1389 and the readback `get_active_escalation_summary_for` at line 1866 — from `status = 'pending'` to `status IN ('pending', 'sent')`. Brief 217's alert dispatcher transitions rows pending→sent immediately, so the old `pending`-only filter matched zero rows in production. (2) Extracted Brief 227's `_generate_escalation_summary` wrapper from `dashboard/api.py:1601-1671` (~70 lines) into a new shared module `wtyj/shared/escalation_dispatcher.py` that registers the dispatcher as a load-time side effect. Both `dashboard/api.py` (one-line replacement: `from shared import escalation_dispatcher`) and `email_poller.py` (added the same import alongside existing shared imports) now register the dispatcher in their respective processes — closes the gap where email_poller had `_summary_dispatcher = None` because it never imported `dashboard.api`.

## Tests
1100 passing / 0 failures (baseline 1095 + 5 new).

## Deployment
Source committed and pushed; deploy still to fire.
