# EXPLANATION 220 — Block conversation (per-conversation runtime drop)

## In one sentence
The operator can now hit a Block button on any conversation in the inbox to silence it completely — every future message from that customer gets dropped the moment it arrives, before it ever gets stored or shown in the inbox, and Unblock reverses it instantly.

## What's changing and why

Until today, the operator had two ways to mute a noisy customer, and neither was good. They could edit the static deny-list in the tenant's config file (the one that lists phone numbers to ignore) and redeploy the whole container, which is slow and requires engineering. Or they could AI-mute the conversation, which keeps Marina quiet but still leaves every incoming message visible in the inbox — useful when you want to watch silently, useless when the customer is being abusive or spammy and you just want them gone.

This change closes that gap. The operator clicks Block on a conversation, and from that moment on, every new inbound from that customer is silently thrown away at the very first moment it enters the system. No row in storage, no notification, no entry in the inbox list, no escalation alert. The conversation stops existing from the operator's point of view. Old messages that were already in the inbox before the block stay where they are — the block only affects new traffic. Clicking Unblock reverses the flag and the next message comes through normally.

This is deliberately different from the AI-mute feature shipped earlier. AI-mute means "store the message but don't let Marina respond" — operator still sees it. Block means "drop it on the floor and never tell anyone." Both flags live side-by-side on the same conversation; an operator can have a conversation that is muted, blocked, in human-takeover, or any combination, without the flags interfering.

The system also still honours the older static phone-number deny-list configured per-tenant. That one runs first on every inbound (it's faster — just a config-file lookup against the caller's digits). If the static list doesn't match, the new per-conversation block flag is checked next. Either one drops the message; the operator now has both a slow tenant-wide tool and a fast one-click conversation-level tool.

## Step by step — what the code does now

STORAGE COLUMN ADDED ON STARTUP

When the system opens its database connection for the first time, it now tries to add a new "blocked" column to the conversation status table, alongside the existing AI-mute flag and the human-takeover timestamp. If the column is already there from a previous run, the system shrugs and moves on. The column defaults to zero (not blocked) for every existing conversation, so nothing changes for current customers until an operator explicitly blocks them.

FLIP THE BLOCK FLAG

When the operator's Block (or Unblock) action reaches the storage layer, the system writes a row keyed by the conversation's identifier. If a row for that conversation already exists, only the blocked flag and the last-updated timestamp are touched — the channel label and any other status fields are left alone. If no row exists yet, a new one is created with a default pending status. Passing False to the same function clears the flag.

CHECK WHETHER A CONVERSATION IS BLOCKED

Every time a new customer message lands, the system runs a single-row lookup keyed by the conversation's identifier and reads back the blocked flag. Empty identifiers return False immediately so the check is safe to call on every inbound. Missing rows return False — the default state is "not blocked."

LIST EVERY BLOCKED CONVERSATION

For the dashboard's settings page, the system can hand back the full list of currently-blocked conversations, sorted with the most recently blocked at the top. Each entry carries the conversation identifier, the channel it lives on (WhatsApp, DM, email, or empty if the channel was never recorded), and when it was last toggled.

DASHBOARD BUTTON: BLOCK A CONVERSATION

The dashboard now has an authenticated endpoint that accepts a conversation identifier in the URL and flips the blocked flag to true for that conversation. It returns a small confirmation payload so the frontend can update the UI immediately.

DASHBOARD BUTTON: UNBLOCK A CONVERSATION

A parallel endpoint clears the flag. The same conversation can be blocked and unblocked any number of times; nothing else about the conversation's state is touched by either action.

DASHBOARD VIEW: LIST OF BLOCKED CONVERSATIONS

A third endpoint feeds the settings page with the full list of currently-blocked conversations, so the operator can review what's been silenced and unblock things from a central management list rather than having to find each conversation in the inbox.

INSTAGRAM AND FACEBOOK DM DROP CHECK

When a direct message arrives from Instagram or Facebook through the Zernio webhook, the system already runs the static phone-number deny-list check. Right after that, it now also checks the per-conversation block flag. If the conversation is blocked, the system writes a log line saying so and returns immediately — the message is never stored, never shown to Marina, never appears in the inbox.

WHATSAPP DROP CHECK (NEW PATH)

When a WhatsApp message comes in through the Zernio integration and the buffer that batches rapid consecutive messages flushes, the system now checks the block flag for that conversation before doing anything else. The check sits before the AI-mute check, because block is the stronger action — if it's blocked, nothing else matters. A blocked conversation logs and exits the flush silently.

WHATSAPP DROP CHECK (LEGACY PATH)

The same check is added to the older direct-from-Meta WhatsApp path, where the conversation is keyed by phone number rather than the Zernio conversation identifier. Same behaviour: log and return before any storage call.

EMAIL DROP CHECK

When the email poller pulls a new unread message from the inbox, it now looks up the sender's email address as the conversation identifier and checks the block flag. If the sender is blocked, the system marks the email as read in the mailbox (so the poller doesn't keep tripping over it on the next sweep), updates the thread's last-activity timestamp, saves state, and moves to the next unread message. The email is never appended to the conversation's message history, so Marina never sees it and the inbox never displays it. The mailbox itself still contains the email — it's just marked read and ignored.

ORDER OF CHECKS ON EVERY INBOUND

For each new customer message, the system now runs through this order before anything is stored: first the tenant-wide static phone deny-list (fast, in-memory config check), then the per-conversation block flag (one database read), then the existing AI-mute and human-takeover logic. The first match wins and silently drops the message. If nothing matches, the message proceeds normally to storage and Marina.

## Edge cases

- If a conversation is blocked while a message from that customer is mid-flight (already past the drop check, on its way to storage), the in-flight message will land normally. Only messages that arrive after the block is set will be dropped. This is acceptable — the window is milliseconds.

- Messages that landed in the inbox before the block was set stay visible. The block only affects future inbound. The operator can still read the history; they just won't get any new entries.

- For email, the system can't truly "drop before storage" the way it does for WhatsApp and DM, because by the time the poller sees the message, the email is already sitting in the mailbox via IMAP. The system handles this by marking it read and skipping the append to the conversation's message history. The operator never sees it in the inbox, but it does still exist in the underlying mailbox if anyone goes looking.

- If the operator blocks a conversation that has no row in the status table yet (a brand-new conversation, never seen before), the block helper creates the row with a default pending status. This works correctly but means a conversation can be blocked before it has ever sent a message.

- If someone manually rolls back this change, the database column for blocked stays in place because SQLite cannot drop columns. The column becomes harmless dead data — nothing reads it anymore, and any conversations that were blocked at rollback time will start receiving messages again on the next inbound. No data fix needed.

- The block helper's channel label is only recorded on the very first insert for a conversation. If the operator blocks an existing WhatsApp conversation that was previously stored as DM, the channel label stays as DM. This is harmless because the channel field is just for display in the management list.

- The per-conversation lookup adds one database read on every inbound message. The lookup is a single-row primary-key fetch and is fast, but it does run on every message in addition to the existing static deny-list check.

- The block check on the WhatsApp path runs inside the flush function, which means messages that arrive within the buffer window but before the flush will sit in memory briefly until the flush triggers, then get dropped. The drop still happens before any storage call, so the inbox stays clean either way.

## What did NOT change

Marina's prompt, the booking flow, the customer reply pipeline, the existing static phone-number deny-list, the AI-mute feature, the human-takeover timestamp logic, escalation handling, the email reply or forward features, and customer data already stored in any conversation are all untouched. The block flag is a new column on the conversation status table that sits alongside existing flags without modifying any of them. No existing conversation's state changes until an operator explicitly blocks it.
