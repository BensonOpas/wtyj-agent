# EXPLANATION 224 — Strip internal escalation tokens from Marina email replies

## In one sentence
Marina will no longer leak internal routing markers like `[ESCALATE]` at the bottom of customer emails — the giveaway "Marina / Unboks / [ESCALATE]" signature that customers were actually receiving in production.

## What's changing and why

Marina's master prompt for unboks (and any client whose escalation script lives in their freeform notes) tells her to end an escalation reply with a literal marker on its own line. That marker is meant for the routing layer — it's how Marina internally signals "I'm handing this to a human." It was never meant to be visible to the person on the other end of the conversation.

The Instagram and Facebook DM path already cleaned this marker out before sending, but the email path did not. As a result, real unboks customers were getting emails that ended with the line `[ESCALATE]` underneath Marina's signature. SR (Calvin) flagged it from production. From today onward, Marina's email replies are sanitized centrally — at the point where her response leaves the agent — so the marker never reaches the customer regardless of which sender code path picks it up.

The cleanup also covers four related markers Marina's prompts may emit in the future (`[SOFT_ESCALATION]`, `[HARD_ESCALATION]`, `[HANDOFF]`, `[HUMAN_TAKEOVER]`) so we don't ship the same leak twice. It deliberately does NOT touch `[BOOKING_REF]` or `[PAYMENT_LINK]`, which are real placeholders the email sender substitutes with a confirmation code or a Stripe link before the message goes out.

## Step by step — what the code does now

INTERNAL TOKEN LIST: A fixed list of five markers is now defined at the top of Marina's agent file: `[ESCALATE]`, `[SOFT_ESCALATION]`, `[HARD_ESCALATION]`, `[HANDOFF]`, `[HUMAN_TAKEOVER]`. The list is explicit on purpose — the code does not pattern-match anything-in-brackets, because the booking flow legitimately uses bracketed placeholders that have to survive untouched.

CLEANUP HELPER: A small helper takes any string and returns it with every listed marker removed by plain text replacement. After removing markers, it also collapses any run of three or more consecutive blank lines down to one (a marker on its own line leaves a gap behind it) and trims trailing whitespace from the very end. If the input is empty, it's returned as-is.

SANITIZE BEFORE RETURN: When Marina finishes processing an inbound message and is about to hand the result back to whichever caller asked for a reply, two fields now go through the cleanup helper. The customer-facing reply text is sanitized every time. The booking-failure fallback text — the one Marina generates when the system couldn't put a hold on a trip — is sanitized only if it's present. Everything else in Marina's structured response (intent flags, the human-routing signal, internal notes for operators) is untouched.

The fallback path that runs when Marina's API call itself fails was left alone — that path returns a fixed apology string with no markers in it, so there's nothing to clean.

## Edge cases

- If Marina emits a marker mid-sentence instead of on its own line, it's still removed cleanly. The surrounding text stays intact, but a stray double space could remain. Acceptable — Marina's prompt instructs her to put the marker on its own line, so this is a defensive case rather than an expected one.
- If a customer's own email body legitimately contains the literal text `[ESCALATE]` (a user quoting documentation, for example) and Marina echoes it back into her reply, that copy will also be stripped. Acceptable — extremely unlikely in practice, and the cost of a false positive (one missing word in a quoted passage) is much lower than the cost of leaking the marker again.
- The cleanup applies only to text fields that come back from Marina's agent. If a future feature adds a new customer-facing text field to Marina's response shape, that new field will NOT be sanitized until someone wires it through the helper. Known limitation — documented here so it's not forgotten.
- If a future caller of Marina wants to detect the raw `[ESCALATE]` marker before it gets stripped (the way the Instagram/Facebook DM path does to fire its own routing notification), they cannot — the marker is gone by the time the result is returned. The brief addresses this: for the email path, escalation is detected from a structured field on Marina's response (`requires_human`), not by reading the marker text. So nothing in today's email pipeline depends on the marker surviving.
- The Instagram/Facebook DM path is unaffected. It does its own marker stripping in its own agent and never goes through Marina's email agent, so this change has no behavioral effect on DM conversations.

## What did NOT change

Marina's prompt was not edited — she still emits the markers exactly as before, the system just cleans them at the exit. The booking flow is untouched: `[BOOKING_REF]` and `[PAYMENT_LINK]` placeholders still flow through to the email sender and get substituted with real values downstream. The escalation routing logic itself is unchanged — the structured `requires_human` field still drives whether a thread is handed to an operator. The Instagram/Facebook DM agent is not modified. No client data, no client.json values, and no other tenant prompts were edited as part of this change.
