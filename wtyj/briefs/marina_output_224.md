# OUTPUT 224 — Strip internal escalation tokens from Marina email replies

## What was done
Added `_INTERNAL_TOKENS` constant (5 sentinels) and `_strip_internal_tokens()` helper near the top of `wtyj/agents/marina/marina_agent.py`. Wired the helper into `process_message()` immediately before the success-path `return result` so both `result["reply"]` and any `result["reply_hold_failed"]` are sanitized before leaving the agent. The helper does plain string replacement against an explicit allowlist (NOT a `\[X\]` regex) so legitimate placeholders `[BOOKING_REF]` and `[PAYMENT_LINK]` survive intact for downstream substitution at `email_poller.py:1212-1225,1290-1291`. dm_agent's existing `[ESCALATE]` strip at line 221 is untouched.

## Tests
1033 passing / 0 failures (baseline 1028 + 5 new).

## Deployment
Source committed and pushed; deploy still to fire.
