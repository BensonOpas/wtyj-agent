# BRIEF 213 — Escalation control surface: mode + takeover + handback + AI mute enforcement
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/agents/social/webhook_server.py`, `wtyj/agents/marina/email_poller.py`, `wtyj/tests/social/test_213_escalation_control.py` | **Depends on:** Brief 211 (placeholder fields), Brief 212 (Body import + endpoint patterns) | **Blocks:** SR's EscalationReplyComposer rendering soft/hard branches with real backing state, and the human-takeover product behavior

## Context

SR's frontend product contract (Tasks board entry "UNBOKS PROJECT 2 — FRONTEND PRODUCT CONTRACT FOR JR", May 6 22:16) requires four escalation-state fields to actually mean something instead of being placeholders:

```
mode:          "soft" | "hard"
aiMuted:       true | false
escalationResolved: true | false  ← already real (Brief 211)
escalated:     true | false       ← already real (Brief 211)
```

Brief 211 closed the contract gap by adding the field shape but returned `escalationMode: null` and `aiMuted: false` as honest sentinels because the backend had no storage for them. SR's UI handled `mode === null` by rendering a LegacyActionPanel — usable but degraded. To unlock the real soft/hard composer + the "Human takeover · AI muted" pill, those fields must be backed by real state.

The behavior SR specifies (from his contract):
- **Soft mode** — AI needs help. Operator coaches Marina, Marina relays.
- **Hard mode** — Human takeover. AI muted on this conversation. Operator replies directly. Customer messages still appear in the operator's inbox but Marina does NOT auto-reply.
- `POST /mode` toggles between soft and hard.
- `POST /takeover` is a shortcut: set mode=hard + aiMuted=true + record `human_takeover_at`.
- `POST /handback` releases the takeover: clear aiMuted, set mode=soft.

The risky surface in this brief is the AI-mute enforcement: `webhook_server._process_zernio_event` (`wtyj/agents/social/webhook_server.py:297`) and `email_poller.py:760` are the customer-message ingestion paths that call Marina/dm_agent. A bug in the mute check there means either (a) Marina answers messages on conversations that were supposed to be muted (operator's takeover is silently broken), or (b) Marina stops answering messages on conversations that should be normal (customers don't get replies, blast radius = all 4 tenants). Test coverage on both paths is non-negotiable.

The guidance flow (`POST /escalations/:id/guidance`) is intentionally NOT in this brief — it routes operator text through `marina_agent.process_message` in relay mode, a distinct mechanism from this brief's "store-message-and-stop" mute check. Brief 214 will cover guidance.

## Why This Approach

- **Schema lives where the data lives.** `mode` is per-escalation (each pending_notifications row has its own mode), so add it as a column on `pending_notifications`. `ai_muted` and `human_takeover_at` are per-conversation (a customer's WhatsApp thread is muted regardless of how many escalations exist on it), so add those as columns on `conversation_status`. This matches the natural cardinality and avoids needing a join.
- **`ALTER TABLE … ADD COLUMN` with a constant default is safe and matches the existing pattern.** SQLite supports adding a column to an existing table with `DEFAULT 0` (for ai_muted) or `DEFAULT NULL` (for mode, human_takeover_at) atomically and without rewriting the existing rows. `state_registry.py:_get_conn()` already has 9+ ALTER TABLE statements wrapped in `try/except sqlite3.OperationalError: pass` for idempotency (lines 20-51). Use that exact pattern rather than introducing a new `_add_column_if_missing` helper.
- **Mute checks go in the customer-message ingestion paths at every channel branch.** Three call sites need the check:
  - `_process_zernio_event` IG/FB DM branch at `wtyj/agents/social/webhook_server.py:354+` (inside the `with _dm_lock:` block, before `handle_incoming_dm`/`handle_incoming_whatsapp_message`)
  - `_flush_buffer` Zernio-WhatsApp branch at `wtyj/agents/social/webhook_server.py:207-247` (mute key = `_zernio_conv`)
  - `_flush_buffer` Meta-WhatsApp legacy branch at `wtyj/agents/social/webhook_server.py:248-254` (mute key = `phone`)
  - The IG/FB-only check would silently leave WhatsApp unmuted — the dominant traffic path. All three branches must check.
  - In every branch, the user message MUST still be stored (`dm_store_message` for Zernio paths, `wa_store_message` for Meta legacy) so the operator sees it in the dashboard. Skipping the store would silently drop customer messages on muted conversations.
- **Email ingestion path mirrors the pattern at `email_poller.py:760`.** That call site already appends the inbound message to the thread state earlier in the loop (the `th["messages"].append({"role": "customer", ...})` block around line ~620), so adding the mute check between the store and the reply just skips the reply call.
- **`_conversation_status_fields` reads real values.** Brief 211 set up the helper at `wtyj/dashboard/api.py:912` and currently returns `escalationMode=None, aiMuted=False`. Brief 213 wires it to two new state_registry helpers: `get_ai_muted(conversation_id)` and `get_active_escalation_mode(conversation_id)` (returns the mode of the most recent non-resolved escalation for this conversation_id; None if none exist).
- **Rejected: store mode + aiMuted on a single new `conversation_state` table** unifying both. Tempting (one source of truth for "what's the AI doing on this conversation"), but it would invalidate every existing call site to `conversation_status.status` and require a data migration of existing conversation_status rows. Adding columns to the existing table is a 5-line change with zero data movement.
- **Rejected: respect `mode=hard` as the mute signal instead of a separate `ai_muted` column.** Cleaner conceptually but couples two semantically distinct things: an escalation can be hard-mode (human will reply) without the conversation being muted (other escalations on the same conversation might still be soft), and a conversation can be muted (operator takeover) without an explicit hard-mode escalation having been created (e.g., direct UI takeover). Keep them as separate signals; the takeover endpoint sets both, but the storage is independent.
- **Rejected: filter `?mode=` server-side via SQL.** Returns the same data either way and SR's frontend already handles `mode` filtering client-side (the EscalationFilter buttons). Server-side filter is a slight optimization on payload size for tenants with many escalations, but unboks has 2 today. Add server-side support per SR's contract (he asked for `?mode=soft|hard|all`) but as a Python-list filter after the SQL query, not as a SQL WHERE — keeps the existing `get_all_escalations()` helper unchanged and the filter is one line in the route handler.

## Instructions

### Step 1 — Schema additions in `wtyj/shared/state_registry.py`

Schema initialization happens inline in `_get_conn()` at `wtyj/shared/state_registry.py:16+`, NOT in a separate `_init_schema()` function. Existing pattern for idempotent ALTER TABLE: bare `try/except sqlite3.OperationalError: pass` (see lines 20-51 for 9 existing precedent ALTERs).

Add three new ALTER blocks immediately after the existing `CREATE TABLE IF NOT EXISTS conversation_status` block (currently around line 235-242) so the new columns are guaranteed to exist by the time any helper runs:

```python
# Brief 213: pending_notifications.mode (per-escalation soft/hard)
try:
    conn.execute("ALTER TABLE pending_notifications ADD COLUMN mode TEXT")
except sqlite3.OperationalError:
    pass
# Brief 213: conversation_status.ai_muted (per-conversation human takeover flag)
try:
    conn.execute("ALTER TABLE conversation_status ADD COLUMN ai_muted INTEGER NOT NULL DEFAULT 0")
except sqlite3.OperationalError:
    pass
# Brief 213: conversation_status.human_takeover_at (ISO timestamp when muted)
try:
    conn.execute("ALTER TABLE conversation_status ADD COLUMN human_takeover_at TEXT")
except sqlite3.OperationalError:
    pass
```

`mode` defaults NULL (escalations created before this brief have no mode — frontend treats null as "legacy / no mode set"). `ai_muted` defaults 0 (existing conversations are not muted). `human_takeover_at` defaults NULL. Place these after the `conversation_status` CREATE so the table exists before the ALTER, and before any subsequent CREATE TABLE statements that reference these tables.

### Step 2 — New helpers in `wtyj/shared/state_registry.py`

Add four helpers in the conversation-status section (around line 1100-1145):

```python
def set_escalation_mode(escalation_id: int, mode: str) -> bool:
    """Brief 213: set the mode of a pending_notifications row.
    `mode` must be 'soft' or 'hard' (caller validates). Returns True
    if a row was updated, False if no row matched."""
    if mode not in ("soft", "hard"):
        return False
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE pending_notifications SET mode = ? WHERE id = ?",
        (mode, escalation_id))
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_ai_muted(conversation_id: str) -> bool:
    """Brief 213: read the ai_muted flag from conversation_status.
    Returns False when no row exists for the conversation (default
    behavior is not muted)."""
    if not conversation_id:
        return False
    conn = _get_conn()
    row = conn.execute(
        "SELECT ai_muted FROM conversation_status WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    conn.close()
    return bool(row and row[0])


def set_ai_muted(conversation_id: str, muted: bool, channel: str = "whatsapp") -> None:
    """Brief 213: takeover/handback. UPSERTs conversation_status with
    ai_muted set, and stamps human_takeover_at when muting (NULL when
    unmuting). Preserves whatever `status` value the row already had
    (escalation status is independent from mute state)."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    takeover_at = now if muted else None
    # ON CONFLICT preserves existing status; we only touch ai_muted /
    # human_takeover_at / updated_at on update. INSERT path needs a
    # default status — use 'pending' to match existing schema default.
    conn.execute(
        "INSERT INTO conversation_status "
        "(conversation_id, channel, status, ai_muted, human_takeover_at, updated_at) "
        "VALUES (?, ?, 'pending', ?, ?, ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET "
        "ai_muted = excluded.ai_muted, "
        "human_takeover_at = excluded.human_takeover_at, "
        "updated_at = excluded.updated_at",
        (conversation_id, channel, 1 if muted else 0, takeover_at, now))
    conn.commit()
    conn.close()


def get_active_escalation_mode(conversation_id: str):
    """Brief 213: return the mode ('soft' / 'hard') of the most recent
    non-resolved escalation for this conversation, or None if none exist
    or the most recent has no mode set (legacy rows). Used by
    /messages/conversations/:phone to populate `escalationMode`."""
    if not conversation_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT mode FROM pending_notifications "
        "WHERE customer_id = ? AND status != 'resolved' "
        "ORDER BY created_at DESC LIMIT 1",
        (conversation_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else None
```

### Step 3 — `get_all_escalations` returns the `mode` field

In `wtyj/shared/state_registry.py:1233+` (the `get_all_escalations()` function from Brief 211), update the SELECT and the dict literal to include `mode`:

- Change SELECT to `"SELECT id, notification_type, relay_token, channel, customer_id, customer_name, subject, body, status, created_at, mode FROM pending_notifications ORDER BY created_at DESC"`
- Add `"mode": r[10]` to the result dict

### Step 4 — New endpoints in `wtyj/dashboard/api.py`

Insert after the existing `delete_escalation_endpoint` at `wtyj/dashboard/api.py:1044-1052`. Three new endpoints. **Critical:** `state_registry.get_all_escalations()` returns int ids (the SQLite PRIMARY KEY). The `id` stringification only happens at the HTTP layer via `list_escalations()`. So lookups inside these handlers must compare int-int, NOT `e["id"] == str(escalation_id)`. Then stringify the response row's id BEFORE returning, to match the contract that GET /escalations established.

```python
# Brief 213: escalation mode + takeover/handback. SR's product contract
# requires real soft/hard mode + AI-muted state per conversation.
# Storage: pending_notifications.mode (per escalation) and
# conversation_status.ai_muted + human_takeover_at (per conversation).

class EscalationModeRequest(BaseModel):
    mode: str  # "soft" | "hard"


def _refresh_and_stringify_escalation(escalation_id: int):
    """Brief 213 helper: fetch the canonical row post-update, with id
    stringified to match the GET /escalations response contract.
    Returns the row dict or None if not found."""
    for e in state_registry.get_all_escalations():
        if e["id"] == escalation_id:  # int-int (storage) compare
            e["id"] = str(e["id"])
            return e
    return None


@router.post("/escalations/{escalation_id}/mode", dependencies=[Depends(_check_auth)])
async def set_escalation_mode_endpoint(escalation_id: int, req: EscalationModeRequest):
    if req.mode not in ("soft", "hard"):
        raise HTTPException(status_code=400, detail=f"invalid mode: {req.mode!r} (must be 'soft' or 'hard')")
    ok = state_registry.set_escalation_mode(escalation_id, req.mode)
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found")
    refreshed = _refresh_and_stringify_escalation(escalation_id)
    return refreshed or {"ok": True, "mode": req.mode}


@router.post("/escalations/{escalation_id}/takeover", dependencies=[Depends(_check_auth)])
async def takeover_escalation(escalation_id: int):
    """Hard takeover: set mode=hard on the escalation, ai_muted=true on
    the conversation, stamp human_takeover_at."""
    esc = next((e for e in state_registry.get_all_escalations()
                if e["id"] == escalation_id), None)
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    state_registry.set_escalation_mode(escalation_id, "hard")
    state_registry.set_ai_muted(esc["customer_id"], True, esc.get("channel", "whatsapp"))
    bm_logger.log("escalation_takeover", escalation_id=escalation_id,
                  customer_id=esc["customer_id"][:30], channel=esc.get("channel"))
    refreshed = _refresh_and_stringify_escalation(escalation_id)
    return refreshed or {"ok": True}


@router.post("/escalations/{escalation_id}/handback", dependencies=[Depends(_check_auth)])
async def handback_escalation(escalation_id: int):
    """Release a hard takeover: clear ai_muted, set mode=soft."""
    esc = next((e for e in state_registry.get_all_escalations()
                if e["id"] == escalation_id), None)
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    state_registry.set_escalation_mode(escalation_id, "soft")
    state_registry.set_ai_muted(esc["customer_id"], False, esc.get("channel", "whatsapp"))
    bm_logger.log("escalation_handback", escalation_id=escalation_id,
                  customer_id=esc["customer_id"][:30])
    refreshed = _refresh_and_stringify_escalation(escalation_id)
    return refreshed or {"ok": True}
```

### Step 5 — `GET /escalations` supports `?mode=` filter

In `wtyj/dashboard/api.py:1009-1019` (the existing `list_escalations()` from Brief 211), add query support:

```python
@router.get("/escalations", dependencies=[Depends(_check_auth)])
async def list_escalations(mode: str = None):
    """Brief 211: stringify id for SR's frontend mapper. Brief 213: support
    ?mode=soft|hard|all filter (all = no filter)."""
    rows = state_registry.get_all_escalations()
    for r in rows:
        r["id"] = str(r["id"])
    if mode and mode in ("soft", "hard"):
        rows = [r for r in rows if r.get("mode") == mode]
    # mode == "all" or anything else: no filter
    return rows
```

### Step 6 — `_conversation_status_fields` reads real values

In `wtyj/dashboard/api.py:935+` (the helper Brief 211 added), replace the placeholder return with real reads:

```python
def _conversation_status_fields(customer_id: str) -> dict:
    """Brief 211: derive escalation-state fields the SR frontend reads on
    /messages/conversations/:phone to gate its EscalationReplyComposer.
    Brief 213: escalationMode + aiMuted now back to real storage."""
    status = state_registry.get_conversation_status(customer_id or "")
    return {
        "escalated": status == "open",
        "escalationResolved": status == "resolved",
        "escalationMode": state_registry.get_active_escalation_mode(customer_id or ""),
        "aiMuted": state_registry.get_ai_muted(customer_id or ""),
    }
```

### Step 7 — AI-mute enforcement at THREE channel branches in `webhook_server.py`

The mute check must fire on every customer-message ingestion path. WhatsApp messages (the dominant traffic) bypass `_process_zernio_event` after line 344 and are routed through `_buffer_message` → `_flush_buffer`. IG/FB DMs continue past line 344 and reach `_process_zernio_event`'s lower block. Meta legacy WhatsApp also lands in `_flush_buffer`. Add the check at all three.

**7a. IG/FB DM branch — `_process_zernio_event` at `webhook_server.py:354+`**

Inside the `with _dm_lock:` block, BEFORE the `if _booking_flow_on:` branch:

```python
# Brief 213: respect ai_muted (operator-takeover state). When a conversation
# has been muted via /escalations/:id/takeover, store the inbound message
# in the dashboard thread so the operator sees it, but DO NOT call the
# reply handler — the human is now responsible for the conversation.
if state_registry.get_ai_muted(conversation_id):
    state_registry.dm_store_message(
        conversation_id=conversation_id, channel=channel,
        role="user", text=text, sender_name=msg["sender_name"])
    log("zernio_dm_ai_muted",
        conversation_id=conversation_id[:20], channel=channel)
    return
```

**7b. Zernio-WhatsApp branch — `_flush_buffer` at `webhook_server.py:207+`**

Inside the `if _zernio_conv:` block, immediately after the `_zernio_*` variable extraction (lines 203-206) and BEFORE the `_booking_flow_on` resolution (line 209). Mute key = `_zernio_conv` (the conversation_id used everywhere else for Zernio paths):

```python
# Brief 213: ai_muted check for Zernio WhatsApp (debounce-buffered path).
if state_registry.get_ai_muted(_zernio_conv):
    state_registry.dm_store_message(
        conversation_id=_zernio_conv, channel=_zernio_channel,
        role="user", text=combined_text, sender_name=_zernio_sender)
    log("whatsapp_zernio_ai_muted", conversation_id=_zernio_conv[:20])
    return  # exits the with _phone_lock block; _flush_buffer returns
```

**7c. Meta legacy WhatsApp branch — `_flush_buffer` at `webhook_server.py:248+`**

Inside the `else:` branch (the Meta-legacy path), at the very top before `handle_incoming_whatsapp_message` is called. Mute key = `phone` (the function parameter, used for Meta-legacy throughout):

```python
# Brief 213: ai_muted check for Meta legacy WhatsApp.
if state_registry.get_ai_muted(phone):
    state_registry.wa_store_message(phone, "user", combined_text)
    log("whatsapp_meta_ai_muted", phone=phone[:20])
    return  # exits the with _phone_lock block; _flush_buffer returns
```

For all three checks: a `return` inside the `with _phone_lock:` context manager releases the lock before exiting, same as the existing `except` handler. No leaked lock.

### Step 8 — AI-mute enforcement in `email_poller.py` + extract testable helper

At `wtyj/agents/marina/email_poller.py:760` (the `marina_agent.process_message(...)` call for new inbound emails — NOT the relay paths at 554/580), insert the mute check immediately before. The `from_email` variable is the conversation_id for email muting (same convention used elsewhere — `customer_id` on email escalations).

The inbound message is already appended to `th["messages"]` earlier in the loop (the `th["messages"].append({"role": "customer", ...})` block around line 617-622), so the operator sees the message; the check only skips the reply.

Variable scope check (verified by reading webhook_server's-equivalent for-uid loop in email_poller.py:460+): `now` is set at line 478 (`now = datetime.now(timezone.utc).isoformat()` — actually verify via Read; if it's a different name use that), and `thread_key` is set at line 470 area. Use whichever names are actually live at line 760.

For testability (the email_poller for-uid loop is hostile to integration tests because it requires IMAP mocking), extract a small helper that the integration code calls and tests can call directly:

```python
# Add at module top (around the other module-level helpers):

def _should_skip_marina_for_mute(from_email: str) -> bool:
    """Brief 213: testable wrapper around the per-conversation mute check
    used inside the for-uid loop. Returns True when this email's
    conversation has been muted via operator takeover; the loop should
    log + persist + mark seen + continue without calling marina_agent."""
    return state_registry.get_ai_muted(from_email or "")
```

Then at the call site (just before line 760):

```python
# Brief 213: ai_muted gate. Inbound was already appended to th["messages"]
# above (around line 617-622), so the operator sees the message; we just
# skip Marina's reply.
if _should_skip_marina_for_mute(from_email):
    log(f"email_ai_muted from={from_email[:40]} subj={subj[:40]}")
    th["last_activity"] = now
    state["threads"][thread_key] = th
    save_json(THREAD_STATE_PATH, state)
    im.uid("store", uid, "+FLAGS", r"(\Seen)")
    continue  # next UID
```

The helper exists so Test #10 can unit-test the mute decision without IMAP setup. Test #9 covers the integration call sites (whatsapp + DM) with mocks.

## Tests (11)

In `wtyj/tests/social/test_213_escalation_control.py`. Mirror existing patterns: TestClient + real state_registry + cleanup helpers.

1. **`test_post_mode_sets_field_and_returns_updated_row`** — seed escalation, POST /mode {mode:"hard"}, assert 200 + response.mode == "hard" + DB row updated.
2. **`test_post_mode_rejects_invalid_value`** — POST {mode:"medium"}, assert 400.
3. **`test_post_takeover_sets_hard_and_mutes_and_preserves_status`** — seed escalation (which sets conversation_status.status="open" via create_pending_notification → set_conversation_status), POST /takeover, assert (a) escalation row mode=hard, (b) get_ai_muted(customer_id) is True, (c) human_takeover_at is set, (d) **status is still "open"** (the UPSERT in set_ai_muted must preserve the status the row already had — invariant from "Why This Approach").
4. **`test_post_handback_clears_mute_and_sets_soft`** — seed escalation in hard mode + muted, POST /handback, assert ai_muted False + mode=soft.
5. **`test_get_escalations_filters_by_mode`** — seed two escalations (one hard one soft), GET /escalations?mode=hard, assert only the hard one in response.
6. **`test_get_escalations_response_includes_mode_field`** — seed escalation with mode set, GET, assert row has `mode` key.
7. **`test_conversation_detail_returns_real_escalation_mode`** — seed escalation in hard mode for phone X, GET /messages/conversations/X, assert escalationMode == "hard".
8. **`test_conversation_detail_returns_real_ai_muted`** — set_ai_muted(X, True), GET /messages/conversations/X, assert aiMuted == True.
9. **`test_dm_ingestion_skips_when_muted`** — set_ai_muted(conversation_id, True), call `_process_zernio_event` with a fake IG/FB DM payload for that conversation, assert dm_store_message was called for the inbound + `handle_incoming_dm` was NOT called. Mock both functions at the module level.
10. **`test_whatsapp_flush_skips_when_muted`** — set_ai_muted(_zernio_conv, True), build a buffered WhatsApp message with `_zernio_conversation_id` metadata, call `_flush_buffer(phone)`, assert dm_store_message was called for the inbound + `handle_incoming_whatsapp_message` was NOT called. Covers the dominant traffic path that Brief 213's first review caught as missing. Mock at the module level.
11. **`test_email_poller_mute_helper_returns_correct_value`** — unit test of `_should_skip_marina_for_mute` (email_poller helper from Step 8): (a) returns True when set_ai_muted writes True, (b) returns False after set_ai_muted writes False, (c) returns False for unknown id. The helper itself is testable in isolation; integration tests of the IMAP-loop wrapping it would need full IMAP mocking which is hostile.

Baseline: 955 (Brief 212). Target: 966 passing / 0 failures.

## Success Condition

After deploy:
1. SR opens an escalation in the dashboard. The frontend's hard-reply composer renders (because `escalationMode` and `aiMuted` now reflect real state).
2. Operator clicks "Human takeover". Backend POST /takeover succeeds. Sidebar pill shows "AI muted".
3. Customer sends a follow-up message on that conversation. Marina does NOT auto-reply. The message appears in the operator's inbox view.
4. Operator clicks "Hand back to AI". Backend POST /handback succeeds. Subsequent customer messages are answered by Marina normally.
5. Live verification (post-deploy):
   ```bash
   ssh root@108.61.192.52 'docker exec wtyj-unboks python3 -c "
   from shared import state_registry
   esc = state_registry.get_all_escalations()
   print(\"escalation count:\", len(esc), \"first row keys include mode:\", \"mode\" in (esc[0] if esc else {}))
   print(\"ai_muted helper works:\", state_registry.get_ai_muted(\"nonexistent\") == False)
   "'
   ```

## Rollback

`git revert <commit>`, push, canary redeploys. The schema columns added in Step 1 are NOT removed by the revert (SQLite ALTER TABLE DROP COLUMN is destructive and not auto-reversed). They simply become unread again — no data corruption, no behavioral regression. The mute-enforcement check in webhook + email_poller goes away on revert, so any conversation that was muted at the time of revert will start receiving Marina replies again on the next inbound message; the operator can re-takeover when the new code is back. Worst case during the revert window: ~1-2 messages get an unwanted Marina reply on a muted conversation; operator addresses via /resolve or by re-deploying.
