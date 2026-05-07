# EXPLANATION 214 — POST /escalations/:id/guidance

Plain-English explanation of commit `7f3f856` for an operator who doesn't read code.

## What was missing

Brief 213 made the dashboard smart enough to know whether an escalation is in "soft" or "hard" mode and let you flip between them. But the actual behavior of the two modes was incomplete:

- **Hard mode**: works end-to-end. Operator types reply → backend sends operator's text directly to the customer. Endpoint = `POST /escalations/:id/reply`.
- **Soft mode**: was missing the backend endpoint. Operator typed coaching for Marina → frontend showed "Saved. Marina connection will be completed by the Unboks team." (a graceful "the backend isn't there yet" notice). Endpoint = `POST /escalations/:id/guidance` — didn't exist.

Brief 214 adds that endpoint.

## What changed

A single new endpoint at `POST /escalations/:id/guidance`. It handles the soft-mode flow: operator coaches Marina, Marina reformulates the coaching into a polished customer-facing reply in her own voice, system sends Marina's reply to the customer.

Behavior:

1. Operator opens an escalation in soft mode (the "AI needs help" tab).
2. Operator types something like *"propose Wednesday 4pm and tell them we'll send a Google Meet invite"* in the composer.
3. Operator clicks "Send to Marina".
4. Frontend sends `{message: "propose Wednesday 4pm..."}` to `POST /escalations/:id/guidance`.
5. Backend validates: non-empty body, escalation exists, not in hard mode. (If hard mode → returns 409 telling the operator to use `/reply` or click "Hand back to AI" first.)
6. Backend dispatches by channel:
   - **WhatsApp**: backend sets a "Marina, you are in relay mode" flag, calls Marina with the operator's coaching as input, takes Marina's reformulated reply (e.g., *"Hi Calvin, Wednesday at 4pm works on our end. I'll send a Google Meet invite shortly."*), sends it to the customer via WhatsApp, stores it in the conversation thread.
   - **Email**: same idea. Loads the email conversation context (so Marina has booking history), calls Marina in relay mode, takes Marina's reply, smtp_sends it to the customer, appends Marina's reply (NOT the operator's coaching) to the thread state. The dashboard conversation view will show what the customer actually saw.
   - **Instagram / Facebook / Messenger**: returns 501 ("not yet implemented"). Frontend handles this gracefully (the calm "will be connected" notice). DM channels need an account_id resolution layer that the dashboard side doesn't have yet — separate brief.
7. Backend marks the escalation as "replied" so it falls out of the active-escalations filter.

The critical detail: in soft mode, the operator's RAW coaching never goes to the customer. Only Marina's reformulation does. This protects against operator typos, internal tone, or formatting that's wrong for a customer-facing message.

## What it does now

- Open any soft-mode escalation in `dashboard.unboks.org`.
- Type coaching in the "Reply to Marina" composer.
- Click "Send to Marina".
- Marina sends a polished reply on your behalf. Customer sees it within seconds.
- Escalation moves to "replied" status and disappears from the active-escalations view.

If you accidentally try to use this on a hard-mode (human-takeover) escalation, the backend now responds with a clear 409 telling you to either use the direct-reply composer or click "Hand back to AI" first.

## What it doesn't do (still pending Tier 2)

- **DM channels (IG/FB/Messenger)**: graceful 501 fallback. Brief 215 or later will wire the account_id resolution + Zernio DM send.
- **Approved learning auto-creation**: SR's contract says every operator answer in soft + hard modes should auto-create an approved learning entry that Marina can use next time someone asks the same thing. Backend does NOT do this yet. Brief 215.
- **"Your Info" / Settings → Marina's prompt**: Brief 216.
- **Escalation alert delivery to email/whatsapp/telegram on new escalation creation**: Brief 217.
- **Email forward / delete**: Brief 218.

## Files changed

- `wtyj/dashboard/api.py` — one new function `guidance_to_marina(escalation_id, req)` registered at `POST /escalations/:id/guidance`. Reuses the existing `EscalationReplyRequest` model (same `{message}` / `{answer}` body).
- `wtyj/tests/social/test_214_guidance_endpoint.py` — six new tests: WhatsApp happy path, email happy path, hard-mode 409, empty body 400, unsupported channel 501, Marina failure 500.
