# BRIEF 202 — Surface sender_name in conversation list for dm_agent-path tenants

**Status:** Draft
**Files:** `wtyj/shared/state_registry.py`, `wtyj/tests/test_202_sender_name_fallback.py` (new)
**Depends on:** Brief 201 (dashboard message field aliases shipping in same area)
**Blocks:** Nothing — discrepancy #12 closes after this.

---

## Context

After Brief 200's cutover, `dashboard.unboks.org` correctly listed unboks's two conversations, but the customer-name column showed Zernio hex IDs like `69efec187aca03948969dc95` instead of human names. SR's audit framed it as "phone field appears to contain MongoDB ObjectID, name is null." Discrepancy #12 from the post-cutover review.

**Verified live on VPS** (2026-05-05):

```
docker exec wtyj-unboks python3 -c '
import sqlite3
c = sqlite3.connect("/app/data/state_registry.db")
for r in c.execute("SELECT phone, sender_name, MAX(created_at) FROM whatsapp_threads "
                   "WHERE role=\"user\" AND sender_name != \"\" GROUP BY phone").fetchall():
    print(r[0][:30], "→", r[1])
'

# Output:
# 69efec187aca03948969dc95 → Calvin
# 69f7cea6e99a2574e014abec → Calvin
```

The data is there. `whatsapp_threads.sender_name` is populated correctly by `dm_store_message()` (`wtyj/shared/state_registry.py:962`). The list endpoint just doesn't surface it.

### Root cause

`wa_list_conversations()` at `wtyj/shared/state_registry.py:885-928` builds each conversation's display name from `whatsapp_booking_state.fields_json.customer_name` (line 910):

```
fields = json.loads(state_row[0] or "{}") if state_row else {}
flags = json.loads(state_row[1] or "{}") if state_row else {}
name = fields.get("customer_name") or fields.get("name") or phone
```

Three-tier fallback:
1. `fields.customer_name` — set by Marina's extractor when she pulls the customer's self-introduced name
2. `fields.name` — same source, alternate key
3. `phone` — last resort, the conversation_id itself

For BlueMarlin (`booking_flow: true`), Marina's path runs the extractor, populates booking_state, and the name resolves correctly. For unboks/calvin-csa (`booking_flow: false`), the dm_agent path doesn't touch `whatsapp_booking_state` at all — that table stays empty for every dm_agent conversation. So step 3 hits and the hex shows.

This affects every current and future `booking_flow:false` tenant: unboks today, Roberto-style psychology-practice tenants tomorrow, any Q&A-only client. The data we need (`sender_name` from Zernio's webhook payload) is already being captured per-message; we just need to look at the right table.

### Why not fix it on the dm_agent inbound side?

We could refactor dm_agent to call `customer_lookup_or_create` and `customer_record_interaction` like Marina's path does. That would populate the `customers` table and unify the model. **But it's a bigger refactor** — touches webhook routing, conversation linking, multi-tenant isolation of customer files, and it changes the data shape of every dm_agent conversation going forward. Out of scope for closing discrepancy #12.

The small fix here closes the visible bug today. The bigger refactor stays as a follow-up if and when the customer-record model becomes useful for dm_agent tenants (e.g., for analytics, repeat-customer detection, etc.).

### Why not fix it on SR's frontend?

His frontend's `safeDisplayName()` in `artifacts/unboks/src/lib/conversation-mapper.ts:23` already tries `name`, `customerName`, `senderName`, `contactName`, `profileName` in priority order. We could add a `senderName` field to our list response and his code would pick it up automatically — that's another option. But **we don't need a frontend change at all** if we just populate `customer_name` correctly server-side. Same end result, fewer cross-repo coordinations.

The chosen fix populates `customer_name` (and only `customer_name`) so the existing frontend mapper resolves it on its first try.

---

## Why This Approach

**Considered alternatives:**

1. **Refactor dm_agent path to populate `customers` and `whatsapp_booking_state`.** Bigger, riskier, changes data model. Rejected for this brief; valid future work.

2. **Add a new `senderName` field to the list response.** Works because SR's mapper already tries it. But requires frontend coordination to verify and adds yet another field to track. Rejected — populating existing `customer_name` is cleaner.

3. **Add the sender_name fallback at the dashboard API layer (`wtyj/dashboard/api.py`)** instead of state_registry. Possible but the api.py endpoint is just a thin pass-through (`messages = state_registry.wa_list_conversations()`). Putting the fallback logic at the data layer means every caller benefits, including any future internal consumer. Rejected the api-layer fix; data-layer fix is correct.

4. **Chosen approach: in `wa_list_conversations()`, after the booking_state-based name resolution, query the most recent user-role `sender_name` for the same phone from `whatsapp_threads`. If booking_state's name is empty/equals-phone AND a sender_name exists, use it.** Single function modified, single SQL query added, fully backward-compatible (Marina's path still wins because booking_state.customer_name takes priority).

**Tradeoff:** One extra small SELECT per conversation in the list query. With 2 conversations on unboks today, ~10 on adamus, scaling to dozens on busy tenants — this stays under 100 SELECTs total per dashboard list refresh. Sub-millisecond impact. Could be optimized into the existing JOIN later if it ever matters; not worth premature optimization now.

**Tradeoff:** If a customer message has `sender_name=""` (Zernio sometimes doesn't pass a name on first contact), we still fall back to the phone. That's correct — we don't manufacture data we don't have. Once the customer's profile name appears on a later message, the next list refresh shows the human name.

---

## Instructions

### Single change in `wtyj/shared/state_registry.py`

The current `wa_list_conversations()` body (lines 885-928) is:

```python
def wa_list_conversations() -> list:
    """List all WhatsApp conversations with latest message and booking state.
    Returns list of dicts sorted by most recent activity."""
    conn = _get_conn()
    # Get unique phones with latest message
    rows = conn.execute(
        "SELECT t.phone, t.text, t.created_at, t.role, t.channel "
        "FROM whatsapp_threads t "
        "INNER JOIN ("
        "  SELECT phone, MAX(created_at) as max_ts "
        "  FROM whatsapp_threads GROUP BY phone"
        ") latest ON t.phone = latest.phone AND t.created_at = latest.max_ts "
        "ORDER BY t.created_at DESC"
    ).fetchall()

    conversations = []
    for r in rows:
        phone = r[0]
        # Get booking state for name + status
        state_row = conn.execute(
            "SELECT fields_json, flags_json, last_activity "
            "FROM whatsapp_booking_state WHERE phone = ?", (phone,)
        ).fetchone()
        fields = json.loads(state_row[0] or "{}") if state_row else {}
        flags = json.loads(state_row[1] or "{}") if state_row else {}
        name = fields.get("customer_name") or fields.get("name") or phone
        status = "escalated" if flags.get("fully_escalated") else "active"
        # Count messages
        count_row = conn.execute(
            "SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ?", (phone,)
        ).fetchone()
        channel = r[4] if len(r) > 4 and r[4] else "whatsapp"
        conversations.append({
            "phone": phone,
            "customer_name": name,
            "last_message": r[1],
            "last_message_role": r[3],
            "last_message_at": r[2],
            "status": status,
            "message_count": count_row[0] if count_row else 0,
            "channel": channel,
        })
    conn.close()
    return conversations
```

Modify the name-resolution block (the line `name = fields.get("customer_name") or fields.get("name") or phone`) to:

```python
        # Brief 202: when booking_state has no customer_name (the dm_agent path
        # for booking_flow:false tenants like unboks doesn't populate it), fall
        # back to the most recent user-role sender_name from whatsapp_threads.
        # Marina's path (booking_flow:true) is unaffected — booking_state's
        # customer_name takes priority.
        name = fields.get("customer_name") or fields.get("name") or ""
        if not name:
            sender_row = conn.execute(
                "SELECT sender_name FROM whatsapp_threads "
                "WHERE phone = ? AND role = 'user' AND sender_name != '' "
                "ORDER BY created_at DESC LIMIT 1",
                (phone,)
            ).fetchone()
            if sender_row and sender_row[0]:
                name = sender_row[0]
        if not name:
            name = phone  # final fallback to hex/phone if no name source at all
```

The `or phone` from the original third-tier fallback is moved to a final `if not name: name = phone` so the new sender_name SELECT runs in between. Behavior:

- If booking_state has `customer_name` → use it (Marina's path, unchanged)
- Else if booking_state has `name` → use it (alternate key, unchanged)
- **Else if any user-role message has a non-empty sender_name** → use the most recent one (NEW — handles dm_agent path)
- Else fall back to phone hex (last resort, unchanged)

The dict key in the response stays `customer_name` — SR's frontend mapper resolves this first via `safeDisplayName(c.name || c.customerName)`. No frontend coordination needed.

---

## Tests

New file: `wtyj/tests/test_202_sender_name_fallback.py` — 2 tests covering both branches.

```python
"""Brief 202: sender_name fallback for dm_agent-path conversation list."""

import os

# Match established test pattern; module-level setdefault before any imports.
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")


def test_dm_only_conversation_uses_sender_name_for_customer_name():
    """When booking_state has no customer_name (dm_agent path / booking_flow:false),
    wa_list_conversations falls back to the most recent user-role sender_name."""
    from shared import state_registry

    # Use a unique phone so other tests don't pollute
    phone = "test-202-dm-only-conv-" + os.urandom(4).hex()

    # Simulate dm_agent inbound: store messages with sender_name, but never
    # touch whatsapp_booking_state.
    state_registry.dm_store_message(phone, "whatsapp", "user", "Hi there",
                                     sender_name="Calvin Adamus")
    state_registry.dm_store_message(phone, "whatsapp", "assistant", "Hi! How can I help?",
                                     sender_name="")

    # Verify booking_state is genuinely empty for this phone
    import sqlite3
    conn = sqlite3.connect(state_registry.DB_PATH)
    booking_row = conn.execute(
        "SELECT * FROM whatsapp_booking_state WHERE phone = ?", (phone,)
    ).fetchone()
    conn.close()
    assert booking_row is None, "Test setup precondition: booking_state must be empty"

    # Call the function under test
    conversations = state_registry.wa_list_conversations()
    matching = [c for c in conversations if c["phone"] == phone]
    assert len(matching) == 1, f"Expected one conversation for phone {phone}"
    assert matching[0]["customer_name"] == "Calvin Adamus", \
        f"Expected sender_name fallback, got {matching[0]['customer_name']!r}"


def test_marina_path_with_booking_state_still_uses_booking_state_name():
    """When booking_state DOES have customer_name (Marina's path / booking_flow:true),
    it takes priority over any sender_name in whatsapp_threads. Regression guard."""
    from shared import state_registry

    phone = "test-202-marina-path-" + os.urandom(4).hex()

    # Simulate Marina's path: store messages AND populate booking_state with
    # an explicitly-extracted customer name.
    state_registry.dm_store_message(phone, "whatsapp", "user", "Hi, I want to book",
                                     sender_name="WhatsApp Display Name")
    state_registry.wa_save_booking_state(phone, {"customer_name": "Marina Extracted Name"}, {})

    conversations = state_registry.wa_list_conversations()
    matching = [c for c in conversations if c["phone"] == phone]
    assert len(matching) == 1, f"Expected one conversation for phone {phone}"
    # Marina's extracted name wins over the WhatsApp display name
    assert matching[0]["customer_name"] == "Marina Extracted Name", \
        f"Expected booking_state.customer_name priority, got {matching[0]['customer_name']!r}"
```

**Why these 2 tests:**

1. **dm_only path uses sender_name** — verifies the new behavior on the booking-flow-false path. Asserts the precondition (booking_state really IS empty) so a future regression that accidentally writes to booking_state in dm_agent path doesn't make this test pass for the wrong reason.

2. **Marina path priority preserved** — regression guard. Asserts that when booking_state.customer_name IS set, it wins over whatever sender_name is in messages (Marina's name extractor is more reliable than WhatsApp's display name, which can be a nickname or empty).

The `os.urandom(4).hex()` suffix on phone avoids collisions with other tests sharing the same SQLite file.

`wa_save_booking_state` is the existing helper that writes to whatsapp_booking_state; verified by prior code review of state_registry.py.

---

## Success Condition

After this brief deploys:

1. Open `https://dashboard.unboks.org` → log in → inbox shows "Calvin" (or whatever sender_name Zernio passed) instead of `69efec187aca03948969dc95` for the unboks conversations.
2. BlueMarlin's dashboard inbox continues to show Marina-extracted customer names for booking-flow conversations (regression preserved).
3. Pytest goes from 911 → 913 passing (2 new), 0 failures.

Verification command (after deploy):

```
TOKEN=$(curl -s -X POST https://api.unboks.org/api/unboks/dashboard/api/login \
  -H "Content-Type: application/json" -d '{"password":"papaesunmono"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.unboks.org/api/unboks/dashboard/api/messages/conversations \
  | python3 -m json.tool
```

Expect: `customer_name: "Calvin"` (or whatever Zernio passed) in both rows, NOT the hex phone.

---

## Rollback

`git revert <commit>` and redeploy. Single function change in one file; revert restores the prior phone-fallback behavior. No DB migration, no schema change, no data writes — just a SELECT and an `if`. Fully reversible. Frontend continues to receive `customer_name=<hex>` after revert (same state as before this brief).
