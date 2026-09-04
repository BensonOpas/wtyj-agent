# Mermaid operator-managed trip catalog

User request: move Trip & pricing out of the primary menu and make the same information editable in Settings.

## Scope and safeguards

- Build on the currently deployed customer-account backend `97a785e`; preserve pickup vehicle pricing, contact numbers, customer history, soft review and checkout fixes.
- Authenticated Mermaid-only `PUT /dashboard/api/mermaid-reservations/catalog`, guarded by the existing dashboard feature and tenant checks. GET now advertises the publishing capability and a SHA-256 content revision.
- The operator edits the existing catalog consumed by TRACY and the quote engine, not a second knowledge store. Publish applies immediately on subsequent catalog reads, with no service restart.
- Editable service, fare, pickup, inclusion, packing and policy fields are allowlisted. Tenant identity, links, message templates, product key and feature controls are protected.
- Whole-unit currency prices match the current integer-based quote engine. USD/EUR/XCG remain explicit. Default and pickup currencies must match until conversion rates exist. Car/van capacity and overflow rules remain authoritative.
- Schedule validation now validates real local clock times and selected weekdays rather than locking the original published schedule. Regular operating days are not seat inventory.
- Demo policy markers, neutral unverified insurance wording, simulated payments and reminders-off safeguards remain. This is not production-policy approval.
- Process-safe file locking and a content-based compare-and-set revision prevent lost updates, including edits outside the dashboard. Validate first, retain the complete previous catalog in protected history, fsync and atomically replace the one mounted catalog file. Return 409 for a stale edit, 422 for invalid content and 503 for persistence failure.
- Remove only the legacy generated pickup extra during publishing so it cannot contradict edited transport prices. Operator-written extras remain. TRACY receives structured pickup prices/capacities.
- No reservation, monetary snapshot, quote/receipt file, agent state or guest message is written by publishing. Existing reservation price snapshots win over current prices in TRACY's prompt.

## Tests and release

Tests exercise authenticated API-to-file persistence, subsequent TRACY prompt reads, quote calculations, vehicle calculations, protected fields, malformed data, file write failure, parallel publishing, stale external edits and unchanged existing reservation snapshots. The old fixed-06:45 test now rejects an invalid 27:00 time instead; valid edited schedules are covered.

Deploy only the three changed runtime modules into a dedicated image derived from the verified current Mermaid image. Preserve mounted configuration, credentials, database, provider bindings and other tenants. Retain the previous image and a protected consistent database/config snapshot. Verify the candidate in an isolated no-network container before cutover. Do not use a shared deployment job.
