# EXPLANATION 232 — Archive auto-restore on inbound email

## In one sentence
When a customer sends a fresh email to a conversation an operator had previously archived, the conversation now pops back into the active inbox automatically — unless the customer has been blocked, in which case it stays gone.

## What's changing and why

Up to now, archiving and blocking behaved the same way on the email channel: once an operator clicked the trash/delete button on a conversation in the dashboard, the conversation was hidden from the inbox forever. Even if the customer wrote in again, the new message was quietly stored on disk but never resurfaced — the operator would never see it.

SR's product spec drew a line between those two ideas. Archiving means "I'm done with this for now, get it out of my view." Blocking means "I never want to hear from this person again." A new email from an archived customer is a sign they still need help, so it should pull the conversation back into the inbox. A new email from a blocked customer should still be silently dropped. This brief implements that distinction on the email path. Other channels (WhatsApp, Instagram, Facebook) already worked correctly because their archive feature lives in the operator's browser only, and their delete button erases the conversation entirely rather than flagging it.

## Step by step — what the code does now

UN-ARCHIVE HELPER

A small helper now lives at the module level of the email-polling code. Given a conversation record, it looks at the conversation's flag bag. If the "archived/deleted" flag is set, the helper removes that flag entirely (not just sets it to false — it deletes the key so the record looks identical to one that was never archived) and reports back that it un-archived the conversation. If the flag wasn't there, it does nothing and reports that no change happened. The helper is deliberately ignorant of blocking; it trusts the caller to have already filtered out blocked customers before invoking it.

INBOUND EMAIL PROCESSING

When the email poller picks up a new inbound message and matches it to a known conversation, the order of operations is now:

First, the blocking check runs. If this customer's address is on the runtime block list, the poller marks the message as seen on the mail server, saves the timestamp, and skips the message entirely. The conversation is never touched, the message is never appended to the chat log, and the un-archive helper is never reached. This is what guarantees blocking always wins over archiving.

Second — only if the customer is not blocked — the un-archive helper runs against the conversation record. If the conversation was previously archived, the flag is cleared and a log line is written noting which customer and which thread just came back to life. If the conversation wasn't archived, nothing changes.

Third, the new inbound message is appended to the conversation's chat log as before, and normal AI processing continues from there.

The net effect is that the next time the dashboard asks for the active inbox, the previously hidden conversation now passes the visibility filter and shows up alongside everything else, with all of its prior history, escalation state, and operator notes intact.

## Edge cases

- If a conversation is both archived AND escalated to a human (the "fully_escalated" flag is on alongside the "deleted" flag), only the archived flag is cleared. The conversation reappears in the inbox still in escalated/human-handled mode. SR explicitly wanted prior escalation context preserved on restore, so this is intended.

- If a conversation is archived AND blocked, the new inbound never reaches the un-archive step. The conversation stays hidden and the customer's message is dropped on the mail-server side. Block always wins.

- If a customer's conversation was archived months ago and they never write back, nothing un-archives it. There is no bulk "restore all archived threads" action and no time-based auto-restore. The trigger is strictly "a fresh inbound message from this customer." SR's spec called for exactly this, so it is a deliberate limit, not a gap.

- If a conversation record somehow has no flag bag at all (a very old or malformed thread), the helper safely creates an empty flag bag, finds no archived flag, and reports no change. No crash.

- If the operator replies to an archived conversation from the dashboard without the customer having written in, the conversation is NOT un-archived. Restore is triggered only by inbound customer mail, not by outbound operator action. This was a deliberate design choice — operator-side and customer-side state changes stay asymmetric.

- The change applies only to the initial inbound branch of the email poller. The relay-receive and escalation-receive branches (other paths where mail can land in a conversation) are not touched. If those paths ever need the same behavior, that is a separate brief.

## What did NOT change

Marina's prompt, the booking flow, customer message content handling, and the AI's reply generation are all untouched. No new endpoints, no new database fields, no schema changes. The dashboard delete button still flags conversations as archived the same way it did before — the only new thing is the path that clears that flag. WhatsApp, Instagram, and Facebook conversation handling is unchanged. Blocked-customer behavior is unchanged: blocked still means silently dropped, on every channel.
