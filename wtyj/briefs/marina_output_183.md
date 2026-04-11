# OUTPUT 183 — Enrich escalation response with real customer contact

## What was done

Added `_lookup_customer_contact(customer_id, contact_type)` helper to `state_registry.py` that joins from the escalation's `customer_id` through `customer_identifiers` to find the customer's real email and/or phone. Wired into both `get_all_escalations()` and `get_pending_notifications()` — each escalation dict now includes `customer_contact` (best human-readable contact), `customer_email`, and `customer_phone`. For WhatsApp escalations (hex conversation IDs), the customer's email/phone is resolved from their cross-channel customer file. For email escalations, the email is returned directly even if no customer file exists.

## Tests

864 passing / 0 failures (860 baseline + 4 new).

## Deployment

Source committed `2a9a77b`, pushed to main. Background deploy to all three containers.
