# BRIEF 211 — Dashboard contract fields: enrich /messages/conversations and /escalations
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/shared/state_registry.py`, `wtyj/tests/social/test_211_dashboard_contract_fields.py` | **Depends on:** Brief 206 (`[ESCALATE]` sentinel writes pending_notifications + conversation_status), Brief 210 (escalation reply endpoint) | **Blocks:** SR's EscalationReplyComposer rendering (currently dead because the gating fields are missing from my response shape)

## Context

Live E2E session today on `dashboard.unboks.org` confirmed two contract gaps that silently kill the operator reply UX:

**Gap 1 — `/messages/conversations/:phone` is missing the fields that gate SR's composer.**
SR's frontend at `unboks-org/unboks-dashboard-api/artifacts/unboks/src/pages/Inbox.tsx:191` reads:
```ts
const showBanner = detail?.escalated && !detail?.escalationResolved;
const mode = detail?.escalationMode ?? null;
// then renders EscalationReplyComposer only when `showBanner && dbId && mode === ...`
```
My `wtyj/dashboard/api.py:912-932` `get_conversation()` response is `{phone, messages, booking_state}` — none of `escalated`, `escalationResolved`, `escalationMode`, `aiMuted`. Result: `showBanner = undefined && !undefined === false` → no composer, no LegacyActionPanel, nothing renders. Operator sees the conversation header in the detail pane and that is it.

**Gap 2 — `/escalations` rows for the email channel have no routable conversation key.**
SR's mapper at `unboks-dashboard-api/.../lib/conversation-mapper.ts:369-378` does:
```ts
phone: pickStr(o, "phone", "external_id", "externalId", "wa_id", "waId", "conversation_id", "conversationId"),
```
Then `escalationToConversationRow` falls back to `\`esc:${n.id}\`` when `phone` is null. My `/escalations` response for an email row carries `customer_id="calvin@gaimin.io"` but exposes none of the keys the mapper looks for. Result: clicking the Calvin Adamus escalation hits `GET /messages/conversations/esc:1`, which my backend lenient-handles by returning `{phone:"esc:1", messages:[], booking_state:{}}`. The detail pane shows zero messages, so even if Gap 1 were fixed the operator would still see no thread.

Verified live (post Brief 210 hotfix `1d4264c`):
- `Escalations1` badge renders correctly in the sidebar after id-stringify fix
- Calvin Adamus row renders in the Escalations panel ✓
- Clicking the row → detail pane shows only the header (name, channel, time, "Escalation"); no thread, no composer, no action buttons
- Network log: `GET /messages/conversations/esc%3A1` → 200 with `{messages: []}`

## Why This Approach

- **Compute the new conversation-detail fields from existing storage**, don't add new columns.
  - `escalated` ↔ `conversation_status[customer_id].status === "open"` (Brief 206 already writes this row when `[ESCALATE]` fires)
  - `escalationResolved` ↔ `conversation_status[customer_id].status === "resolved"`
  - `escalationMode` → return `null` (no per-conversation soft/hard storage exists yet — that's Tier 2 work in a future brief)
  - `aiMuted` → return `false` (no takeover storage exists yet — Tier 2)
  - SR's frontend handles `mode === null` by rendering the LegacyActionPanel (`Inbox.tsx:302-304`), which is the simple action-buttons UI. That's a degraded-but-usable experience: the operator can act on the escalation through the buttons even before soft/hard mode lands.
- **For the email-route key on `/escalations`**, walk `email_thread_state.json` looking for thread_keys containing the customer email. We already do this exact substring lookup in `state_registry.email_append_assistant_message` (Brief 210, `state_registry.py:892-940`). Lift that lookup pattern out as a small helper `_find_email_thread_key_for(email)` so both call sites reuse it.
- **Rejected: storing the email thread_key directly on `pending_notifications.customer_id` at escalation-creation time** (Brief 206 path). Cleaner long-term but invasive — would require a migration of existing rows + changes to dm_agent.py and email_poller.py escalation creators. The lookup cost on `/escalations` is one JSON load per request, threads dict has ≤ tens of entries today, and the response is already O(N rows). Not a hot path. If it ever becomes one we can cache.
- **Rejected: returning `escalationMode: "hard"` as a default for any escalated conversation** so SR's hard-reply composer renders today. Tempting but lies to the frontend — would gate features that depend on real soft/hard state behind a default that means the opposite. Lying-by-default produces silent bugs later. Better to render LegacyActionPanel honestly.
- **Rejected: changing `get_conversation()` to also fetch the matching email thread when phone starts with `esc:`** to fix the empty-detail symptom. The clean fix is upstream in `/escalations` (Gap 2), so the frontend never builds an `esc:1` URL in the first place. Fixing the symptom downstream would mask the real shape mismatch.

## Instructions

### Step 1 — Add `_find_email_thread_key_for(email)` helper in `wtyj/shared/state_registry.py`

Insert just before `email_append_assistant_message` (around line 891, after `email_get_conversation`). Reads `email_thread_state.json`, scans the `threads` dict, returns the first thread_key whose lowercased text contains the customer email. Returns `None` when no match. Lift the substring-match logic from `email_append_assistant_message:903-911` so both call sites share it.

```python
def _find_email_thread_key_for(customer_email: str):
    """Brief 211: locate the email_thread_state.json thread_key for a customer
    email. Used by /escalations to expose a routable key, and by
    email_append_assistant_message to find the thread for an outbound reply.
    Returns the thread_key string or None if no thread exists yet."""
    if not customer_email:
        return None
    path = _get_email_state_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return None
    needle = customer_email.lower()
    for thread_key in (state.get("threads") or {}).keys():
        if needle in thread_key.lower():
            return thread_key
    return None
```

Then refactor `email_append_assistant_message` (around line 903) to call this helper instead of inlining the loop. Keep the rest of that function unchanged — only the lookup line changes.

### Step 2 — Enrich `get_all_escalations()` in `wtyj/shared/state_registry.py:1233`

The function already returns the dict with `customer_id`, `customer_email`, `channel`, etc. (lines 1248-1257). Add one new key inside that dict literal:

```python
"phone": (
    f"email::{_find_email_thread_key_for(r[4])}" if r[3] == "email" and _find_email_thread_key_for(r[4])
    else r[4] if r[3] in ("whatsapp", "dm")
    else r[4]
),
```

Wait — that calls the helper twice. Cleaner:
```python
# Inside the for-loop, before the result.append(...):
_email_thread_key = _find_email_thread_key_for(r[4]) if r[3] == "email" else None
_phone_routing_key = (
    f"email::{_email_thread_key}" if _email_thread_key
    else r[4]  # whatsapp/dm: customer_id is already the routing key; email with no thread yet: customer_id (frontend will get an empty thread on click, which is fine)
)
```
Then add `"phone": _phone_routing_key` to the dict.

This makes SR's `pickStr(o, "phone", ...)` capture the right key. For email rows with a matched thread → `email::subj:calvin@gaimin.io:testing`. For whatsapp → the conversation hex (already the routing key). For email with no thread yet → the email address (frontend `GET /messages/conversations/calvin@gaimin.io` returns empty messages, same as today's `esc:1` fallback — no regression).

### Step 3 — Enrich `/messages/conversations/:phone` response in `wtyj/dashboard/api.py:912-932`

Before the final return, compute the four new fields and merge them into both the email-branch response and the whatsapp-branch response. Use a small helper to keep the two branches symmetric.

```python
def _conversation_status_fields(customer_id: str) -> dict:
    """Brief 211: derive escalation-state fields the SR frontend reads on
    /messages/conversations/:phone to gate its EscalationReplyComposer.
    `escalationMode` and `aiMuted` are placeholders (Tier 2) — null/false
    means SR's UI renders LegacyActionPanel, which is the legacy buttons."""
    status = state_registry.get_conversation_status(customer_id)
    return {
        "escalated": status == "open",
        "escalationResolved": status == "resolved",
        "escalationMode": None,
        "aiMuted": False,
    }
```

In `get_conversation`:
- Email branch: extract the customer email from the thread_key (`thread_key.split(":", 2)[1]` — same pattern used at `state_registry.py:838-841`), call the helper, merge into the response.
- WhatsApp branch: pass `phone` directly to the helper (for whatsapp the path-param IS the customer_id), merge into the response.

### Step 4 — Tests in `wtyj/tests/social/test_211_dashboard_contract_fields.py` (new file, 5 tests)

Mirror the patterns in `wtyj/tests/social/test_125_escalation_reply.py` and `test_210_email_escalation_reply.py`. Use the real `state_registry` (no monkeypatch isolation) and clean up rows in a `_cleanup` helper.

Tests:
1. **`test_get_conversation_returns_escalated_true_when_open`** — seed a conversation_status row with status="open" via `state_registry.set_conversation_status(...)`, GET `/messages/conversations/{phone}`, assert `escalated == True` and `escalationResolved == False`. Cleanup.
2. **`test_get_conversation_returns_escalated_false_when_no_row`** — clean phone, GET, assert `escalated == False`.
3. **`test_get_conversation_returns_resolved_when_status_resolved`** — set status="resolved", GET, assert `escalationResolved == True` and `escalated == False`.
4. **`test_get_conversation_defaults_mode_null_and_aimuted_false`** — any conversation, assert response contains `escalationMode is None` and `aiMuted == False` (Tier 2 placeholders).
5. **`test_list_escalations_email_row_has_routable_phone`** — write a fake email_thread_state.json with one thread, seed a `pending_notifications` row with channel="email" and customer_id matching that thread's email, GET `/escalations`, assert the row's `phone` field starts with `email::`. Use `tmp_path` + monkeypatching `state_registry._get_email_state_path` to point at the temp file.

### Step 5 — No changes to schema, no migration

Both new behaviors read from existing storage (`conversation_status` table for Gap 1, `email_thread_state.json` for Gap 2). Zero column additions, zero data movement.

## Tests (5)

Defined above. Summary:
1. `test_get_conversation_returns_escalated_true_when_open`
2. `test_get_conversation_returns_escalated_false_when_no_row`
3. `test_get_conversation_returns_resolved_when_status_resolved`
4. `test_get_conversation_defaults_mode_null_and_aimuted_false`
5. `test_list_escalations_email_row_has_routable_phone`

Plus the full regression must stay at baseline + 5 new = **949 passing / 0 failures** (baseline 944 from Brief 210 hotfix).

## Success Condition

After deploy:
1. Open `dashboard.unboks.org`, log in, go to Escalations.
2. Calvin Adamus row still renders (regression guard for Brief 210's id-stringify).
3. Click the Calvin Adamus row.
4. Detail pane now shows the email thread (the actual chat log between Calvin and Marina), not just the header.
5. Below the thread: the LegacyActionPanel buttons render (because `escalated=true` and `mode=null`). Operator can take action on the escalation.
6. Live verification:
   ```bash
   ssh root@108.61.192.52 'docker exec wtyj-unboks python3 -c "
   import urllib.request, json
   req = urllib.request.Request(
       \"http://localhost:8001/dashboard/api/messages/conversations/email::subj:calvin@gaimin.io:testing\",
       headers={\"Authorization\": \"Bearer \" + open(\"/app/data/session_token\").read().strip()}
   )
   d = json.loads(urllib.request.urlopen(req).read())
   print(\"escalated:\", d.get(\"escalated\"), \"resolved:\", d.get(\"escalationResolved\"), \"mode:\", d.get(\"escalationMode\"))
   "'
   ```
   Expected: `escalated: True resolved: False mode: None`

## Rollback

`git revert <commit>`, push, the canary pipeline redeploys. No data changes — purely additive response fields. SR's frontend tolerates fields it doesn't recognize (TanStack Query just stores them) and the legacy code path before this brief ignored these keys, so revert is safe and zero-loss.

If the response is malformed (JSON parse error or 500), the dashboard's escalation panel goes back to its current degraded state — composer not rendering. No customer impact.
