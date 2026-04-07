# BRIEF 159 — Relay reply repair: Zernio send + don't strip relay flag

**Status:** Draft
**Files:**
- `wtyj/agents/social/whatsapp_client.py` (new helper `send_whatsapp_message` that picks Zernio vs legacy Meta)
- `wtyj/dashboard/api.py` (`/escalations/{id}/reply` endpoint, lines 1079-1128 — keep `awaiting_relay` flag, switch to new helper)
- `wtyj/agents/marina/email_poller.py` (WhatsApp relay branch, lines 654-685 — switch to new helper)

**Depends on:** Brief 157 (escalation wording), Brief 158 (escalation display)
**Blocks:** Demos where the operator needs to actually answer customer questions through the relay

---

## Context

User reported that the relay flow is broken in BOTH directions:

1. **Dashboard relay:** operator clicks Reply on a semi escalation, types an answer, clicks Send. Frontend toast says "Reply sent to customer", but the customer never receives anything on WhatsApp.

2. **Email relay (whatsapp customer):** operator gets Marina's relay alert email (`[RELAY-token] ref - name`), replies with an answer, the email reaches Marina's polled inbox, the email_poller matches the token... and again the customer never receives the reformulated reply.

Two bugs with one shared root cause + one bonus dashboard-only bug.

### Bug A — both paths use legacy Meta WhatsApp send for Zernio customers

After Brief 143 migrated WhatsApp from Meta Cloud API to Zernio, the inbound webhook routes Zernio messages through `handle_incoming_whatsapp_message` and uses `send_dm_reply` (Zernio Inbox API) for the immediate response (`webhook_server.py:205`). This works because the inbound webhook payload contains the Zernio `_zernio_account_id` metadata.

**But the relay reply paths don't have access to that metadata.** They retrieve a stored escalation row and try to send via `wa_send_text_message` (legacy Meta Cloud API) at:
- `dashboard/api.py:1111` (dashboard reply path)
- `email_poller.py:671` (email-side WhatsApp branch)

For Zernio customers (everyone in production), `customer_id` is a 24-char hex conversation ID like `69d41ae77d2c605d08114697`, not a phone number. Meta's Cloud API rejects this as an invalid phone, the call fails silently, and the customer receives nothing.

### Bug B — dashboard relay reply strips `awaiting_relay` flag

`dashboard/api.py:1100`:
```python
agent_flags = dict(wa_flags)
for rk in ("relay_token", "reply_times", "awaiting_relay", "relay_question"):
    agent_flags.pop(rk, None)
```

The `awaiting_relay` flag is what tells Marina to enter RELAY MODE (`marina_agent.py:161-168`):
```python
if thread_flags.get("awaiting_relay"):
    relay_mode_section = (
        "\nRELAY MODE: A human team member has answered the customer's pending question. "
        "Their answer is in the INBOUND MESSAGE body below. "
        "Reformulate it in Marina's warm voice, using the same language the customer used. "
        ...
    )
```

In relay mode, Marina knows the inbound message body is the operator's answer (not a customer message) and reformulates it warmly. Without the flag, Marina sees the operator's answer and treats it as a fresh customer message — generating a totally unrelated reply.

The email-side relay branch (`email_poller.py:661-663`) correctly KEEPS `awaiting_relay`:
```python
_wa_agent_flags = dict(_wa_flags)
for _rk in ("relay_token", "reply_times"):  # NOTE: awaiting_relay NOT in this list
    _wa_agent_flags.pop(_rk, None)
```

So the email-side has the right flag-handling logic, but the dashboard endpoint accidentally over-strips. Easy fix.

### Correction — Brief 158's "Zernio history table mismatch" finding was WRONG

Brief 158's output flagged a latent bug: Zernio messages are stored via `dm_store_message`, supposedly into a different table than `wa_store_message`, so `wa_get_history` would return empty for Zernio customers. **Verified during Brief 159 research: this is false.** Both functions write to the SAME `whatsapp_threads` table (`state_registry.py:625-633` and `:762-773`). `wa_get_history(phone)` filters by `phone = ?` only — no channel filter — so it returns Zernio messages too because they're stored with the same `phone` (= conversation_id) value.

The Brief 158 lessons entry already documents this finding as flagged-for-investigation; Brief 159 confirms it's a non-issue and the existing `wa_get_history` calls in the relay paths work correctly for Zernio customers.

---

## Why This Approach

### Single helper that abstracts the send decision

Both broken call sites share the same fix shape: detect whether `customer_id` is a Zernio conversation_id or a Meta phone number, then call the appropriate send function. Putting this logic inline in two places duplicates the detection and the imports. A helper in `whatsapp_client.py` (where `send_text_message` already lives) is the natural home:

```python
def send_whatsapp_message(customer_id: str, text: str) -> bool:
    """Send a WhatsApp text via Zernio Inbox API (preferred — Brief 143)
    if customer_id is a Zernio conversation_id, otherwise fall back to the
    legacy Meta Cloud API. Returns True on success."""
    if _is_zernio_conversation_id(customer_id):
        # Zernio path — DM Inbox API
        from agents.social.zernio_dm_client import send_dm_reply
        from agents.social.social_publisher import get_account_id
        account_id = get_account_id("whatsapp")
        if not account_id:
            log("zernio_send_no_account",
                conversation_id=customer_id[:20])
            return False
        return send_dm_reply(customer_id, account_id, text)
    # Legacy Meta path
    return send_text_message(to=customer_id, text=text)


def _is_zernio_conversation_id(s: str) -> bool:
    """Zernio conversation IDs are 24-char lowercase hex strings.
    Meta phone numbers are E.164 (+15551234567) or all-digit.
    The two formats don't overlap."""
    if len(s) != 24:
        return False
    try:
        int(s, 16)  # raises ValueError if not hex
        return True
    except ValueError:
        return False
```

**Detection logic rationale:**
- Zernio conversation IDs are 24 lowercase hex chars (`69d41ae77d2c605d08114697`). Confirmed by inspecting the live state earlier in the session.
- Meta phone numbers are either `+15551234567` (E.164 format with leading `+`) or all-digit (`15551234567`). Phones are 10-15 digits typically, never 24 hex chars.
- Edge case: a 24-digit "phone number" would match the length but `int(s, 16)` succeeds for digits only, so it'd be misclassified as Zernio. Risk: extremely rare; no real phone is 24 digits long. Acceptable for v1.

**Why pull `account_id` via `social_publisher.get_account_id("whatsapp")` instead of storing it in pending_notifications?** Adding a column to `pending_notifications` is a schema migration; pulling from the existing Late account list is a single API call that already happens elsewhere in the codebase. BlueMarlin has exactly one whatsapp Zernio account so the lookup is unambiguous. Future multi-account scenarios would need a different approach but that's not now.

### Don't strip `awaiting_relay` in the dashboard handler

One-line fix at `api.py:1100`: remove `"awaiting_relay"` from the list of flags to pop. The email-side handler (`email_poller.py:661-663`) already does this correctly — the dashboard handler was over-stripping. After the fix, Marina will enter relay mode for dashboard-initiated replies just like she does for email-initiated replies.

### NOT touching the email-customer relay path (lines 690-722 of email_poller.py)

This is the path where the customer is on EMAIL (not WhatsApp). The user said "i believe the relay actually doesn't work on email too" — but they qualified with "i believe", and I can't reproduce without a fresh test. The email-customer relay path:
- Looks up the customer thread by relay_token (line 644-651)
- Calls `marina_agent.process_message(...)` with the FULL flags dict (no popping at all — line 695 passes `customer_th.get("flags", {})` directly)
- Sends via `smtp_send` (line 701) which is correct for email customers

This path LOOKS structurally correct. If there's a real bug here, it surfaces in the marina_agent call (Marina might generate an empty reply for some reason) or in the thread state lookup (the thread might not be found if the relay_token doesn't match exactly). Without a reproducible failure, fixing this is shooting in the dark.

**Out of scope. Listed in the live test plan: if email-customer relay still fails after Brief 159, file a follow-up brief with specific log evidence.**

### NOT changing how relay_token gets matched

The token-matching regex `\[RELAY-([a-f0-9]{12})\]` at `email_poller.py:640` looks correct. The token is generated as `uuid.uuid4().hex[:12]` (12 hex chars) at `social_agent.py:533` and `email_poller.py:961`. The regex matches that format exactly. No bug here.

---

## Source Material

### Current dashboard `/escalations/{id}/reply` handler (api.py:1079-1128)

```python
@router.post("/escalations/{escalation_id}/reply", dependencies=[Depends(_check_auth)])
async def reply_to_escalation(escalation_id: int, req: EscalationReplyRequest):
    """Reply to a semi escalation. Marina reformulates and sends to customer."""
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Answer text required")

    all_esc = state_registry.get_all_escalations()
    esc = next((e for e in all_esc if e["id"] == escalation_id), None)
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")

    channel = esc.get("channel", "whatsapp")
    customer_id = esc.get("customer_id", "")

    if channel == "whatsapp" and customer_id:
        wa_state = state_registry.wa_get_booking_state(customer_id)
        wa_fields = wa_state.get("fields", {})
        wa_flags = wa_state.get("flags", {})
        wa_history = state_registry.wa_get_history(customer_id, limit=10)

        agent_flags = dict(wa_flags)
        for rk in ("relay_token", "reply_times", "awaiting_relay", "relay_question"):
            agent_flags.pop(rk, None)

        relay_result = marina_agent.process_message(
            customer_id, "", req.answer.strip(),
            wa_fields, agent_flags,
            channel="whatsapp", messages=wa_history,
        )
        relay_reply = relay_result.get("reply", "")

        if relay_reply:
            wa_send_text_message(to=customer_id, text=relay_reply)
            state_registry.wa_store_message(customer_id, "assistant", relay_reply)
            bm_logger.log("dashboard_relay_sent", phone=customer_id, escalation_id=escalation_id)
        else:
            raise HTTPException(status_code=500, detail="Marina returned empty reply")

        wa_flags.pop("awaiting_relay", None)
        wa_flags.pop("relay_token", None)
        wa_flags.pop("relay_question", None)
        state_registry.wa_save_booking_state(
            customer_id, wa_fields, wa_flags,
            wa_state.get("completed_bookings", []))

        state_registry.update_notification_status(escalation_id, "replied")

        return {"ok": True, "reply": relay_reply}
    else:
        raise HTTPException(status_code=400, detail=f"Channel '{channel}' reply not supported from dashboard")
```

**Two bugs** in this block:
1. Line 1100: `for rk in ("relay_token", "reply_times", "awaiting_relay", "relay_question"):` — strips `awaiting_relay`, breaking Marina's relay mode
2. Line 1111: `wa_send_text_message(to=customer_id, text=relay_reply)` — uses legacy Meta API, fails silently for Zernio customers

### Current email_poller WhatsApp relay branch (email_poller.py:654-685)

```python
# Check WhatsApp relay
_wa_relay = state_registry.get_relay_by_token(relay_token_in)
if _wa_relay and _wa_relay["channel"] == "whatsapp":
    _wa_phone = _wa_relay["customer_id"]
    _wa_state = state_registry.wa_get_booking_state(_wa_phone)
    _wa_fields = _wa_state.get("fields", {})
    _wa_flags = _wa_state.get("flags", {})
    _wa_history = state_registry.wa_get_history(_wa_phone, limit=10)
    _wa_agent_flags = dict(_wa_flags)
    for _rk in ("relay_token", "reply_times"):
        _wa_agent_flags.pop(_rk, None)
    relay_result = marina_agent.process_message(
        _wa_phone, "", body,
        _wa_fields, _wa_agent_flags,
        channel="whatsapp", messages=_wa_history,
    )
    relay_reply = relay_result.get("reply", "")
    if relay_reply:
        wa_send_text_message(to=_wa_phone, text=relay_reply)
        state_registry.wa_store_message(
            _wa_phone, "assistant", relay_reply)
        log(f"RELAY: WhatsApp relay sent to {_wa_phone}")
    _wa_flags.pop("awaiting_relay", None)
    _wa_flags.pop("relay_token", None)
    _wa_flags.pop("relay_question", None)
    state_registry.wa_save_booking_state(
        _wa_phone, _wa_fields, _wa_flags,
        _wa_state.get("completed_bookings", []))
    state_registry.update_notification_status(
        _wa_relay["id"], "replied")
    im.uid("store", uid, "+FLAGS", r"(\Seen)")
    save_json(THREAD_STATE_PATH, state)
    continue
```

**One bug** in this block:
- Line 671: `wa_send_text_message(to=_wa_phone, text=relay_reply)` — same legacy Meta API issue

This block CORRECTLY keeps `awaiting_relay` (line 662 only pops `relay_token` and `reply_times`) so Marina enters relay mode here. Just the send function needs fixing.

### Current `whatsapp_client.py` (relevant excerpt)

```python
import os
import json
import urllib.request

from shared.bm_logger import log

_API_VERSION = "v22.0"


# Brief 154 — read env vars at call time, not at import time.
def _access_token() -> str:
    return os.environ.get("WHATSAPP_ACCESS_TOKEN", "")


def _phone_number_id() -> str:
    return os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")


def parse_webhook_payload(payload: dict) -> list:
    ...


def send_text_message(to: str, text: str) -> bool:
    """Send a text message via WhatsApp Cloud API. Returns True on success."""
    url = f"https://graph.facebook.com/{_API_VERSION}/{_phone_number_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_access_token()}",
        "Content-Type": "application/json",
    }
    body = json.dumps({...}).encode("utf-8")
    ...
```

The new `send_whatsapp_message` helper goes here, alongside the existing `send_text_message`. Imports for `zernio_dm_client.send_dm_reply` and `social_publisher.get_account_id` go inside the helper function (deferred imports) to avoid circular import issues with `social_publisher` which already imports from `social_agent` etc.

### Current `marina_agent.py:161-168` — the relay mode prompt section

```python
relay_mode_section = ""
if thread_flags.get("awaiting_relay"):
    relay_mode_section = (
        "\nRELAY MODE: A human team member has answered the customer's pending question. "
        "Their answer is in the INBOUND MESSAGE body below. "
        "Reformulate it in Marina's warm voice, using the same language the customer used. "
        "Do not add information the human did not provide. Do not make promises beyond what was stated. "
        "Set intents to [\"inquiry\"]. Do not set any booking or escalation flags.\n"
    )
```

Confirms: `awaiting_relay` is the trigger. Once we stop stripping it in the dashboard handler, Marina enters relay mode and reformulates the operator's answer correctly.

### `send_dm_reply` signature (zernio_dm_client.py:94-110) — read-only reference

```python
def send_dm_reply(conversation_id: str, account_id: str, text: str) -> bool:
    """Send a DM reply via Zernio Inbox API. Returns True on success."""
    client = _get_client()
    if not client:
        return False
    try:
        client.inbox.send_inbox_message(
            conversation_id=conversation_id,
            account_id=account_id,
            message=text,
        )
        bm_logger.log("zernio_dm_sent", conversation_id=conversation_id[:20])
        return True
    except Exception as e:
        bm_logger.log("zernio_dm_send_failed", conversation_id=conversation_id[:20],
                       error=str(e)[:200])
        return False
```

`get_account_id("whatsapp")` returns the Zernio account_id for the connected WhatsApp account (already used elsewhere; I verified earlier in the session that BlueMarlin has exactly one connected whatsapp account on Zernio).

### Existing tests that must remain green

Searched `wtyj/tests/` for `wa_send_text_message` and `relay_reply`:
- `test_077_relay_bridge.py` — relay bridge tests. They mock `marina_agent.process_message` and assert structured behavior (notification creation, flag handling). They do NOT mock `wa_send_text_message` so they don't exercise the send path. My helper change is invisible to them.
- `test_125_escalation_reply.py` — escalation reply tests. The test at line 95+ uses `customer_id="phone"` and asserts the reply gets stored. **I need to verify** in execution that this test still passes after the helper change. The test mocks `wa_send_text_message` from `dashboard.api`'s namespace, which my refactor will rename to `send_whatsapp_message` if I change the import.

**Risk noted: the import-name swap in dashboard/api.py might break the test_125 mock.** Mitigated by either (a) keeping the import name `wa_send_text_message` as an alias for `send_whatsapp_message`, or (b) updating the test mock target. I'll prefer option (b) — explicit is better.

---

## Instructions

### Step 1 — Read everything before editing

- `wtyj/agents/social/whatsapp_client.py` (full file, ~95 lines)
- `wtyj/agents/social/zernio_dm_client.py` (lines 1-110, focus on `send_dm_reply` signature)
- `wtyj/agents/social/social_publisher.py` (lines 60-100 to confirm `get_account_id` signature)
- `wtyj/dashboard/api.py` (lines 1075-1130 — full reply endpoint)
- `wtyj/agents/marina/email_poller.py` (lines 654-690 — WhatsApp relay branch)
- `wtyj/agents/marina/marina_agent.py` (lines 155-170 — relay mode prompt section)
- `wtyj/tests/social/test_125_escalation_reply.py` (full file — to find the wa_send_text_message mock)

### Step 2 — Add `send_whatsapp_message` helper to `whatsapp_client.py`

Append to the end of `wtyj/agents/social/whatsapp_client.py`:

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
        # Deferred imports to avoid circular dependency with social_publisher
        from agents.social.zernio_dm_client import send_dm_reply
        from agents.social import social_publisher
        account_id = social_publisher.get_account_id("whatsapp")
        if not account_id:
            log("zernio_send_no_account", conversation_id=customer_id[:20])
            return False
        return send_dm_reply(customer_id, account_id, text)
    return send_text_message(to=customer_id, text=text)
```

Note: `log` is imported at the top of `whatsapp_client.py` from `shared.bm_logger` (verified). No new top-level imports required — the Zernio + social_publisher imports are deferred inside the function to avoid circular import issues.

### Step 3 — Fix dashboard `/escalations/{id}/reply` (api.py:1079-1128)

**3a.** Update the import at line 21 of `dashboard/api.py`:

```python
# BEFORE
from agents.social.whatsapp_client import send_text_message as wa_send_text_message

# AFTER
from agents.social.whatsapp_client import send_whatsapp_message
```

**3b.** Update line 1100 (the flag-stripping list) to KEEP `awaiting_relay`:

```python
# BEFORE
agent_flags = dict(wa_flags)
for rk in ("relay_token", "reply_times", "awaiting_relay", "relay_question"):
    agent_flags.pop(rk, None)

# AFTER
agent_flags = dict(wa_flags)
# Brief 159: keep awaiting_relay so Marina enters RELAY MODE and
# reformulates the operator's answer instead of generating a fresh reply.
# Mirrors email_poller.py:661-663 which does the same.
for rk in ("relay_token", "reply_times"):
    agent_flags.pop(rk, None)
```

**3c.** Update lines 1110-1115 (the send call + error handling) to use the new helper AND check its return value:

```python
# BEFORE
if relay_reply:
    wa_send_text_message(to=customer_id, text=relay_reply)
    state_registry.wa_store_message(customer_id, "assistant", relay_reply)
    bm_logger.log("dashboard_relay_sent", phone=customer_id, escalation_id=escalation_id)
else:
    raise HTTPException(status_code=500, detail="Marina returned empty reply")

# AFTER
if not relay_reply:
    raise HTTPException(status_code=500, detail="Marina returned empty reply")
sent_ok = send_whatsapp_message(customer_id, relay_reply)
if not sent_ok:
    raise HTTPException(status_code=500, detail="Failed to send WhatsApp reply (Zernio account missing or send failed)")
state_registry.wa_store_message(customer_id, "assistant", relay_reply)
bm_logger.log("dashboard_relay_sent", phone=customer_id, escalation_id=escalation_id)
```

This catches the case where `send_whatsapp_message` returns False (e.g., `get_account_id("whatsapp")` returned empty because the Zernio account is disconnected, or the Zernio API call itself failed). Without this check, the operator would see a successful 200 response while the customer received nothing — same silent-failure shape as the original bug.

The rest of the handler (state save, notification update, return value) is unchanged.

### Step 4 — Fix email_poller WhatsApp relay branch (email_poller.py:654-685)

**4a.** Update the import at line 24:

```python
# BEFORE
from agents.social.whatsapp_client import send_text_message as wa_send_text_message

# AFTER
from agents.social.whatsapp_client import send_whatsapp_message
```

**4b.** Update line 671 (the send call):

```python
# BEFORE
if relay_reply:
    wa_send_text_message(to=_wa_phone, text=relay_reply)

# AFTER
if relay_reply:
    send_whatsapp_message(_wa_phone, relay_reply)
```

The `_wa_agent_flags` at line 661-663 is already correct (only pops `relay_token` and `reply_times`, keeps `awaiting_relay`). No flag fix needed here.

### Step 5 — Update `test_125_escalation_reply.py` mock target AND assertion

The test at `tests/social/test_125_escalation_reply.py:88-120` has TWO things that break after the rename:

**5a. Update the `@patch` decorator at line 88:**

```python
# BEFORE
@patch("dashboard.api.wa_send_text_message")

# AFTER
@patch("dashboard.api.send_whatsapp_message")
```

This is the only `@patch` referencing the old name in test_125 (verified by reviewer in round 1).

**5b. Update the assertion at line 120 — kwargs → positional args:**

After Step 3c, the dashboard endpoint calls `send_whatsapp_message(customer_id, relay_reply)` with POSITIONAL args (no `to=` kwarg). The current assertion uses `call_args.kwargs["to"]` which will raise `KeyError` because the new call has empty kwargs.

```python
# BEFORE
mock_wa_send.assert_called_once()
assert mock_wa_send.call_args.kwargs["to"] == phone

# AFTER
mock_wa_send.assert_called_once()
assert mock_wa_send.call_args.args[0] == phone
```

The mock parameter name `mock_wa_send` is fine to leave as-is — it's just a local variable in the test function. Renaming would add unnecessary diff churn.

**5c. Verify no other tests reference the old name:**

```bash
grep -rn "wa_send_text_message" wtyj/tests/
```

Expected after the patch: zero matches in `wtyj/tests/`. Round-1 reviewer verified test_077 does NOT mock the send function and no other test in `wtyj/tests/` references `wa_send_text_message`.

**5d. Verify the mock helper return value won't break the test:**

Step 3c added a `if not sent_ok:` check that raises 500 if `send_whatsapp_message` returns False. By default, `MagicMock` calls return another `MagicMock` which is truthy — so `sent_ok` will be a truthy MagicMock and the check passes. No fixup needed unless the test explicitly sets `mock_wa_send.return_value = False` (which it doesn't, per the round-1 reviewer's read).

### Step 6 — Run marina + social regression suites

```bash
cd /Users/benson/Projects/bluemarlin-agent/wtyj
python3 -m pytest tests/marina/ tests/social/ -q --tb=line
```

Expected: 738 passing / 0 failures (same as Brief 157). If `test_073_whatsapp_hardening::test_change_detection_cancels_hold` recurs from stale data, clean via the same one-liner from Brief 156.

If `test_125_escalation_reply.py` fails because of the mock target rename, fix the mock and re-run.

### Step 7 — Commit + push (backend repo only — no frontend changes)

```bash
cd /Users/benson/Projects/bluemarlin-agent
git add wtyj/agents/social/whatsapp_client.py \
        wtyj/dashboard/api.py \
        wtyj/agents/marina/email_poller.py \
        wtyj/tests/social/test_125_escalation_reply.py \
        wtyj/briefs/marina_brief_159_relay_reply_repair.md
git commit -m "Brief 159 — relay reply repair: Zernio send helper + keep relay flag"
git push
```

### Step 8 — Deploy backend to VPS

```bash
ssh root@108.61.192.52 "
  set -e
  cd /root && git pull
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
  sleep 8
  docker ps --filter name=wtyj- --format 'table {{.Names}}\t{{.Status}}'
  curl -s http://localhost:8001/health && echo
  curl -s http://localhost:8002/health && echo
"
```

### Step 9 — User-driven live test

**Test 1 — dashboard relay reply:**

1. Trigger a fresh semi escalation (send Marina a question she can't answer via WhatsApp, e.g. "is the boat wheelchair accessible?")
2. Marina replies "Let me check with the team and get back to you"
3. Open the dashboard → Escalations → click the new semi escalation
4. Verify the new "Relay Details" section (Brief 158) shows the question
5. Click **Reply**, type an answer in the compose box (e.g. "Yes, we have a wheelchair-accessible ramp on the dock and assistance from the crew on boarding")
6. Click **Send Reply**
7. **Confirm the customer receives a WhatsApp message** within ~5 seconds — Marina's warm reformulation of your answer
8. Check the BlueMarlin container log for `zernio_dm_sent` event with the customer's conversation_id

**Test 2 — email-side relay reply:**

1. Same scenario: trigger a fresh semi escalation via WhatsApp
2. Check the operator's email inbox (`butlerbensonagent@gmail.com` per `business.support_email` in client.json) for the relay alert email subject `[RELAY-{token}] {ref} - {customer_name} - {question}`
3. **Reply to that email** with your answer text
4. Wait ~30 seconds for the email_poller to pick up your reply
5. **Confirm the customer receives a WhatsApp message** with Marina's reformulation
6. Check the BlueMarlin container log for `zernio_dm_sent` event

**Test 3 — verify Marina is actually in relay mode (not generating a fresh reply):**

The reformulated reply should clearly REFERENCE the operator's answer content. If Marina generates something unrelated (like "How can I help you today?"), `awaiting_relay` is not being passed correctly. Look for `RELAY MODE` in the prompt context if you can grep the structured log.

**Test 4 — verify Brief 158 display still works:**

After replying, the escalation should be marked `replied` (status). Verify:
- Dashboard escalation card shows the resolved/replied state
- The "Relay Details" section still renders correctly

---

## Tests

No new automated tests for the helper itself. Reasoning:

- The helper has trivial branching: hex check → Zernio path, else → Meta path. Both paths call existing functions (`send_dm_reply` and `send_text_message`) that are already tested.
- Adding a unit test for `_is_zernio_conversation_id` would test 4 lines of regex-equivalent logic. Low value.
- The existing `test_125_escalation_reply.py` exercises the full dashboard reply flow with mocks; updating its mock target (Step 5) keeps coverage intact.
- The full marina + social regression suites catch any integration breakage.

If the helper proves brittle in practice (e.g. an edge-case customer ID that misclassifies), THAT's the time to add a unit test with the failing input.

---

## Success Condition

**One sentence:** When the operator replies to a semi escalation via the dashboard (or via email), Marina's reformulated reply reaches the customer's WhatsApp via Zernio within seconds, and the BlueMarlin structured log shows a `zernio_dm_sent` event for the customer's conversation_id.

---

## Rollback

```bash
cd /Users/benson/Projects/bluemarlin-agent
git revert <commit-sha>
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

The change is contained to 3 files in the backend. The new helper is additive (other call sites of `send_text_message` are unchanged). Revert is fully clean.

---

## Risks I want flagged before execution

1. **`test_125_escalation_reply.py` mock target** — Step 5's mock-rename might miss occurrences. Run the explicit `grep` after the rename to confirm zero stale references. If the test mocks the function via `@patch.object(...)` with a string argument or via `mocker.patch(...)`, the rename pattern might be different — read the test file fully before editing.

2. **Deferred imports in `send_whatsapp_message`** — Python's deferred import inside a function works at runtime but adds ~5-10ms latency on the first call (subsequent calls are cached). Acceptable for relay reply (not a hot path). If we ever move the helper to a hot path, hoist the imports.

3. **`get_account_id("whatsapp")` could return empty** if Zernio's account list call fails or the account is disconnected. The helper logs `zernio_send_no_account` and returns False. The dashboard endpoint will then NOT raise (it currently only raises on empty `relay_reply`), so the operator sees a 200 response with `ok: true` but the customer never receives anything. **Documented gap:** the dashboard endpoint should check the `send_whatsapp_message` return value and raise 500 if it returns False. Adding this to Step 3c.

4. **Email-customer relay path (lines 690-722)** is genuinely untested — if the user's complaint about "email relay also broken" turns out to be in this branch, Brief 159 won't fix it. Documented as out of scope. If the live test in Step 9 confirms email-customer relay is broken, file a follow-up brief.

5. **Brief 158's "Zernio history table mismatch" finding was wrong** — confirmed in research. Both `wa_*` and `dm_*` write to the same `whatsapp_threads` table; `wa_get_history(phone)` returns Zernio messages because it filters by phone only. Brief 158's lessons file has this as a flagged-for-investigation note; Brief 159 closes the note as a non-issue. Worth updating the lessons file to mark it resolved.

6. **The `_is_zernio_conversation_id` check is fragile.** If Zernio ever changes their conversation_id format (e.g. to UUIDs with hyphens or longer hex strings), the helper misclassifies and routes to legacy Meta. Mitigation: the function is in ONE place and easy to update. If this becomes a real problem, add a `metadata_json` column to `pending_notifications` and store the channel explicitly at relay creation time.
