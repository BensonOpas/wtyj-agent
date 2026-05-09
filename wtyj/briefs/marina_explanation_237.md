# EXPLANATION 237 — Data Retention Action Endpoints

## In one sentence
Three dashboard buttons that used to return "not yet implemented" now actually archive old conversations, export customer data, and delete or anonymize a customer's records — with a hard refusal to delete anyone whose case is still open.

## What's changing and why
Operators can finally use the data-retention controls. Archive sweeps any conversation silent longer than the configured days and marks it hidden, leaving messages intact. Export dumps customer-side records into one timestamped JSON file on the server. Delete-customer-data either removes one person's records entirely or replaces identifying details with "[redacted]," depending on the saved policy.

A new audit log table records every retention attempt — successful runs, exports, and refused deletions alike. If an operator tries to delete a customer with an unresolved escalation, the system blocks the action, writes the refusal to the audit log, and returns an error instead of touching any data. Approved learnings stay untouched when the policy says to keep them.

## What did NOT change
Marina's prompt, the booking flow, customer messaging behavior, and the automatic retention cron (still off) were not touched.
