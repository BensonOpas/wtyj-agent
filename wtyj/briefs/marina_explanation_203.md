# EXPLANATION 203 — Wire agent_persona.freeform_notes injection in dm_agent + install SR's master prompt

## In one sentence
Calvin (the AI handling Unboks's WhatsApp, Instagram, and Facebook DMs) now reads its full voice and behavior playbook from Unboks's config file instead of silently ignoring it.

## What's changing and why

For the entire time the Unboks tenant has been live, the carefully written voice rules sitting in Unboks's config file were never reaching the AI. The DM agent's prompt builder simply never opened that section of the config. So while SR kept refining the rules — how Calvin should sound, what topics to refuse, what phrasing to avoid, how to handle questions about pricing, contracts, privacy, competitors, and so on — none of it was being read. Calvin was running on a short, generic set of voice rules that were hardcoded into the platform itself and originally written with the BlueMarlin charter business in mind.

This brief fixes both halves of that problem. First, it teaches the DM prompt builder to actually look at the persona section of the tenant's config. Second, it loads SR's full master playbook (about 17,400 characters covering tone, refusal style, and roughly 25 specific topic scenarios) into that field for Unboks. From now on, whenever a prospect or customer messages Calvin, the AI receives the full playbook as part of its instructions. Tweaking Calvin's voice no longer requires a code change — it's a config edit.

For tenants that don't have a persona section filled in (BlueMarlin and Adamus, which use Marina on a different code path anyway), nothing changes. Those tenants fall back to the original hardcoded voice rules, byte-for-byte the same as before.

## Step by step — what the code does now

PROMPT BUILDER LOOKS UP THE PERSONA

When the DM agent is about to answer a customer message, the prompt builder runs first. After loading the usual business info, services list, and FAQ, it now also opens the raw config file and looks for a persona section. If that section has a "freeform notes" field with content in it, the builder remembers that as the master playbook. If the field is missing or empty, the builder remembers it as nothing.

PROMPT BUILDER ASSEMBLES THE STRUCTURAL PIECES

Whether or not a master playbook exists, the builder always assembles the same set of structural pieces: a short intro identifying the agent and the company, a list of services, the FAQ, the booking redirect rules (which tell the AI never to take bookings in DMs and to point people at WhatsApp or email), the supported languages, the emoji rule, and the "reply with only your message text" rule. These are data-injection blocks, not voice rules, and they're the same in both modes.

PROMPT BUILDER PICKS A VOICE SOURCE

Then the builder makes one decision. If a master playbook exists, it stitches the playbook in as a standalone block between the intro and the structural pieces, and it deliberately leaves out the old hardcoded WRITING STYLE block, the old AVOID list, and the "friendly, casual, and human" line that used to follow the role description. The reason: the master playbook already covers tone, writing style, and forbidden phrases in much greater detail, and the system should have one source for voice, not two competing ones.

If no master playbook exists, the builder takes the fallback path and includes the hardcoded WRITING STYLE block, the hardcoded AVOID list, and the "friendly, casual, and human" tail. This is exactly what the prompt looked like before this brief — same blocks, same order, same content.

UNBOKS GETS SR'S FULL PLAYBOOK INSTALLED

Unboks's config file gets a new "freeform notes" value: SR's master playbook. The playbook covers what Unboks does, the desired tone (calm, professional, direct, no hype, no em-dashes), the writing style (short paragraphs, no jargon, no "your team" assumption, no "paid booking" assumption), the standard explanation to use when someone asks what Unboks does, how to handle the "is it worth it" objection, what to say about wrong AI answers, automatic replies, tone-matching, knowledge updates, database connections, real estate, bookings and orders, escalations, privacy, competitor comparisons (ChatGPT, ManyChat), Meta channel setup, guarantees, languages, voice notes and attachments, outages, contracts and cancellation, medical/legal/financial topics, abuse and trick prompts, protected identity questions, and how to handle uncertainty. The IDENTITY block at the end (which keeps Calvin saying "I'm Calvin from Unboks" and admitting it's an AI when asked) is preserved from the previous version.

POST-PROCESSING STILL STRIPS EM-DASHES

The em-dash strip from the prior brief still runs on every reply Calvin produces. Even if Claude slips an em-dash into a reply, the system swaps it for a comma before the message goes out.

## Edge cases

- If a tenant has the persona section but its "freeform notes" field is blank or whitespace-only, the system treats it as absent and falls back to the hardcoded voice rules. This means a half-filled config doesn't accidentally produce a weak prompt.
- If a tenant has no persona section at all (the BlueMarlin and Adamus case), the fallback path runs and the prompt is identical to what it was before this brief.
- The services and FAQ blocks render with empty content if the tenant has no services or FAQ entries. Unboks is currently in this state — the service list is empty. The block headers ("SERVICES:", "FAQ:") still appear in the prompt with nothing after them. Same as before this brief; no change in empty-state handling.
- The master playbook is roughly 5,000 tokens. Adding it to every inbound message bumps the per-message input cost from about $0.0018 to about $0.0033 in Claude pricing. At Unboks's expected volume (a few dozen messages per day during early sales push), that's pennies per day.
- The master playbook contains opinionated phrasing specific to Unboks ("we help run your inbox with AI", rules about not assuming "your team", default-to-human-escalation framing). If a future tenant wants different phrasing, they get their own "freeform notes" content. This brief only changes Unboks's behavior; other tenants are unaffected.
- The change does NOT honor a `requires_human:true` flag on inbound webhook payloads. Unboks's escalation logic is intent-based, not flag-based, and that's a separate piece of work if ever needed.
- Voice-quality verification is not automatable. The four new tests confirm the playbook actually reaches Claude and that the hardcoded blocks don't sneak in alongside it, but whether Calvin actually sounds the way SR wants is judged manually by sending real prospect-style questions to Calvin's WhatsApp and reading the replies.
- If voice still drifts after deploy on a specific topic, the fix is to refine the playbook content in the config file. It is no longer a code change.

## What did NOT change

Marina's email path is untouched. BlueMarlin and Adamus, which run through Marina rather than the DM agent, are unaffected — their prompts render exactly as they did before. The booking flow is unchanged: DMs still cannot take bookings, and the booking redirect text still points customers to WhatsApp or email. The list of services, the FAQ rendering, the language line, the emoji rule, and the "reply with only message text" rule are all in the same place and unchanged. The em-dash post-processing from the prior brief still runs. No database changes, no schema changes, no new endpoints.
