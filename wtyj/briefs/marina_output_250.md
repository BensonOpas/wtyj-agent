# OUTPUT 250 — Fix `wa_get_full_history` to return newest N + anchor escalation summary on latest customer message

## What was done

P1 fix for issue #20 — Calvin's "dog is sick / 10:00" message wasn't reflected in the dashboard escalation summary. Live audit confirmed the root cause was a **long-latent SQL bug** in `wa_get_full_history`: the SELECT used `ORDER BY created_at ASC LIMIT ?`, returning the OLDEST N rows instead of the newest N. For Calvin's 44-message WhatsApp thread with `limit=20`, the dog-sick message at position #44 was completely invisible to Claude AND to Brief 239's `latestCustomerMessage` extraction (which walked the same truncated 20-row window and picked the most-recent message AMONG THOSE — "Ill be there" from message ~14, 23 hours stale). Per-step shipped:

1. **Fixed `wa_get_full_history` SQL** at `wtyj/shared/state_registry.py:1584-1602`. Changed `ORDER BY ASC LIMIT ?` to `ORDER BY DESC LIMIT ? ... reversed()`. SELECT now picks the most-recent N rows; Python `reversed()` preserves the documented "oldest first" output contract for all 5 production callers (verified via grep — `social_agent.py:695`, `escalation_dispatcher.py:37`, `state_registry.py:4136`, `dashboard/api.py:1404`, `dashboard/api.py:2342`). Backward-compat: when total <= limit, behavior is unchanged from pre-Brief-250.
2. **Added a hard prompt rule** in `wtyj/dashboard/escalation_summary.py` (immediately after Brief 248's confirmedTime rule). The new bullet instructs Claude that when the customer's MOST RECENT message changes the requested time / asks to reschedule / introduces a new decision point, the `customerWants` / `operatorNeedsToDecide` / `recommendedOptions` fields MUST reflect that NEW request — not the older proposed times. This is belt-and-suspenders for cases where Claude DOES see the latest message but might over-weight older context.
3. **3 new tests appended to `wtyj/tests/test_201_dm_agent_em_dash.py`** (per Brief 236 rule — that file already has `test_wa_get_full_history_includes_id` at line 91, the existing per-module test for `wa_get_full_history`). Tests: (a) returns most-recent N when total > limit (seeds 25 messages, asserts only `msg_15..msg_24` returned, NOT `msg_0..msg_9`), (b) preserves oldest-first output order on short conversations, (c) returns all when total <= limit.

**Brief-reviewer:** FAIL round 1 with 2 real issues — (a) Test 4 was a banned source-string-grepper per Brief 236 (opening `escalation_summary.__file__` and grepping for "Brief 250" / "MOST RECENT message" — exactly the pattern Brief 236 deleted last week). (b) Created a new `test_250_*.py` file violating Brief 236's per-module-extension rule. Round 2 PASS zero issues after dropping Test 4 (acknowledged its effect is observable in production but not unit-testable without real Claude calls) and relocating Tests 1-3 to extend `test_201_dm_agent_em_dash.py`.

## Tests

1073 passing / 0 failures (1070 baseline + 3 new = 1073). Targeted file `wtyj/tests/test_201_dm_agent_em_dash.py` runs 7/7 (was 4; added 3).

The most diagnostic test is `test_wa_get_full_history_returns_most_recent_when_total_exceeds_limit` — it seeds 25 messages and asserts the returned list is `msg_15..msg_24` (most recent 10), NOT `msg_0..msg_9` (oldest 10). Pre-Brief-250 this assertion would have failed with `texts[-1] == "msg_9"` (oldest 10's last entry). This is the direct regression test for Calvin's exact bug shape.

## Production verification needed (post-deploy)

The next time Calvin sends a customer message that changes a decision context (asks to reschedule, proposes a new time, introduces a new request inside an unresolved escalation), the escalation summary should:
1. Have `latestCustomerMessage` set to the actual most-recent customer message (not a stale older one).
2. Have `customerWants` reflect the NEW request (not the older proposals).
3. Have `recommendedOptions` propose actions on the new request.

For Calvin's existing escalation summary on `69efec187aca03948969dc95` (esc_id=29), the stale data won't auto-correct — it'll update on the NEXT escalation event for that conversation (any new customer message that re-triggers summary generation).

## Deployment

Source commit pending. Will deploy via the standard CI pipeline. **Side effect (worth surfacing):** all 5 production callers of `wa_get_full_history` start receiving the most-recent N messages instead of the oldest N. The dashboard's full-history view at `limit=200` is unaffected for any conversation < 200 messages (most). For longer conversations, operators will see the recent messages first instead of the oldest — that's a behavioral improvement matching what the function name and docstring always implied.

Briefs 238-249 all preserved (Brief 248's confirmedTime field + bridge unchanged; Brief 239's latestCustomerMessage extraction unchanged; Brief 228's appointment_upsert bridge unchanged — all just receive correct (non-truncated) input now).

## Out-of-scope (deferred per brief Step 4)

- Brief 248 confirmedTime over-extraction on pure acknowledgements ("Ill be there") — separate prompt tweak; defer.
- DB index on `(phone, created_at)` for query speed — defer until measurable.
- Backfill stale escalation summaries — auto-corrects on next escalation event for each conversation.
- Bumping limits at call sites — limits stay; the SQL fix makes them semantically correct.
- Stricter prompt rule about auto-retracting older proposed times — defer; could lose context.
