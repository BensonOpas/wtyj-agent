# BRIEF 214 — POST /escalations/:id/guidance — soft-mode operator coaches Marina, Marina relays
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_214_guidance_endpoint.py` | **Depends on:** Brief 213 (mode column + hard-mode guard), Brief 210 (email reply path) | **Blocks:** SR's "Send to Marina" button on the soft-escalation composer (`EscalationReplyComposer` mode="soft" branch)

## Context

SR's frontend product contract distinguishes two operator workflows on an escalation:

- **Hard mode** ("Reply to customer") — operator writes a direct customer reply. AI is muted. The operator's exact text is sent to the customer. Backend endpoint: `POST /escalations/:id/reply`. Brief 210 + 213 already wire this.
- **Soft mode** ("Send to Marina") — operator writes coaching/guidance for Marina. Marina reformulates that into a customer-facing reply in her own voice and sends it. AI is NOT muted — Marina is still in the loop. Backend endpoint: `POST /escalations/:id/guidance`. Does not exist yet.

The frontend's `EscalationReplyComposer` (`unboks-org/.../components/inbox/EscalationReplyComposer.tsx:81-115`) already calls the backend at `POST /escalations/:id/guidance` for the soft branch and shows the "Saved. Marina connection will be completed by the Unboks team." fallback when the endpoint 404s. Today every soft-mode submit shows that fallback because the endpoint doesn't exist.

The "Marina relays operator text" pattern is well-precedented:

- The existing `/reply` WhatsApp branch (`wtyj/dashboard/api.py:1306-1343`) is exactly this flow: clear `relay_token`/`reply_times` from booking flags, call `marina_agent.process_message(customer_id, "", operator_text, fields, flags, channel="whatsapp", messages=history)` with `awaiting_relay` retained in flags, take `relay_result["reply"]`, send via `send_whatsapp_message`, store in thread, mark notification `replied`.
- The email-poller relay-receive path at `wtyj/agents/marina/email_poller.py:588-612` does the same for email when an operator replies to a `[RELAY-token]` email: call `marina_agent.process_message(customer_email, subj, operator_text, fields, flags)`, take `relay_result["reply"]`, `smtp_send` to customer, append `{"role": "marina", ...}` to thread `messages`.

`/guidance` is the dashboard-initiated equivalent of those flows, sharing the WhatsApp branch's structure with `/reply`'s WhatsApp branch (which ironically already does soft-mode relay) and adding a new email branch that mirrors `email_poller.py:588-612`.

## Why This Approach

- **Reuse `EscalationReplyRequest`.** Same body shape (`{message}` / `{answer}` accepted, `.text` accessor strips). No new model. Keeps the endpoints symmetric for the frontend (one request shape, two paths).
- **Hard-mode guard returns 409 not 400.** 409 Conflict is the right code per HTTP semantics ("the request conflicts with the current state of the resource"): the escalation is in hard mode, the operator should be using `/reply` instead. SR's contract Section 12 lists 409 as the standard for "wrong escalation state". Frontend can intercept 409 and either auto-redirect to `/reply` or show a "this escalation is in human-takeover mode, click 'Hand back to AI' to switch to soft" notice.
- **Channel coverage in this brief: whatsapp + email only.** The same channels `/reply` covers today (Brief 210). Instagram/Facebook/Messenger return 501 with a clear `detail` string so SR's frontend's `NOT_CONNECTED_STATUSES` set (`{0, 404, 501, 503}`) shows the calm "will be connected by the Unboks team" notice. Adding DM channel guidance is a follow-up brief — needs the channel-specific account_id + Zernio routing layer that `send_reply` from `webhook_server.py` provides; not a copy-paste from the WhatsApp branch.
- **Email branch mirrors `email_poller.py:588-612` not Brief 210's `/reply` email branch.** Brief 210's email `/reply` is verbatim send (hard mode); for `/guidance` (soft mode) we want Marina to relay. Pattern: load thread (via `email_get_conversation` to read fields + flags), set `awaiting_relay=True` in flags, call `marina_agent.process_message`, take Marina's reformulated reply, `smtp_send` it, append Marina's reply (NOT operator's text) to thread state via `email_append_assistant_message`. Critical: the operator's coaching text is NEVER sent to the customer in soft mode — only Marina's reformulation goes out.
- **Status flip to `replied` only on successful send.** Same convention as `/reply` (Brief 210 hotfix sets `replied` only after `smtp_send` succeeds). Failed sends → 500, status stays `pending`/`sent`. Operator can retry.
- **Rejected: bundle DM (IG/FB) coverage into this brief.** Doable but requires looking up `account_id` from prior conversation state, and the existing dashboard endpoints have NO precedent for sending DM messages from the dashboard side — `webhook_server.send_reply` is wired into the inbound webhook flow only. Channel surface to design: where to store account_id, how to route by Zernio channel, fallback when account_id is missing for legacy threads. That's a separate brief; for now, DM channels return 501 (graceful fallback in SR's UI).
- **Rejected: rename existing `/reply` WhatsApp branch from soft-relay to hard-verbatim** to enforce the "/reply = hard, /guidance = soft" symmetry strictly. The change is the right cleanup but risks breaking `test_125_escalation_reply.py::test_escalation_reply_sends_whatsapp` and any in-the-wild caller that relied on the old relay behavior. Out of scope. Brief 214 ADDS `/guidance`; it doesn't refactor `/reply`. Document the asymmetry: today, `/reply` WhatsApp = soft (legacy quirk from Brief 159), `/reply` email = hard (Brief 210). After 214, `/guidance` is unambiguously soft on both channels. SR's frontend already calls the right endpoint per mode (`/reply` for hard, `/guidance` for soft), so the legacy mixed `/reply` behavior never actually surfaces in normal operation.
- **Rejected: write to `email_append_assistant_message` with operator's text instead of Marina's reformulated text.** Tempting because `email_append_assistant_message` was added in Brief 210 specifically for the dashboard reply path, but using it that way for `/guidance` would silently lose the relay distinction in the audit trail — the dashboard conversation view would show the operator's coaching as if Marina sent it verbatim. Pass Marina's reformulated reply as the `body` parameter so the thread record reflects what was actually sent.

## Instructions

### Step 1 — Add `POST /escalations/:id/guidance` in `wtyj/dashboard/api.py`

Insert immediately after the existing `/reply` endpoint at `wtyj/dashboard/api.py:1376-1377` (i.e., after the `else: raise HTTPException(...)` that closes the `/reply` channel-dispatch). Reuse the existing `EscalationReplyRequest` model defined at `:1280-1290`.

```python
@router.post("/escalations/{escalation_id}/guidance", dependencies=[Depends(_check_auth)])
async def guidance_to_marina(escalation_id: int, req: EscalationReplyRequest):
    """Brief 214: soft-mode escalation. Operator writes guidance for Marina;
    Marina reformulates into a customer-facing reply in her own voice and
    sends it. Mirrors the relay pattern in /reply WhatsApp + email_poller
    relay-receive at email_poller.py:588-612.

    Pre-checks:
      - non-empty body
      - escalation exists
      - escalation.mode != 'hard' (operator should use /reply for hard)

    Per-channel branches:
      - whatsapp: marina_agent.process_message in relay mode → send_whatsapp_message
      - email:    marina_agent.process_message in relay mode → smtp_send
      - other:    501 (frontend shows "will be connected" notice)
    """
    if not req.text:
        raise HTTPException(status_code=400, detail="Guidance text required (field: 'message' or 'answer')")

    esc = next((e for e in state_registry.get_all_escalations()
                if e["id"] == escalation_id), None)
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")

    if esc.get("mode") == "hard":
        raise HTTPException(status_code=409,
            detail="Escalation is in hard mode (human takeover). Use /reply for direct customer reply, or /handback to return to AI control.")

    channel = esc.get("channel", "whatsapp")
    customer_id = esc.get("customer_id", "")

    if channel == "whatsapp" and customer_id:
        wa_state = state_registry.wa_get_booking_state(customer_id)
        wa_fields = wa_state.get("fields", {})
        wa_flags = wa_state.get("flags", {})
        wa_history = state_registry.wa_get_history(customer_id, limit=10)

        # Mirror /reply's relay-mode flag setup (api.py:1312-1317): keep
        # awaiting_relay so Marina enters RELAY MODE; clear ephemeral
        # token/timing keys so the prompt doesn't see stale relay metadata.
        agent_flags = dict(wa_flags)
        agent_flags["awaiting_relay"] = True  # Brief 214: explicit set for /guidance entry point
        for rk in ("relay_token", "reply_times"):
            agent_flags.pop(rk, None)

        relay_result = marina_agent.process_message(
            customer_id, "", req.text,
            wa_fields, agent_flags,
            channel="whatsapp", messages=wa_history,
        )
        relay_reply = relay_result.get("reply", "")
        if not relay_reply:
            raise HTTPException(status_code=500, detail="Marina returned empty reply")

        sent_ok = send_whatsapp_message(customer_id, relay_reply)
        if not sent_ok:
            raise HTTPException(status_code=500,
                detail="Failed to send WhatsApp reply (Zernio account missing or send failed)")

        state_registry.wa_store_message(customer_id, "assistant", relay_reply)
        bm_logger.log("dashboard_guidance_sent_whatsapp",
                      phone=customer_id, escalation_id=escalation_id)

        # Clear the relay flags from persistent state (one guidance = one relay)
        wa_flags.pop("awaiting_relay", None)
        wa_flags.pop("relay_token", None)
        wa_flags.pop("relay_question", None)
        state_registry.wa_save_booking_state(
            customer_id, wa_fields, wa_flags,
            wa_state.get("completed_bookings", []))

        state_registry.update_notification_status(escalation_id, "replied")
        return {"ok": True, "reply": relay_reply, "channel": "whatsapp"}

    elif channel == "email":
        if not customer_id or "@" not in customer_id:
            raise HTTPException(status_code=400,
                detail="Email escalation missing valid email address")

        # Load the email thread state for fields + flags context (mirrors
        # email_poller.py:588 which reads from customer_th).
        thread_key = state_registry._find_email_thread_key_for(customer_id)
        if thread_key:
            email_conv = state_registry.email_get_conversation(thread_key)
            email_state = email_conv.get("booking_state", {}) or {}
            email_fields = email_state.get("fields", {}) or {}
            email_flags = dict(email_state.get("flags", {}) or {})
        else:
            # Fresh email conversation — no prior thread state. Marina still
            # relays the operator's text but with no booking context.
            email_fields = {}
            email_flags = {}

        email_flags["awaiting_relay"] = True
        for rk in ("relay_token", "reply_times"):
            email_flags.pop(rk, None)

        subject = esc.get("subject") or "Re: Unboks"
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject

        try:
            relay_result = marina_agent.process_message(
                customer_id, subject, req.text,
                email_fields, email_flags,
            )
        except Exception as exc:
            bm_logger.log("dashboard_guidance_marina_failed",
                          email=customer_id, escalation_id=escalation_id,
                          error=str(exc)[:200])
            raise HTTPException(status_code=500,
                detail=f"Marina relay failed: {str(exc)[:120]}")

        relay_reply = relay_result.get("reply", "")
        if not relay_reply:
            raise HTTPException(status_code=500, detail="Marina returned empty reply")

        try:
            smtp_send(customer_id, subject, relay_reply)
        except Exception as exc:
            bm_logger.log("dashboard_guidance_send_failed",
                          email=customer_id, escalation_id=escalation_id,
                          error=str(exc)[:200])
            raise HTTPException(status_code=500,
                detail=f"Failed to send email reply: {str(exc)[:120]}")

        # Append Marina's REFORMULATED reply to thread state (NOT the operator's
        # coaching text). The dashboard conversation view should reflect what
        # the customer actually saw.
        appended_thread_key = state_registry.email_append_assistant_message(
            customer_id, relay_reply)
        bm_logger.log("dashboard_guidance_sent_email",
                      email=customer_id, escalation_id=escalation_id,
                      thread_key=appended_thread_key or "(no thread match)")

        state_registry.update_notification_status(escalation_id, "replied")
        return {"ok": True, "reply": relay_reply, "channel": "email"}

    else:
        raise HTTPException(status_code=501,
            detail=f"Channel '{channel}' guidance flow not yet implemented (frontend will show graceful fallback)")
```

### Step 2 — No other source files change

The Marina prompt, the relay-mode behavior, and the channel senders are all already wired. `/guidance` is purely a new endpoint composing existing helpers.

## Tests (6)

In `wtyj/tests/social/test_214_guidance_endpoint.py`. Mirror the pattern in `test_210_email_escalation_reply.py` (TestClient + real state_registry + mock the Marina + send paths).

1. **`test_guidance_whatsapp_relay_succeeds`** — seed soft-mode WhatsApp escalation, mock `marina_agent.process_message` to return `{"reply": "reformulated text"}` and `send_whatsapp_message` to return True. POST `/guidance` with `{message: "tell them weight limit is 150kg"}`. Assert 200, `reply == "reformulated text"`, channel=whatsapp, escalation status flipped to `replied`. Verify Marina was called with the operator's text as the third arg. Verify `wa_store_message` recorded Marina's reply.

2. **`test_guidance_email_relay_succeeds`** — seed soft-mode email escalation, write a fake thread to `email_thread_state.json` (via tmp_path + monkeypatch on `_get_email_state_path`), mock `marina_agent.process_message` to return `{"reply": "Hi Calvin, ..."}`, mock `smtp_send`. POST `/guidance` with `{message: "propose Wed 4pm"}`. Assert 200, `reply` matches mock, smtp_send called with customer_id + subject + Marina's reply.

3. **`test_guidance_rejects_hard_mode_with_409`** — seed escalation with mode="hard". POST `/guidance`. Assert 409, detail mentions "hard mode" and `/reply` or `/handback`.

4. **`test_guidance_empty_body_returns_400`** — POST `/guidance` with `{message: "   "}`. Assert 400, detail mentions "guidance" or "required".

5. **`test_guidance_unsupported_channel_returns_501`** — seed escalation with channel="instagram", mode="soft". POST `/guidance`. Assert 501, detail mentions "instagram" and "not yet implemented".

6. **`test_guidance_marina_failure_returns_500_and_status_unchanged`** — seed soft-mode WhatsApp escalation, mock `marina_agent.process_message` to raise. POST `/guidance`. Assert 500, escalation status remains `sent`/`pending` (not `replied`).

Baseline: 966 (Brief 213). Target: 972 passing / 0 failures.

## Success Condition

After deploy, SR's frontend EscalationReplyComposer in soft mode submits successfully:
1. Operator opens an escalation, the soft tab is selected (because `escalationMode == "soft"` from Brief 213).
2. Operator types coaching: "Calvin, propose Wednesday 4pm and tell them we'll send a Google Meet invite."
3. Operator clicks "Send to Marina".
4. Backend `POST /guidance` returns 200 with Marina's reformulated reply.
5. Customer receives Marina's polished version (not the operator's raw coaching text).
6. Escalation flips to `replied` status.
7. Live verification (post-deploy):
   ```bash
   ssh root@108.61.192.52 'docker exec wtyj-unboks curl -s -X POST \
     -H "Authorization: Bearer $(cat /app/data/session_token)" \
     -H "Content-Type: application/json" \
     -d "{\"message\": \"test\"}" \
     http://localhost:8001/dashboard/api/escalations/9999/guidance'
   ```
   Expected: 404 (no escalation 9999) — confirms endpoint exists and routes correctly.

## Rollback

`git revert <commit>`, push, canary redeploys. Endpoint disappears, frontend falls back to "Saved. Marina connection will be completed by the Unboks team." notice. No data corruption — all writes were either (a) successful and the customer already received the reply, or (b) failed and rolled back via the 500 status. The new endpoint is purely additive; no existing code path was modified.
