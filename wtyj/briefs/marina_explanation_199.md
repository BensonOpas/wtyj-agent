# EXPLANATION 199 — Unboks tenant: SOT-based client.json + WhatsApp credential migration for FB promo

## In one sentence
The WhatsApp number Calvin uses for the upcoming Facebook promo no longer hits BlueMarlin's "Marina the boat-charter agent" — it now reaches a new agent named Calvin who knows what Unboks actually is, sells discovery calls instead of quoting prices, and replies in five languages.

## What's changing and why

For weeks, Calvin's WhatsApp number (+599 968 81585) was wired to the BlueMarlin tenant because BlueMarlin was the first tenant we ever set up and nobody re-pointed the wiring. That meant if SR launched the planned Facebook promo for Unboks today, anyone messaging the number to ask "what does Unboks do" would get a reply about Klein Curaçao boat trips and jet ski excursions. The Unboks tenant container existed but ran an empty placeholder configuration with no real persona, no FAQ, and no idea what Unboks does.

This change replaces that placeholder with a full customer-facing configuration written from Calvin's official Source of Truth document. The agent is now named Calvin, speaks English, Papiamentu, Spanish, Dutch, and Swedish, knows what Unboks does (and explicitly knows what it is not — not a chatbot builder, CRM, helpdesk, or marketing tool), refuses to quote prices, and pushes serious prospects toward a discovery call with the human team. A separate manual step on the server (not in this commit) moved the WhatsApp, Zernio, Meta, and Late credentials out of the BlueMarlin folder and into the Unboks folder, with timestamped backups, so the same phone number now flows to the Unboks tenant once SR flips the webhook URL on the Meta or Zernio side.

## Step by step — what the code does now

CONFIGURATION FILE: Unboks tenant identity

The Unboks tenant configuration was rewritten from a near-empty shell. It now declares the business name as Unboks, the location as Curaçao, the operating window as 24/7, the WhatsApp and phone number as Calvin's number, and the agent as Calvin (with an internal handle of calvin-csa). The supported language list grew from English-only to five languages. A new field marks the operating mode as "qualify and hand off" — meaning the agent's job is to qualify prospects and pass them to a human, not to close sales itself.

CONFIGURATION BLOCK: Agent persona

A full persona block was added where there was none before. It tells the agent to be professional but casual, to introduce itself only on the first message of a thread and skip the intro on follow-ups, to keep replies short, and to sign off only on email. It enumerates concrete brand-voice rules: no em-dashes, at most one exclamation mark per message, no canned phrases like "I'd be happy to" or "Absolutely," no bullet-heavy formatting on chat, no forced enthusiasm, and the hard rule that the agent must mirror the customer's language. Two rules are critical for this promo: never quote a specific price, and never claim Unboks does something outside its actual scope.

CONFIGURATION BLOCK: Allowed and refused topics

The persona names which topics the agent should engage on (what Unboks is, supported channels, how escalation works, onboarding, the 14-day free trial, what makes Unboks different from chatbot builders or CRMs, booking a discovery call, supported languages) and which topics it must refuse (any specific price or monthly fee, direct comparisons to named competitors like Tidio or Intercom, technical implementation details, anything unrelated to Unboks, promises about unreleased features, and any discussion of other clients' setups).

CONFIGURATION BLOCK: Source of Truth context dump

The persona contains a long freeform notes field that holds Calvin's full Source of Truth document verbatim. This includes Unboks's core value proposition, the full channel list, every piece of core functionality, the three escalation modes (hard, soft, none) and their exact triggers, how the knowledge base is built during intake, how human handover works through the dashboard, how structured data is extracted from messages, the six-step onboarding flow, the pricing posture, and the explicit "what Unboks is not" list. The same field also pins down the agent's identity — Calvin is an AI representing Unboks, not the human founder Calvin Adamus, and if asked directly the agent admits it is an AI without over-apologizing.

CONFIGURATION BLOCK: FAQ

Eleven FAQ entries were added in plain prose: what Unboks is, which channels are supported, how escalation works, how pricing works (always defer to a discovery call), how to get started, whether Unboks is a chatbot builder (no), whether it handles bookings (yes, as escalations), supported languages, where Unboks is based, whether the customer can change the AI's tone (no — only Unboks can), how temporary offers and seasonal hours are handled, and the 14-day free trial.

CONFIGURATION BLOCK: Common-sense knowledge

The short summary block that gets injected into the AI prompt now describes Calvin instead of describing an empty test sandbox. It tells the agent to qualify prospects, never quote a specific price, never claim out-of-scope capabilities, escalate to humans when prospects want to actually sign up, and match the customer's language across all five supported languages.

CONFIGURATION FIELD: Service label

The generic terminology label was changed from "session" to "service" so that any internal copy referring to what Unboks sells reads more naturally.

NEW TESTS: Unboks configuration sanity

Three tests were added that read the Unboks configuration file and confirm the structure is real, not a placeholder. The first test parses the file as JSON and confirms all required top-level sections exist. The second test checks that the business name is Unboks, the agent name is Calvin, the internal handle is calvin-csa, exactly five languages are listed, and the booking flow is turned off (because Unboks itself does not take bookings — its clients do). The third test checks that the brand-voice rules include the words "never quote" and "price" together, locking in the price-quoting prohibition so a future config edit cannot silently remove it.

VPS-SIDE COMPANION CHANGE (manual, not in this commit)

A small idempotent script was run on the production server. It read each WhatsApp, Zernio, Meta, and Late credential line out of the BlueMarlin tenant's environment file, wrote those values into the Unboks tenant's environment file (deleting any existing line for the same key first so re-runs are safe), and blanked out the original line in BlueMarlin's file. Both files were copied to timestamped backups before any change. Both tenant containers were then restarted so they re-read their configurations. After this, the BlueMarlin tenant has no live WhatsApp, Zernio, Meta, or Late credentials and runs as a code-only demo; the Unboks tenant holds them all.

## Edge cases

- The webhook URL on Meta's developer dashboard or in the Zernio account dashboard still points at the BlueMarlin tenant's WhatsApp endpoint. Until SR or Calvin flips that to the Unboks endpoint, messages to +599 968 81585 will still arrive at BlueMarlin — but BlueMarlin no longer has the credentials to verify them, so they will fail rather than be answered with boat-charter content. This is a known and acceptable interim state; the brief is explicit that flipping the webhook URL is out of scope.
- BlueMarlin's demo no longer has a working WhatsApp channel. This is acceptable because BlueMarlin is a demo tenant with no real customers. If we ever need WhatsApp on BlueMarlin again, that requires a separate brief (a new Zernio profile and a new number).
- The Unboks tenant's WhatsApp number is Calvin's personal number. There is no separate dedicated number for Unboks yet. If that ever needs to change, it is a future brief.
- The agent identity disclaimer is enforced only by prompt instruction, not by code. If a customer pushes hard enough, the model could in principle slip up — the rule lives in the brand-voice rules and the freeform notes, not in a structural guard.
- The escalation rules are encoded as prose inside the freeform notes, not as machine-checked logic. A future brief is planned to formalize escalation rules in code.
- The configuration file is committed to the repository. Container restart is required for changes to take effect because the file is mounted into the container at start time.

## What did NOT change

BlueMarlin's Marina prompt, BlueMarlin's client configuration, BlueMarlin's booking flow, and the Adamus and Consulta Despertares tenant configurations were not touched. No code paths in the agent itself, the webhook handlers, or the dashboard were modified — this change is entirely in tenant configuration and tests. The Marina agent's processing pipeline, the one-Claude-call-per-message rule, the deploy queue, and the canary pipeline are all untouched. No new endpoints, no new database fields, no new dependencies.
