# BRIEF — Tracy customer accounts
**Status:** Complete | **Files:** shared/mermaid_customers.py, shared/state_registry.py, dashboard/api.py, clients/mermaid/config/client.json, dashboard customer pages | **Depends on:** Tracy contact collection | **Blocks:** none

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

## Verification and rollout
Backend source 97a785e deployed as wtyj-agent:tracy-customers-97a785e (digest sha256:5c868ffcc9f4daf920353c1d7fe129d4424595291c9375769b4c0c88ee701863). All 304 Mermaid backend tests passed; 50 focused tests passed inside the exact release image without network access. The final transaction simplification passed the seven account tests again.

Backfill created one customer account, retaining all 27 messages and the existing reservation, quote and receipt. The live private PDF endpoint returned both original verified PDF byte streams. Old phone remains unknown because it was not explicitly collected. No test messages were sent. Six peer containers were unchanged; watchdog healthy. Backup: /root/backups/tracy-customers-97a785e.

Dashboard source 704e6a0 in unboks-org/unboks-dashboard-api deployed to /var/www/unboks-dashboard/releases/704e6a0fe80c77da82ff45a3f20dd2d14e2410bc, preserving older hashed assets. Typecheck and build passed. Frontend suite passed 229/230 initially; the failing new test used an unsupported memory-router test helper and was corrected, after which both new account tests passed. Existing receipt/attention/pause/navigation tests passed. Browser verified desktop and 390px mobile customer pages with real authenticated read-only data, preserved paragraphs, no horizontal overflow, and PDF download action.
