# EXPLANATION 253 — Filter get_all_escalations by conversation_status.deleted (Brief 249 follow-up)

## In one sentence

When Calvin archives a WhatsApp/Instagram/Facebook conversation, every escalation tied to that conversation now disappears from the dashboard's Escalations tab — instead of staying stuck and visible forever the way Calvin's eight rows had been.

## What's changing and why

A few weeks ago Brief 249 added an "archive conversation" button so Calvin could clear out Messages-tab clutter. That fix worked — once a conversation was archived, it stopped appearing in the Messages list. The problem nobody caught at the time: the Escalations tab pulls its rows from a different query, and that query was never taught about the archive flag. So Calvin would archive a noisy conversation, the conversation would vanish from Messages, but the seven or eight escalation rows attached to it would keep sitting in the Escalations tab with no way to dismiss them. He flagged one as "impossible to archive, it's stuck."

This change applies the same archive-aware filter Brief 249 used for the Messages tab to the Escalations tab. From this deploy forward, an escalation only shows up in the Escalations tab if its underlying conversation is either active or has never been archived. The eight stuck rows on Calvin's two archived WhatsApp conversations (seven on his main one, one on a second) will be gone the moment he refreshes the dashboard. Nothing is deleted from storage — this is purely a "what gets shown" filter — so if Calvin ever unarchives one of those conversations, the escalations come right back, exactly as they were.

## Step by step — what the code does now

STEP: Loading the Escalations tab

When the dashboard asks the system for the full list of escalation rows, the system now also peeks at the conversation-status table at the same time. For every escalation it would normally return, it asks: "Has the conversation this escalation belongs to been archived?" If the answer is yes, that escalation is dropped from the list before it ever leaves the database. If the conversation has never had a status entry created for it (which is the case for most active conversations), the escalation is kept — the lookup gracefully treats "no status row" the same as "not archived."

STEP: Archiving a WhatsApp/IG/FB conversation

Nothing about the archive button itself changed. When Calvin clicks Archive on a conversation, the system still flips the conversation's status to archived in exactly the same way Brief 249 set up. The new behavior is downstream of that: the next time the Escalations tab refreshes, every escalation tied to that conversation simply stops appearing.

STEP: Unarchiving a conversation

If Calvin ever unarchives a previously-archived conversation, the system flips the archive flag back off. On the next Escalations tab refresh, every escalation that had been hidden for that conversation reappears in the list, in its original order, with its original status (replied, resolved, etc.). No data was destroyed when the conversation was archived, so the rows return intact.

STEP: Cleaning up Calvin's eight stuck rows

No special migration runs. The eight specific rows Calvin has been staring at — seven on conversation `69efec...` and one on `69f7ce...` — were already attached to conversations that had been archived weeks ago. The new filter automatically excludes them from the Escalations tab the moment the deploy completes. Calvin needs to refresh his browser to see them disappear.

## Edge cases

- If a conversation has no conversation-status row at all (the normal state for most active conversations), its escalations are kept and shown. The lookup is built to treat missing status rows the same as "not archived."
- If Calvin unarchives an archived conversation, every escalation that was hidden comes back. This is intentional — the fix is a view filter, not a deletion. Acceptable and documented.
- Email-channel conversations are not covered by this filter. Email archives use a different storage mechanism (a flag inside a JSON file rather than the conversation-status table), so an archived email conversation can still leave its escalations visible in the Escalations tab. Calvin's reported stuck rows were all WhatsApp, so this gap doesn't affect the immediate problem. If the same complaint shows up for email later, a follow-up brief will extend the filter.
- Resolved/history view also benefits — when Calvin filters the Escalations tab by status=resolved, he no longer sees ghost history of conversations he intentionally archived. This is a minor side benefit of using a single filter at the database layer.
- Calvin must refresh the dashboard after the deploy completes. The browser caches the existing list; until he refreshes, his old screen will still show the stuck rows.
- The eight existing stuck rows are not deleted from storage. They remain in the pending-notifications table for audit trail purposes, including their links to delivery records. If anyone runs a raw database query, the rows are still there — they just no longer surface to the dashboard.

## What did NOT change

Marina's prompt, the booking flow, customer data handling, the archive button itself, the way escalations get created, the way Calvin replies to or resolves an escalation, and the email-side archive mechanism are all untouched. No database columns were added or removed; no historical data was migrated, mutated, or deleted. The change is contained to a single database query that decides what the Escalations tab is allowed to see, plus two new tests that prove the filter works in both the archived-conversation and the no-status-row cases.
