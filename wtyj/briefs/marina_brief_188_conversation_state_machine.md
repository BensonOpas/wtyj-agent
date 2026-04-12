# BRIEF 188 — Conversation state machine: pending → open → resolved (Pattern 4)
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/agents/social/social_agent.py` | **Depends on:** — | **Blocks:** s34 (email poller split — email threads will wire into the same state machine)

## Context

The blueprint Pattern 4 ("Conversation State Machine") calls for three states per conversation: `pending` (AI owns it), `open` (human needs to look), `resolved` (done). Currently, conversation state is tracked by **scattered boolean flags in different stores**, with no unified status field and no clean transitions:

- **`fully_escalated`** — a boolean in `whatsapp_booking_state.flags_json` (`social_agent.py:634` sets it). Checked at `social_agent.py:226` to skip the booking flow and enter the escalated path. **Critical design debt:** this flag is **one-way** — once set to True, it is **never cleared**. After an operator resolves the escalation via `POST /escalations/{id}/resolve` (`api.py:941-946`), the notification status changes to `"resolved"`, but `fully_escalated` stays True. The next customer message still enters the escalated path (`social_agent.py:226`), creates a re-escalation notification (`social_agent.py:276`), and the cycle repeats. There is no mechanism for a conversation to return to AI mode after resolution. Conversations are trapped in human-only mode permanently.

- **`awaiting_relay`** — a boolean in `flags_json`, set when a relay question is created (`social_agent.py:263`). This one IS properly cleaned up by the dashboard relay reply handler (`api.py:1169`). Not a one-way trap.

- **`pending_notifications` table** — has its own `status` field (`pending`/`resolved`/`replied`/`sent`/`archived`) per notification row (`state_registry.py:222-233`). This is a per-notification lifecycle, not a per-conversation status. A conversation can have multiple notifications at different statuses with no unified view.

The dashboard currently derives conversation state by looking at these scattered flags independently. There is no single source of truth for "what state is this conversation in?"

## Why This Approach

**Parallel field, not full replacement — except for one behavioral fix.** This brief adds a new `conversation_status` table alongside the existing flags. It populates the status at the right transition points but does NOT change `social_agent.py`'s orchestrator routing to read `status` instead of `fully_escalated`. The existing `fully_escalated` check at `social_agent.py:226` stays as-is. A follow-up brief can migrate the orchestrator to use `status` once the field has been running in production and is trustworthy.

**The one behavioral change: clear `fully_escalated` when the operator resolves.** Without this, the state machine has no practical value — conversations can never return to `pending` because the one-way `fully_escalated` flag blocks them. Clearing it on resolve is the minimum change needed to make the `resolved → pending` transition functional. This is implemented via SQLite's `json_set()` for atomicity (no read-modify-write race with concurrent message processing).

**Email threads are out of scope.** Email conversation state lives in a file-based JSON store (`/app/config/email_thread_state.json`), not SQLite. Integrating email threads into the state machine requires the email poller split (s34) to migrate email state to SQLite first. This brief covers WhatsApp/DM channels only — the same boundary as Briefs 186 and 187.

### Rejected alternatives

1. **Replace `fully_escalated` reads in social_agent.py with `status` reads.** Rejected: that's a deeper change to the orchestrator's routing logic (the guard at `social_agent.py:226` would check `status == "open"` instead of `flags.get("fully_escalated")`). Needs more testing, more edge cases, more risk. Better as a follow-up once the status field is proven in production.

2. **Don't clear `fully_escalated` on resolve — let operator manually un-escalate.** Rejected: this defeats the purpose of the state machine. The operator's "resolve" action should mean "I'm done, give it back to the AI." Adding a separate "un-escalate" button is UX complexity for the same result. The resolve handler is the natural place to return conversations to AI.

3. **Use read-modify-write to clear `fully_escalated` in the resolve handler.** Rejected in favor of `json_set()` — one SQL statement instead of SELECT + Python modify + UPDATE. However, `json_set` does NOT fully prevent the concurrent race: if a message thread has already loaded `flags` with `fully_escalated=True` into a Python dict, then the resolve handler does `json_set(..., false)`, the message thread's subsequent `wa_save_booking_state()` (`INSERT OR REPLACE` with the full flags dict) will overwrite the resolve handler's change. The `json_set` only avoids a race WITHIN the resolve handler itself. **This race is LOW SEVERITY:** worst case is one extra message goes through the escalated path and creates a re-escalation notification; the operator resolves again, the second attempt clears the flag permanently (the message thread has finished by then). Proper fix would require a per-conversation lock shared between the webhook handler and the dashboard API — deferred as out of scope for this brief.

4. **Check for other pending notifications before clearing `fully_escalated`.** Rejected for minimum viable scope: if the operator resolves ONE notification and there's another pending, the AI resumes. If the second notification's issue recurs, Marina will re-escalate naturally (that's what Marina does for any message she can't handle). The state machine's `pending → open` transition covers re-escalation. Adding "don't clear if other pending notifications exist" adds query complexity for an edge case that resolves itself.

## Instructions

### Step 1 — Add `conversation_status` table to state_registry.py

In `state_registry.py`'s `_ensure_tables()` function (the block of `conn.execute("CREATE TABLE IF NOT EXISTS ...")` statements), add after the `pending_notifications` table creation (line 234):

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversation_status ("
        "conversation_id TEXT PRIMARY KEY, "
        "channel TEXT NOT NULL DEFAULT 'whatsapp', "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "updated_at TEXT NOT NULL"
        ")"
    )
```

### Step 2 — Add helper functions to state_registry.py

Add these after the existing `create_pending_notification` function (after line 996):

```python
def set_conversation_status(conversation_id: str, status: str,
                            channel: str = "whatsapp") -> None:
    """Set or update the conversation status (pending/open/resolved).
    Uses UPSERT so the first call creates the row and subsequent calls update it."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversation_status (conversation_id, channel, status, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET status = excluded.status, "
        "channel = excluded.channel, updated_at = excluded.updated_at",
        (conversation_id, channel, status,
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def get_conversation_status(conversation_id: str) -> str:
    """Get the current conversation status. Returns 'pending' if no record exists."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT status FROM conversation_status WHERE conversation_id = ?",
        (conversation_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else "pending"


def resolve_conversation_from_escalation(escalation_id: int) -> None:
    """When operator resolves an escalation: set conversation status to 'resolved'
    AND clear fully_escalated from booking state flags so the conversation returns
    to AI mode on the next customer message.

    Uses json_set() for the flag clear to avoid read-modify-write race with
    concurrent message processing."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT customer_id, channel FROM pending_notifications WHERE id = ?",
        (escalation_id,)
    ).fetchone()
    if not row:
        conn.close()
        return
    customer_id, esc_channel = row

    # Set conversation status to resolved
    conn.execute(
        "INSERT INTO conversation_status (conversation_id, channel, status, updated_at) "
        "VALUES (?, ?, 'resolved', ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET status = 'resolved', "
        "updated_at = excluded.updated_at",
        (customer_id, esc_channel or "whatsapp",
         datetime.now(timezone.utc).isoformat())
    )

    # Atomically clear fully_escalated in booking state flags
    conn.execute(
        "UPDATE whatsapp_booking_state "
        "SET flags_json = json_set(COALESCE(flags_json, '{}'), '$.fully_escalated', json('false')) "
        "WHERE phone = ?",
        (customer_id,)
    )

    conn.commit()
    conn.close()
```

### Step 3 — Set status to "open" inside `create_pending_notification`

In `state_registry.py:create_pending_notification` (line 979-996), after the `conn.commit()` at line 994, add:

```python
    # Brief 188: escalation/relay created → conversation is now "open" (human attention needed)
    set_conversation_status(customer_id, "open", channel)
```

Note: `set_conversation_status` opens its own connection, so it must be called AFTER `conn.close()` on line 995. Or: move the `conn.close()` after the status call. Better: call `set_conversation_status` after `conn.close()` at line 995, before `return row_id` at line 996. The function opens/closes its own connection internally.

### Step 4 — Set status to "resolved" + clear `fully_escalated` in the resolve handler

In `dashboard/api.py:resolve_escalation` (lines 941-947), add a call to the new helper after the notification status update:

Replace:
```python
@router.post("/escalations/{escalation_id}/resolve", dependencies=[Depends(_check_auth)])
async def resolve_escalation(escalation_id: int):
    """Mark an escalation as resolved."""
    ok = state_registry.update_notification_status(escalation_id, "resolved")
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return {"ok": True}
```

With:
```python
@router.post("/escalations/{escalation_id}/resolve", dependencies=[Depends(_check_auth)])
async def resolve_escalation(escalation_id: int):
    """Mark an escalation as resolved and return conversation to AI."""
    ok = state_registry.update_notification_status(escalation_id, "resolved")
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found")
    # Brief 188: clear fully_escalated + set conversation status to resolved
    state_registry.resolve_conversation_from_escalation(escalation_id)
    return {"ok": True}
```

### Step 5 — Set status to "pending" on normal message processing

In `social_agent.py:handle_incoming_whatsapp_message`, after the `fully_escalated` guard block (after line 292 `return esc_reply`), at the start of the normal processing path (before `# Step 1: Build action context` at line 294), add:

```python
    # Brief 188: conversation is being handled by AI → status "pending"
    state_registry.set_conversation_status(phone, "pending", channel)
```

This is called only when `fully_escalated` is False (the guard at line 226 returned early for escalated conversations). So:
- Non-escalated conversations: status set to "pending" ✅
- Post-resolve conversations (`fully_escalated` cleared by Step 4): status set to "pending" ✅
- Still-escalated conversations: guard returns early, this line not reached, status stays "open" ✅

### Step 6 — Include conversation status in escalation API response

In `state_registry.py:get_all_escalations` (line 1060-1090), after building each result dict, add the conversation status. In the loop body (around line 1075 where the dict is assembled), add a `get_conversation_status(customer_id)` call.

Specifically, in the result dict that `get_all_escalations` builds for each notification row, add:

```python
"conversation_status": get_conversation_status(r[4]),  # r[4] is customer_id
```

This adds the field to the API response without changing the endpoint path or method.

### Step 7 — Do NOT touch

- The `fully_escalated` CHECK at `social_agent.py:226` — it still reads `flags.get("fully_escalated")`. The state machine works because Step 4 CLEARS the flag on resolve, not because the check was removed. Follow-up brief can migrate the check to `get_conversation_status() == "open"`.
- The `fully_escalated` SET at `social_agent.py:634` — it still sets the flag to True when an escalation is created. Step 3 sets `status = "open"` in parallel via `create_pending_notification`.
- `email_poller.py` — email threads use file-based JSON state, not this SQLite table. Integration is s34's job.
- `awaiting_relay` — properly managed already (set/cleared by relay flow). Not touched.
- Any existing test mocks or assertions about `fully_escalated` — the flag still exists and works. Tests that set `fully_escalated = True` in flags will still trigger the escalated path. The only new behavior is that the resolve handler clears it, which existing tests don't exercise.

## Tests

Create `wtyj/tests/social/test_188_conversation_status.py` with 5 tests:

### Test 1 — `set_conversation_status` creates and updates correctly

Call `set_conversation_status("conv_188_a", "pending", "whatsapp")`. Assert `get_conversation_status("conv_188_a") == "pending"`. Then call `set_conversation_status("conv_188_a", "open")`. Assert `get_conversation_status("conv_188_a") == "open"`. Verifies the UPSERT works (create on first call, update on second). Clean up the row after.

### Test 2 — `get_conversation_status` returns "pending" for unknown conversations

Assert `get_conversation_status("conv_188_nonexistent_xyz") == "pending"`. No setup needed.

### Test 3 — `create_pending_notification` sets conversation status to "open"

Call `create_pending_notification('escalation', 'whatsapp', 'conv_188_esc', 'Test User', 'subject', 'body')`. Assert `get_conversation_status('conv_188_esc') == "open"`. Clean up notification + status rows after.

### Test 4 — `resolve_conversation_from_escalation` sets status to "resolved" AND clears `fully_escalated`

Set up: create a booking state with `fully_escalated=True` for conversation "conv_188_resolve" using `wa_save_booking_state`. Create a notification via `create_pending_notification`. Call `resolve_conversation_from_escalation(notification_id)`. Assert:
- `get_conversation_status("conv_188_resolve") == "resolved"`
- Reload booking state flags via `wa_get_booking_state("conv_188_resolve")` — `flags.get("fully_escalated")` is `False` (was True before resolve)

Clean up booking state, notification, status rows after.

### Test 5 — After resolve, new message goes through normal AI flow (not re-escalation)

Full integration test. Set up:
1. Create booking state with `fully_escalated=True, booking_ref="TESTREF"` for conversation "conv_188_reopen"
2. Create a notification for that conversation
3. Resolve the notification via `resolve_conversation_from_escalation(notification_id)` — this clears `fully_escalated`

Now mock the following in the `agents.social.social_agent` namespace:
- `marina_agent.process_message` — return a simple inquiry response that does NOT trigger booking logic:
  ```python
  {"intents": ["inquiry"], "fields": {}, "confidence": "high",
   "reply": "Hello! How can I help you today?",
   "clarifications_needed": [], "requires_human": False,
   "flags": {}, "internal_note": ""}
  ```
  This reply shape avoids hitting unmocked `gws_calendar`, `sheets_writer`, `payment_stub`, or any booking branch.
- `state_registry` (the full module mock, so `create_pending_notification`, `wa_get_booking_state`, `wa_save_booking_state`, `dm_get_history`, etc. are all MagicMocks). Configure `state_registry.wa_get_booking_state.return_value` to return `{"fields": {}, "flags": {}, "completed_bookings": []}` (clean state, no `fully_escalated`).
- `sheets_writer` — MagicMock (prevents any real Google Sheets calls)
- `config_loader` — configure `config_loader.get_raw.return_value` to return `{"features": {"booking_flow": True}}` so the orchestrator path is active.

Call `handle_incoming_whatsapp_message({"from": "conv_188_reopen", "text": "Hello again!", "from_name": "Test User"})`.

Assert:
- `marina_agent.process_message` was called (normal path worked) with `channel="whatsapp"` kwarg
- `state_registry.create_pending_notification` was NOT called (no re-escalation created — this is the key behavioral assertion: the conversation did NOT enter the fully_escalated guard)
- `state_registry.set_conversation_status` was called with `("conv_188_reopen", "pending", "whatsapp")` — proves the status transition happened
- The function returned a reply string (the mock's "Hello! How can I help you today?")

**Note:** Test 4 proves `resolve_conversation_from_escalation` clears `fully_escalated` (using real DB). Test 5 proves that a conversation WITHOUT `fully_escalated` takes the normal AI path (using mocks). Together they prove the full `escalated → resolved → pending` cycle.

This is the critical behavioral test: it proves the resolved → pending transition works end-to-end (operator resolves → fully_escalated cleared → next message goes through normal AI → status set to pending).

Clean up all rows after.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` reports **886 passed / 0 failed** (881 baseline + 5 new). After deploy, the dashboard's `GET /escalations` response includes a `conversation_status` field. Resolving an escalation via the dashboard returns the conversation to AI mode — the next customer message goes through the normal booking flow instead of creating a re-escalation.

## Rollback

`git revert <commit>`. The new `conversation_status` table persists in SQLite but is unused (no code reads or writes it after revert). The `json_set` call in `resolve_conversation_from_escalation` is removed, so `fully_escalated` stays True on resolve (restoring the old one-way behavior). No data migration needed — the table can be dropped manually via `sqlite3 state_registry.db 'DROP TABLE conversation_status'` if desired, but leaving it is harmless.
