# BRIEF 268 — Restore relationship-first intake for Consulta Despertares

## Problem

Live conversation review shows a partial reply-quality regression for the
`consulta-despertares` tenant after the July 26 mandatory-boundaries release.
The agent still answers some chats well, but can move into contact-data
collection too early and can append the mandatory callback question while it is
already asking a different question. In one live chat, that produced repeated
two-question replies, explicit customer confusion, and abandonment.

The earlier classification-tag removal is not causal. Commit `d868f68` only
suppresses generic appointment/order metadata and dashboard badges. The
customer-facing regression follows commit `bc07963`, which routed this tenant
through the structured orchestrator and added deterministic callback-boundary
rewriting.

## Required behavior

Apply this only to `consulta-despertares`.

1. Keep the exact first-message greeting rules already approved.
2. Keep the callback follow-up workflow and its stored fields:
   - first name
   - surname(s)
   - telephone number
   - preferred time for the human team to call
   - reason for the visit, optional
3. Restore relationship-first pacing:
   - answer the customer's actual question before collecting contact details;
   - acknowledge emotional or sensitive context naturally;
   - do not request name, surnames, telephone, or callback time in the first
     substantive reply;
   - treat an appointment request as a conversation, not a checklist trigger.
4. Ask at most one question in each reply.
5. Do not combine preferred appointment time and preferred callback time.
   `callback_preference` means when the human team may call, not when the
   customer wants the appointment.
6. If the customer corrects the agent or says a reply is confusing, address the
   correction first and do not repeat the callback question in that reply.
7. Ask the exact approved callback closing only when:
   - first name, surname(s), and telephone are known;
   - callback preference is still missing; and
   - the reply is not already asking another question.
8. Do not show a captured-data checklist or summary unless the customer asks
   for one. A short natural acknowledgement is allowed.
9. The reason for the visit remains optional and must never block a callback.
10. Never ask for a timezone; all callback times are understood as Spain local
    time.

## Scope

- Tenant-specific prompt guidance for Consulta Despertares.
- Tenant hard-boundary logic for the callback closing.
- Regression tests for one-question pacing and callback-time semantics.

Do not remove the structured WhatsApp orchestrator, the follow-up queue, field
extraction, storage, operator handoff, exact greeting, or tag-suppression
behavior.

## Acceptance criteria

- A reply that already contains a question never receives the callback closing
  as a second question.
- Appointment date/time fields do not count as callback preference.
- A plain handoff-ready acknowledgement receives the exact callback closing
  once when callback preference is missing.
- Once `callback_preference` is present, the closing is removed and not added.
- Other tenants are byte-for-byte unaffected by the hard-boundary function.
- The prompt explicitly enforces relationship-first pacing, one question per
  reply, optional visit reason, no timezone question, and no unsolicited data
  summary.
- Existing callback follow-up persistence and mandatory greeting tests continue
  to pass.
