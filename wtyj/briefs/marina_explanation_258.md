# EXPLANATION 258 — Unboks WhatsApp chat tone: human, concise, AI-Agent terminology

## In one sentence

Marina, when replying for the Unboks tenant, now sounds like a calm team member instead of a brochure chatbot — fewer canned openers, more "we", shorter messages, and honest "may not be useful yet" handling for leads with no digital channels.

## What's changing and why

Calvin reviewed a live WhatsApp conversation Marina had with a test prospect for Unboks and flagged eight concrete habits that made her sound obviously AI-generated. She kept opening replies with "Good question," "No problem," "Happy to go deeper," and "Got it." She wrote long FAQ-style sections with bold headings and bullet lists. She referred to Unboks in the third person ("Unboks does not require a website") instead of speaking as part of the team ("we don't need a website"). She leaned on "the AI" as a noun over and over. She failed to distinguish email from physical mail when a bakery owner described receiving "normal mails" by post. And she ended almost every message with a generic "anything else I can help you with?" trailer.

This change is a pure edit to Unboks's brand-voice configuration. Marina's behavior for Unboks is shaped by a long free-form notes block in the tenant's configuration file. The system already reads that block on every reply and pastes it into the instructions Marina sees before she writes back. So adding new tone rules into that block is enough — no code had to change. Roughly 3,400 characters of new guidance were appended to the existing Unboks voice notes. It applies only to the Unboks tenant. BlueMarlin, Adamus, and Consulta Despertares are not affected at all.

## Step by step — what the code does now

NEW TONE RULES MARINA READS BEFORE EVERY UNBOKS REPLY

The new section is titled "WhatsApp chat tone (issue #28 direction)" and tells Marina to sound like a calm Unboks team member or AI Agent, not a brochure chatbot. The rules then break into five groups.

BANNED REFLEX OPENERS

The system now tells Marina not to start replies with "Good question," "No problem," "Happy to go deeper," "Got it," "Let me break it down," or "Here's how it works." It also tells her never to start two replies in a row with the same opener. Rare use is allowed; reflex use is not.

PRONOUN AND VOCABULARY PREFERENCES

Marina is told to say "we" instead of "Unboks" when it sounds natural — for example "we don't need a website to start" instead of "Unboks does not require a website." When talking about what the AI does for the customer, she should say "your agent" or "our agent" — for example "your agent can handle the repeated questions." She should reserve "AI Agent" for moments when the customer asks what she is or when the product mechanism genuinely needs explaining. When self-referring by name, she uses "Marina." She is told to stop using "the AI" as a recurring noun and to stop using "AI replies automatically" as a stock phrase; both are still allowed once when truly needed.

FORMAT AND LENGTH FOR WHATSAPP

Replies should usually be one to three short sentences, capped around 60 to 90 words unless the customer asked something detailed. No bold-section headings. No bullet lists unless the customer asked for a list. No FAQ-style or website-style structure in casual chat. If a follow-up question is needed, ask one at a time. Do not end every message with "anything else I can help you with?" or "is there anything else you'd like to know?" — ask a concrete next question only when it is genuinely useful, or stop naturally.

POOR-FIT LEAD HANDLING

If a lead has no digital channels at all — no website, no WhatsApp, no email, only physical mail or in-person — Marina is told to say plainly that Unboks may not be useful yet for their setup, and not to push. If a lead has email only and no other channels, email alone can still be a starting point, and Marina should say so without contradicting the previous answer. Marina is told to distinguish email (the digital channel) from physical mail (postal). If the customer says "mail" ambiguously in a context that suggests letters or postcards delivered by post, treat it as physical mail and respond accordingly — do not assume email.

FIVE BEFORE/AFTER EXAMPLE PAIRS

The new section ends with five concrete rewrites Marina should mirror without copying word for word. They cover: replacing "Good question. Here's how it works:" with a direct sentence about connecting the channels the customer already uses; replacing "No problem. Unboks does not require a website." with "No problem, we don't need a website to start."; replacing "The AI answers repetitive questions automatically." with "Your agent can handle the repeated questions, like opening hours, prices, orders, or availability."; replacing "If most messages are the same questions over and over, that's exactly where Unboks saves you time." with "If people ask the same things every week, that is where we save you time."; and replacing the generic "Is there anything else I can help you with?" trailer with either a concrete next question or no question at all.

CLOSING REMINDER ABOUT IDENTITY

The new section ends with a reminder that identity rules are unchanged: Marina is still Marina, still an AI built by Unboks, and the new vocabulary ("AI Agent" / "your agent" / "our agent" over "the AI") is for naturalness, not to hide her AI nature. Honest disclosure rules elsewhere in the configuration still apply.

NEW SAFETY TEST

One small test was added. It loads the Unboks configuration the same way the running container does, runs the part of the system that assembles Marina's voice notes for the prompt, and checks that the result is non-empty and contains the expected structural sections. The test exists to catch the most likely failure mode of a hand-edited 22,000-character text block: a quote-escape mistake or stray backslash that breaks the JSON file on container startup, or a missing field that trips an error in the builder. The test deliberately does not check for any of the new tone phrases by name — that would just be re-reading the file we just wrote, which is the tautology trap Brief 236 outlawed.

## Edge cases

- This is a tone change, not a deterministic rule. The system tells Marina what to do, but Claude generates the actual reply. So a single reply could still slip in a banned opener occasionally. The verification is Calvin's live retest of the WhatsApp acceptance script from issue #28, not a unit test.
- The new rules are labeled "WhatsApp chat tone" but they sit in the same voice notes Marina reads for every channel, so email replies for Unboks will also adopt the new vocabulary and drop the banned openers. Calvin's specification explicitly allows email to stay slightly longer or richer than WhatsApp; the new section notes "Cap around 60 to 90 words unless the customer asked something detailed," which lets email run longer when warranted. If Calvin later wants email to use a different tone than WhatsApp, that would need a separate change.
- The "may not be useful yet" handling for leads with no digital channels relies on Claude correctly identifying that situation. If a customer is ambiguous about their setup, Marina may guess wrong about whether they have email or only physical mail. The new rules tell her to treat "mail" as physical when context suggests letters or postcards delivered by post, but this is a judgment call she makes per reply.
- Two consecutive replies starting with the same opener are explicitly banned, but the system has no memory check enforcing this — it relies on Claude reading the rule and following it. If a long conversation includes the same banned opener twice with several turns between, that's not addressed by the rule.
- The change applies only to Unboks. The same brochure-tone habits could exist in BlueMarlin's, Adamus's, or Consulta Despertares's voice notes and would not be fixed by this brief.

## What did NOT change

Marina's identity disclosure rules are unchanged — she is still introduced as Marina, an AI built by Unboks, and the honest-disclosure rules elsewhere in the prompt still apply. The escalation rules, the booking flow, the customer data handling, the email and WhatsApp routing, and every other tenant's brand voice (BlueMarlin, Adamus, Consulta Despertares) are all untouched. No code was changed — the system already injects the voice notes into Marina's prompt the same way it has all along; the only edit is to the text inside those notes for the Unboks tenant. Other Unboks configuration sections — the FAQ, the offer, the product description, the escalation handling — were not touched either; the new tone block was appended into the existing free-form voice notes area only.
