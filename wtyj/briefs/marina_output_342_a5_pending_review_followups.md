# OUTPUT 342 A5 — Truthful pending-review follow-ups

## What was done
Plain acknowledgments during an unresolved review now render the recorded review status instead of arbitrary model progress claims. The structured wildlife_guarantee selector renders six-language tenant copy stating that sightings are possible but never guaranteed, with recorded handover status only when a review exists. The understanding contract requires a status selector whenever generated prose would otherwise mention staff review and forbids volunteering those claims in ordinary FAQ answers. The focused tests use real isolated SQLite and model stubs to preserve saved intake, a single soft review, safe follow-up answers and existing security/cancellation/operator safeguards. Papiamentu remains a draft despite bounded assistant lexical review.

## Tests
105 passing / 0 failures across audit-policy, soft-review webhook and confirmation/cancellation modules (88 prior focused cases + 17 new). Command: `/tmp/unboks-mermaid-venv/bin/python -m pytest wtyj/tests/agents/test_mermaid_audit_policy.py wtyj/tests/social/test_mermaid_soft_review.py wtyj/tests/agents/test_mermaid_confirmation_cancellation.py -q`. Six acknowledgment regressions reproduced the original false progress wording before the patch. Parent owns the combined exact-image and real-model gates. Independent output review approved the bounded diff; pending-review cancellation/confirmation/new-booking also retains its prior outcome when the model supplies the wildlife selector.

## Deployment
Not deployed or pushed. Isolated source worktree based on 2286d9f; parent integrates and owns release verification. No live state or guest/provider messages changed.
