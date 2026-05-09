# OUTPUT 237 — Data Retention Action Endpoints

## What was done
Replaced the 3 honest-501 stubs at `wtyj/dashboard/api.py:913-942` with real implementations: `archive_now` sweeps email threads + WhatsApp/IG/FB conversations older than `activeInboxArchiveAfterDays`, skipping active escalations (Brief 235's `IN ('pending','sent')` filter) and human takeover; `export` dumps customer-side data to `data/exports/{tenant}-{ISO}.json` with atomic write; `delete_customer_data` resolves the integer customer PK + every text identifier the customer was filed under (phones, emails, conv_ids), then either DELETEs rows or sets PII to `[redacted]` per `endOfRetentionAction`. Added new `data_retention_audit_log` table + `data_retention_audit_write()` helper — audit row fires for ALL outcomes including the blocked-by-active-escalation 409 path (Rule 10). Updated `get_data_retention_settings` status to `policyActive=False, manualActionsAvailable=True, nextCleanupAt=None` per brief-reviewer's "no fake success" call. Removed stale `test_action_endpoints_return_501` from test_229 — it codified the 501 behavior we just replaced.

## Tests
1015 passing / 0 failures (baseline 1007 + 9 new − 1 stale).

## Unexpected findings
Two schema mismatches caught during execution: `customers` table has no `phone`/`email` columns (those live in `customer_identifiers` keyed by integer FK), and `escalation_learnings` keys on `conversation_id` + `human_answer`, not `customer_id` + `answer_text`. Production code corrected for both before tests were re-run. Brief reviewer caught the related `pending_notifications.customer_id IS TEXT` schema issue in round 1; the same vigilance was warranted for these adjacent tables.

## Deployment
Source committed and pushed; deploy to fire next.
