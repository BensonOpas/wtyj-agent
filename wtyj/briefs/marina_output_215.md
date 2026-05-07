# OUTPUT 215 — Operator-answer-as-approved-learning

## What was done

New table `escalation_learnings` (id, conversation_id, channel, source_question, human_answer, status, ai_may_use_automatically, category, created_by, created_at, updated_at), placed adjacent to `content_learnings` in `state_registry._get_conn()`. Five helpers in `state_registry.py`: `save_escalation_learning`, `list_escalation_learnings`, `update_escalation_learning_status`, `delete_escalation_learning`, `_last_customer_message_for` (used to fill `source_question` from the most recent customer message in the conversation, with branches for email and whatsapp/dm). Repointed `GET /learning` and `DELETE /learning/:id` from `content_learnings` (Brief 212 alias) to the new escalation_learnings table; added `POST /learning/:id/approve` and `POST /learning/:id/save` per SR's product contract Section 3. Auto-creation hook installed at four call sites (after successful send + status flip): `/reply` WhatsApp + `/reply` email + `/guidance` WhatsApp + `/guidance` email — each wrapped in try/except so a learning-write failure never blocks the customer reply. `/resolve` upgraded to accept a `ResolveRequest` body with `resolutionNote`, `saveAsLearning`, `autoUseNextTime`, `category`; when `saveAsLearning=true` it creates an approved learning row and returns `{learningEntryId}`. Brief 212's two `/learning` alias tests updated in place to reflect the new contract — they now seed `escalation_learnings` rows and assert the singular path returns those (not content_learnings).

## Tests

982 passing / 0 failures (baseline 972 + 10 new in test_215, plus 2 rewritten in test_212).

## Deployment

Pending — commit/push/deploy in step 16.
