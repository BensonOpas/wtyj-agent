# OUTPUT 188 — Conversation state machine: pending → open → resolved

## What was done

Added a `conversation_status` table to SQLite (conversation_id, channel, status, updated_at) and three helper functions in `state_registry.py`: `set_conversation_status` (UPSERT), `get_conversation_status` (returns "pending" for unknowns), and `resolve_conversation_from_escalation` (sets status to "resolved" AND atomically clears `fully_escalated` via `json_set`). Wired the transitions into the existing code: `create_pending_notification` now also sets status to "open"; the dashboard's `POST /escalations/{id}/resolve` handler now calls `resolve_conversation_from_escalation` (clearing the one-way `fully_escalated` flag so conversations can return to AI mode); and `handle_incoming_whatsapp_message`'s normal path now sets status to "pending" before entering the booking/inquiry flow. Added `conversation_status` to the `get_all_escalations` API response. Brief-reviewer FAIL round 1 (race condition claim was misleading — `json_set` only avoids the internal read-modify-write, not the concurrent `wa_save_booking_state` overwrite from message threads; also test 5 didn't specify the exact mock return value structure needed to avoid hitting unmocked calendar/sheets services). Both patched, PASS round 2.

## Tests

886 passing / 0 failures (881 baseline + 5 new).

## Deployment

Pending — deploy after commit + push.
