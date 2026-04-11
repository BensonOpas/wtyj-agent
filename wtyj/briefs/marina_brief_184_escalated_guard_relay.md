# BRIEF 184 — Allow semi-escalation notifications from fully-escalated conversations
**Status:** Draft | **Files:** `wtyj/agents/social/social_agent.py`, new `wtyj/tests/marina/test_184_escalated_relay.py` | **Depends on:** Brief 162 (relay flow) | **Blocks:** None

## Context

SR reported: a customer asking about wheelchair accessibility on a fully-escalated WhatsApp conversation triggered Marina to say "I'm just waiting to hear back from the team" — but NO escalation appeared in the dashboard (0 open escalations). Benson confirmed via screenshot.

**Root cause:** the `fully_escalated` guard at `social_agent.py:222-242` catches ALL messages on fully-escalated conversations and returns Marina's reply directly WITHOUT checking for new semi-escalation/relay flags in the result. The normal semi-escalation creation path at lines 505-555 (which calls `create_pending_notification('relay', ...)`) is NEVER reached because the guard returns at line 242 before processing gets that far.

Verified in production: conversation `69d41ae77d2c605d08114697` has `fully_escalated: true`, ONE old resolved escalation (id=74), and ZERO pending notifications for the wheelchair question despite Marina clearly being in a "waiting for team" state.

**The wheelchair question scenario:** customer mentions wheelchair accessibility → Marina can't answer from client.json → Marina's response includes `semi_escalation: true` + `relay_question` → but the guard doesn't check these flags → notification never created → operator never sees it → customer waits forever.

## Why This Approach

Add semi-escalation detection to the fully-escalated guard (lines 222-242) — check Marina's response for `semi_escalation: true` and create a relay notification if present. This is the same logic as lines 505-542 but adapted for the escalated path. Rejected: resetting `fully_escalated` on resolution (would change the conversation behavior for all subsequent messages, and the escalated path is still useful for keeping Marina in a simplified mode).

## Instructions

### Step 1: Add semi-escalation detection after the marina_agent call in the fully-escalated guard

In `social_agent.py`, after line 235 (`bm_logger.log("whatsapp_escalated_reply"...)`), insert the semi-escalation detection block:

```python
        # Brief 184: even in fully-escalated mode, Marina may flag a relay question
        # (e.g. wheelchair accessibility) that the operator needs to answer. Create
        # the notification so it appears in the dashboard.
        # Note: semi_escalation and requires_human are TOP-LEVEL keys in the
        # marina_agent response (not inside the "flags" dict).
        if esc_result.get("semi_escalation"):
            _relay_q = esc_result.get("relay_question", "(no question captured)")
            _relay_token = uuid.uuid4().hex[:12]
            _cname = fields.get("customer_name") or from_name or "Unknown"
            _ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
            _alert_subject = f"[RELAY-{_relay_token}] {_ref} - {_cname}"
            _alert_body = (
                f"Customer: {_cname} (WhatsApp: {phone})\n"
                f"Their question: {_relay_q}\n\n"
                f"Booking context:\n"
                f"  Trip: {fields.get('service_key', '')} | "
                f"Date: {fields.get('date', '')} | "
                f"Guests: {fields.get('guests', '')}\n"
                f"  Ref: {_ref}\n\n"
                f"INSTRUCTIONS: Reply to this email with your answer.\n"
                f"Marina will relay it to the customer in her own words."
            )
            state_registry.create_pending_notification(
                'relay', 'whatsapp', phone, _cname,
                _alert_subject, _alert_body, relay_token=_relay_token)
            flags["awaiting_relay"] = True
            flags["relay_token"] = _relay_token
            flags["relay_question"] = _relay_q
            bm_logger.log("whatsapp_escalated_semi_relay", phone=phone,
                          relay_question=_relay_q, relay_token=_relay_token)
```

Also add: check for `requires_human: true` on the fully-escalated path. `requires_human` is a TOP-LEVEL key in marina_agent's response (NOT inside `flags`). If Marina flags it and it's not already a semi-escalation, create a new full escalation:

```python
        _esc_req_human = esc_result.get("requires_human")
        if _esc_req_human and not esc_result.get("semi_escalation"):
            _cname = fields.get("customer_name") or from_name or "Unknown"
            _ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
            _esc_note = esc_result.get("internal_note", "")
            state_registry.create_pending_notification(
                'escalation', 'whatsapp', phone, _cname,
                f"[ESCALATION] {_ref} - {_cname} (WhatsApp: {phone}) - {_esc_note[:200]}",
                f"=== RE-ESCALATION (fully_escalated conversation) ===\n"
                f"Customer: {_cname}\nNew issue: {_esc_note}\n\n"
                f"=== CHAT LOG ===\n" + "\n".join(
                    f"[{m.get('role','?').upper()}] {m.get('text','')}" for m in (history or [])
                ))
            bm_logger.log("whatsapp_escalated_re_escalation", phone=phone)
```

This goes between the `bm_logger.log` at line 235 and the reply timestamp at line 237.

### Step 2: Verify the uuid import

Confirm `import uuid` is present at the top of `social_agent.py`. Check line ~5.

## Tests

Create `wtyj/tests/marina/test_184_escalated_relay.py`:

1. **Semi-escalation in fully-escalated creates notification.** Mock `marina_agent.process_message` to return `{"semi_escalation": true, "relay_question": "Can the boat accommodate a wheelchair?", "reply": "checking with team..."}`. Set up a conversation with `fully_escalated: true`. Call `handle_incoming_whatsapp_message`. Verify `create_pending_notification` was called with notification_type='relay'.

2. **Normal message in fully-escalated does NOT create notification.** Same setup but Marina returns a normal reply without semi_escalation. Verify `create_pending_notification` was NOT called.

3. **Re-escalation (requires_human) in fully-escalated creates notification.** Marina returns `{"requires_human": true, "flags": {}, "reply": "I'll escalate this...", "intents": ["complaint"]}` (requires_human is a TOP-LEVEL key per the marina_agent schema, NOT inside flags). Verify notification with type='escalation' is created.

**Scope note:** the email poller has an identical fully-escalated guard at `email_poller.py:758-782` with the same bug. This brief only fixes the WhatsApp (social_agent.py) path because it's the active production channel. The email poller fix is deferred — the poller is being rebuilt (Brief 182) and the same pattern should be added there as a follow-up.

## Success Condition

864 baseline + 3 new tests = **867 passing / 0 failures**. When Marina flags a relay question on a fully-escalated conversation, a notification appears in the dashboard. The wheelchair scenario produces a visible semi-escalation.

## Rollback

`git revert <commit>`, deploy. Fully-escalated conversations return to the current behavior (no new notifications). The workaround is to manually clear `fully_escalated` from the booking state.
