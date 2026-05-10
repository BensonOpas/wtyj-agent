# EXPLANATION 244 — Stop internal email leakage + strip em-dashes from Marina customer replies

## In one sentence

When Marina tells an unboks customer "expect an email shortly," she now points them at the public address `hello@unboks.org` instead of leaking Benson's internal Gmail, and any em-dash characters Marina writes into a customer reply are scrubbed out before the customer sees them.

## What's changing and why

Calvin reported two surface-level defects in the unboks customer replies. First, Marina was telling customers to watch for an email from `butlerbensonagent@gmail.com` — that's the internal mailbox the system uses to authenticate when sending mail, not the address Calvin wants customers to see. The public-facing inbox is `hello@unboks.org`. Second, Marina kept using em-dashes in customer replies (the long dash character), which Calvin has explicitly banned in the brand voice rules. Marina's own writing instructions say "never use em-dashes," but Claude kept producing them anyway because the writing samples baked into Marina's prompt are full of them, and Claude tends to mirror that style.

This change does the simplest fix for both. The unboks customer-facing email address gets switched at the configuration source so every spot in Marina's prompt that says "expect an email from ___" now substitutes the public address. And on the way out the door — after Marina has finished writing her reply but before it gets handed off to the email or WhatsApp channel — the system now finds any em-dash in the customer-visible text and replaces it with a comma. The Instagram/Facebook/Messenger DM agent already did the same em-dash swap; Marina (which handles email and WhatsApp) just didn't, and now does. Internal team-relay routing, operator notes, and the actual SMTP login mailbox are all left alone — only the address customers see, and only the em-dashes in customer-visible text, change.

## Step by step — what the code does now

STEP: Public-contact address swap for unboks

The unboks tenant's configuration file holds a single business-email field that Marina's prompt reads in six different places when she needs to tell a customer "the team will reply from this address." That field used to hold the internal Gmail used for sending. It now holds `hello@unboks.org`. From this point forward every customer-facing line Marina generates that mentions the team's email will say `hello@unboks.org`. The internal "support" address (a separate field used only behind the scenes to recognize when an operator replies into a thread) was deliberately left as-is, because changing it would break the system's ability to tell operator replies apart from customer replies.

STEP: Em-dash scrub on Marina's customer-visible reply

After Marina's one Claude call finishes and produces a structured result, the system already runs a cleanup pass that strips out internal escalation markers (things like `[ESCALATE]` that aren't meant for customers). That cleanup pass now does one extra thing on the customer-visible reply text: it walks through the reply and replaces every em-dash with a comma. The replacement uses a plain comma with no surrounding space, matching what the DM agent has been doing for IG/FB/Messenger since an earlier brief. The result is that even if Claude produces "shortly — keep an eye on your inbox," the customer receives "shortly , keep an eye on your inbox."

STEP: Same scrub on the apologetic "slot just got taken" reply

Marina has a separate customer-facing field she uses when a booking slot disappears between the time she offered it and the time the customer accepted it (the "sorry, that one just got taken" message). That field also gets the em-dash-to-comma swap, for the same reason and using the same logic, so the apology text can't sneak an em-dash through either.

STEP: Operator-facing fields untouched

The internal note Marina writes for the dashboard, the question she asks a human teammate when she needs help, and the summary she writes when escalating a thread are all left exactly as Claude wrote them. Em-dashes are fine in those — they're for operators reading the dashboard, not customers, and Calvin's no-em-dash rule was about customer perception only.

STEP: Three new tests prove the scrub runs

A small test file got three new checks added. The first feeds Marina a reply with an em-dash in it and confirms the em-dash is gone and the comma is in its place. The second does the same for the "slot just got taken" apology field. The third feeds a reply that contains both an internal escalation marker and an em-dash, and confirms both get cleaned out — proving the em-dash scrub and the existing escalation-marker scrub run together correctly and in the right order.

## Edge cases

- The replacement is a plain comma with no surrounding space, so "shortly — please" becomes "shortly , please" with a stray space before the comma. This matches the DM agent's existing behavior on purpose; Calvin accepted the comma swap in the original ticket. If someone later wants tidier spacing, both spots get changed together.
- Em-dashes still live throughout Marina's prompt template (sixty-plus of them in the writing-style instructions). They're not removed because mass-editing the prompt risks changing other instructions by accident, and Claude can produce em-dashes from its own training even with a clean prompt. The post-Claude scrub catches them regardless of where they came from.
- En-dashes (the slightly shorter dash, used in things like "5–10 guests") are not scrubbed. The original ticket only asked about em-dashes, and en-dashes show up legitimately in number ranges. If Calvin reports an en-dash slipping through later, that's a separate change.
- The same internal-email leak exists in BlueMarlin's and Adamus's configuration files. BlueMarlin is deprecated and has no live customers, so its leak is technical only. Adamus's leak is in a field that's only used for internal routing, not in anything customers see. Both are deliberately not touched in this change.
- The unboks SMTP login mailbox on the server (the actual account the system authenticates with to send mail) is still `butlerbensonagent@gmail.com`. Only the address quoted to customers changed. The send pipeline still works.
- The team-relay detection (the system recognizing when an operator replies into an escalation thread) still works because it keys off a different field that wasn't changed.

## What did NOT change

Marina's prompt was not edited. The booking flow, the escalation logic, the way Marina decides when to hand off to a human, the way replies are sent, and the way customer data is stored are all unchanged. No business values moved out of `client.json` and no static reply templates were added — Marina still generates every reply through her one Claude call. The DM agent's existing em-dash swap was not modified, only mirrored. The other tenants (BlueMarlin, Adamus, Consulta Despertares) had no configuration changes in this commit.
