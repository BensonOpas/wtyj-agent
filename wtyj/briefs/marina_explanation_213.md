# EXPLANATION 213 — Escalation control surface

Plain-English explanation of commit `2511a65` for an operator who doesn't read code.

## What was broken

When you opened an escalation in the dashboard, SR's reply composer was supposed to show one of two modes:
- **Soft mode** — "AI needs help" → operator coaches Marina, Marina replies in her voice.
- **Hard mode** — "Human takeover" → operator replies directly to the customer, AI is muted on that conversation.

Both modes existed in the FRONTEND code already (the EscalationReplyComposer, the soft/hard tabs, the "AI muted" pill). But the BACKEND had no way to remember which mode an escalation was in, and no way to actually mute Marina on a specific conversation. So the frontend always fell back to a basic action-buttons UI — usable, but not the rich workflow SR built.

Worse: even if you had set "Human takeover" somehow, when the customer sent another message Marina would have replied anyway. There was no "stop replying on this conversation" switch.

## What changed

Three database columns added (all with safe defaults so existing data is untouched):

- `pending_notifications.mode` — the soft/hard mode of each escalation. Defaults to NULL for legacy rows (frontend treats null as "no mode set, show legacy panel").
- `conversation_status.ai_muted` — boolean per conversation. 0 = AI replies normally; 1 = human has taken over, AI stays quiet.
- `conversation_status.human_takeover_at` — timestamp recording WHEN takeover happened (for audit / debugging).

Three new dashboard endpoints that the frontend can now call:

- `POST /escalations/{id}/mode` — operator clicks the soft/hard tab. Backend writes the mode and returns the updated row.
- `POST /escalations/{id}/takeover` — operator clicks "Human takeover". Backend sets the escalation's mode to "hard", flips ai_muted to true on that conversation, stamps the timestamp.
- `POST /escalations/{id}/handback` — operator clicks "Hand back to AI". Reverses the takeover: ai_muted goes back to false, mode resets to "soft".

The list-escalations endpoint also now returns the `mode` field on every row, and supports a `?mode=soft|hard` filter so the frontend's "AI needs help" / "Human takeover" filter buttons work.

## The mute check — the careful part

The four places where customer messages get processed before Marina replies:

1. **Instagram and Facebook DMs** — through `webhook_server._process_zernio_event`
2. **WhatsApp via Zernio** — through `webhook_server._flush_buffer` (the debounce-buffered path that batches multiple rapid-fire messages)
3. **WhatsApp via Meta directly** — through `webhook_server._flush_buffer` (the legacy path, kept around for the old Meta integration)
4. **Email** — through `email_poller.py` (the IMAP poll loop)

At every one of these four entry points, Marina's reply call is now gated by an `ai_muted` check. If the conversation is muted:
- The customer's message is STILL stored in the conversation thread, so you see it in the dashboard inbox.
- Marina is NOT called. No reply goes out.
- A log line records the skip ("zernio_dm_ai_muted", "whatsapp_zernio_ai_muted", "whatsapp_meta_ai_muted", "email_ai_muted") so you can see in the logs which conversations went silent and when.

This is the most important detail: the inbound message is recorded BEFORE Marina is gated. If you mute a conversation and the customer keeps writing, you see every message in your dashboard. You just have to reply to them yourself (or click "Hand back to AI" to let Marina take over again).

## What it does now

- Open an escalation on `dashboard.unboks.org` → the rich soft/hard composer renders (because mode is now real, not null).
- Click "Human takeover" → the conversation goes into AI-muted state. Customer messages on that conversation appear in your inbox but don't get auto-replies.
- Click "Hand back to AI" → Marina resumes replying on the next inbound message.
- Use the "AI needs help" / "Human takeover" filter buttons on the Escalations list → backend filters the response by mode.

## What it doesn't do (still pending Tier 2)

- `POST /escalations/{id}/guidance` — soft-mode "operator coaches Marina, Marina relays" flow. Marina's prompt is wired but the backend endpoint that routes operator text through her isn't. Brief 214.
- `POST /learning/{id}/approve` and `/save` — the operator-answer-as-approved-learning flow SR's contract specifies. Brief 215.
- "Your Info" / Settings → Marina's prompt — Brief 216.
- Escalation alert delivery (email/whatsapp notifications when a new escalation fires) — Brief 217.
- Email forward / delete actions — Brief 218.

## Files changed

- `wtyj/shared/state_registry.py` — schema ALTER TABLEs + 4 new helpers + `get_all_escalations` returns `mode`.
- `wtyj/dashboard/api.py` — 3 new endpoints + `_refresh_and_stringify_escalation` helper + `?mode=` filter + `_conversation_status_fields` reads real values.
- `wtyj/agents/social/webhook_server.py` — ai_muted check at 3 ingestion sites (DM, Zernio-WA, Meta-WA).
- `wtyj/agents/marina/email_poller.py` — `_should_skip_marina_for_mute` helper at module scope + check after the inbound-append.
- `wtyj/tests/social/test_213_escalation_control.py` — 11 tests covering schema, endpoints, ingestion paths, and the email helper.
