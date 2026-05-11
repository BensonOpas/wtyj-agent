# EXPLANATION 256 — Compact WhatsApp escalation alerts (strip email artifacts, hard length cap)

## In one sentence

When the system pings Calvin on WhatsApp because a customer conversation needs a human, the alert is now a short five-line summary instead of the full email-style write-up that used to flood his phone.

## What's changing and why

Before today, every time a customer email got escalated to Calvin, the system built one long alert body and shipped that same body to both his email inbox and his WhatsApp. On email that was fine — operators expect detail there. On WhatsApp it was unusable. Calvin actually got an alert that included the full reason block, the customer's quoted reply chain, the customer's email signature, contact details, and a confidentiality disclaimer pasted verbatim from the bottom of the original email. His own words: "This is not an alert, this is a book."

Brief 256 splits the two. Email still receives the rich body with all the context. WhatsApp now receives a compact, action-oriented summary that names the customer, names the channel the customer wrote from, states what needs to be decided, quotes the latest customer message (cleaned up), and ends with a call to action telling Calvin to open the dashboard. That's it. No quoted history, no signatures, no disclaimers, no bullet lists, no em dashes.

## The five-line target format Calvin wants

The WhatsApp alert now reads like this:

Escalation alert. Customer: (name). Channel: (Email or WhatsApp or Instagram, etc.). Need: (one short sentence about what to decide). Latest: (one short sentence quoting what the customer last wrote). Action: Open dashboard to reply.

That's the entire body. Five labelled lines plus a header and an action line. If the latest customer message is empty or gets cleaned away entirely, the Latest line is omitted rather than shown blank.

## Step by step — what the code does now

THE EMAIL SANITIZER

When the system has the customer's latest message in hand, it runs it through a cleanup pass before letting any of it appear in the WhatsApp alert. The cleanup looks for the things that make customer emails long and noisy, and chops them out.

It cuts everything from the first "On (date), so-and-so wrote:" line onward, which is the standard way Gmail, Outlook, and Apple Mail introduce a quoted reply chain. It cuts everything from "-----Original Message-----" or "-----Forwarded message-----" onward, which is how forwarded mail is marked. It cuts everything from the standard email signature delimiter (a line with two dashes) onward. It cuts everything from common sign-offs like "Best regards," "Kind regards," "Thanks," "Cheers," "Sincerely," "Sent from my iPhone," and "Sent from my Android." It cuts any line containing classic confidentiality-disclaimer phrases like "This email and any attachments," "confidentiality notice," "CONFIDENTIAL:," "intended recipient," "privileged and confidential," or "IMPORTANT NOTICE."

After those cuts, it also walks the remaining text line by line and stops at the first line that starts with a greater-than sign, which is the standard prefix for a quoted reply line. Everything from that point down is dropped.

Finally, it replaces em dashes and en dashes with simple hyphens (to match the project-wide brand rule), collapses runs of blank lines down to single blank lines, trims whitespace, and hard-caps the result at 180 characters. If it had to truncate, it appends a single ellipsis character so the operator can see the message was cut.

THE COMPACT WHATSAPP BUILDER

When an escalation fires, the system now builds a second, separate body specifically for WhatsApp. It starts with the customer's display name, but caps that name at 60 characters so an unusually long sender name from an email header can't blow the message size budget.

It picks the "Need" line by first looking at the structured decision field that Claude already extracts for every escalation. If that field is filled in, it uses that, capped at 180 characters. If it's empty, it falls back to the reason field, capped at 180 characters. If both are empty, it shows "(no decision specified)."

It picks the "Latest" line by taking the latest customer message field, running it through the email-artifact sanitizer described above, and using whatever survives. If the cleanup leaves nothing usable, it tries the same cleanup on the older fallback summary string. If that also comes up empty, the Latest line is dropped from the alert entirely rather than shown as an empty field.

For the older legacy path where the structured summary doesn't exist at all (an alert that pre-dates the structured-summary feature), the builder collapses to an even shorter shape: header, Customer, Channel, a single Need line built from the fallback summary, and the Action line.

THE DISPATCHER ROUTING

The function that actually fires the escalation alerts now builds two bodies side by side: the rich body, which is exactly what it has always built, and the new compact body. When it sends to email, it sends the rich body — unchanged from before. When it sends to WhatsApp, it sends the compact body. The handoff to the WhatsApp send function changed in exactly one place: it now passes the compact text instead of the rich text. Everything else about the WhatsApp path (which conversation to send to, which account ID, how delivery is recorded as "sent" or "skipped") is identical to before.

## Worst-case length math

The compact body is structurally bounded. The fixed labels and line breaks add up to roughly 119 characters of overhead. The customer name is capped at 60. The Need line is capped at 180. The Latest line is capped at 180 (after the sanitizer's own 180-cap runs). Add it all up and the ceiling sits at about 539 characters. Calvin's target was "under 600." The new code has a test that drives the worst-case input — a 200-character pathological customer name, a 300-character decision string, an 800-character customer message stuffed with a signature, a disclaimer, and a quoted history — and the resulting body must come in under 600 characters. Without the three caps, that same input produces a body over 1000 characters.

## Edge cases

- If Claude does its job and returns a clean, short latest message, the sanitizer is essentially a no-op and the message passes through untouched.
- If Claude regresses and includes the whole quoted email chain in the latest-message field, the sanitizer catches it on the Python side regardless. This is the belt-and-suspenders point: prompt rules alone already failed once in this exact scenario, which is what triggered the brief.
- If a customer uses a non-standard sign-off the sanitizer doesn't recognize (some made-up phrase, a different language), that text passes through, but the 180-character hard cap still applies, so the worst case is a truncated alert with an ellipsis, never a "book."
- If the latest message is entirely quoted history with no original content, the sanitizer will strip all of it and the Latest line gets dropped from the alert. The operator sees Customer, Channel, Need, Action — no Latest. This is intentional rather than showing "Latest: " with nothing after it.
- If both the structured summary and the fallback summary are empty, the Need line shows "(no decision specified)" so Calvin still knows an alert fired and can open the dashboard.
- The compact builder only runs for escalation alerts. Appointment alerts use a separate builder that was already compact (topic, time, location, call-to-action) and was not flagged in Calvin's bug report, so it stays exactly as it was.

## The pre-existing test that had to be updated in place

One existing test in the alert-delivery suite — the one that verifies a resolved WhatsApp route correctly calls the WhatsApp send function and records the alert as sent — had a line that explicitly checked the WhatsApp body contained the word "Reason:". That test was asserting the very behavior this brief is removing. It wasn't a stale check, it was actively wrong in the new world. The test was updated in place: instead of asserting the rich-body label appears, it now asserts the compact format is present (the "Escalation alert" header, the Customer line, the Channel line, the Need line, the Latest line, the Action line) and explicitly asserts that the rich-body fields ("Reason:", "Suggested options:", any recommended-option bullet text) do NOT appear in the WhatsApp body. Five new tests were added alongside it covering the shape, the quoted-history stripping, the signature-and-disclaimer stripping, the under-600-character bound, and the legacy fallback path. Total test count: 1095 passing, zero failures.

## What did NOT change

The email side of the escalation pipeline is byte-identical to before. The email subject builder, the email rich body, the email HTML body with its dashboard button, and the dashboard-link resolver are all untouched. The email branch of the dispatcher still uses the original rich text. Appointment alerts on either channel are untouched. Marina's prompt is untouched. The escalation-summary entity extraction Claude does upstream is untouched — this brief is purely a defensive Python-side cleanup layer on top of that. The way alerts get recorded as "sent" or "skipped" in the delivery log is untouched. Rollback is the standard one-line script call; the change is additive code with no schema, no migration, no data touched.
