# BRIEF 183 — Enrich escalation response with real customer contact
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, new `wtyj/tests/marina/test_183_escalation_contact_enrichment.py` | **Depends on:** Brief 181 (contact_type field) | **Blocks:** None

## Context

Escalations in the dashboard show `customer_id` in the "PHONE" column, which is either a 24-char Zernio hex conversation ID (e.g. `69d42a044b32d4847a2f19d8` — meaningless to an operator) or an email address. Brief 181 added `contact_type` ("whatsapp"/"email"/"phone") so the frontend knows WHAT kind of identifier it is, but didn't resolve the core problem: for WhatsApp escalations, there's no useful contact info visible.

The customer's real email and/or phone often IS in the system — stored in `customer_identifiers` via the cross-channel customer file (Brief 166). When Marina asks "what's your email?" and the customer provides it, `customer_add_identifier` links it to their customer row. The escalation just doesn't look it up.

Benson wants the "phone" section renamed to "contact" and enriched with the customer's actual email/phone. Backend enrichment so the frontend (SR) can just display what the API returns.

## Why This Approach

Enrich at the API layer in `get_all_escalations()` rather than at the DB schema layer. The `customer_id` column stays as-is (it's the routing key for replies — changing it would break the escalation reply flow). Instead, add `customer_contact` (the best human-readable contact) and `customer_email`/`customer_phone` fields to the API response by joining through `customer_identifiers`. Rejected: adding email/phone columns to `pending_notifications` (would require backfilling existing rows + updating all `create_pending_notification` call sites).

## Instructions

### Step 1: Add a helper to look up customer contact info from an identifier

In `state_registry.py`, near `_infer_contact_type` (line 999), add:

```python
def _lookup_customer_contact(customer_id: str, contact_type: str) -> dict:
    """Brief 183: look up the customer's real email and phone from customer_identifiers
    via the customer_id stored in the escalation. Returns {'email': ..., 'phone': ...}
    with None for any identifier not found."""
    if not customer_id:
        return {"email": None, "phone": None}
    
    # Determine the identifier type from contact_type
    id_type = "email" if contact_type == "email" else "wa_conversation_id" if contact_type == "whatsapp" else "phone"
    
    conn = _get_conn()
    # Find the customer row via their identifier
    cust_row = conn.execute(
        "SELECT customer_id FROM customer_identifiers WHERE type = ? AND value = ? LIMIT 1",
        (id_type, customer_id)
    ).fetchone()
    
    if not cust_row:
        conn.close()
        # If customer_id IS an email, return it directly
        if contact_type == "email":
            return {"email": customer_id, "phone": None}
        return {"email": None, "phone": None}
    
    cust_id = cust_row[0]
    
    # Get all identifiers for this customer
    idents = conn.execute(
        "SELECT type, value FROM customer_identifiers WHERE customer_id = ?",
        (cust_id,)
    ).fetchall()
    conn.close()
    
    email = None
    phone = None
    for ident in idents:
        if ident[0] == "email" and not email:
            email = ident[1]
        elif ident[0] == "phone" and not phone:
            phone = ident[1]
    
    return {"email": email, "phone": phone}
```

### Step 2: Enrich `get_all_escalations()` response

Modify the list comprehension in `get_all_escalations()` at line 1026-1030 to include the enriched contact:

```python
def get_all_escalations() -> list:
    """Return all escalation notifications, newest first.
    Brief 181: includes contact_type. Brief 183: includes customer_contact, customer_email, customer_phone."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at "
        "FROM pending_notifications ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        ct = _infer_contact_type(r[4] or "")
        contact = _lookup_customer_contact(r[4] or "", ct)
        # customer_contact = best available human-readable contact
        customer_contact = contact["email"] or contact["phone"] or r[4] or ""
        result.append({
            "id": r[0], "notification_type": r[1], "relay_token": r[2],
            "channel": r[3], "customer_id": r[4], "customer_name": r[5],
            "subject": r[6], "body": r[7], "status": r[8], "created_at": r[9],
            "contact_type": ct,
            "customer_contact": customer_contact,
            "customer_email": contact["email"],
            "customer_phone": contact["phone"],
        })
    return result
```

### Step 3: Same enrichment for `get_pending_notifications()`

Apply the identical pattern to `get_pending_notifications()` at lines 1033-1047 — replace the list comprehension with the same loop + lookup + enrichment.

## Tests

Create `wtyj/tests/marina/test_183_escalation_contact_enrichment.py`:

1. **`_lookup_customer_contact` finds email for WhatsApp escalation.** Create a customer with both `wa_conversation_id` and `email` identifiers. Call `_lookup_customer_contact(conv_id, "whatsapp")`. Assert returned `email` matches and `phone` is None.

2. **`_lookup_customer_contact` returns email directly for email escalations.** Call with an email address and `contact_type="email"`. Assert `email` is returned even if the customer has no file.

3. **`_lookup_customer_contact` returns both when available.** Create a customer with email + phone identifiers. Assert both fields are populated.

4. **Escalation response includes `customer_contact` and `customer_email`.** Create a test escalation for a customer with a known email. Call `get_all_escalations()`. Verify the escalation dict has `customer_contact`, `customer_email`, and `customer_phone` keys.

## Success Condition

860 baseline + 4 new tests = **864 passing / 0 failures**. Escalation API response now includes `customer_contact` (best human-readable), `customer_email`, and `customer_phone` fields. SR can display the contact column with real info instead of hex IDs.

## Rollback

`git revert <commit>`, deploy. The `customer_contact`/`customer_email`/`customer_phone` fields disappear from the API response. Frontend gracefully ignores absent fields and falls back to `customer_id`.
