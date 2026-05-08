# EXPLANATION 234 — Marina-uses-approved-learnings on IG/FB DM path

## In one sentence
When a customer messages unboks on Instagram or Facebook DMs, the AI now reads the same operator-curated "approved answers" library that already shapes its email and WhatsApp replies — so the team's coaching finally reaches every channel.

## What's changing and why

Before this change, an earlier brief (219) taught the AI to read recent operator answers — questions a human had reviewed and approved — and use them as authoritative coaching when replying. That worked for email and WhatsApp. But Instagram and Facebook DMs go through a separate code path that calls the AI directly, and that path never got the upgrade. The result was that an operator could carefully answer a tricky DM question, mark it as "approved," and the AI would happily forget the lesson the next time the same question came in.

This change closes that gap. The DM reply path now builds the same "APPROVED ANSWERS" block of recent operator-vetted question-and-answer pairs and hands it to the AI as part of every Instagram or Facebook DM reply. Instagram answers stay in Instagram's pool, and Facebook answers stay in Facebook's pool — they don't bleed into each other. unboks already had the feature flag turned on, so this starts working for them on the very next DM. Other tenants stay off until they opt in.

## Step by step — what the code does now

BUILDING THE APPROVED-ANSWERS BLOCK FOR DMs

When a DM comes in, the system asks: "Does this client have the approved-answers feature turned on?" If the flag is missing or off, the system returns nothing and moves on. If the flag is on, it asks the database for up to twenty recent operator-approved question-and-answer pairs that were resolved on this exact channel (Instagram DM or Facebook DM). If the database call fails for any reason, the system silently returns nothing rather than crashing the reply. If there are no matching answers yet, the system also returns nothing. Otherwise, it formats each entry as a "Q:" line and an "A:" line (or just an "A:" line if no question was recorded), drops any entry whose answer is blank, and wraps the whole list in a header that tells the AI: "These are how the human team has handled similar questions on this channel — match the spirit, don't copy word-for-word."

ASSEMBLING THE DM SYSTEM PROMPT

When the system builds the instructions it sends to the AI for a DM reply, it now computes the approved-answers block once at the start, then weaves it into both versions of the prompt. There are two versions because some clients have written their own custom persona instructions ("master prompt") and some haven't.

For clients with a custom persona, the prompt is now stitched together as: greeting and name, the short role description, the client's custom persona, then (only if there's an approved-answers block) the approved-answers block, then the services list, the FAQ, the optional booking redirect, language guidance, emoji guidance, and the output rule.

For clients without a custom persona, the prompt is now stitched together as: greeting and name, the full role description, then (only if there's an approved-answers block) the approved-answers block, then the services list, FAQ, writing style, booking redirect, language, "avoid these phrases" list, emoji guidance, and output rule. When the flag is off and there are no approved answers, this version produces a final string identical to what the old code produced — no other behavior shifted.

CHANNEL ISOLATION

The system passes the channel name straight through — "instagram_dm" or "facebook_dm" — exactly as it was stored when the operator originally answered. The database lookup matches that string exactly, so an Instagram answer never appears in a Facebook prompt and vice versa.

## Edge cases

- If the database that holds approved answers is briefly unavailable, the DM reply still goes out — just without the approved-answers context that round. This is intentional: a DM customer waiting for a reply is more important than getting the coaching layer perfect.
- If an operator approved an entry but left the answer blank, that entry is silently skipped. Only entries with a real answer make it into the block.
- A tenant with hundreds of approved entries does not blow up the prompt. The system caps the block at the twenty most recent entries per channel — same cap as the email and WhatsApp paths.
- The first time the feature is turned on for a tenant that has never had any operator answers approved, the block stays empty until the first answer is approved on that channel. There is no warm-up data; the library grows as operators do their normal work.
- An Instagram-approved answer will not influence Facebook replies, even on the same client. Operators who want the same coaching on both channels need to approve answers on both — this is by design, since the customer audiences and tone often differ.
- Clients who do not turn on the feature flag see exactly the prompt they saw before this change. The feature is opt-in, default off.

## What did NOT change

The actual conversation flow, the booking redirect logic, the AI's persona, the services and FAQ data, and the rate limits on DM replies are all untouched. The way operators approve answers in the dashboard, and the way those answers get stored, are unchanged — this brief only reads from the existing pool, it does not write to it. The email and WhatsApp paths were already doing this correctly and were not modified. Customer data handling, escalation rules, and the underlying AI model selection are all the same as before.
