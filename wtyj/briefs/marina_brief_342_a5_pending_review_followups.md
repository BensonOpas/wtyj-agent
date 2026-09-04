# BRIEF 342 A5 — Truthful pending-review follow-ups
**Status:** Deployed and verified at f220c3e; A4/A8 acceptance holds remain | **Files:** `wtyj/agents/social/mermaid_understanding.py`, `wtyj/agents/social/mermaid_response_policy.py`, `wtyj/agents/social/mermaid_reservation_workflow.py`, `clients/mermaid/config/response_policy.json`, `wtyj/tests/agents/test_mermaid_audit_policy.py` | **Depends on:** 2286d9f and issue 342 | **Blocks:** candidate transcript acceptance

## Context
The isolated candidate audit still found unsupported staff-progress wording despite queued durable review. BASE-045 German turn 5 returned “Die Rollstuhlfrage wird noch vom Mermaid-Team geprüft. Sobald die Freigabe vorliegt, geht es mit der Buchung weiter.” The model classified this as acknowledge with no status selector. BASE-046 Spanish turn 5 promised follow-up. BASE-048 Portuguese turn 4 answered a turtle condition and volunteered active review despite status_request=none. Only a pending soft review existed. The original 47/60 functional and 32/60 accepted baseline stays unchanged.

## Why This Approach
Issue 342 explicitly authorizes server-owned critical status wording. Reuse that narrow exception for a structured wildlife_guarantee selector and catalog/config-owned six-language copy: sightings may be possible but are never guaranteed. Keep model understanding and ordinary FAQ prose. Reject response-text scanning and broader replacement of all review-time replies because those would introduce language classifiers or suppress useful answers. Papiamentu remains draft pending qualified Curaçao review. No additional model call, guest message, live mutation or deployment is authorized in this workstream.

## Instructions
1. Extend the tool status selector and prompt at `wtyj/agents/social/mermaid_understanding.py:23` and `:89`. Any reply that would mention review selects handover, even if the guest did not explicitly ask status. Ordinary supported FAQ replies must not volunteer staff status or future clearance. Wildlife guarantee questions/conditions select wildlife_guarantee; an existing separate review stays pending.
2. Add six-language wildlife guarantee copy in tenant `clients/mermaid/config/response_policy.json`. Add a helper adjacent to `wtyj/agents/social/mermaid_response_policy.py:97` that renders that fact plus recorded handover status only when a review exists. Never infer active handling from the model.
3. In the existing critical-fact routing at `wtyj/agents/social/mermaid_reservation_workflow.py:664`, replace plain review-time acknowledgments with recorded handover copy and render the wildlife selector. Preserve security, explicit human request and cancellation priority; preserve safe FAQ, reservation freeze, manual hard-mute and tenant pause behavior.
4. Extend the existing behavioral tests at `wtyj/tests/agents/test_mermaid_audit_policy.py:66`, using isolated real SQLite and stubbed model results with recorded review context. Do not modify sibling pickup-pricing implementation hunks beyond unavoidable integration resolution by the parent.

## Tests
- Six-language pending review plus plain acknowledgment containing false active/follow-up text returns exactly recorded queued copy, keeps intake and one soft work item, and stays unmuted with no booking.
- Six-language conditional turtle question returns exact approved non-guarantee plus recorded queue copy; no reservation or confirmation is created, and the following safe FAQ remains answerable.
- No-review wildlife question does not create or claim a review. The selector is schema-valid through the actual recovery wrapper.
- Existing security and cancellation priority regressions include the new selector and remain green. Existing hard-mute/tenant-pause end-to-end regressions remain green. Parent owns combined full gate and real-model reruns; no paid calls here. Local focused gate: 105 passed across audit-policy, soft-review webhook and confirmation/cancellation modules. The six acknowledgment regressions failed against 2286d9f before the patch. The wildlife selector/copy regressions also failed before addition. Papiamentu copy received a bounded assistant lexical review and remains pending native certification.

## Success Condition
Queued review cannot become active/future-promised prose through plain acknowledgments or the structured wildlife guarantee route, while supported follow-up answers and operator controls still work.

## Rollback
Revert this source/config commit before the parent's combined deployment. No data repair or state rollback is needed; the work changes response selection only.
