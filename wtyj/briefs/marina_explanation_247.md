# EXPLANATION 247 — Register alert dispatcher in email_poller process; remove duplicate legacy email send

## In one sentence

Email-channel escalations now actually fire operator alerts (multiple emails plus WhatsApp) instead of silently going nowhere, and the old single hardcoded email is removed so nobody gets duplicates.

## What's changing and why

For months, when a rude or off-topic email arrived and Marina decided to escalate, the dashboard would dutifully record the escalation, but the operator alerts the team expected to receive — emails to the configured destinations and a WhatsApp ping — never went out. Calvin tripped over this during live verification: the dashboard showed his escalation row, but his primary inbox at calvin@gaimin.io stayed empty and his phone never buzzed. The only thing that actually arrived was a single legacy email to butlerbensonagent@gmail.com that nobody monitors as an operator destination.

The cause is a quiet structural surprise about how the unboks container is laid out. The container is not one Python program — it is three independent worker programs running side by side under supervisord. They share the same database files on disk, but they do not share Python's in-memory state. The "alert dispatcher" — the thing that knows how to fan an escalation out to four channels — is a single in-memory pointer that has to be plugged in once when each program starts. It was getting plugged in only inside the webhook program, the one that handles WhatsApp messages. The email program never plugged it in, so when an email-driven escalation tried to fire alerts, the pointer was empty and the call did nothing. No error, no log line — just nothing.

This change makes the email program plug the dispatcher in at startup, the same way the webhook program already does. It also deletes the old single-recipient legacy email that was masking the problem, because once the dispatcher is wired in correctly, leaving the legacy email in place would mean Calvin gets three emails per escalation instead of two.

## Step by step — what the code does now

STEP: Email program startup wiring

When supervisord boots the email-polling program, the program now reaches into the dashboard module on its way up. That single act of reaching in causes the dispatcher pointer for escalations and the dispatcher pointer for appointment alerts to both get registered in this program's memory. Before this change, the email program never touched the dashboard module, so those pointers were empty for the entire lifetime of the program.

STEP: Customer sends a rude or off-topic email and Marina decides to escalate

Marina reads the email, decides it warrants human attention, writes an internal note, and the email program records an escalation row in the database — exactly as before. Nothing about that decision changes.

STEP: The escalation row triggers operator alerts (this is the part that was broken)

Right after the row is written, the system asks the dispatcher to fan the alert out to every configured channel. Before this change, the dispatcher pointer was empty in this program, so the request quietly went nowhere. Now the pointer is wired in, so the dispatcher actually runs. It sends an email to the default operator address, sends a second email to the alternative operator address (calvin@gaimin.io for unboks), sends a WhatsApp message to the operator's phone via the Zernio route, and attempts a Telegram alert (skipped because Telegram isn't configured). The email body is the rich format that the WhatsApp side already used — booking reference, customer name, summary, link back to the dashboard — not the old hardcoded one-line body.

STEP: The old single-recipient legacy email no longer runs

The block of code that used to send one hardcoded email to butlerbensonagent@gmail.com has been removed. In its place is a comment marker explaining why it's gone, so the next person reading the file doesn't put it back. The internal note text that the old email used is still computed, because the dispatcher reuses it as the body of the alerts it sends out.

STEP: WhatsApp-side escalations are unaffected

When the customer comes in over WhatsApp instead of email, everything continues to work exactly as it did before. Those escalations originate inside the webhook program, where the dispatcher has always been wired in correctly. This change does not touch the webhook program.

## Edge cases

- If the email program starts up but the dashboard module fails to import for some reason, the program won't start at all — supervisord will keep trying to restart it. This is louder than the old silent no-op, which is the right trade-off.
- The four historical escalation rows that silently no-op'd (id 16, 23, 26, 27) are not back-filled. Those customers were already handled manually; no alerts will be retroactively sent for them.
- The hold-reaper program — the third worker process — was checked and confirmed not to create escalation rows, so it does not need the same fix.
- The relay-mode email path (a different concept, used to route operator replies back through email threads) still uses its own direct send. The dispatcher was never meant to handle that path, so it was deliberately left alone.
- If a future feature adds a fourth worker process that needs to create escalations, that brief will need to add the same one-line wiring at the top of the new process. Until somebody extracts the dispatcher functions into a standalone shared module, every new worker process has to opt in this way.
- The dispatcher's underlying call has its own try/except wrapper that swallows errors silently. So if (for example) WhatsApp delivery fails, the escalation row still gets created and the email alerts still go out, but the WhatsApp failure won't be loudly surfaced.

## What did NOT change

Marina's prompt, her decision logic for when to escalate, the booking flow, the customer-facing email reply, the dashboard's escalation display, the WhatsApp escalation path, the relay email path, and the database schema were all left untouched. Only two things were modified inside the email-polling program: the addition of one wiring import at the top of the file, and the removal of the old single-recipient hardcoded email block. Everything else — including the eight other briefs landed in the same week — is preserved.

EXPLANATION WRITTEN: wtyj/briefs/marina_explanation_247.md
