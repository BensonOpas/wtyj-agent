# EXPLANATION 218 — Email forward + delete actions

Plain-English explanation of commit `6c6e6a7` for an operator who doesn't read code.

## What was missing

In the dashboard's email inbox view, every conversation row has three buttons: Reply, Forward, Delete. Reply was already wired up in earlier briefs. Forward and Delete have been visible but inert — clicking them did nothing meaningful (the frontend showed its calm "will be connected" notice). Brief 218 wires both up.

## What changed

**Forward** — when you click Forward on an email conversation:

1. You type one or more recipients (and optional cc / bcc).
2. You can write a short note to prepend ("FYI" or "thoughts?").
3. The backend grabs the most recent customer message in that conversation and sends it via SMTP to each recipient. The forwarded email's subject is "Fwd: from <customer's email>" and the body looks like:

```
[your note, if any]

---------- Forwarded message ----------
From: customer@example.com

[the original customer message body]
```

Each recipient gets the same message addressed to themselves. cc and bcc are flattened into per-recipient sends (no shared cc list visible in the recipient inbox — this is a v1 simplification).

**Attachments are NOT forwarded.** The customer's original email might have had attachments, but our backend doesn't store them when emails are first ingested (only the parsed text body is kept). The response signals `attachments_included: false` so the frontend can show a small caveat in the UI ("attachments not forwarded — open original in Gmail").

Hard cap of 20 recipients per forward — prevents accidental spam-blasts.

**Delete** — when you click Delete on an email conversation:

1. You confirm the action (frontend handles the confirmation dialog).
2. The backend marks the conversation as deleted in our local state.
3. The conversation disappears from the dashboard inbox.

For v1, only `deleteMode: "trash"` is accepted. The frontend's `archive` and `permanent` modes return a 400 error with a clear message ("v1 supports trash only"). Permanent delete is intentionally restricted — accidental clicks should be recoverable.

**The original email is NOT moved to trash on the provider side yet.** The conversation disappears from the dashboard, but if you log in to `hello@unboks.org` Gmail directly, the email is still there. We have a TODO to add IMAP MOVE-to-trash later; the design notes are in the code (Gmail folder is `[Gmail]/Trash`, Outlook folder will be `Deleted Items`, detection is via the `EMAIL_PASSWORD` env var). For now, the operator-facing experience (conversation gone from dashboard) works; provider cleanup is a follow-up.

## What it does now

- Click Forward on an email conversation → operator types recipients + optional note → backend sends real SMTP forwards → recipients get the customer's message in their inbox.
- Click Delete on an email conversation → conversation disappears from the dashboard inbox immediately.

## What it doesn't do (deferred)

- Forward attachments (would require storing them at ingestion time — separate brief).
- Delete from the provider's mailbox (Gmail trash). Local-only delete v1.
- Archive or permanent delete modes. Trash-only v1.

## Files changed

- `wtyj/dashboard/api.py` — two new endpoints (`/email/forward`, `/email/delete`) with their request models. Routes use the `:path` URL converter to handle `email::`-prefixed conversation ids.
- `wtyj/shared/state_registry.py` — two new helpers (`email_mark_deleted`, `email_get_latest_customer_message`); `email_list_conversations` now skips threads marked deleted.
- `wtyj/tests/social/test_218_email_actions.py` — six tests covering forward happy path, empty recipients 400, empty thread 404, attachments-skipped acknowledgment, delete + filter from list, invalid mode 400.
