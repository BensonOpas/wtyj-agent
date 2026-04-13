# BRIEF 192 — Email poller escalated guard: detect relay + re-escalation
**Status:** Draft | **Files:** `wtyj/agents/marina/email_poller.py` | **Depends on:** Brief 184 (same fix for WhatsApp/DMs) | **Blocks:** —

## Context

Brief 184 fixed the fully-escalated guard in `social_agent.py:240-284` — when Marina flags a `semi_escalation` (relay question) or `requires_human` (re-escalation) on a `fully_escalated` conversation, a notification is now created so the operator sees it.

The email poller's fully-escalated guard at `email_poller.py:618-642` has the SAME bug: it calls `marina_agent.process_message()` (line 624), sends the reply (line 628), persists state (lines 630-640), and hits `continue` (line 642) — **without ever checking `result.get("semi_escalation")` or `result.get("requires_human")`**. Both flags are silently dropped.

Real scenario: a customer's email conversation is fully escalated. The customer emails again asking "can we bring a wheelchair?" Marina's response includes `semi_escalation: true` and `relay_question: "wheelchair accessibility"`. The email poller sends Marina's holding reply but never creates a relay notification. The operator never sees the question. The customer waits forever.

## Why This Approach

Same fix pattern as Brief 184 (social_agent.py), adapted for the email poller's data structures (thread-based JSON state vs. WhatsApp booking state, `"email"` channel, email-specific relay fields like `relay_customer_email` and `relay_reply_subject`).

### Rejected alternatives

1. **Extract a shared escalated-guard function used by both social_agent and email_poller.** Rejected: the two guards have different data structures (WhatsApp uses `state_registry.wa_*` functions + `phone` as key; email uses thread dicts + JSON file + `from_email` as key). A shared function would need extensive parameter abstraction for minimal code-reuse gain. The duplicate ~20 lines are simpler and safer than a fragile shared abstraction.

## Instructions

### Step 1 — Add semi_escalation + requires_human checks after `marina_agent.process_message()`

In `email_poller.py`, between lines 627 (after `result = marina_agent.process_message(...)`) and 628 (before `smtp_send(from_email, ...)`), insert the two checks. Use the SAME relay notification pattern that already exists at `email_poller.py:869-911` (the non-escalated semi-escalation path) and the SAME re-escalation pattern at `email_poller.py:920-974` (the non-escalated requires_human path).

Insert after line 627:

```python
                    # Brief 192: even in fully-escalated mode, Marina may flag
                    # a relay question or re-escalation. Same fix as Brief 184
                    # for social_agent.py.
                    if result.get("semi_escalation"):
                        _relay_q = result.get("relay_question", "(no question captured)")
                        _relay_token = uuid.uuid4().hex[:12]
                        _cname = th["fields"].get("customer_name") or from_email
                        _ref = _resolve_booking_ref(th)
                        th["flags"]["awaiting_relay"] = True
                        th["flags"]["relay_token"] = _relay_token
                        th["flags"]["relay_question"] = _relay_q
                        th["flags"]["relay_customer_email"] = from_email
                        th["flags"]["relay_reply_subject"] = "Re: " + subj
                        _relay_alert = (
                            f"Customer: {_cname} <{from_email}>\n"
                            f"Their question: {_relay_q}\n\n"
                            f"Booking context:\n"
                            f"  Trip: {th['fields'].get('service_key', '')} | "
                            f"Date: {th['fields'].get('date', '')} | "
                            f"Guests: {th['fields'].get('guests', '')}\n"
                            f"  Ref: {_ref}\n\n"
                            f"INSTRUCTIONS: Reply to this email with your answer.\n"
                            f"Marina will relay it to the customer in her own words."
                        )
                        state_registry.create_pending_notification(
                            'relay', 'email', from_email, _cname,
                            f"[RELAY-{_relay_token}] {_ref} - {_cname}",
                            _relay_alert, relay_token=_relay_token)
                        log(f"Escalated semi-relay: {from_email} re: {_relay_q[:60]}")

                    if result.get("requires_human") and not result.get("semi_escalation"):
                        _cname = th["fields"].get("customer_name") or from_email
                        _ref = _resolve_booking_ref(th)
                        _esc_note = result.get("internal_note", "")
                        _chat_lines = []
                        for _m in th.get("messages", []):
                            _chat_lines.append(f"[{_m.get('role','?').upper()}] {_m.get('body','')}")
                        state_registry.create_pending_notification(
                            'escalation', 'email', from_email, _cname,
                            f"[ESCALATION] {_ref} - {_cname} ({from_email}) - {_esc_note[:200]}",
                            f"=== RE-ESCALATION (fully_escalated email) ===\n"
                            f"Customer: {_cname} <{from_email}>\n"
                            f"New issue: {_esc_note}\n\n"
                            f"=== CHAT LOG ===\n" + "\n".join(_chat_lines))
                        log(f"Escalated re-escalation: {from_email}")
```

Note: the relay alert says "Marina will relay it" — matching the existing relay strings at `email_poller.py:886` and `social_agent.py:258`. All relay instruction strings should eventually be updated to read from `config_loader.get_business().get("agent_name", "CSA")`, but that's a separate sweep across all 4 relay sites, not this brief's scope.

### Step 2 — Do NOT touch

- The non-escalated semi-escalation path (lines 869-916) — already works
- The non-escalated requires_human path (lines 920-974) — already works
- `social_agent.py`'s escalated guard (Brief 184, already fixed) — untouched
- Any other file

## Tests

Create `wtyj/tests/marina/test_192_email_escalated_guard.py` with 2 tests:

Both tests use the `_SentinelException(BaseException)` pattern from `test_146_adamus_second_client.py:66-98` to break out of `main()`'s `while True` loop after one iteration. The full mock chain for each test:

1. `monkeypatch.setattr(email_poller, "EMAIL_ADDR", "test@example.com")`
2. `monkeypatch.setattr(email_poller, "REFRESH_TOKEN_PATH", str(tmp_path / "token.txt"))` (write "fake" to the file)
3. `monkeypatch.setattr(email_poller, "THREAD_STATE_PATH", str(tmp_path / "state.json"))` (write pre-seeded thread state with `fully_escalated: True` via `save_json`)
4. Mock `imap_connect` → returns a `MagicMock` IMAP object where:
   - `.select()` returns `("OK", [b"1"])`
   - `.noop()` returns `("OK", [b""])`
   - `.uid("search", ...)` returns `("OK", [b"1"])`
   - `.uid("fetch", ...)` returns `("OK", [(b"1", <crafted RFC822 email bytes>)])` — build a simple email with `email.mime.text.MIMEText("test body")`, set From/Subject/Message-ID headers
   - `.uid("store", ...)` returns `("OK", [b""])` (mark Seen)
5. After the first UID is processed, the loop hits `continue` (escalated guard) then comes back to the next `for uid in uids:` iteration (no more UIDs), then the post-processing block, then `time.sleep()`. Mock `time.sleep` to raise `_SentinelException` so the loop exits after one iteration.
6. Mock `smtp_send` → noop (prevent real SMTP)
7. Mock `marina_agent.process_message` → controlled return (different per test)
8. Mock `state_registry.create_pending_notification` → MagicMock (track calls)

### Test 1 — Semi-escalation in fully-escalated email creates relay notification

Mock `marina_agent.process_message` to return `{"reply": "Let me check on that for you.", "semi_escalation": True, "relay_question": "wheelchair access", "requires_human": False, "intents": ["inquiry"], "fields": {}, "flags": {}, "internal_note": ""}`.

After `main()` raises `_SentinelException`, assert:
- `state_registry.create_pending_notification` was called at least once
- The call included `notification_type='relay'` and `channel='email'`
- The thread state (re-read from the temp JSON file) has `awaiting_relay: True` and a `relay_token` set

### Test 2 — requires_human in fully-escalated email creates re-escalation notification

Mock `marina_agent.process_message` to return `{"reply": "I'll connect you with the team.", "requires_human": True, "semi_escalation": False, "intents": ["escalation"], "fields": {}, "flags": {}, "internal_note": "customer needs special arrangements"}`.

After `main()` raises `_SentinelException`, assert:
- `state_registry.create_pending_notification` was called at least once
- The call included `notification_type='escalation'` and `channel='email'`
- The notification body contains `"RE-ESCALATION"`

## Success Condition

`python3 -m pytest wtyj/tests/ -q` reports **893 passed / 0 failed** (891 baseline + 2 new). After deploy, a fully-escalated email conversation where Marina flags a relay question results in a visible notification in the dashboard (previously silently dropped).

## Rollback

`git revert <commit>`. Restores the guard to its pre-fix state (silently drops relay/re-escalation flags). No data migration.
