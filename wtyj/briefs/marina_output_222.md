# OUTPUT 222 — Conversation detail extras: humanTakeoverAt + learningStatus

## What was done

Two new state_registry helpers in `wtyj/shared/state_registry.py`: `get_human_takeover_at(conversation_id)` reads `conversation_status.human_takeover_at` (the ISO timestamp Brief 213 stamps when the operator hits takeover); `get_learning_status_for_conversation(conversation_id)` queries `escalation_learnings` and returns the highest-precedence non-deleted status (`saved` > `approved` > `suggested` > `none`). Extended `_conversation_status_fields()` in `wtyj/dashboard/api.py:982-1004` to include 5 new keys: 2 real (`humanTakeoverAt`, `learningStatus`) and 3 explicit-null placeholders (`humanGuidance`, `humanResponder`, `humanRespondedAt`) flagged in code comments as pending an operator-identity model. Both call sites (email branch + WhatsApp branch) of `get_conversation` automatically pick up the new fields via the existing `result.update(_conversation_status_fields(...))` pattern — zero new wiring.

## Tests

1005 passing / 0 failures (1001 baseline + 4 new).

## Deployment

Pending — commit/push/deploy in step 16.
