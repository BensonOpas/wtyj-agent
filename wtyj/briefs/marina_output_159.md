# OUTPUT 159 — Relay reply repair

## What was done

### New helper in `wtyj/agents/social/whatsapp_client.py`

Added two functions at the end of the file:

```python
def _is_zernio_conversation_id(s: str) -> bool:
    """Zernio conversation IDs are 24-char lowercase hex strings.
    Meta phone numbers are E.164 or all-digit (10-15 chars).
    The two formats don't overlap. Brief 159."""
    if len(s) != 24:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


def send_whatsapp_message(customer_id: str, text: str) -> bool:
    """Send a WhatsApp text via Zernio Inbox API (preferred, Brief 143)
    if customer_id is a Zernio conversation_id, otherwise fall back to the
    legacy Meta Cloud API. Returns True on success.

    Brief 159: introduced to fix relay reply paths that previously used
    the legacy Meta API for ALL customers, silently failing for Zernio
    customers (everyone in production)."""
    if _is_zernio_conversation_id(customer_id):
        from agents.social.zernio_dm_client import send_dm_reply
        from agents.social import social_publisher
        account_id = social_publisher.get_account_id("whatsapp")
        if not account_id:
            log("zernio_send_no_account", conversation_id=customer_id[:20])
            return False
        return send_dm_reply(customer_id, account_id, text)
    return send_text_message(to=customer_id, text=text)
```

### `wtyj/dashboard/api.py` — `/escalations/{id}/reply` handler

1. **Import rename:** `from agents.social.whatsapp_client import send_text_message as wa_send_text_message` → `from agents.social.whatsapp_client import send_whatsapp_message`

2. **Keep `awaiting_relay` flag** (the bug that caused Marina to generate fresh replies instead of reformulating the operator's answer):
   ```python
   # BEFORE: for rk in ("relay_token", "reply_times", "awaiting_relay", "relay_question"):
   # AFTER:  for rk in ("relay_token", "reply_times"):
   ```

3. **Use the new helper + check return value** to fail loudly instead of silently:
   ```python
   if not relay_reply:
       raise HTTPException(status_code=500, detail="Marina returned empty reply")
   sent_ok = send_whatsapp_message(customer_id, relay_reply)
   if not sent_ok:
       raise HTTPException(status_code=500, detail="Failed to send WhatsApp reply (Zernio account missing or send failed)")
   state_registry.wa_store_message(customer_id, "assistant", relay_reply)
   bm_logger.log("dashboard_relay_sent", phone=customer_id, escalation_id=escalation_id)
   ```

   Previously the handler did `if relay_reply: send + log else: raise`. Now it's restructured: empty reply raises first, then send + check + raise on send failure.

### `wtyj/agents/marina/email_poller.py` — WhatsApp relay branch (lines 654-685)

1. **Import rename:** same swap as the dashboard

2. **Use the new helper:**
   ```python
   # BEFORE: wa_send_text_message(to=_wa_phone, text=relay_reply)
   # AFTER:  send_whatsapp_message(_wa_phone, relay_reply)
   ```

   The flag handling at lines 661-663 is unchanged because it was already correct (only pops `relay_token` and `reply_times`, keeps `awaiting_relay`). Marina enters relay mode here.

### `wtyj/tests/social/test_125_escalation_reply.py`

1. **Mock target rename** (line 88): `@patch("dashboard.api.wa_send_text_message")` → `@patch("dashboard.api.send_whatsapp_message")`

2. **Assertion fix** (line 120): the new call uses positional args, not kwargs:
   ```python
   # BEFORE: assert mock_wa_send.call_args.kwargs["to"] == phone
   # AFTER:  assert mock_wa_send.call_args.args[0] == phone
   ```

The reviewer caught both of these in round 1. The kwargs assertion would have raised `KeyError: 'to'` after the rename.

## Test results

```
$ python3 -m pytest tests/marina/ tests/social/ -q --tb=line
738 passed, 6 warnings in 4.67s
```

**738 tests pass / 0 failures.** Same baseline as Briefs 156/157/158. The updated `test_125_escalation_reply::test_escalation_reply_sends_whatsapp` passes cleanly with the new mock target and positional assertion. The 6 warnings are pre-existing `datetime.utcnow()` deprecations in `payment_stub.py` — out of scope.

## Live deploy verification

```
$ ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

Both containers up and healthy:
- `wtyj-bluemarlin` Up 8 seconds
- `wtyj-adamus` Up 8 seconds
- `curl localhost:8001/health` → `{"status":"ok"}`
- `curl localhost:8002/health` → `{"status":"ok"}`

Backend code is now running with the new helper, the awaiting_relay flag preservation, and the return-value check.

## Bugs fixed

### Bug A — both relay paths used legacy Meta send for Zernio customers (FIXED)

**Root cause:** `dashboard/api.py:1111` and `email_poller.py:671` both called `wa_send_text_message(to=customer_id, text=...)` which posts to Meta's Cloud API. For Zernio customers (everyone in production), `customer_id` is a 24-char hex conversation_id like `69d41ae77d2c605d08114697`, not a phone number. Meta API rejects this as invalid, the call fails silently, customer never receives anything.

**Fix:** new `send_whatsapp_message(customer_id, text)` helper that detects Zernio conversation_ids (24-char hex) and routes to `send_dm_reply` via the Zernio Inbox API. Falls back to Meta for legacy phone numbers. Both call sites now use the helper.

### Bug B — dashboard relay reply stripped `awaiting_relay` (FIXED)

**Root cause:** `dashboard/api.py:1100` had `for rk in ("relay_token", "reply_times", "awaiting_relay", "relay_question"):` — over-stripped. The `awaiting_relay` flag is what triggers Marina's RELAY MODE prompt section (`marina_agent.py:161-168`). Without it, Marina sees the operator's answer as a fresh customer message and generates an unrelated reply.

**Fix:** removed `awaiting_relay` (and `relay_question`) from the strip list. Marina now enters relay mode, sees the operator's answer in the INBOUND MESSAGE position, and reformulates it warmly per the prompt.

### Bonus — silent send failures now raise 500

Previously, if `wa_send_text_message` failed (e.g. Meta API error), the dashboard handler would still hit the `state_registry.wa_store_message` + `bm_logger.log("dashboard_relay_sent")` lines and return 200 to the operator. The operator saw a success toast while the customer received nothing.

**Fix:** the new `send_whatsapp_message` returns a bool. The dashboard handler now checks it: `if not sent_ok: raise HTTPException(500, "Failed to send WhatsApp reply...")`. Operator gets a clear error toast on the dashboard if anything in the Zernio send path fails.

## Unexpected findings

### 1. Brief 158's "Zernio history table mismatch" finding was WRONG

Brief 158's output documented this as a latent bug to investigate in Brief 159: "Zernio messages are stored via dm_store_message... so wa_get_history will return EMPTY for Zernio customers." Verified during Brief 159 research: this is false.

- `dm_store_message` (state_registry.py:762-773) writes to the `whatsapp_threads` table with a `channel` field
- `wa_store_message` (state_registry.py:625-633) writes to the SAME `whatsapp_threads` table without a channel field
- `wa_get_history` (state_registry.py:636-647) filters by `phone = ?` ONLY — no channel filter — so it returns Zernio messages because they're stored with the same `phone` value (which IS the conversation_id)

The Brief 158 lessons entry has this as a flagged-for-investigation note. Brief 159 closes the note as a non-issue. Worth updating the lessons file if I'm being pedantic.

### 2. Round-1 reviewer caught a subtle test breakage

The reviewer noticed that switching the dashboard call from kwargs to positional args (`wa_send_text_message(to=phone, text=reply)` → `send_whatsapp_message(customer_id, relay_reply)`) would break the existing test assertion `mock_wa_send.call_args.kwargs["to"] == phone` with `KeyError: 'to'`. My initial brief only mentioned the @patch decorator rename in Step 5 — not the assertion fix. Without the reviewer's catch, the test would have failed in Step 6 and I'd have hit the patch limit fixing it.

Lesson reinforced: when refactoring a function signature, grep tests for `kwargs[`/`args[` references to the mock's `call_args`. Either mock target or the calling convention needs to match.

### 3. Email-customer relay branch (lines 690-722 of email_poller.py) is untouched

The user said "i believe the relay actually doesn't work on email too" but qualified with "i believe". I read the code carefully — the email-customer branch:
- Looks up the thread by relay_token (lines 644-651)
- Calls `marina_agent.process_message(...)` with FULL flags (line 695 — no popping at all, awaiting_relay preserved)
- Sends via `smtp_send` (line 701) which is correct for email

This LOOKS structurally correct. If there's a real bug here, it's in marina_agent producing an empty reply, or in the thread state lookup, or in something I can't see without a reproducible failure. Brief 159 explicitly leaves this out of scope and includes it in the live test plan — if email relay still fails after Brief 159, file a follow-up brief.

### 4. The detection regex for Zernio IDs is fragile

`_is_zernio_conversation_id` checks `len(s) == 24 and int(s, 16) succeeds`. If Zernio ever changes their conversation_id format (UUIDs with hyphens, longer hex, base64), the helper misclassifies and routes to legacy Meta. Mitigation: the function is in ONE place, easy to update. If this becomes a real problem, add a `metadata_json` column to `pending_notifications` and store the channel explicitly at relay creation time.

### 5. Smoothest of the 3 briefs in the sequence

157 → 158 → 159 was an escalation in complexity (wording → display → actual broken flow). Brief 159 was the largest in scope (5 files including a test) but executed cleanly because the prior briefs had already exposed the relevant code paths and the reviewer's pre-execution patches prevented the test breakage.

## Files modified

| Repo | File | Change |
|------|------|--------|
| wtyj | `wtyj/agents/social/whatsapp_client.py` | new `send_whatsapp_message` + `_is_zernio_conversation_id` helpers |
| wtyj | `wtyj/dashboard/api.py` | escalation reply: import, keep awaiting_relay, use helper, check return |
| wtyj | `wtyj/agents/marina/email_poller.py` | WhatsApp relay branch: import, use helper |
| wtyj | `wtyj/tests/social/test_125_escalation_reply.py` | mock target + positional-args assertion |
| wtyj | `wtyj/briefs/marina_brief_159_*.md` | new brief file |

## Commit

Backend: `b075392` on `main`

## Next

The 3-brief sequence (157 wording → 158 display → 159 relay repair) is complete. All 5 issues from the user's original list are addressed:

1. ✅ **#1** — Marina full-escalation wording (Brief 157)
2. ✅ **#2** — PHONE field shows "69" (Brief 158)
3. ✅ **#3** — Semi escalation has no body (Brief 158)
4. ✅ **#4** — REASON shows customer name (Brief 158)
5. ✅ **#5** — Relay flow broken (Brief 159, with email-customer branch flagged for follow-up if user confirms it's still broken)

## Live verification pending

User-driven tests required to confirm all 5 fixes work end-to-end on real escalations:

1. **Brief 157:** trigger a complaint escalation, confirm Marina says "expect an email from butlerbensonagent@gmail.com" instead of the customer's own email
2. **Brief 158:** trigger a semi escalation, confirm dashboard shows full WhatsApp ID, the question in REASON, and "Relay Details" section with the structured body
3. **Brief 159 (dashboard path):** click Reply on a semi escalation, type an answer, click Send Reply. Customer should receive a WhatsApp message within ~5 seconds. Check BlueMarlin container log for `zernio_dm_sent` event.
4. **Brief 159 (email path):** reply to Marina's relay alert email with an answer. Customer should receive a WhatsApp message within ~30 seconds. Check log for same event.
5. **Brief 159 (Marina relay mode):** the reformulated reply should clearly reference the operator's answer content. If Marina generates something unrelated, `awaiting_relay` is not propagating.

If any of these fail, file a follow-up brief with specific log evidence and the reproducer.
