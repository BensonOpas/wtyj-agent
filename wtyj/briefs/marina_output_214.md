# OUTPUT 214 — POST /escalations/:id/guidance

## What was done

Added `POST /escalations/{id}/guidance` to `wtyj/dashboard/api.py` after the existing `/reply` endpoint. Endpoint accepts the existing `EscalationReplyRequest` body shape (`{message}` / `{answer}`), short-circuits with 409 when the escalation's mode is "hard" (operator should use `/reply` for hard takeover, or `/handback` to return AI control), and dispatches by channel: WhatsApp branch sets `awaiting_relay=True` then calls `marina_agent.process_message` in relay mode, sends Marina's reformulated reply via `send_whatsapp_message`, stores it in `whatsapp_threads`, clears the relay flags, marks the escalation `replied`. Email branch loads thread context via `_find_email_thread_key_for` + `email_get_conversation`, sets `awaiting_relay=True` on flags, calls `marina_agent.process_message`, smtp_sends Marina's reformulated reply (NOT the operator's coaching), appends Marina's reply to the email thread state, marks `replied`. IG/FB/messenger return 501 with a clear "not yet implemented" detail so SR's frontend NOT_CONNECTED_STATUSES set shows the calm "will be connected" notice. Status flips to `replied` only after a successful send, matching `/reply`'s convention.

## Tests

972 passing / 0 failures (baseline 966 + 6 new).

## Deployment

Pending — commit/push/deploy in step 16.
