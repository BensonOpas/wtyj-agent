# BRIEF 181 — Escalation "contact" field + customer display_name update
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/agents/social/social_agent.py`, `wtyj/dashboard/api.py`, new `wtyj/tests/marina/test_181_escalation_contact.py` | **Depends on:** Brief 166 (customer file), Brief 178 (normalization) | **Blocks:** Frontend column rename (SR or follow-up)

## Context

Two findings from the e2e test, both about customer identity correctness:

**A. Escalation "phone" field is misleading.** The dashboard's Escalations page has a field labeled "PHONE" that actually shows the `customer_id` from `pending_notifications`. For WhatsApp escalations this is a Zernio conversation hex string like `69d42a044b32d4847a2f19d8` (NOT a phone number). For email escalations it's the customer's email address shown in a "phone" field. Benson wants this renamed to "contact" so it makes sense for both channels.

The backend's `get_all_escalations()` (`state_registry.py:999-1011`) returns `customer_id` as-is. The fix: add a `contact_type` field to each escalation dict that tells the frontend how to display it — "email" if it contains `@`, "whatsapp" if it's a 24-char hex Zernio conversation ID, "phone" otherwise. The frontend column rename (PHONE → CONTACT) is a separate change in `Escalations.tsx` — deferred to SR or a follow-up since SR is actively committing to the dashboard repo.

**B. Customer display_name not updated after Marina's extraction.** When Zernio sends `sender_name: "Calvin Adamus"` but the customer says "Hi, Mark here" in the message, Marina correctly extracts `customer_name: "Mark"` into the fields dict. The BOOKING record uses the extracted name (verified in Brief 178 investigation). But the CUSTOMER FILE's `display_name` stays as "Calvin Adamus" because it was set at creation time from `sender_name` (`social_agent.py:202+216`). This means Marina's greeting on subsequent messages uses the wrong name.

The fix: after Marina's fields merge and the interaction recording block (`social_agent.py:314-327`), check if the extracted `customer_name` differs from the customer file's current `display_name` and update it if so. Add a `customer_update_display_name(id, name)` function to `state_registry.py`.

## Why This Approach

Both changes are targeted: one new state_registry helper + one API-layer enrichment. No schema changes — the `pending_notifications` table already has `customer_id`; we're just adding a derived `contact_type` field to the API response. The customer display_name update is a single UPDATE WHERE. Rejected: renaming the `customer_id` DB column (unnecessary migration risk for a field that already works; the enrichment is at the API layer).

## Instructions

### Step 1: Add `customer_update_display_name` to state_registry.py

Add near the existing `customer_record_interaction` function (`state_registry.py:2166`):

```python
def customer_update_display_name(customer_id: int, display_name: str):
    """Brief 181: update a customer's display_name when Marina extracts a different
    name from the conversation than what was set from the webhook sender_name."""
    if not customer_id or not display_name:
        return
    conn = _get_conn()
    conn.execute(
        "UPDATE customers SET display_name = ? WHERE id = ?",
        (display_name.strip(), customer_id)
    )
    conn.commit()
    conn.close()
```

### Step 2: Wire the display_name update into social_agent.py

In `handle_incoming_whatsapp_message`, after the Brief 166 "record interaction + merge" block (line 314-327), add:

```python
# Brief 181: update customer display_name when Marina extracts a
# different name from the conversation (e.g. customer says "Hi, Mark
# here" but Zernio sender_name was "Calvin Adamus").
_extracted_name = (_new_fields_for_merge.get("customer_name") or "").strip()
if _extracted_name and _cust_row and _extracted_name != (_cust_row.get("display_name") or ""):
    try:
        state_registry.customer_update_display_name(_cust_row["id"], _extracted_name)
        _cust_row["display_name"] = _extracted_name
    except Exception as _e:
        bm_logger.log("customer_name_update_failed", error=str(_e))
```

Note: this must be INSIDE the existing `if _cust_row and _cust_row.get("id"):` block (line 314), after the identifier merge at line 319-325 and before the `except` at line 326. The `_new_fields_for_merge` variable is already defined at line 319 in this block.

### Step 3: Add `contact_type` to escalation API response

In `state_registry.py:get_all_escalations()` at line 999, modify the list comprehension to include a derived `contact_type` field:

Replace the return at lines 1008-1011 with:

```python
def _infer_contact_type(customer_id: str) -> str:
    """Brief 181: infer the type of contact identifier."""
    if not customer_id:
        return "unknown"
    if "@" in customer_id:
        return "email"
    if len(customer_id) == 24:
        try:
            int(customer_id, 16)
            return "whatsapp"
        except ValueError:
            pass
    return "phone"

# ... in get_all_escalations():
    return [{
        "id": r[0], "notification_type": r[1], "relay_token": r[2],
        "channel": r[3], "customer_id": r[4], "customer_name": r[5],
        "subject": r[6], "body": r[7], "status": r[8], "created_at": r[9],
        "contact_type": _infer_contact_type(r[4] or ""),
    } for r in rows]
```

The `_infer_contact_type` function reuses the same 24-char hex check from `whatsapp_client._is_zernio_conversation_id` (`whatsapp_client.py:93-103`). Duplicated rather than imported to avoid a circular dependency between state_registry and whatsapp_client.

### Step 4: Same enrichment for `get_pending_notifications`

Apply the same `contact_type` enrichment to `get_pending_notifications()` at line 1014 — same pattern, add `"contact_type": _infer_contact_type(r[4] or "")` to the list comprehension.

## Tests

Create `wtyj/tests/marina/test_181_escalation_contact.py`:

1. **`_infer_contact_type` for email.** Input `"calvin@gaimin.io"` → returns `"email"`.
2. **`_infer_contact_type` for WhatsApp hex.** Input `"69d42a044b32d4847a2f19d8"` → returns `"whatsapp"`.
3. **`_infer_contact_type` for phone.** Input `"+5999686564"` → returns `"phone"`.
4. **`customer_update_display_name` updates the row.** Create a customer, update name, verify change persists.
5. **Escalation response includes `contact_type`.** Create a pending notification, call `get_all_escalations`, verify the returned dict has `contact_type` key.

## Success Condition

850 baseline + 5 new tests = **855 passing / 0 failures**. Escalation API responses include `contact_type` field. Customer display_name updates after Marina extracts a new name.

## Rollback

`git revert <commit>`, deploy. The `contact_type` field disappears from the API response (frontend gracefully ignores absent fields). Customer display_name behavior reverts to sender_name-only.
