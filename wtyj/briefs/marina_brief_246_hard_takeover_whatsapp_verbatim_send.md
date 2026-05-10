# BRIEF 246 — Hard-takeover WhatsApp /reply: send operator text verbatim, store as role=operator

**Status:** Draft | **Files:** wtyj/dashboard/api.py, wtyj/tests/social/test_213_escalation_control.py | **Depends on:** Brief 245 (`03748b4`) | **Blocks:** none

## Context

Issue #11 (Calvin live-test verification blocker) — during a hard-takeover WhatsApp test, Calvin typed an intentionally abusive operator reply into the dashboard composer. Observed:

1. The customer received a Marina-style safety refusal: `"That's not something I'll engage with. If you need help with your Monday appointment or anything else, I'm here."`
2. The dashboard conversation trail showed the same message stored as role=`MARINA`.

Both are wrong. The expected behavior for hard takeover (operator IS the author of the reply) is verbatim-send + role=`operator`, mirroring the email branch's Brief 210 behavior.

**Root cause traced via grep + read:**
- `wtyj/dashboard/api.py:2418-2468` — the `/escalations/{id}/reply` WhatsApp branch unconditionally routes operator text through `marina_agent.process_message(customer_id, "", req.text, ...)` regardless of escalation mode. Marina is asked to process the operator's text as if it were the customer's message body.
- When Calvin's text was abusive, Marina (correctly) refused to engage and generated the safety refusal phrase. The branch then sent that refusal verbatim via `send_whatsapp_message` (line 2440) and stored it via `wa_store_message(customer_id, "assistant", relay_reply)` (line 2443) — surfacing as MARINA in the dashboard.
- The email branch at lines 2470-2511 (Brief 210) correctly distinguishes hard mode: `smtp_send(customer_id, subject, operator_reply)` sends the operator text verbatim, and `email_append_assistant_message(customer_id, operator_reply, role="operator")` stores it with the right role.
- The WhatsApp branch was never split when Brief 210 added the hard-mode-verbatim email distinction. WhatsApp `/reply` has always been the soft-mode-relay path; hard-mode WhatsApp had no dedicated verbatim path, so it fell through to relay-mode reformulation.

**Verified read-only:**
- `wtyj/shared/state_registry.py:1028-1036` `wa_store_message(phone, role, text)` accepts any role string — no enum check, no validation.
- `wtyj/agents/social/whatsapp_client.py:111` `send_whatsapp_message(customer_id, text) -> bool` is the customer-facing WhatsApp send (NOT `send_dm_reply` which is Brief 240's operator-alert path).
- Brief 213 introduced `/escalations/{id}/takeover` which sets `mode='hard'` + `human_takeover_at` timestamp + `ai_muted=true`. Brief 213's existing test (`test_213_escalation_control.py:82-108`) confirms the takeover endpoint does NOT clobber escalation `status="open"`. So when an operator replies in hard takeover, `esc.get("mode") == "hard"` is reliable.

## Why This Approach

**Considered:** Adding a content-classifier check to operator text (Python keyword list or new Claude moderation call) before send. **Rejected:** (a) Python content classification violates CLAUDE.md Rule 5 (no Python language classifiers). (b) A second Claude call per operator reply adds latency to a synchronous dashboard action. (c) Issue #11 explicitly says hard-mode acceptable text "send the operator text verbatim" — so the design IS "operator-takes-responsibility, no AI moderation in hard mode". Filtering belongs to soft-mode reformulation, not hard-mode verbatim.

**Considered:** Adding a `safety_blocked: bool` field to Marina's tool-use schema for the soft-mode case (Marina sets it true when she would refuse; soft branch checks the flag and returns 409 instead of sending). **Rejected for this brief:** soft-mode "what if operator coaching produces a refusal" is a different bug and Calvin's observed scenario was hard mode, not soft. Adding Marina schema fields is invasive (touches prompt + schema + multiple branches). Defer to a future brief if a real soft-mode-blocked case is observed.

**Considered:** Routing hard-mode WhatsApp through a new endpoint like `/escalations/{id}/hard-reply`. **Rejected:** the email branch already handles both modes in `/reply` by checking `esc.get("mode")` (well, actually email always sends verbatim because there's no other email path; soft email coaching uses `/guidance`). The WhatsApp branch can do the same — same endpoint, behavior depends on stored mode. Frontend doesn't need a new endpoint or a contract change; it just keeps calling `/reply` and the backend chooses the right behavior. Symmetric with email.

**Tradeoff — when mode is missing/None (legacy escalations):** there are escalation rows where `mode IS NULL` (verified during issue #1 verification — 6 of the 10 most-recent unboks rows have `mode=None`, all from before Brief 239's mode-wiring went live). For those rows, `esc.get("mode") == "hard"` is False → falls through to the existing relay-mode behavior. That's a safe fallback for legacy rows: they were created before hard-mode-WhatsApp-verbatim existed; the operator probably wants the historical behavior on those.

**Tradeoff — frontend role rendering:** the frontend's conversation trail must render role=`operator` distinctly from role=`assistant` (otherwise the trail still looks like a Marina message even though the backend now stores it correctly). The email branch (Brief 210) has been writing role=`operator` for ~6 weeks, so the frontend should already handle it. **Frontend contract** for SR documented in OUTPUT 246: WhatsApp now also writes role=`operator` in `whatsapp_threads` for hard-mode operator replies — the same render rule that handles email-side `operator` role applies.

## Instructions

### Step 1 — Split the WhatsApp branch in `/escalations/{id}/reply` by escalation mode

In `wtyj/dashboard/api.py:2418-2468`, the current WhatsApp branch reads:

```python
    if channel == "whatsapp" and customer_id:
        wa_state = state_registry.wa_get_booking_state(customer_id)
        wa_fields = wa_state.get("fields", {})
        wa_flags = wa_state.get("flags", {})
        wa_history = state_registry.wa_get_history(customer_id, limit=10)

        agent_flags = dict(wa_flags)
        # Brief 159: keep awaiting_relay so Marina enters RELAY MODE and
        # reformulates the operator's answer instead of generating a fresh reply.
        # Mirrors email_poller.py:661-663 which does the same.
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
            raise HTTPException(status_code=500, detail="Failed to send WhatsApp reply (Zernio account missing or send failed)")
        state_registry.wa_store_message(customer_id, "assistant", relay_reply)
        bm_logger.log("dashboard_relay_sent", phone=customer_id, escalation_id=escalation_id)

        wa_flags.pop("awaiting_relay", None)
        wa_flags.pop("relay_token", None)
        wa_flags.pop("relay_question", None)
        state_registry.wa_save_booking_state(
            customer_id, wa_fields, wa_flags,
            wa_state.get("completed_bookings", []))

        state_registry.update_notification_status(escalation_id, "replied")

        # Brief 215: auto-create approved learning entry from operator answer.
        # Wrapped in try/except — never block the customer reply on a write
        # failure here.
        try:
            state_registry.save_escalation_learning(
                conversation_id=customer_id, channel="whatsapp",
                source_question=state_registry._last_customer_message_for(customer_id, "whatsapp"),
                human_answer=req.text,
                status="approved", ai_may_use=True)
        except Exception as _learn_exc:
            bm_logger.log("learning_write_failed", error=str(_learn_exc)[:120],
                          escalation_id=escalation_id, source="reply_whatsapp")

        return {"ok": True, "reply": relay_reply}
```

Replace with the following — adds a hard-mode verbatim path BEFORE the existing relay-mode path; relay-mode path unchanged for backward compat:

```python
    if channel == "whatsapp" and customer_id:
        # Brief 246: hard mode = operator IS the author. Send verbatim.
        # Soft/legacy mode = relay (Marina reformulates).
        # Mirrors the email branch at lines 2470-2511 (Brief 210).
        if esc.get("mode") == "hard":
            operator_reply = req.text
            sent_ok = send_whatsapp_message(customer_id, operator_reply)
            if not sent_ok:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to send WhatsApp reply (Zernio account missing or send failed)")
            state_registry.wa_store_message(customer_id, "operator", operator_reply)
            bm_logger.log("dashboard_hard_reply_sent",
                          phone=customer_id, escalation_id=escalation_id,
                          mode="hard", channel="whatsapp")
            state_registry.update_notification_status(escalation_id, "replied")

            # Brief 215: auto-create approved learning entry from operator answer.
            try:
                state_registry.save_escalation_learning(
                    conversation_id=customer_id, channel="whatsapp",
                    source_question=state_registry._last_customer_message_for(customer_id, "whatsapp"),
                    human_answer=operator_reply,
                    status="approved", ai_may_use=True)
            except Exception as _learn_exc:
                bm_logger.log("learning_write_failed", error=str(_learn_exc)[:120],
                              escalation_id=escalation_id, source="reply_whatsapp_hard")

            return {"ok": True, "reply": operator_reply,
                    "channel": "whatsapp", "role": "operator"}

        # ── Soft / legacy / no-mode path: existing relay behavior unchanged ─
        wa_state = state_registry.wa_get_booking_state(customer_id)
        wa_fields = wa_state.get("fields", {})
        wa_flags = wa_state.get("flags", {})
        wa_history = state_registry.wa_get_history(customer_id, limit=10)

        agent_flags = dict(wa_flags)
        # Brief 159: keep awaiting_relay so Marina enters RELAY MODE and
        # reformulates the operator's answer instead of generating a fresh reply.
        # Mirrors email_poller.py:661-663 which does the same.
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
            raise HTTPException(status_code=500, detail="Failed to send WhatsApp reply (Zernio account missing or send failed)")
        state_registry.wa_store_message(customer_id, "assistant", relay_reply)
        bm_logger.log("dashboard_relay_sent", phone=customer_id, escalation_id=escalation_id)

        wa_flags.pop("awaiting_relay", None)
        wa_flags.pop("relay_token", None)
        wa_flags.pop("relay_question", None)
        state_registry.wa_save_booking_state(
            customer_id, wa_fields, wa_flags,
            wa_state.get("completed_bookings", []))

        state_registry.update_notification_status(escalation_id, "replied")

        # Brief 215: auto-create approved learning entry from operator answer.
        # Wrapped in try/except — never block the customer reply on a write
        # failure here.
        try:
            state_registry.save_escalation_learning(
                conversation_id=customer_id, channel="whatsapp",
                source_question=state_registry._last_customer_message_for(customer_id, "whatsapp"),
                human_answer=req.text,
                status="approved", ai_may_use=True)
        except Exception as _learn_exc:
            bm_logger.log("learning_write_failed", error=str(_learn_exc)[:120],
                          escalation_id=escalation_id, source="reply_whatsapp")

        return {"ok": True, "reply": relay_reply}
```

**Why the hard-mode block goes BEFORE the soft path:** early-return pattern keeps the soft-path block visually identical to the original (single replace; reviewer can verify nothing changed in soft mode). Inserting the new branch INSIDE the existing flow with an else would have shifted indentation on the unchanged code.

**Why hard-mode block does NOT update `wa_flags` or call `wa_save_booking_state`:** the hard-mode operator IS not Marina-orchestrating the flow; relay-mode flags (`awaiting_relay`, `relay_token`, `relay_question`) only matter for the Marina-reformulation path. In hard mode, the operator has already taken over — `ai_muted=true` is set by the prior `/takeover` call (Brief 213); these relay flags shouldn't exist in hard-mode state. If they do (legacy stale state), they're harmless — they only affect Marina's NEXT inbound-message processing, which won't happen because `ai_muted=true`.

**Why hard-mode block KEEPS the Brief 215 learning save:** the operator's text IS the canonical answer — saving it as an approved learning is exactly the same use case as the relay path. The wrapped try/except matches the existing pattern.

### Step 2 — Add 3 new tests to `wtyj/tests/social/test_213_escalation_control.py`

Append to the existing per-source-module file (per Brief 236 rule). The file already covers Brief 213's takeover endpoint and is the right home for "what happens after takeover when operator replies."

Tests to add:

```python


# ── Brief 246: hard-takeover WhatsApp /reply sends verbatim ─

def test_hard_mode_whatsapp_reply_sends_verbatim_not_through_marina(monkeypatch):
    """Brief 246: when escalation.mode='hard' (set by /takeover), a WhatsApp
    /reply MUST send operator text verbatim via send_whatsapp_message — NOT
    route through marina_agent.process_message which would reformulate or
    refuse abusive text. Mirrors email branch Brief 210 verbatim behavior."""
    from shared import state_registry
    from dashboard import api as dapi

    customer_id = "246_hard_wa_verbatim_phone"
    # Seed a hard-mode WhatsApp escalation
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation",
        channel="whatsapp",
        customer_id=customer_id,
        customer_name="Test Customer",
        subject="Marina escalated",
        body="needs help",
        mode="hard",
    )

    # Capture send_whatsapp_message + verify Marina is NOT called
    sent = {}
    monkeypatch.setattr(dapi, "send_whatsapp_message",
                         lambda phone, text: sent.update(phone=phone, text=text) or True)
    marina_called = {"called": False}
    def fail_if_called(*a, **k):
        marina_called["called"] = True
        return {"reply": "MARINA SHOULD NOT BE CALLED"}
    monkeypatch.setattr(dapi.marina_agent, "process_message", fail_if_called)

    operator_text = "Hi, this is Calvin from Unboks. Quick test reply."
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": operator_text}, headers=_auth(token))

    assert r.status_code == 200, f"reply failed: {r.text}"
    body = r.json()
    assert body["ok"] is True
    assert body["reply"] == operator_text
    assert body.get("role") == "operator"
    assert body.get("channel") == "whatsapp"
    assert sent.get("text") == operator_text, (
        f"send_whatsapp_message was called with {sent.get('text')!r}, "
        f"expected verbatim {operator_text!r}")
    assert marina_called["called"] is False, (
        "marina_agent.process_message MUST NOT be called in hard-mode WhatsApp /reply")


def test_hard_mode_whatsapp_reply_stores_role_operator_not_assistant(monkeypatch):
    """Brief 246: stored conversation trail row uses role='operator' so the
    dashboard does NOT render it as Marina/assistant. Mirrors email branch
    Brief 210 storage behavior."""
    from shared import state_registry
    from dashboard import api as dapi

    customer_id = "246_hard_wa_role_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation",
        channel="whatsapp",
        customer_id=customer_id,
        customer_name="Test Customer",
        subject="Marina escalated",
        body="needs help",
        mode="hard",
    )
    monkeypatch.setattr(dapi, "send_whatsapp_message", lambda p, t: True)

    operator_text = "Operator reply for role storage test."
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": operator_text}, headers=_auth(token))
    assert r.status_code == 200

    # Verify the stored row has role='operator'
    history = state_registry.wa_get_history(customer_id, limit=5)
    assert any(m["role"] == "operator" and m["text"] == operator_text
               for m in history), (
        f"expected role='operator' row with verbatim text; history={history}")
    # Should NOT have stored as 'assistant' (the bug)
    assert not any(m["role"] == "assistant" and m["text"] == operator_text
                   for m in history), (
        f"hard-mode operator text MUST NOT be stored as role='assistant'; "
        f"history={history}")


def test_soft_mode_whatsapp_reply_unchanged_still_routes_through_marina(monkeypatch):
    """Brief 246: regression — when escalation.mode is NOT 'hard' (soft or
    None for legacy rows), WhatsApp /reply preserves the existing Brief 159
    relay behavior: routes through marina_agent.process_message and stores
    Marina's reformulation as role='assistant'."""
    from shared import state_registry
    from dashboard import api as dapi

    customer_id = "246_soft_wa_relay_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation",
        channel="whatsapp",
        customer_id=customer_id,
        customer_name="Test Customer",
        subject="Marina escalated",
        body="needs help",
        mode="soft",
    )

    monkeypatch.setattr(dapi, "send_whatsapp_message", lambda p, t: True)
    monkeypatch.setattr(
        dapi.marina_agent, "process_message",
        lambda *a, **k: {"reply": "Marina-reformulated reply", "flags": {}})

    operator_text = "Operator coaching text — Marina should reformulate."
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": operator_text}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    # Soft-mode response is the Marina reformulation, not the verbatim text.
    assert body["reply"] == "Marina-reformulated reply"
    # No 'role' field in the soft response (existing contract — only the new
    # hard-mode response includes role).

    history = state_registry.wa_get_history(customer_id, limit=5)
    assert any(m["role"] == "assistant" and m["text"] == "Marina-reformulated reply"
               for m in history), (
        f"soft-mode reply MUST still store as role='assistant'; history={history}")
```

The test file already imports `_login()` and `_auth(token)` helpers at the top. The `client = TestClient(app)` import is also already present (Brief 213 set this up). Verify before writing — if missing, the test file's first 30 lines need to be inspected.

### Step 3 — Out of scope (documented)

- **Soft-mode "what if Marina would refuse to reformulate operator's coaching text"** — a separate bug not observed in Calvin's test. Would require Marina tool-schema change (`safety_blocked: bool`). Defer to future brief if a real case is observed.
- **Pre-send safety filter for hard-mode operator text.** Hard mode = operator-takes-responsibility, no AI moderation needed. Per issue #11's "acceptable hard operator reply still sends correctly" — verbatim send is the design.
- **Frontend rendering of role='operator' in WhatsApp conversation trail.** Email already writes role='operator' (Brief 210), so the frontend should already handle it; this brief just adds WhatsApp parity. Confirmed in OUTPUT 246; SR notified if a frontend gap exists.
- **Backfill of historical mistakenly-stored Marina-refusal rows in `whatsapp_threads`.** Out of scope; rare; specific to Calvin's one test.
- **Same fix for `/escalations/{id}/guidance` endpoint.** `/guidance` is explicitly Brief 214's soft-mode path — it returns 409 if mode=hard (verified at api.py:2538-2540). So `/guidance` is already gated correctly; only `/reply` needed the split.

## Tests

3 new tests in `wtyj/tests/social/test_213_escalation_control.py` (extends existing file per Brief 236 rule).

Expected after-test count: **1058 passing / 0 failures** (1055 baseline + 3 new = 1058).

## Success Condition

After this brief lands:
1. POST `/dashboard/api/escalations/{id}/reply` with `mode='hard'` + `channel='whatsapp'` → operator's text sent VERBATIM via `send_whatsapp_message`, no `marina_agent.process_message` call.
2. Stored row in `whatsapp_threads` has `role='operator'`, NOT `role='assistant'`.
3. Response body includes `"role": "operator"` so frontend can render distinct from Marina.
4. Soft/None-mode WhatsApp `/reply` behavior is BIT-for-BIT unchanged (relay through Marina, store as `assistant`, return reply only).
5. Email `/reply` branch (lines 2470-2511) is unchanged.
6. Calvin's exact scenario reproduced as a unit test: abusive operator text in hard-mode WhatsApp `/reply` does NOT generate a Marina refusal sent to the customer (test 1 proves Marina is never invoked in this path).
7. `/guidance` endpoint behavior unchanged (already 409s on hard mode).
8. Existing 1055 tests still pass.

## Rollback

Revert the brief commit:
```
git revert <brief-246-commit-sha>
git push origin main
```

This restores the unconditional Marina-relay behavior on WhatsApp `/reply`. CI will re-deploy in ~90s. No data migration needed; the `whatsapp_threads` rows already written with role='operator' before rollback are harmless (the table accepts any role string).
