# OUTPUT 218 — Email forward + delete actions

## What was done

Two new endpoints in `wtyj/dashboard/api.py`: `POST /messages/conversations/{conversation_id:path}/email/forward` and `POST /messages/conversations/{conversation_id:path}/email/delete`. Forward looks up the email thread (via Brief 211's `_find_email_thread_key_for`), grabs the latest customer-role message via the new `state_registry.email_get_latest_customer_message` helper, builds a "Fwd: from <email>" subject + a body that prepends an optional operator note then the standard "Forwarded message" delimiter then the original body, and calls `smtp_send` per recipient (cc/bcc flattened into per-recipient sends). Returns `{ok, forwarded_to, failed, attachments_included: false}` — `includeAttachments=true` is honored as `false` because attachments aren't stored at ingestion time today. Delete validates `deleteMode == "trash"` (returns 400 for `archive`/`permanent`), then calls the new `state_registry.email_mark_deleted` helper which sets `flags.deleted=True` on the email_thread_state.json thread; `email_list_conversations` was patched to filter those rows so the dashboard hides them. Provider-side IMAP MOVE to `[Gmail]/Trash` (or `Deleted Items` for future Outlook tenants) is deferred with a TODO comment + Why-this-approach explanation. Routes use `:path` URL converter for the conversation_id (matches the existing pattern at `/messages/conversations/{phone:path}`).

## Tests

988 passing / 0 failures (baseline 982 + 6 new).

## Unexpected findings

Test 6 originally asserted the literal string `"trash only"` in the 400 detail; the actual detail uses single-quoted `'trash' only`, so the substring match failed. One-line fix to assert `"trash" in detail and "only" in detail` instead — semantically equivalent, less brittle.

## Deployment

Pending — commit/push/deploy in step 16.
