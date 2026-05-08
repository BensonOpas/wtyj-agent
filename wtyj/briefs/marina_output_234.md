# OUTPUT 234 — Marina-uses-approved-learnings on IG/FB DM path

## What was done
Added module-private `_build_dm_approved_answers_block(channel)` helper to `wtyj/agents/social/dm_agent.py` mirroring `marina_agent._build_approved_answers_block` line-for-line. Helper gated on `features.approved_learnings_in_prompt` (already true for unboks). Computed once at the top of `_build_dm_system_prompt` after `output_rule`, used by both branches: the master_prompt branch (freeform_notes set) inserts it between `master_prompt` and `services_block`; the fallback branch was rewritten from string concatenation to a parts-list-join idiom that preserves the exact original block order (intro → qa_role_full → services → faq → writing_style → booking_redirect → language → avoid → emoji → output_rule) with the new approved-answers block inserted between `qa_role_full` and `services`. Channel string passes through verbatim — Instagram and Facebook learning pools stay isolated per the existing exact-match filter in Brief 219's `get_approved_learnings_for_prompt`.

## Tests
1095 passing / 0 failures (baseline 1088 + 7 new).

## Unexpected findings
Brief-reviewer round 1 caught two real issues: (1) the original "before" snippet for the fallback branch invented an ordering that didn't match source — would have silently re-shuffled four prompt blocks for every fallback-branch tenant despite the brief asserting byte-equivalence; (2) `marina_agent.py:553` reference was 25 lines stale. Patched both in round 2 by re-reading the actual source. Lesson reinforced: when a brief says "byte-equivalent rewrite," the executor must verify by reading the existing code, not by trusting the brief's "before" snippet.

## Deployment
Source committed and pushed; deploy still to fire.
