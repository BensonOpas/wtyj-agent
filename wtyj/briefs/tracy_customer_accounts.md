# BRIEF — Tracy customer accounts
**Status:** In progress | **Files:** shared/mermaid_customers.py, shared/state_registry.py, dashboard/api.py, clients/mermaid/config/client.json, dashboard customer pages | **Depends on:** Tracy contact collection | **Blocks:** none

## Context
The live Mermaid tenant has one reservation, 27 transcript messages and no customer accounts. Customers redirects to reservations, hiding enquiries before a quote. The transcript cleanup deletes messages after 30 days. The owner requires all collected information in the customer account.

## Why This Approach
Reuse the existing customer registry and link canonical conversations, reservations and documents. Persist changed intake snapshots in the same transaction as intake/message writes. Reject copying reservations or money into a second CRM store; copies drift. Do not merge accounts by a callback number, since families may share one.

## Instructions
Enable Mermaid-only customer persistence through tenant config. Backfill current data without modifying booking, payment or document snapshots. Keep chat history from automatic expiry. Add authenticated, tenant-scoped, no-store customer list/detail/history endpoints; paginate messages and detail revisions. Add actual Customers routes, contact and trip details, all linked reservations/documents and links to the operational booking/conversation screens. Preserve existing pause, escalation, document and receipt controls.

## Tests
Verify pre-booking enquiries, atomic rollback, idempotent backfill, corrections/history across state reset, distinct accounts sharing a callback, chronological message pagination beyond 200 records, retention and tenant isolation, API auth and file links. Exercise customer navigation in the browser with production-equivalent assets.

## Success Condition
The existing customer and every new enquiry have a dashboard account with retained details, chats and linked booking documents, without changing existing prices or sending test messages.

## Rollback
Restore the previous Mermaid image/config and dashboard symlink. Leave additive customer and intake records in SQLite; never restore an older database over newer customer messages.
