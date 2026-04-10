# OUTPUT 181 — Escalation contact_type + customer display_name update

## What was done

Two changes: (A) Added `customer_update_display_name(id, name)` to `state_registry.py` and wired it into `social_agent.py`'s post-Marina processing block — when Marina extracts `customer_name` from the conversation text and it differs from the Zernio `sender_name` that was set at creation time, the customer file's `display_name` is updated so Marina uses the right name on subsequent messages. (B) Added `_infer_contact_type(customer_id)` to `state_registry.py` that returns "email" / "whatsapp" / "phone" based on the identifier format (@ for email, 24-char hex for Zernio, else phone), wired into both `get_all_escalations()` and `get_pending_notifications()` as a new `contact_type` field in the response dict. Frontend column rename (PHONE → CONTACT) deferred to SR or follow-up.

## Tests

855 passing / 0 failures (850 baseline + 5 new).

## Deployment

Source committed `5936954`, pushed to main. Background deploy to all three containers.
