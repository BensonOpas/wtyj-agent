# BRIEF 316 — Ali Confirmed After-Sales Terminal Boundary
**Status:** Executed | **Files:** `agents/social/social_agent.py`, `agents/marina/marina_agent.py`, `tests/agents/test_ali_quote_intake_dispatch.py`, `tests/agents/test_ali_latest_change_orchestration.py` | **Depends on:** Brief 315 | **Blocks:** None

## Context
After a confirmed reservation, Calvin supplied an email address in response to Nick's optional document-delivery offer. The address was correctly extracted and persisted, but the outbound reply was replaced with the generic intake safety fallback. His next acknowledgement then re-entered the quote planner and repeated the reservation confirmation and hotel details. The persisted audit showed a confirmed reservation alongside the legacy `QUOTED` phase, proving that quote-phase flags outlived the reservation workflow and were incorrectly treated as the active authority.

The defects were independent but compounding: the intake contact-redirect sanitizer treats every email address as unsafe, and the quote planner continued to run after the reservation had reached its terminal confirmed state.

## Why This Approach
Persisted reservation status is the strongest available state signal, so `confirmed` becomes a hard boundary around quote-intake post-processing. Nick still receives the confirmed reservation context and produces one natural model response; that response is no longer rewritten by vehicle discovery, child-seat discovery, the contact-redirect sanitizer, or the quote turn planner. This preserves after-sales reasoning and the normal structured extraction of an optional customer email.

Hard-coded email and acknowledgement templates were rejected because they would make Nick scripted again and violate the project's single-model, model-understands architecture. Weakening the contact sanitizer globally was also rejected because it would reopen contact-redirection failures during intake.

## Instructions
1. Load persisted quote and reservation context before the model call in `agents/social/social_agent.py`, and pass both into the model flags.
2. Derive the terminal boundary only from persisted reservation status `confirmed`.
3. Keep normal model extraction, customer identifier linking, field merge, and persistence for after-sales turns.
4. Skip quote-intake media routing, proactive intake prompts, reply sanitization, and quote turn planning when the terminal boundary is active.
5. Preserve the model's after-sales reply and return no quote confirmation, vehicle recommendation, or quote delivery commit.
6. Strengthen the confirmed after-sales prompt in `agents/marina/marina_agent.py` so optional email replies are acknowledged without claiming delivery, and short acknowledgements never repeat reservation details.
7. Log the terminal-boundary path without customer email content.

## Tests
1. Reproduce a confirmed reservation receiving `Calvin@gaimin.io`; assert Nick's natural reply survives unchanged, the email persists, and no quote artifact is planned.
2. Reproduce `Ok` immediately afterward; assert the brief reply survives unchanged and does not repeat the reference or confirmation.
3. Confirm the ordinary intake contact guard still blocks an email redirect even when an email value exists in fields.
4. Confirm the Ali prompt explicitly requires brief, non-repetitive acknowledgements after confirmation.

## Success Condition
A confirmed customer can supply an optional email and continue chatting naturally without a safety fallback, repeated confirmation, vehicle media, or a new quote action.

## Rollback
Revert the Brief 316 commit. No data migration is required because the change adds no schema or persisted state fields.
