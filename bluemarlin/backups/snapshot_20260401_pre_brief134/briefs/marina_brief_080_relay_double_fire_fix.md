# BRIEF 080 — Fix Relay Double-Fire Bug
**Status:** Approved | **Files:** `shared/state_registry.py`, `agents/marina/email_poller.py`, `tests/social/test_077_relay_bridge.py` | **Depends on:** 077 | **Blocks:** —

## Context
When an operator replies to a relay email (`[RELAY-xxx]` in subject), `email_poller.py` calls `get_relay_by_token()` to find the matching WhatsApp notification and deliver the reformulated answer. But `get_relay_by_token()` queries `WHERE relay_token = ?` without filtering by `status = 'pending'`. After the first reply is processed and the notification is marked `status='replied'`, any subsequent email containing the same `[RELAY-xxx]` token (duplicate, forwarded, or re-fetched) matches again — sending the reformulated answer to the customer's WhatsApp chat a second time.

This happened in production on 2026-03-13: Calvin Adamus received the same relay answer twice because two operator emails contained the same relay token.

## Why This Approach
Two layers of defense:

1. **Root cause** — Add `AND status = 'pending'` to `get_relay_by_token()`. This is the canonical fix: the function should never return already-processed relays.
2. **Log clarity** — Update the log message in email_poller.py's relay fallback path to say "no pending relay... (may be already replied)" instead of the misleading "no matching thread". The existing `if _wa_relay` condition naturally guards against double-fire since `get_relay_by_token()` now returns `None` for non-pending relays.

The alternative of only fixing the caller would leave `get_relay_by_token()` as a footgun for any future caller. Fixing both is the right call.

A third defense (atomic lookup-and-claim via `UPDATE ... SET status='processing' WHERE status='pending' RETURNING *`) was considered but rejected — SQLite RETURNING requires 3.35+, and the current two-layer fix eliminates the bug without adding complexity.

## Source Material

### `shared/state_registry.py` lines 561–575 (current)
```python
def get_relay_by_token(relay_token: str) -> "dict | None":
    """Look up a relay notification by token. Returns dict or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications WHERE relay_token = ?",
        (relay_token,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "notification_type": row[1], "relay_token": row[2],
            "channel": row[3], "customer_id": row[4], "customer_name": row[5],
            "subject": row[6], "body": row[7], "status": row[8], "created_at": row[9]}
```

### `agents/marina/email_poller.py` lines 630–663 (current)
```python
                        # Check WhatsApp relay
                        _wa_relay = state_registry.get_relay_by_token(relay_token_in)
                        if _wa_relay and _wa_relay["channel"] == "whatsapp":
                            _wa_phone = _wa_relay["customer_id"]
                            # ... reformulate and send ...
                            wa_send_text_message(to=_wa_phone, text=relay_reply)
                            # ... clear flags ...
                            state_registry.update_notification_status(
                                _wa_relay["id"], "replied")
```

### `tests/social/test_077_relay_bridge.py` lines 79–93 (current)
```python
def test_get_relay_by_token():
    """Look up relay by token, returns None for non-existent."""
    customer_id = "TEST_077_TOKEN_001"
    _cleanup_notification(customer_id)
    state_registry.create_pending_notification(
        'relay', 'whatsapp', customer_id, 'Test',
        '[RELAY-aaa111bbb222] NO-REF', 'body',
        relay_token='aaa111bbb222')
    result = state_registry.get_relay_by_token('aaa111bbb222')
    assert result is not None
    assert result["channel"] == "whatsapp"
    assert result["customer_id"] == customer_id
    # Non-existent token
    assert state_registry.get_relay_by_token('nonexistent1') is None
    _cleanup_notification(customer_id)
```

## Instructions

### Step 1 — Fix `get_relay_by_token()` in `shared/state_registry.py`

Change the WHERE clause from:
```python
"FROM pending_notifications WHERE relay_token = ?",
```
to:
```python
"FROM pending_notifications WHERE relay_token = ? AND status = 'pending'",
```

No other changes to this function. Docstring update: "Look up a **pending** relay notification by token."

### Step 2 — Add caller guard in `agents/marina/email_poller.py`

After line 631 (`_wa_relay = state_registry.get_relay_by_token(relay_token_in)`), the existing check is:
```python
if _wa_relay and _wa_relay["channel"] == "whatsapp":
```

Add a log line after the existing `if` block to cover the case where `get_relay_by_token` returns None but a notification exists with non-pending status. Replace the log line at line 664:
```python
log(f"RELAY: no matching thread for token={relay_token_in} — skipping")
```
with:
```python
log(f"RELAY: no pending relay for token={relay_token_in} — skipping (may be already replied)")
```

This makes the log message accurate — previously it said "no matching thread" which was misleading for the WhatsApp relay path.

### Step 3 — Add regression test in `tests/social/test_077_relay_bridge.py`

Add a new test after `test_get_relay_by_token` (after line 93):

```python
# --- Test 2b: get_relay_by_token filters out non-pending ---

def test_get_relay_by_token_ignores_replied():
    """get_relay_by_token returns None if notification already replied."""
    customer_id = "TEST_077_TOKEN_002"
    _cleanup_notification(customer_id)
    row_id = state_registry.create_pending_notification(
        'relay', 'whatsapp', customer_id, 'Test',
        '[RELAY-ddd444eee555] NO-REF', 'body',
        relay_token='ddd444eee555')
    # Pending → should find it
    assert state_registry.get_relay_by_token('ddd444eee555') is not None
    # Mark replied
    state_registry.update_notification_status(row_id, 'replied')
    # After replied → should NOT find it
    assert state_registry.get_relay_by_token('ddd444eee555') is None
    # Also test 'sent' status
    _cleanup_notification(customer_id)
    row_id2 = state_registry.create_pending_notification(
        'relay', 'whatsapp', customer_id, 'Test',
        '[RELAY-fff666ggg777] NO-REF', 'body',
        relay_token='fff666ggg777')
    state_registry.update_notification_status(row_id2, 'sent')
    assert state_registry.get_relay_by_token('fff666ggg777') is None
    _cleanup_notification(customer_id)
```

## Tests

Run the full test_077 suite:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python -m pytest tests/social/test_077_relay_bridge.py -v
```

Expected: 9/9 pass (8 original + 1 new).

Key assertion: `test_get_relay_by_token_ignores_replied` — creates notification, marks it 'replied', verifies `get_relay_by_token()` returns `None`. This is the exact scenario that caused the double-fire.

Also run regression:
```bash
python -m pytest tests/social/ -v
```

## Success Condition
All 9 test_077 tests pass. `get_relay_by_token('token')` returns `None` when notification status is 'replied' or 'sent'. Full social test regression green.

## Rollback
Revert the one-line change in `state_registry.py`, remove the new test, revert log message in `email_poller.py`.
