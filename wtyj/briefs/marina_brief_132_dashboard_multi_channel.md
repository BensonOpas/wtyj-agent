# BRIEF 132 — Dashboard Multi-Channel Conversations
**Status:** Draft | **Files:** `shared/state_registry.py`, `dashboard/api.py` | **Depends on:** Brief 130, 131 | **Blocks:** None

## Context

Briefs 130-131 added IG/FB DM storage and processing. DM conversations are stored in `whatsapp_threads` with `channel='instagram_dm'` or `'facebook_dm'`. But the dashboard API still treats all conversations as WhatsApp — `wa_list_conversations()` doesn't return channel info, and the conversation detail endpoint has no channel awareness. DM conversations show up in the list with conversation_ids displayed as phone numbers.

This brief makes the backend multi-channel aware. The frontend changes (channel badges, icons, filter UI) are SR's domain in the separate dashboard repo.

## Why This Approach

**What changes (backend):**
1. `wa_list_conversations()` → returns `channel` field per conversation. Groups by `(channel, phone)` instead of just `phone`. DM conversations get sender_name from threads table instead of booking_state.
2. `/messages/conversations/{phone}` → accepts optional `?channel=` query param. Returns channel-specific history.
3. New `POST /messages/send-dm` → operator sends manual DM reply via Zernio from dashboard.

**What stays the same:**
- Suggest-reply endpoint works as-is (conversation_id works like phone for history lookup)
- Escalations page unchanged

**`wa_get_full_history` left unfiltered by channel (intentional):** WhatsApp phone numbers (e.g. `5999690xxxx`) and Zernio conversation IDs (e.g. `conv_abc123`) are different namespaces that will never collide. Adding a channel filter to `wa_get_full_history` would require changing all callers (social_agent.py, email_poller.py, suggest-reply) for zero benefit. The new `dm_get_full_history` is used for DM channels and includes a channel filter. The conversation detail endpoint in Step 2b routes by channel, so no cross-contamination.

**Not in scope:** Frontend UI changes (channel badges, icons, filters). Those are SR's commits in the dashboard repo.

## Source Material

### Current `wa_list_conversations()` (state_registry.py lines 625-666):
Groups by phone only. Gets name from `whatsapp_booking_state.fields.customer_name`. Returns: `{phone, customer_name, last_message, last_message_role, last_message_at, status, message_count}`.

### New columns available (Brief 130):
- `channel TEXT DEFAULT 'whatsapp'` on `whatsapp_threads`
- `sender_name TEXT DEFAULT ''` on `whatsapp_threads`
- Index: `idx_whatsapp_threads_channel` on `(channel, phone, created_at)`

### Zernio DM reply function (Brief 130):
```python
from agents.social.zernio_dm_client import send_dm_reply
send_dm_reply(conversation_id, account_id, text) -> bool
```
Account IDs: Instagram `69b8689d6cb7b8cf4c7846ff`, Facebook `69bb24a66cb7b8cf4c8074aa`

### Dashboard API auth pattern:
All endpoints use `dependencies=[Depends(_check_auth)]` with Bearer token.

## Instructions

### Step 1: Modify `shared/state_registry.py`

**1a.** Replace `wa_list_conversations()` with a channel-aware version:

```python
def wa_list_conversations(channel_filter: str = None) -> list:
    """List conversations with latest message, grouped by (channel, phone).
    Optional channel_filter: 'whatsapp', 'instagram_dm', 'facebook_dm', or None for all.
    Returns list of dicts sorted by most recent activity."""
    conn = _get_conn()
    # Build channel filter clause
    if channel_filter:
        where_clause = f"WHERE channel = ?"
        params = (channel_filter,)
    else:
        where_clause = ""
        params = ()

    rows = conn.execute(
        f"SELECT t.phone, t.text, t.created_at, t.role, t.channel, t.sender_name "
        f"FROM whatsapp_threads t "
        f"INNER JOIN ("
        f"  SELECT phone, channel, MAX(created_at) as max_ts "
        f"  FROM whatsapp_threads {where_clause} GROUP BY phone, channel"
        f") latest ON t.phone = latest.phone AND t.channel = latest.channel "
        f"AND t.created_at = latest.max_ts "
        f"ORDER BY t.created_at DESC",
        params
    ).fetchall()

    conversations = []
    for r in rows:
        phone = r[0]
        channel = r[4]
        sender_name = r[5] or ""

        # For WhatsApp: get name from booking_state. For DMs: use sender_name from threads.
        if channel == "whatsapp":
            state_row = conn.execute(
                "SELECT fields_json, flags_json "
                "FROM whatsapp_booking_state WHERE phone = ?", (phone,)
            ).fetchone()
            fields = json.loads(state_row[0] or "{}") if state_row else {}
            flags = json.loads(state_row[1] or "{}") if state_row else {}
            name = fields.get("customer_name") or fields.get("name") or phone
            status = "escalated" if flags.get("fully_escalated") else "active"
        else:
            # DM conversations: get sender_name from first user message
            if not sender_name:
                name_row = conn.execute(
                    "SELECT sender_name FROM whatsapp_threads "
                    "WHERE phone = ? AND channel = ? AND sender_name != '' "
                    "ORDER BY created_at ASC LIMIT 1",
                    (phone, channel)
                ).fetchone()
                sender_name = name_row[0] if name_row else ""
            name = sender_name or phone
            status = "active"

        count_row = conn.execute(
            "SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ? AND channel = ?",
            (phone, channel)
        ).fetchone()
        conversations.append({
            "phone": phone,
            "channel": channel,
            "customer_name": name,
            "last_message": r[1],
            "last_message_role": r[3],
            "last_message_at": r[2],
            "status": status,
            "message_count": count_row[0] if count_row else 0,
        })
    conn.close()
    return conversations
```

**1b.** Add a channel-aware full history function (after `wa_get_full_history`):

```python
def dm_get_full_history(conversation_id: str, channel: str, limit: int = 200) -> list:
    """Get full DM conversation history (no 24h cutoff). Oldest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, text, created_at, sender_name FROM whatsapp_threads "
        "WHERE phone = ? AND channel = ? ORDER BY created_at ASC LIMIT ?",
        (conversation_id, channel, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "created_at": r[2], "sender_name": r[3]} for r in rows]
```

### Step 2: Modify `dashboard/api.py`

**2a.** Add import at top:

```python
from agents.social.zernio_dm_client import send_dm_reply
```

**2b.** Update the messages section header and `list_conversations` endpoint:

Replace the current endpoints (lines 866-883) with:

```python
# ── Messages (all channels) ──────────────────────────────────────────────────

@router.get("/messages/conversations", dependencies=[Depends(_check_auth)])
async def list_conversations(channel: str = Query(default=None)):
    """List conversations from all channels (or filtered by channel)."""
    return state_registry.wa_list_conversations(channel_filter=channel)


@router.get("/messages/conversations/{phone}", dependencies=[Depends(_check_auth)])
async def get_conversation(phone: str, channel: str = Query(default="whatsapp")):
    """Get full conversation thread. For WhatsApp also includes booking state."""
    if channel == "whatsapp":
        messages = state_registry.wa_get_full_history(phone, limit=200)
        booking_state = state_registry.wa_get_booking_state(phone)
    else:
        messages = state_registry.dm_get_full_history(phone, channel, limit=200)
        booking_state = {"fields": {}, "flags": {}, "completed_bookings": []}
    return {
        "phone": phone,
        "channel": channel,
        "messages": messages,
        "booking_state": booking_state,
    }
```

**2c.** Add send-DM endpoint after the conversation endpoints (before the Escalations section):

```python
class SendDMRequest(BaseModel):
    conversation_id: str
    channel: str
    text: str

@router.post("/messages/send-dm", dependencies=[Depends(_check_auth)])
async def send_dm(req: SendDMRequest):
    """Send a manual DM reply from the operator via Zernio."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Message text required")
    if req.channel not in ("instagram_dm", "facebook_dm"):
        raise HTTPException(status_code=400, detail="Invalid channel for DM")

    # Determine account_id by channel
    if req.channel == "instagram_dm":
        account_id = social_publisher.get_instagram_account_id()
    else:
        account_id = social_publisher.get_facebook_account_id()

    if not account_id:
        raise HTTPException(status_code=500, detail="No connected account for this platform")

    ok = send_dm_reply(req.conversation_id, account_id, req.text.strip())
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send DM")

    # Store the operator's reply
    state_registry.dm_store_message(
        conversation_id=req.conversation_id,
        channel=req.channel,
        role="assistant",
        text=req.text.strip(),
    )
    bm_logger.log("dashboard_dm_sent", conversation_id=req.conversation_id[:20],
                   channel=req.channel)
    return {"ok": True}
```

**2d.** Update the file header: `# Last modified: Brief 132`

## Tests

File: `tests/social/test_132_dashboard_multi_channel.py`

Setup: Insert `wa_store_message("132_wa_phone", "user", "Hi WA")` and `dm_store_message("conv_132_ig", "instagram_dm", "user", "Hi IG", "Alice")`. Clean up both after each test.

1. **test_list_conversations_returns_channel** — call `wa_list_conversations()`, find entry with phone=`"132_wa_phone"` → assert `channel == "whatsapp"`. Find entry with phone=`"conv_132_ig"` → assert `channel == "instagram_dm"`.
2. **test_list_conversations_filter_whatsapp** — call `wa_list_conversations(channel_filter="whatsapp")`, assert no result has `channel == "instagram_dm"`. Assert `"132_wa_phone"` is in results.
3. **test_list_conversations_filter_dm** — call `wa_list_conversations(channel_filter="instagram_dm")`, assert no result has `channel == "whatsapp"`. Assert `"conv_132_ig"` is in results.
4. **test_list_conversations_dm_uses_sender_name** — insert DM with `sender_name="Alice"`, call `wa_list_conversations()`, find conv_132_ig entry, assert `customer_name == "Alice"`.
5. **test_dm_get_full_history** — insert 2 DM messages ("Hi" from user, "Hello" from assistant), call `dm_get_full_history("conv_132_ig", "instagram_dm")`, assert `len == 2`, `result[0]["text"] == "Hi IG"`, `result[1]["role"] == "assistant"`, `result[0]["sender_name"] == "Alice"`.
6. **test_api_list_conversations_channel_param** — HTTP GET `/messages/conversations?channel=whatsapp` via TestClient, assert 200, assert each result has `channel == "whatsapp"`.
7. **test_api_get_conversation_dm** — HTTP GET `/messages/conversations/conv_132_ig?channel=instagram_dm` via TestClient, assert 200, assert `response["channel"] == "instagram_dm"`.
8. **test_api_send_dm_success** — mock `send_dm_reply` → True, mock `social_publisher.get_instagram_account_id` → "acc_1", POST `/messages/send-dm` with `{conversation_id: "conv_x", channel: "instagram_dm", text: "Thanks!"}`, assert 200, assert `dm_get_full_history("conv_x", "instagram_dm")` has an assistant message with text "Thanks!".
9. **test_api_send_dm_invalid_channel** — POST `/messages/send-dm` with `channel="whatsapp"`, assert 400.

## Success Condition

Dashboard API returns channel-tagged conversations, supports channel filtering, serves DM conversation detail, and allows operator to send manual DM replies. All 9 tests pass.

## Rollback

Revert `wa_list_conversations()` to the pre-Brief-132 version (no channel field, group by phone only). Remove `dm_get_full_history`, `send-dm` endpoint. Dashboard falls back to WhatsApp-only view.
