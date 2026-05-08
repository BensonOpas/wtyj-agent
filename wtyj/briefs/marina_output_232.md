# OUTPUT 232 — Archive auto-restore on inbound email

## What was done
Extracted `_un_archive_thread_if_deleted(th)` as a module-level helper in `wtyj/agents/marina/email_poller.py` near `_cleanup_stale_data`. Production code at the inbound append site calls it between the existing Brief 220 block-check and `th["messages"].append(...)`. The helper pops `flags.deleted` (set by Brief 218's dashboard delete) and returns True when the flag was cleared so the caller can log the restore. Block-check at line 641 still short-circuits the iteration first — block always wins per SR's spec, the helper never runs on blocked threads. Other flags (`fully_escalated`, `ai_muted`) are preserved.

## Tests
1083 passing / 0 failures (baseline 1078 + 5 new).

## Unexpected findings
Output-reviewer round 1 caught the original tests as tautologies — they exercised a hand-copy of the production logic instead of importing the real code. Refactored: extracted the un-archive into a module-level helper that both production AND tests call; tests now import `_un_archive_thread_if_deleted` from `email_poller` directly. A regression in production now fails the test. Block-precedence test still mirrors the poller's two-step flow (block check → helper) but exercises the real helper on the not-blocked branch.

## Deployment
Source committed and pushed; deploy still to fire.
