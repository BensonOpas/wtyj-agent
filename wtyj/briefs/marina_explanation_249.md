# EXPLANATION 249 — Server-side per-conversation archive endpoints + resolved escalations history

## In one sentence

When an operator archives a conversation on one device, every other device they sign into now sees that conversation as archived too — and the long-broken nightly WhatsApp archive sweep finally starts hiding old conversations the way it was always supposed to.

## What's changing and why

Until today, the archive button in the dashboard only remembered its choice inside the browser the operator clicked it on. Calvin and Sonia caught this in a live test: archive a conversation on the desktop, then open the dashboard on the phone, and the conversation is right back in the inbox — because "archived" was a sticky note saved in the browser, not a fact saved on the server. That broke the basic promise of a shared inbox.

The fix moves the archive state out of the browser and into the server. Archive lives next to the conversation itself, so every device sees the same inbox. Two new buttons (archive and unarchive) talk to the server, and a new list shows everything that's been put away. The escalations list also gains a filter so the dashboard can finally show a Resolved/History view of past escalations.

There is one more thing worth knowing. Several weeks ago, an earlier change (Brief 237) added a nightly sweep that was supposed to hide WhatsApp conversations that had gone quiet. That sweep has been silently failing every single night since it shipped, because it was writing to a column in the database that was never actually created. Nobody noticed because the sweep's tests only exercised the email side. Brief 249 adds the missing column, so starting with the next nightly run, the sweep will work for the first time. The first time it runs, operators may see the WhatsApp conversation count drop noticeably as the backlog of "should have been archived weeks ago" conversations gets cleared in one pass. That is the intended behavior catching up with reality, not a bug.

## Step by step — what the code does now

ADD THE MISSING DATABASE COLUMN

The system now adds a "deleted" column to the conversation status table the first time the service starts up after this change. If the column is already there from a previous boot, the system shrugs and moves on. This single line is what unblocks every other piece of the brief — without it, both the new manual archive endpoint and the old nightly sweep would crash on every WhatsApp conversation they touched.

ARCHIVE A SINGLE CONVERSATION (operator-initiated)

When an operator hits the archive button in the dashboard, the server looks at the conversation's identifier. If it begins with the email prefix, the server opens the email thread file, finds that thread, and writes a flag onto it that means "hide from the active inbox." If the identifier is a phone number or social handle, the server writes a row into the conversation status table marking that conversation as archived, creating the row if no row exists yet. Either way, the server replies with a confirmation that says which channel was archived and that the new state is "archived." Archiving a conversation that's already archived is harmless — the server just confirms the state again.

UNARCHIVE A SINGLE CONVERSATION

The unarchive button does the exact reverse. For an email thread, the server removes the hide flag entirely so the thread file looks like it was never archived. For a WhatsApp/IG/FB conversation, the server flips the archived marker back to off. As with archive, doing this on a conversation that isn't archived is harmless.

LIST WHAT'S IN THE ACTIVE INBOX

The active inbox query was updated to skip any WhatsApp/IG/FB conversation whose archived marker is on. Conversations without a status row at all (the common case for new conversations) are still shown. Email already had this filter, so nothing changed there. The visible result is what operators expect: archived conversations disappear from the main inbox view immediately, on every device.

LIST WHAT'S BEEN ARCHIVED

A new list endpoint returns the opposite view — only conversations that have been archived, from both email and WhatsApp/IG/FB, merged into one list and sorted by most recent activity. The shape of each entry is identical to an active-inbox entry, so the dashboard can render the archived view with the same row component it already uses. Each row is tagged with the status "archived" so the UI can style it differently if it wants.

FILTER ESCALATIONS BY STATUS

The escalations list endpoint already supported filtering by mode (soft vs hard). It now also accepts a status filter — resolved, sent, pending, replied, or all. Pass nothing and the behavior is unchanged. Pass "resolved" and the dashboard gets back only escalations that have been marked resolved, which is exactly what the new Resolved/History view needs.

WHAT THE FRONTEND HAS TO DO

SR's React app needs to swap its old browser-only archive memory for calls to the new endpoints. The active inbox should hit the existing conversations endpoint (now correctly excluding archived), the archived view should hit the new archived list endpoint, and the archive/unarchive buttons should call the new POST endpoints. The Resolved/History view points at the escalations endpoint with the new status filter. Until SR ships that swap, the dashboard will continue using browser-only archive — but the server side is ready and waiting.

## Edge cases

- If a customer sends a new message into an archived conversation, the conversation still gets fully processed (Marina answers, escalations fire, the works) — archiving only hides the row from the inbox list, it does not block ingestion. The conversation stays archived even after the new message arrives. Whether that conversation should auto-pop back into the active inbox on new activity is a product decision deliberately left for a future brief.
- Archive on email uses the underlying flag named "deleted" but it is not a real delete — the thread file is left intact and the row is recoverable by unarchive. The destructive email-delete endpoint is untouched and still removes rows for good. Two different buttons, two different operations, both kept.
- If an operator tries to archive an email thread whose identifier doesn't match any thread on disk, the server returns "not found" rather than silently succeeding. WhatsApp archive does not have this check — it will create a status row for any identifier passed in, archived from the start. This matches how the bulk sweep already works.
- Archiving a conversation that has an open escalation does not close or change the escalation. The escalation row keeps its status and will show up wherever escalations are listed. The archive flag only affects the inbox listing.
- When the column-adding migration runs for the first time on each tenant's database, conversations that had been silently failing to archive over the past several weeks via the nightly sweep will get archived on the next nightly run. Operators may see a noticeable one-time drop in the WhatsApp conversation count after that run. This is expected.
- If the email thread file cannot be opened or written (disk error, permission issue), the archive call returns "false" and the dashboard shows no change. The thread file is written through a temp-file rename so a crash partway through cannot corrupt it.
- Archive and unarchive are both idempotent — repeating them does no harm.

## What did NOT change

Marina's prompt, Marina's reply behavior, the booking flow, the escalation creation logic, customer message ingestion, and the destructive email-delete endpoint are all untouched. The block/unblock endpoints are unchanged. The bulk archive-now sweep added by Brief 237 is unchanged in code — what changed is that the database column it writes to now actually exists, so the sweep's effect becomes visible. No existing list endpoints changed shape; the changes are additive (new endpoints, one new optional query parameter on the escalations list).
