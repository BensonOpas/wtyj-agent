# EXPLANATION 240 — Operator WhatsApp alerts via Zernio + delivery-status truth

## In one sentence
Calvin will start receiving operator escalation alerts on WhatsApp at +351963618003 (after a one-time bootstrap text), and until that bootstrap happens the audit log will honestly say the alert was skipped instead of falsely claiming it was sent.

## What's changing and why

For weeks, escalation alerts to Calvin's WhatsApp number looked successful in the audit log — they were marked "sent" — but Calvin never actually got them on his phone. The audit traced this to the old WhatsApp provider (Meta's Cloud API). Meta accepted the outgoing call, gave back a confirmation ID, and then silently threw the message away because Calvin's number had never started a conversation with the unboks WhatsApp Business number in the previous 24 hours. Meta only delivers free-form messages inside that 24-hour window; outside it, only pre-approved templates go through, and there were none configured for operator alerts. The audit log only ever heard back from Meta on the synchronous "yes I got it" reply, not the later "actually I dropped it" report, so the system kept marking failures as successes.

This change moves operator WhatsApp alerts onto Zernio — the same provider already used for the unboks customer chat — which has no 24-hour-window restriction. The catch is that Zernio identifies a destination by an internal conversation ID, not by a phone number, so the system needs to learn that ID before it can send anything. That learning happens through a one-time bootstrap step: the operator sends a single WhatsApp message from their phone to the unboks WhatsApp Business number, the system spots the inbound, recognizes the sender as the configured operator number, and quietly captures the Zernio routing details for future use. Until that bootstrap inbound arrives, every escalation alert records its status as "skipped" with a clear reason explaining why — no more false "sent" claims.

## Step by step — what the code does now

STEP: Storing the Zernio routing details next to the operator's phone

The settings table that holds operator alert preferences gains three new optional fields: the Zernio conversation ID, the Zernio account ID, and a timestamp marking when those values were captured. The phone number the operator typed into Settings is left exactly where it was — that's still the human-readable destination the operator and the audit log both see. The three new fields hold the machine-readable route the system actually uses to deliver. They start out empty and stay empty until the bootstrap inbound arrives. Existing tenant databases pick up the new fields automatically the first time the system starts; databases that already have them are left alone.

FUNCTION: Reading the resolved route

A new lookup answers the question "have we captured the Zernio route for the operator's WhatsApp yet?" It returns the conversation ID, account ID, and resolved-at timestamp as a small bundle — but only if both the conversation ID and account ID are present. If either is missing, it returns nothing, which the rest of the system treats as "not yet bootstrapped."

FUNCTION: Writing the resolved route

A second new helper is what saves a captured route. It refuses to write half-resolved data: if either the conversation ID or the account ID is missing, it does nothing. Otherwise it writes both values plus the current timestamp. If a route was already captured before, the new write replaces it and just refreshes the timestamp. The write is careful to leave every other field in the settings row untouched — the operator's chosen phone number, the enable flags, the email destinations — so that capturing the route never accidentally erases what the operator configured.

STEP: Making the Settings save survive the new route fields

The Settings save used to be a brute-force "delete and rewrite the row" operation. That worked fine before, but it would now wipe the three new route fields every time the operator opened Settings and clicked Save. The save was rewritten to be a column-by-column update: it updates the user-controlled fields (enable flags, phone number, email addresses) and explicitly does not touch the three new route fields. The end result is that Calvin can edit Settings as often as he likes without losing the bootstrap.

STEP: Auto-capture when the operator's WhatsApp inbound arrives

Inside the inbound webhook handler — the code that runs every time a new message lands from Zernio — a new check sits between the tenant-isolation guard (which makes sure a misrouted webhook can't poison anything) and the empty-text skip (which would otherwise drop a one-character "hi"). The check only fires for WhatsApp inbounds, never for Instagram or Facebook DMs, so the operator messaging the wrong account by mistake doesn't capture the wrong route. It looks up the configured operator phone from Settings, strips both that number and the inbound sender's number down to just digits (so "+351963618003" matches "351963618003" matches "00351963618003"), and if they match, it saves the inbound's conversation ID and account ID as the resolved route. The whole thing is wrapped in a safety net: if anything goes wrong reading Settings or writing the route, the system logs the failure and carries on processing the inbound message normally — capturing the route is never allowed to block actual message handling.

STEP: How escalation alerts to WhatsApp now work

The alert dispatcher's WhatsApp branch was rewritten end-to-end. When an escalation fires and WhatsApp alerting is enabled, the dispatcher now follows this flow:

First, if no destination phone is configured at all, it records the delivery as "skipped" with the reason "no whatsapp destination configured" — same as before.

Second, if a destination is configured but the Zernio route has not been captured yet, it records the delivery as "skipped" with the reason "zernio_operator_destination_not_resolved." Critically, it does not call the old Meta send function, so there is no chance of a false "sent" status sneaking back in.

Third, if the route is captured, it sends the alert through Zernio's direct-message function using the stored conversation ID and account ID, with the same rich alert body that goes to email (the one introduced in the previous brief — reason, what the operator needs to decide, recommended options, the customer's latest message). If Zernio confirms the send, the delivery is recorded as "sent." If Zernio reports a problem or throws an error, the delivery is recorded as "failed" with the exact reason from Zernio. In every case, the destination column in the audit log shows the human-readable phone number ("+351963618003"), so the audit trail still matches what the operator sees in Settings — only the actual delivery mechanism changed under the hood.

STEP: Telling the dashboard whether the route is resolved

The Settings endpoint that the operator's dashboard reads to display the WhatsApp configuration now includes a new flag — a true/false value indicating whether the Zernio route has been captured yet. The dashboard frontend can use this to show a hint like "send a WhatsApp from this number to bootstrap operator alerts" when the value is false, and hide that hint once it flips to true. The flag is also returned in the synthesized default response (the one returned when the settings table is completely empty), so the response shape is consistent.

## Edge cases

- If Calvin saves Settings before sending the bootstrap WhatsApp, the row gets created without route information; the next escalation will record "skipped" with the bootstrap reason. This is the expected first-run state, and the dashboard hint should make it obvious what to do.

- If Calvin sends the bootstrap WhatsApp before ever opening Settings, the auto-capture creates the settings row with empty user-controlled fields and the three route fields filled in. The settings reader treats empty user fields as defaults, so this works, but the more natural ordering is Settings first, then bootstrap.

- If Calvin's number changes or Zernio reassigns the conversation ID for any reason, alerts will silently keep going to the old (now wrong) Zernio conversation. The fix is to clear the three route fields manually on the server and have Calvin send a fresh bootstrap inbound. There's no automatic re-resolution on a number change.

- If Calvin sends a bootstrap WhatsApp from the configured number but to the wrong unboks platform (the Instagram or Facebook account instead of the WhatsApp Business number), nothing happens. The auto-capture is gated to WhatsApp inbounds only, by design.

- If the auto-capture fails for any reason — settings table unreadable, database locked, anything else — the inbound message is still processed normally and a failure note is written to the log. The operator's regular WhatsApp conversation never breaks because of a bootstrap problem.

- If Zernio's send function returns false, the audit log records the alert as "failed" with the literal reason "zernio_send_dm_reply_returned_false." If Zernio throws an error mid-send, the audit log records "failed" with the first 200 characters of the error text. Either way, the status in the audit log now reflects what actually happened, not what Meta claimed happened.

- The phone-number comparison strips both numbers down to digits before comparing, so "+351963618003" written in Settings will still match "351963618003" or "00351963618003" arriving from Zernio. Format mismatches between Settings and inbound metadata won't block the bootstrap.

- The bootstrap is honored even for an empty inbound — a single emoji or one character is enough to trigger it, because the conversation ID and account ID arrive on the inbound regardless of whether there's any text.

- Rolling this change back is safe: reverting the commit removes all the new code, and the three new database columns simply sit unused. SQLite tolerates unknown extra columns, so no data migration is needed to undo this.

## What did NOT change

The marina/customer-facing prompt was not touched. The booking flow was not touched. The customer reply paths through WhatsApp (the relay reply and the dashboard's "Send WA" feature) still go through the legacy Meta send function — only operator escalation alerts moved to Zernio. The operator's chosen phone number in Settings is still stored exactly as typed and is still what shows up in the alert delivery audit log. Email, Telegram, and Messenger alert paths are unchanged. Tenant isolation behavior from the previous tenant-guard work is preserved — the auto-capture runs only after the guard accepts the inbound, so misrouted webhooks can never write a route.
