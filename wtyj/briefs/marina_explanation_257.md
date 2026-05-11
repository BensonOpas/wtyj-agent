# EXPLANATION 257 — WhatsApp alert content sanitization (strip internal prefixes, CRM/ticket hallucinations, subject-as-Latest leak)

## In one sentence

When a WhatsApp escalation alert goes to Calvin's phone, the system now scrubs out internal subject tags, customer email addresses, and any made-up references to "CRM" or "ticket history" before the message leaves the building, so Calvin sees a clean, action-only alert instead of leaked internal plumbing.

## What's changing and why

Last round (Brief 256) fixed the shape of the WhatsApp alert — it became a short five-line message with a "Customer", "Channel", "Need", "Latest", and "Action" line, capped near 600 characters. Calvin re-tested in the live environment and reported two problems that the shape fix didn't catch.

First problem: when the underlying AI summary came back without a real customer message, the alert fell back to using the email's subject line as if it were the customer's message. Email subjects are constructed internally and look like `[ESCALATION] NO-REF - Calvin Adamus (calvin@gaimin.io) - wants to book` — they're not customer text, they're routing metadata. Calvin saw that whole prefix on his phone in the "Latest" line.

Second problem: the AI sometimes invented external systems Marina does not have. Calvin's "Need" line said things like "Reach out to Calvin directly to establish context, or review any external records and CRM/ticket history for prior interactions." Marina has no CRM, no Zendesk, no ticket history — and the source email it would need was already sitting in the dashboard. The AI was inventing missing context.

This change adds two new cleanup steps that run on the alert text just before it goes out by WhatsApp. One scrubs internal subject tags and bracketed email/phone metadata. The other deletes whole sentences that mention systems Marina doesn't have or that claim "no conversation history available." Together they make sure the operator's phone shows only real, action-relevant text. The richer email version of the alert is left alone on purpose — operators reading the email want the full context, including the noisy bits.

## Step by step — what the code does now

INTERNAL-PREFIX SCRUBBER (new helper):

When given any piece of text, this step runs through six ordered cleanup passes. It removes the bracketed tokens `[ESCALATION]`, `[BOOKING REQUEST]`, and `[RELAY-<token>]`. It removes the bare token `NO-REF`. It removes anything in parentheses that looks like an email address (anything wrapped in parens that contains an `@` sign). It removes anything in parentheses that looks like a phone number (six or more digits, dashes, spaces, optional leading plus). It trims dangling punctuation and dashes from the start and end. It collapses runs of spaces and tabs to single spaces. If everything got stripped — meaning the input was nothing but internal metadata with no real text — it returns an empty string, and the caller is expected to drop the whole field rather than show emptiness.

Two subtleties matter here and were caught by the test suite. The scrubber does NOT strip trailing periods, because some valid AI outputs end with a period (e.g. "Confirm appointment time change.") and earlier Brief 256 tests asserted those periods remain. The scrubber also does NOT collapse newlines — only horizontal spaces and tabs — because the next cleanup step in the chain (the email-artifact stripper from Brief 256) looks for newline-anchored patterns to find email signatures and confidentiality disclaimers. An earlier version of this helper collapsed all whitespace including newlines, which silently disabled the signature stripper downstream. The full regression run caught both regressions before deploy.

Before: `[ESCALATION] NO-REF - Calvin Adamus (calvin@gaimin.io) - wants to book`
After: `wants to book`

HALLUCINATED-SYSTEMS SCRUBBER (new helper):

This step scans the text for any of a fixed list of forbidden phrases — `external records`, `CRM` (as a whole word), `ticket history`, `helpdesk`, `Salesforce`, `Zendesk`, `no conversation history available`, `no prior context available`, `cannot find any conversation history`, `Reach out to the customer directly to establish context`, and `Review any external records`. For each match, it deletes the ENTIRE sentence containing it — from the start of that sentence to the next period, exclamation mark, question mark, or end of the text. After all cuts, it collapses any leftover double-spaces. If the entire text got removed (nothing survived), it returns a generic operator-facing fallback: `Review and reply.` That fallback is intentionally bland: it tells the operator to take action without inventing any context Marina didn't actually have.

Before: `Reach out to Calvin directly to establish context, or review any external records and CRM/ticket history for prior interactions.`
After: `Review and reply.` (entire string was banned phrases, so fallback fires)

Before: `The customer wants pricing. There is no conversation history available.`
After: `The customer wants pricing.` (only the second sentence is dropped)

THE COMPACT WHATSAPP ALERT BUILDER (modified):

The Need line — the field that tells the operator what decision is required — now runs through both new scrubbers in order: first the internal-prefix scrub, then the hallucinated-systems scrub. Only after both passes is the result trimmed to 180 characters. If the result ends up empty, the alert shows `Review and reply.` instead of the old "(no decision specified)" placeholder.

The Latest line — the field that shows the most recent customer message — now has a guard at the very top. If the raw incoming "latestCustomerMessage" starts with `[ESCALATION]`, `[BOOKING REQUEST]`, or `[RELAY-`, the system treats that as proof the value is not a real customer message and omits the Latest line entirely. Otherwise it runs the value through the internal-prefix scrubber FIRST, then the existing email-artifact stripper from Brief 256. Order matters here: the prefix scrubber removes bracketed tokens that would otherwise confuse the signature/disclaimer patterns in the email-artifact stripper.

The fallback chain from Brief 256 that filled an empty Latest line with the subject line has been deleted outright. If the AI didn't return a real customer message, the alert simply shows no Latest line at all. The operator gets a four-line alert instead of five, which Calvin's spec explicitly accepts as valid.

THE LEGACY FALLBACK PATH (modified):

There's an older code path that runs when no structured AI summary is available at all — it just produces a single Need line from a raw fallback string. That path now runs the fallback through the same three-step chain: internal-prefix scrub, hallucinated-systems scrub, then the Brief 256 email-artifact strip. If the result is empty, it falls back to `Review and reply.` (replacing the older "(no decision specified)" placeholder). This keeps the legacy path's output consistent with the modern path's output — a subject-only fallback can't leak through either route.

## Edge cases

- If the AI returns a Need line that is ENTIRELY composed of banned phrases (all sentences talk about CRM or ticket history), the operator sees `Review and reply.` — generic, but honest. The operator opens the email alert for full context. This is acceptable; Calvin's rule six explicitly preferred a blunt operator-prompt over invented context.

- If the AI returns an empty `latestCustomerMessage`, the Latest line is silently omitted. The operator gets four lines (Customer / Channel / Need / Action) instead of five. This is by design — Brief 256 already documented empty-Latest omission, and Brief 257 explicitly removes the older "use the subject as a substitute" fallback.

- If the AI returns a `latestCustomerMessage` that starts with `[ESCALATION]`, `[BOOKING REQUEST]`, or `[RELAY-`, the WHOLE field is omitted even if there's customer-looking text after the prefix. This is intentional: the prefix at the front is treated as a signal the value was never a real customer message in the first place, so trusting any of it is risky.

- If the AI's "Need" sentence happens to contain the exact word `CRM` for a legitimate reason (e.g. a customer asking about a CRM product), the sentence is still cut. This is an accepted false-positive trade-off — Marina's clients (charters, restaurants, dental, consulting) do not have customers who ask about CRM systems. If a future client genuinely does, the banned list can be tightened.

- If the operator decision text genuinely ends with a period (e.g. `"Confirm appointment time change."`), that period is preserved. The internal-prefix scrubber explicitly leaves trailing periods alone — an earlier draft stripped them and broke Brief 256's existing tests.

- If the AI emits multiple banned phrases across multiple sentences, all those sentences are dropped and only the clean ones remain. If none remain, the `Review and reply.` fallback fires.

- The "first verbose WA alert" Calvin reported in round-two (the one with `Mode:` and `Reason:` labels) is not addressed by this fix and does not need a fix. That format only exists in the rich email body builder. A code audit confirmed only one dispatcher path sends operator WhatsApp alerts in production, and that dispatcher uses the compact builder for WhatsApp. The verbose alert almost certainly landed in the nine-minute deploy window when Brief 256's source had been pushed but the live container hadn't yet swapped to the new image — the old image's email-poller process was still using the rich body for both channels.

## What did NOT change

The email version of the escalation alert (the long, richer Brief 239 format) is untouched — operators reading the alert by email still get full context including any noisy AI text, signatures, and quoted history. The dispatcher that decides which alerts go where is unchanged. The appointment-reminder alert path is unchanged. No changes were made to Marina's customer-facing prompt, to the booking flow, to customer data handling, or to which numbers receive alerts. No database schema changes. The fix is a pair of additive helpers and a few extra lines in one existing builder; rollback is a single retag-and-restart of the four production containers.
