# BRIEF 220 — Block conversation (per-conversation runtime drop)
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/agents/social/webhook_server.py`, `wtyj/agents/marina/email_poller.py`, `wtyj/tests/social/test_220_block_conversation.py` | **Depends on:** Brief 208 (ignored_phones precedent), Brief 213 (per-conversation state on conversation_status) | **Blocks:** SR's "block conversation" feature — operator wants to silence noisy/abusive conversations without touching client.json

## Context

Brief 208 shipped `features.ignored_phones` in client.json — a static deny-list configured per-tenant. Worked for the one specific phone Excluir kept testing with, but it's compile-time config: editing requires re-deploying the container.

SR's product requirement (May 6 conversation): operator-side button to mute a conversation ENTIRELY at runtime. Different from Brief 213's `ai_muted` which keeps the conversation visible in the dashboard so the operator can see what's happening — `blocked` means "drop this conversation completely; it should NOT appear in the inbox at all." Same semantic as `ignored_phones`, but per-conversation, runtime, dashboard-driven, reversible.

Concrete operator scenarios:
- Customer is being abusive — block, never see them again unless explicitly unblocked.
- Spam / probe traffic — block, no point cluttering the inbox.
- Internal test conversation gone wild — block to silence without redeploying client.json.

The drop happens at WEBHOOK INGESTION, before any storage call. So no `whatsapp_threads` row, no `whatsapp_processed` row that needs cleanup, no escalation row. The conversation stops existing from the dashboard's point of view (with one nuance: rows that existed BEFORE the block stay visible in the inbox, but any NEW message from that conversation_id is silently dropped).

## Why This Approach

**Considered:** add `blocked` to `client.json::features.blocked_conversations` (parallel to `ignored_phones`). Rejected: same problem as ignored_phones — config edits require redeploy. The operator should be able to flip block/unblock from the dashboard without touching the runtime.

**Considered:** new `blocked_conversations` table. Rejected: `conversation_status` already exists with one row per conversation_id and per-conversation flags (Brief 213 added `ai_muted` and `human_takeover_at` there). Adding a `blocked` column there matches the established pattern, no new table needed, no new join cost.

**Considered:** drop in `handle_incoming_whatsapp_message` / `handle_incoming_dm` (the message handlers). Rejected: those functions also store the inbound message before processing it. Block-after-store would leak the message into `whatsapp_threads` / `dm_messages` and the conversation would appear in the inbox momentarily — visible until the next refresh. Drop point must be BEFORE any state_registry write.

**Chosen:** new column `conversation_status.blocked INTEGER NOT NULL DEFAULT 0` via idempotent ALTER. Three helpers (`set_blocked`, `get_blocked`, `list_blocked_conversations`). Three dashboard endpoints (POST `/messages/conversations/:id/block`, POST `/.../unblock`, GET `/settings/blocked-conversations`). Drop check at all 4 customer-message ingestion paths: Zernio DM (IG/FB), Zernio-WhatsApp `_flush_buffer`, Meta-legacy WhatsApp `_flush_buffer`, email_poller's main loop. Drop point is BEFORE any storage call, mirroring Brief 208's `ignored_phones` pattern in `_process_zernio_event:323-333`.

**Why this differs from `ignored_phones`:** ignored_phones is a tenant-level static deny-list keyed by phone number digits. `blocked` is a per-conversation_id runtime flag. They coexist — ignored_phones runs first (since it's faster: single client.json read + digit compare), `blocked` runs second (DB lookup keyed by conversation_id). Either-or drop.

**Email channel handling:** the conversation_id for email is the customer's email address (via `_find_email_thread_key_for` in Brief 211). `set_blocked("calvin@example.com", True, "email")` blocks all future emails from that address — the email_poller's main loop checks `get_blocked(from_email)` before processing each UNSEEN message. Note: this differs from the WhatsApp/DM path's drop-before-storage in that the email is already in the inbox (IMAP fetched it); the drop is "skip Marina, mark as seen, move on."

## Instructions

### Step 1: Schema column + 3 helpers in state_registry

Add to `wtyj/shared/state_registry.py` near the existing Brief 213 ALTERs around line 264-273 (the `ai_muted` + `human_takeover_at` ALTERs):

```python
# Brief 220: conversation_status.blocked (per-conversation drop flag,
# operator-controlled via dashboard). Different from ai_muted: blocked
# drops the inbound BEFORE any storage so the conversation doesn't
# appear in the inbox at all; ai_muted stores then skips Marina so
# operator still sees it.
try:
    conn.execute("ALTER TABLE conversation_status ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
except sqlite3.OperationalError:
    pass
```

Three helpers near `set_ai_muted` / `get_ai_muted` / `get_human_takeover_at` (around state_registry.py:1325-1365 — Brief 213 + Brief 222 helpers):

```python
def set_blocked(conversation_id: str, blocked: bool, channel: str = ""):
    """Brief 220: flip the per-conversation blocked flag. UPSERT pattern
    matching set_ai_muted: insert row if missing (status='pending'),
    otherwise update only the blocked column. channel is required for
    INSERT but ignored on UPDATE — existing rows keep their channel."""
    if not conversation_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversation_status "
        "(conversation_id, channel, status, blocked, updated_at) "
        "VALUES (?, ?, 'pending', ?, ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET "
        "blocked = excluded.blocked, updated_at = excluded.updated_at",
        (conversation_id, channel or "", 1 if blocked else 0, now))
    conn.commit()
    conn.close()


def get_blocked(conversation_id: str) -> bool:
    """Brief 220: return True if this conversation is blocked. Hot path —
    called on every customer-message ingestion. Single-row PK lookup."""
    if not conversation_id:
        return False
    conn = _get_conn()
    row = conn.execute(
        "SELECT blocked FROM conversation_status WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    conn.close()
    return bool(row[0]) if row else False


def list_blocked_conversations() -> list:
    """Brief 220: return all currently-blocked conversations for the
    dashboard's Settings → Blocked Conversations management list.
    Each row: {conversation_id, channel, updated_at}."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT conversation_id, channel, updated_at FROM conversation_status "
        "WHERE blocked = 1 ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [{"conversationId": r[0], "channel": r[1] or "", "updatedAt": r[2]} for r in rows]
```

### Step 2: Three dashboard endpoints in api.py

Add near the existing escalation endpoints (around `wtyj/dashboard/api.py:1377` — the `/escalations/{escalation_id}/takeover` block from Brief 213. Note: line 1230 is the `_fire_escalation_alerts` dispatcher from Brief 217, NOT the takeover endpoint. Scan downward to find `@router.post("/escalations/{escalation_id}/takeover"`):

```python
@router.post("/messages/conversations/{conversation_id:path}/block",
             dependencies=[Depends(_check_auth)])
async def block_conversation(conversation_id: str):
    """Brief 220: silence this conversation. Future messages from this
    conversation_id will be dropped at webhook ingestion."""
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id required")
    state_registry.set_blocked(conversation_id, True)
    return {"ok": True, "conversationId": conversation_id, "blocked": True}


@router.post("/messages/conversations/{conversation_id:path}/unblock",
             dependencies=[Depends(_check_auth)])
async def unblock_conversation(conversation_id: str):
    """Brief 220: clear the block flag so future messages flow normally."""
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id required")
    state_registry.set_blocked(conversation_id, False)
    return {"ok": True, "conversationId": conversation_id, "blocked": False}


@router.get("/settings/blocked-conversations",
            dependencies=[Depends(_check_auth)])
async def get_blocked_conversations():
    """Brief 220: list of currently-blocked conversations for the
    Settings → Blocked Conversations management list."""
    return {"conversations": state_registry.list_blocked_conversations()}
```

### Step 3: Drop check at Zernio DM ingestion (IG/FB)

In `wtyj/agents/social/webhook_server.py`, inside `_process_zernio_event` (around line 323-333 where Brief 208's `ignored_phones` check already lives), add a parallel check IMMEDIATELY AFTER the ignored_phones loop and BEFORE the `text = msg.get("text", "")` line:

```python
# Brief 220: per-conversation runtime block. Mirrors ignored_phones (which
# runs above, statically configured) but works on a dashboard-controlled
# per-conversation_id flag. Drop BEFORE any storage so the conversation
# doesn't appear in the inbox.
if state_registry.get_blocked(msg.get("conversation_id", "")):
    log("zernio_dm_blocked_conversation",
        conversation_id=msg.get("conversation_id", "")[:20],
        message_id=message_id)
    return
```

### Step 4: Drop check at WhatsApp `_flush_buffer` (Zernio + Meta legacy)

In the same file, inside `_flush_buffer` (around line 200+, inside the `with _phone_lock:` block), add a drop check at TWO locations:

**(a) Zernio-WhatsApp branch (around line 207, just after `if _zernio_conv:`)** — INSERT BEFORE the existing Brief 213 `if state_registry.get_ai_muted(...)` check at line 209:

```python
# Brief 220: per-conversation runtime block. Drop BEFORE storage so the
# conversation doesn't appear in the inbox.
if state_registry.get_blocked(_zernio_conv):
    log("whatsapp_zernio_blocked_conversation", conversation_id=_zernio_conv[:20])
    return  # exits the with _phone_lock block
```

**(b) Meta-legacy WhatsApp branch (the `else:` arm where _zernio_conv is empty)** — find the parallel ai_muted check from Brief 213 (search for `get_ai_muted(phone)` in the same `_flush_buffer` function); INSERT a Brief 220 block check IMMEDIATELY BEFORE it:

```python
# Brief 220: per-conversation runtime block (Meta-legacy WhatsApp path).
if state_registry.get_blocked(phone):
    log("whatsapp_meta_blocked_conversation", phone=phone[:20])
    return
```

### Step 5: Drop check in email_poller

In `wtyj/agents/marina/email_poller.py`, find the per-message processing loop. The actual structure (verified at lines 624-630): the loop appends inbound to `th["messages"]` INLINE (no helper function — it's a `th.setdefault("messages", []); th["messages"].append({...})` pair). Brief 213's `_should_skip_marina_for_mute` check sits at line 635, AFTER this append, because ai_muted's semantic is "store then skip Marina."

Brief 220's semantic is DIFFERENT: drop entirely, no storage. Insert the check BEFORE the `th.setdefault("messages", [])` line (so around line 624, INSIDE the per-uid loop, AFTER `from_email` is parsed):

```python
# Brief 220: per-conversation runtime block (email path).
# from_email is the conversation_id for email channel.
# Drop BEFORE the th["messages"].append so the operator never sees this
# message in the inbox. Mark IMAP as seen so the poller doesn't loop on it.
if state_registry.get_blocked(from_email):
    log(f"email_blocked_conversation from={from_email[:50]}")
    th["last_activity"] = now
    threads[thread_key] = th
    save_json(THREAD_STATE_PATH, state)
    im.uid("store", uid, "+FLAGS", r"(\Seen)")
    continue  # next UNSEEN message
```

(IMAP STORE casing matches the file's existing convention: lowercase `store`, raw string `r"(\Seen)"`. See line 620 + 640 for precedent.)

### Step 6: Test file `wtyj/tests/social/test_220_block_conversation.py`

Mirror the test harness pattern at `wtyj/tests/social/test_211_dashboard_contract_fields.py` (login + auth helper + TestClient).

Required tests (6):

1. **`test_set_blocked_get_blocked_round_trip`** — `state_registry.set_blocked("220_phone_a", True, "whatsapp")`, then `get_blocked("220_phone_a")` returns True. Then `set_blocked(False)`, then `get_blocked` returns False. Plus initial `get_blocked("220_unknown")` returns False (no row).
2. **`test_list_blocked_conversations_returns_only_blocked`** — block 3 conversations, leave 2 unblocked. `list_blocked_conversations()` returns exactly the 3 blocked rows. Each row has the camelCase keys (`conversationId`, `channel`, `updatedAt`).
3. **`test_block_endpoint_sets_flag`** — POST `/dashboard/api/messages/conversations/220_endpoint_phone/block` → 200, `{"ok": true, "blocked": true}`. Then `state_registry.get_blocked("220_endpoint_phone")` is True.
4. **`test_unblock_endpoint_clears_flag`** — pre-seed blocked, POST `/.../unblock`, assert helper returns False.
5. **`test_zernio_webhook_drops_blocked_conversation`** — block conversation_id, then call `_process_zernio_event` with a mock payload for that conversation_id, assert no `wa_store_message` / `dm_store_message` was called (use `unittest.mock.patch` on `state_registry.dm_store_message` and `state_registry.wa_store_message`).
6. **`test_get_blocked_conversations_returns_response_shape`** — GET `/dashboard/api/settings/blocked-conversations` after seeding 2 blocked rows. Response is `{"conversations": [...]}` with 2 rows, each with the expected camelCase keys.

For all tests: cleanup deletes from `conversation_status` WHERE `conversation_id LIKE '220_%'`.

## Tests

6 tests covering the 3 helpers (round-trip + list filter), the 3 endpoints (block + unblock + GET), and the regression-critical webhook drop check (Test 5). All assertions check real return values + DB state, not source strings.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` passes at **1022 / 0** (1016 baseline + 6 new). Live verification post-deploy: POST `/api/unboks/dashboard/api/messages/conversations/<conv_id>/block` → 200; send a message from that conversation via WhatsApp/DM → message does NOT appear in the dashboard inbox; POST `/.../unblock` → next message DOES appear.

## Rollback

`git revert <commit>` and redeploy. The `blocked` column stays in `conversation_status` (SQLite can't drop columns) but becomes unused — `set_blocked`/`get_blocked` stop being called, the 3 endpoints disappear (404), the 4 ingestion drop checks no-op. Any rows where `blocked=1` lose their effect (next message from that conversation flows through normally). Schema-leftover-column is harmless dead state, no migration needed.
