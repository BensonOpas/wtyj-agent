# OUTPUT 211 — Dashboard contract fields

## What was done

Added two enrichments to the dashboard API so SR's EscalationReplyComposer can render. In `wtyj/shared/state_registry.py`: extracted a new `_find_email_thread_key_for(email)` helper from the existing logic in `email_append_assistant_message`, and used it in `get_all_escalations()` to set a new `phone` field per row — `email::<thread_key>` for email rows that have a matched thread, customer_id otherwise. In `wtyj/dashboard/api.py`: added a `_conversation_status_fields(customer_id)` helper that reads `get_conversation_status` and returns `{escalated, escalationResolved, escalationMode, aiMuted}`, then merged that dict into both branches of `get_conversation()` (email and whatsapp). For the email branch the customer_id is parsed from the thread_key middle part. `escalationMode` and `aiMuted` are honest placeholders (None / False) so SR's UI renders the LegacyActionPanel branch — Tier 2 will replace these with real soft/hard storage.

## Tests

949 passing / 0 failures (baseline 944 + 5 new).

## Deployment

Pending — commit/push/deploy in step 16.
