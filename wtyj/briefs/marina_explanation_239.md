# EXPLANATION 239 — Escalation alert quality + active summary freshness

## In one sentence
The alert email an operator gets when the AI hands a conversation off now reads like a useful one-page brief instead of a one-line "something happened," and the dashboard view stays fresh when the customer changes their mind mid-handoff.

## What's changing and why

Before this change, when the AI decided it needed a human, the operator got an email that said almost nothing — just the customer's name, the channel, and the line "Marina escalated a whatsapp conversation." It did not say what the customer wanted, what the operator had to decide, or what the customer's last message was. The operator had to open the dashboard for every single one to find out whether it mattered. The "Mode" line in those emails was always blank too, so the operator could not tell at a glance whether the AI was asking for help (and would resume after) or stepping out entirely.

There was a second problem on the dashboard side. When a customer who had already triggered a handoff sent a follow-up message — for example, "I changed my mind, can we do Friday at 12 instead of Thursday at 5" — the structured summary panel on the dashboard kept showing the old proposed times. The operator was looking at stale information without knowing it.

This change fixes both. The AI already produces a structured summary of every handoff for the dashboard panel; that same summary is now also used to write the alert email. The email now carries the reason, the customer's most recent message word-for-word, the decision the operator needs to make, suggested options, the mode (soft means "AI needs help and will resume," hard means "AI is stepping out"), and — when the customer retracts a previously proposed time — a separate line listing the times that are no longer on the table. The dashboard panel pulls from the same source, so when the customer's situation changes, the panel changes with it. To prevent the operator's inbox from filling up with near-identical follow-up emails on a chatty conversation, the system also compares the new summary against the previous one and only sends a follow-up alert when something operator-relevant actually changed.

## Step by step — what the code does now

STEP: A handoff is created or updated

When any part of the system decides the AI should hand off to a human, it calls into a single shared routine that records a row for the operator. That routine now accepts an extra piece of information called the mode — either "soft" (the AI is asking for help and will resume once the human chimes in) or "hard" (the AI is stepping out entirely). The mode is stored on the handoff row at the moment it is created, so it is no longer blank.

If a row for this customer already exists and is still open, the routine updates it instead of creating a duplicate. On an update, the previously saved structured summary is read from the row first, so the system has a "before" picture to compare against later.

STEP: The structured summary is generated before the alert is sent

The order of two steps was swapped. The system now produces the structured summary first — describing the reason, what the customer wants, what the operator must decide, suggested options, and any proposed times — and only then decides whether to send the alert. This matters because the alert email now reads from that summary. Doing it in the old order meant the email left for the operator before the summary was ready and could not include any of it.

STEP: The most recent customer message is captured verbatim

Right after the summary is produced, the system walks the conversation history backwards and grabs the most recent message that came from the customer (as opposed to the AI). It tucks that exact text into the summary under the label "latest customer message." This way the alert email can quote what the customer just said without the operator having to scroll through the thread.

STEP: The system decides whether to actually send the alert email

If this is a brand-new handoff, the alert is always sent. If this is an update to an existing open handoff, the system compares the new summary against the previous one on three specific things: what the customer wants, the most recent customer message, and the list of proposed times. If none of those three changed, no follow-up email is sent — the dashboard panel still updates silently, but the operator's inbox is spared. If any of those three did change, an updated alert is sent.

STEP: The alert email subject is built

When a structured summary is available, the subject line is now specific. For a scheduling-related update where the customer changed times, the subject reads like "Updated escalation: Calvin changed meeting time to Friday 12:00." For other scheduling situations, it reads "Escalation alert: Calvin needs a scheduling decision." For non-scheduling cases, it includes the first sixty characters of what the customer wants. If the structured summary failed to generate for any reason (no AI key, the AI call errored), the subject falls back to the old short form like "New escalation: Calvin" so nothing breaks.

STEP: The alert email body is built

When a structured summary is available, the body contains: the customer's name, a friendly channel label (WhatsApp, Email, Instagram, Facebook, Messenger), the mode written out as "Agent needs help" for soft or "Hard escalation" for hard, the reason for the handoff, optionally a "Previously proposed (now retracted): ..." line listing times the customer pulled back, optionally the customer's most recent message in quotes, the decision the operator needs to make, up to five suggested options, and a closing line pointing the operator to the dashboard. When the structured summary is missing, the body falls back to the old short format so the operator still gets something.

STEP: The AI's summary instructions learn a new field

The instructions the AI follows when writing the summary now include a new optional field for "previously proposed times" — times the customer raised earlier but explicitly retracted or changed. The AI is told to put the new time in the active proposed-times list and the retracted ones in this new list, and never to put the same time in both. This is what lets the alert email say "Previously proposed (now retracted): Thursday 17:00, Monday 11:00" when the customer pivots to a new time.

STEP: Mode is set at every place a handoff is created

There are eleven places in the code where a handoff can be triggered (one in the Instagram and Facebook DM path, six in the WhatsApp path, and four in the email path). Each one now passes the right mode. Soft mode is used when the AI is asking for human input and will resume — for example, when the AI asks for help on its own, when a group booking exceeds standard capacity, when the booking flow is turned off and the AI is escalating booking intents, or when a large group needs operator review. Hard mode is used when a human takes over entirely — for example, when a customer comes back after the AI was already pulled out, when a full booking conversation requires a human, or when the booking system failed multiple times in a row. The five "relay" rows (Marina's "ask the team a question" flow, which is a separate channel) are intentionally not touched and do not send alerts.

## Edge cases

- If the AI summary fails to generate (no API key, the AI service is down, an error during generation), the alert email reverts to the old short subject and body. The operator still gets notified — they just lose the rich detail for that one event. Acceptable trade-off; nothing breaks.

- If a customer pivots from one topic to another while keeping the same wording and the same proposed times (for example, switches from asking about a refund to making a complaint without changing how they word it or what times they suggested), the follow-up alert will be suppressed because the three watched fields look identical. This is a known limitation; in practice this combination almost never happens, and it can be fixed later by adding the intent field to the comparison.

- The first time a handoff happens for a given customer, an email always goes out. The suppression only ever applies to second and later updates on the same open handoff. Once the operator marks the handoff resolved, the next message starts a fresh handoff with a fresh first email.

- If the database read for the previous summary fails for any reason on an update, the system treats it as if there was no previous summary and lets the alert fire. The operator never silently misses an update due to a transient database hiccup.

- If a customer sends multiple follow-up messages in quick succession that genuinely change the situation, every one of them will produce a follow-up email. There is no time-based throttle. This is intentional — late follow-ups would otherwise be silently dropped by a debounce window.

- The routine that creates the handoff row now initializes a small internal placeholder up front so non-escalation cases (the relay rows) cannot trip over a missing variable. Without that initialization, those non-escalation paths would have hit a reference error.

- The mode column on existing rows is preserved on updates: if an update call passes no mode, whatever mode was set when the row was first created stays put. Only an explicit new mode value overrides.

- Old handoff rows from before this change are unaffected. Their mode column may still be blank, and their summaries (if any) still render on the dashboard the same way they did before. Nothing about the storage shape changed in a backward-incompatible way.

## What did NOT change

The AI's main reply prompt was not touched. The booking flow was not touched. Customer data handling was not touched. The relay channel — Marina's separate "ask the team a question" path — was deliberately left alone, including its five call sites that still record rows without a mode and without sending alerts. The actual delivery of WhatsApp alerts (where the alert goes out as a WhatsApp message instead of an email) was only touched enough to pass the new subject and body through; the underlying WhatsApp send path is unchanged. No tenant-specific code was added — the same alert format works for every client because the client's name and per-tenant summaries come from configuration. The appointment-summary feature wired in earlier was not extended here. BlueMarlin-specific code was not touched.
