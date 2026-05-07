# EXPLANATION 215 — Operator-answer-as-approved-learning

Plain-English explanation of commit `68c0436` for an operator who doesn't read code.

## What was missing

When you reply to an escalation in the dashboard (either by typing directly to the customer or by coaching Marina), that answer disappears into the conversation log. Nothing is captured for "next time someone asks the same thing, Marina should already know what to say."

SR's product contract is explicit: every operator answer in escalation flows is valuable, treat it as approved knowledge for Marina to reuse. The frontend already has a Learning Entries panel, an "Approve" button, a "Save permanently" button, and a checkbox in the Resolve dialog ("save this as learning"). All of those buttons hit backend endpoints that didn't exist yet. They've been showing the calm "will be connected by the Unboks team" notice instead of doing real work.

## What changed

A new database table `escalation_learnings` to hold the captured operator answers. Each row records:

- **conversationId** — which customer this came from
- **channel** — WhatsApp, email, etc.
- **sourceQuestion** — the customer's most recent message before you replied (auto-extracted from the conversation history)
- **humanAnswer** — your answer text. For hard mode this is what you typed and sent to the customer. For soft mode this is the COACHING you gave Marina (the underlying intent), not Marina's polished reformulation.
- **status** — "approved" by default. Operator can flip to "saved" (permanent) or "deleted".
- **aiMayUseAutomatically** — true by default. If you uncheck this on a row, Marina won't auto-reply with this answer (it stays as a reference for the operator only).
- **category** — optional tag like "complaint" or "scheduling".
- **createdAt / updatedAt** — timestamps.

Auto-creation hooks installed at four places — every successful operator answer creates a row:

1. POST `/escalations/:id/reply` WhatsApp branch (after WhatsApp send succeeds)
2. POST `/escalations/:id/reply` email branch (after smtp_send succeeds)
3. POST `/escalations/:id/guidance` WhatsApp branch (after Marina's reformulated reply is sent)
4. POST `/escalations/:id/guidance` email branch (after Marina's reformulated reply is sent via SMTP)

Each hook is wrapped in try/except so a database failure NEVER blocks the customer reply. If the learning-write fails, the customer still gets your reply, and the failure is logged for later review.

Three new endpoints the frontend can now call:

- **GET `/learning`** — returns the list of escalation learning entries, with `status` per row. Supports `?status=approved|saved|suggested` filter.
- **POST `/learning/:id/approve`** — flips status to "approved". Operator clicks "Approve" on a suggested entry.
- **POST `/learning/:id/save`** — flips status to "saved" (permanent). Operator clicks "Save permanently".

Plus: **POST `/escalations/:id/resolve`** now accepts a body `{resolutionNote, saveAsLearning, autoUseNextTime, category}`. When you check "save this as learning" in the Resolve dialog, the backend now actually creates a learning row with your resolution note as the answer.

## A small but important contract break

Earlier (Brief 212) we made `/learning` an alias for `/learnings` — both pointed at the same content_learnings table (which content_agent uses for content posts, unrelated to escalations). That was a misunderstanding of SR's contract — he was always asking for an escalation-derived learning panel, not a content-rules panel.

Brief 215 deliberately breaks that alias: `/learning` (singular) now points at the new `escalation_learnings` table, and `/learnings` (plural) still serves content_learnings unchanged. Two paths, two clean domains. The two old tests for the alias have been rewritten in place to match the new contract.

## What it does now

- Reply to an email escalation. Backend sends the reply to the customer AND writes a new approved learning row.
- Send guidance to Marina via /guidance. Backend has Marina send her polished version AND writes a learning row capturing your coaching text (because that's the operator-authored knowledge, not Marina's polish).
- Open the Learning Entries panel in the dashboard. See your captured answers with their status.
- Click "Approve" on a row → backend flips status. Click "Save permanently" → backend flips to "saved". Click delete → backend removes the row.
- Resolve an escalation with the "save this as learning" checkbox → backend creates a row from your resolution note.

## What it doesn't do yet (deferred to a future brief)

**Marina doesn't actually USE the saved learnings yet.** That's the read+inject half — making Marina read the approved entries when generating a reply and use them as guidance. That touches `marina_agent._build_system_prompt`, the most sensitive code in the project (prompt drift causes silent quality regressions). It deserves its own focused brief with careful review. Brief 215 is the storage half: entries accumulate, you can manage them, and when the read half ships, Marina starts learning from them.

## Files changed

- `wtyj/shared/state_registry.py` — new escalation_learnings table CREATE; 5 helpers (save, list, update_status, delete, _last_customer_message_for).
- `wtyj/dashboard/api.py` — repointed /learning GET + DELETE to escalation_learnings; new /learning/:id/approve + /save; ResolveRequest body model + body-aware /resolve handler; 4 auto-creation try/except blocks at the existing hook points.
- `wtyj/tests/social/test_215_escalation_learning.py` — 10 new tests (round-trip helpers, endpoints, hook integration, resolve body params).
- `wtyj/tests/social/test_212_dashboard_endpoint_polish.py` — 2 alias tests rewritten in place to match the new /learning contract.
