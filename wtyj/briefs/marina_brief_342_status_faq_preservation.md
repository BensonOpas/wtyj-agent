# BRIEF 342 — Preserve FAQ answers beside recorded status
**Status:** Deployed and verified at f220c3e; A4/A8 acceptance holds remain | **Files:** `mermaid_understanding.py`, `mermaid_reservation_workflow.py`, `test_mermaid_audit_policy.py` | **Depends on:** 535508c / 78c541a and issue 342 | **Blocks:** final follow-up acceptance

## Context
The isolated follow-up BASE-045 turn 6 asked in German whether breakfast is
included and when to arrive. The model correctly answered breakfast and 06:45
pier check-in, while emitting `status_request=handover` because a soft review
was pending. The workflow replaced the whole FAQ with queued-status copy.
Guest details and the review remained safe, but the question was unanswered.

## Why This Approach
Extend the existing schema-owned `other_question_reply` channel to payment,
handover and delivery status replies. Keep the ordinary model reply discarded
on those routes, because it can contain unverified payment or staff claims.
Reject using guest-question presence as permission to reuse raw prose; a guest
question can itself be about staff status. No Python language matching, extra
model call or broad FAQ rewrite is needed. A present field remains strictly a
string; require it in new generated output with empty string when inapplicable,
while the existing recovery validator keeps omitted legacy fields compatible.

## Instructions
1. At `wtyj/agents/social/mermaid_understanding.py:23`, clarify that pending
   review alone does not select handover. Populate `other_question_reply` with
   distinct supported FAQ answers, including food and general pier check-in;
   keep pickup, money, payment, delivery and staff-progress claims out of it.
2. Add the field to the new output contract's required list. Update the existing
   status and pickup prompt paragraphs consistently, preserving one model call.
3. At `wtyj/agents/social/mermaid_reservation_workflow.py:708`, prepend only the
   dedicated FAQ string to server-owned payment/handover/delivery text. Empty or
   omitted strings add nothing; never fall back to ordinary generated reply.
4. Retain security, explicit human, cancellation and review-blocked decision
   priority. Do not change controls, pending reviews, immutable money or intake.

## Tests
Replay the observed German FAQ with the dedicated field as the new structured
contract expects, then all six languages under soft review. Cover payment and
delivery states, empty/omitted FAQ without raw-prose leakage, malformed field
recovery compatibility and action priority. Use the real isolated SQLite and
existing model boundary stubs. Parent independently reviews the brief and output
before commit; no paid model calls, live actions, deployment or guest sends.
The exact German case plus all 18 locale/selector cases failed before the fix.
Afterward, 252 tests passed across authoritative policy, pickup replies, model
recovery and soft-review integration (including 40 new regressions). Six existing
record-state cases also now check FAQ composition beside real unpaid/paid and
waiting/failed/delivered states. Existing malformed-field recovery and omitted
legacy-field coverage remains green.

## Success Condition
Supported FAQ answers remain visible alongside truthful recorded status, while
unverified model status prose and blocked booking decisions remain excluded.

## Rollback
Revert this source/test/brief commit before the combined deployment, or restore
the prior runtime after deployment; no customer-state repair is required.
