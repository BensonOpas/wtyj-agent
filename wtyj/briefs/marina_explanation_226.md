# EXPLANATION 226 — Alternative email destination for escalation alerts

## In one sentence
Operators can now save a second email address on the escalation-alert settings page, and every escalation will email both the main support address and the backup address.

## What's changing and why

Until now each tenant had exactly one email destination for escalation alerts — by default the support email stored in client.json. When something needed human attention, that one address got the alert and that was the end of it. The dashboard frontend was already wired to show an "Alternative email" field, but the backend was throwing the value away on save and never returning anything for it on load.

This change makes that second email field real. An operator can type a backup address into the settings page, save it, and from that point forward every escalation email goes to both addresses. Each send is recorded separately in the delivery audit log, so an operator looking at the alert history can see whether the primary, the alternative, or both got through. If one address bounces or the mail server hiccups on one of the two attempts, the other still goes out — neither one waits on the other.

## Step by step — what the code does now

STEP: Loading the escalation-alert settings page

When the frontend asks for the current alert settings, the system now reads the alternative email out of the database alongside the primary email and the on/off switches for each channel. The response always includes an "alternativeDestination" field under email, even when it has never been set — in that case it comes back as an empty string. WhatsApp, Telegram, and Messenger channels do not get this field; it is email-only.

STEP: Saving the escalation-alert settings page

When the frontend sends a save, the system first validates the alternative email. An empty string is fine and means "no backup configured." Anything non-empty has to look like an actual email — there must be an at-sign, something before it, and a domain that contains a dot but does not start or end with one. If the address fails that check the save is rejected with a validation error and nothing is written to the database. If the address is empty or valid, the system writes both the primary and the alternative into the singleton settings row in one atomic upsert. The alternative does not overwrite the primary — they live in two separate columns and are saved as two separate fields.

STEP: First-time database setup on an existing tenant

When the system opens the database, it tries to add the new "alternative email destination" column to the alert settings table. If the column already exists (because this code has run before, or because a fresh tenant DB created it from scratch), the attempt fails silently and the system carries on. This means an existing tenant gets the new column the first time the updated code starts up, with no manual migration step.

STEP: Sending an escalation alert

When an escalation fires and the email channel is enabled, the system builds a list of recipients. The primary address goes in first — if the saved value is empty or the literal string "default," the system substitutes the support email from client.json, exactly as before. Then, if an alternative address is configured and it is not the same as the primary, that gets added too. The system sends the alert to each recipient in turn. Every send attempt — whether it succeeds or fails — gets its own row in the delivery audit log, recording the address, the status, and any error message. A failure on one address does not stop the next address from being tried, and does not bubble up to break the escalation itself.

STEP: Same address typed into both fields

If an operator types the same email into both the primary and the alternative slot, the system notices they match and only sends once. Only one row goes into the audit log. The operator does not get two copies of the same alert.

STEP: Both addresses empty or unconfigured

If the email channel is enabled but neither the primary nor the alternative resolves to anything sendable, the system records a single "skipped" row in the audit log with the reason "no email destination configured" and moves on. No send is attempted.

## Edge cases

- If the operator types the same address in the primary and alternative fields, only one email is sent and only one delivery row is logged. Acceptable — prevents duplicate alerts.
- If the alternative email passes the basic shape check but the SMTP server later rejects it (typo'd domain, mailbox does not exist, etc.), the primary still sends successfully and the alternative shows up in the audit log as "failed" with the SMTP error. Acceptable — matches the brief's "best-effort independent" rule.
- If the primary email send fails but the alternative succeeds, the alternative still goes out. The escalation row itself is created either way, so the human handoff is recorded even when both emails fail.
- Validation is intentionally loose: the system checks for an at-sign, a non-empty local part, and a dot-separated domain, but does not enforce full RFC-5322. An address like "x@y.z" passes. This is by design — strict email validation is a known rabbit hole and SMTP delivery failures already get logged.
- The alternative email field is silently ignored on the WhatsApp, Telegram, and Messenger channels. If a frontend ever sends one for a non-email channel, it is dropped on save and not returned on load.
- The new column is added with a default of empty string and an idempotent ALTER. Tenants who never visit the settings page after this deploy will simply have an empty alternative — no behavior change for them.
- The reverse migration is a no-op. If this commit is reverted, the column remains in the database but is unused; reapplying the change later is also a no-op.

## What did NOT change

The primary email destination behavior is untouched — the support email from client.json still serves as the default, the "default" sentinel string still resolves to that value, and the existing single-recipient code path still works for any tenant that has not configured an alternative. The WhatsApp, Telegram, and Messenger channels are not affected at all. Marina's prompt, the booking flow, the customer-facing reply path, and the escalation row insertion logic are all unchanged. The alternative email is a notification backup only — it never overwrites the support email on the tenant record and is never used as a from-address or a customer-facing address.
