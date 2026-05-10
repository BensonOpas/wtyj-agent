# EXPLANATION 238 — Tenant isolation: account-id allowlist guard + BlueMarlin credential strip

## In one sentence

Customers messaging Calvin's WhatsApp number will no longer receive a second, off-topic reply from Marina (the boat-charter agent) — and the system now has two independent safeguards that prevent any future tenant from accidentally answering on a phone number it doesn't own.

## What's changing and why

Earlier today, customers who messaged Calvin's promo WhatsApp line got two responses to every single message. One came from Calvin (the right agent), and one came from Marina, BlueMarlin's boat-charter agent, who has no business talking about Unboks at all. The cause: Zernio (our messaging provider) was delivering the same incoming message to two of our tenant containers at once, and both tenants were configured with credentials that let them reply through the same upstream account. Each container thought the message was for it, each ran its own AI agent, and each sent a reply. The customer saw both.

The immediate bleed has already been stopped — the duplicate webhook subscription was removed in Zernio's dashboard earlier today, so future inbound messages reach only one container at the network layer. This change layers two more defenses behind that fix so the same failure can't quietly come back. First, every tenant now declares which messaging accounts it is allowed to handle. If a webhook arrives for an account a tenant doesn't own, that tenant either drops the message silently or just logs a warning, depending on its mode. Second, BlueMarlin's stored credentials for WhatsApp, Late, Zernio, Meta, and email have been wiped from its environment file on the server, so even if the routing breaks again BlueMarlin physically cannot prove its identity to Zernio and physically cannot send a reply.

## Step by step — what the code does now

NEW SHARED RULE: "is this account mine to handle?"

A new shared module answers a single question: given an account ID and whether we're talking about an incoming or outgoing message, is the current tenant allowed to act on it? It opens the tenant's configuration file, looks for a new section called the channel account allowlist, and decides based on three possible states. If the section is missing entirely, the rule stays out of the way and answers yes — this keeps every existing tenant working without changes. If the section exists in "permissive" mode, an unknown account ID gets a warning written to the log but the answer is still yes (the work proceeds). If the section exists in "strict" mode, an unknown account ID gets a log entry and the answer is no (the work is blocked).

GUARD AT THE FRONT DOOR (incoming messages)

When a webhook arrives from Zernio, the system already parses out the message details and checks whether it has seen this exact message before. Right after that duplicate check, the new guard runs. It pulls the account ID off the parsed message and asks the shared rule whether the current tenant should be touching this. If the answer is no, the system stops right there — the AI agent is never invoked, no reply is generated, no buffering happens, nothing further occurs for that message. The message has already been marked as "seen" by the duplicate-check, which is intentional: even if the allowlist is updated later in the day, we don't want to re-process a stale misrouted event.

GUARD AT THE BACK DOOR (outgoing replies)

The Zernio sender — the piece of code that actually pushes replies out to WhatsApp, Instagram, and Facebook through Zernio — now runs the same check just before it talks to Zernio's API. If the account it's about to send through isn't on this tenant's allowlist, the send is refused immediately and reports failure to whatever called it. This is mostly a backstop. The inbound guard plus the credential strip already make a misrouted reply nearly impossible, but if someone in the future re-adds credentials without re-adding the allowlist entry, this is the last line of defense.

TENANT CONFIGURATION CHANGES

BlueMarlin and Adamus both have the new section set to strict mode with an empty list of accounts. Neither one has any live inbound messaging today, so anything reaching them through Zernio is by definition wrong and gets dropped. Unboks (Calvin) has the new section set to permissive mode with an empty list, which means any inbound message will go through but every unknown account ID generates a warning in the log. The reason for the difference is practical: we don't yet know the exact account ID Zernio assigns to Calvin's WhatsApp number, because it doesn't appear in the existing log lines. Permissive mode lets real customer messages keep flowing while we collect the actual account ID from the warnings. Once we see it in the logs, we'll add it to the list and switch to strict — that's a two-line config change, not new code.

CREDENTIAL STRIP ON THE SERVER

BlueMarlin's environment file on the production server has been emptied of its WhatsApp access token, WhatsApp phone number ID, WhatsApp verify token, WhatsApp business account ID, Meta app credentials, Late API key, Zernio webhook signing secret, and email address. The values are still present as keys (so the file format is unchanged), but the right side of each is now blank. A timestamped backup was made before any change. The practical effect: BlueMarlin's container can no longer authenticate to Zernio, can no longer verify a Zernio webhook signature, and can no longer send a Zernio reply, regardless of what code runs inside it.

TEST-SUITE COMPATIBILITY HOOK

The existing test suite has more than a thousand tests, many of which exercise the webhook handler and the sender. To avoid having every one of those tests fail because of the new guard, an automatic test-setup hook now removes the allowlist section from the in-memory test configuration before each test runs and restores it afterward. With the section absent, the guard answers "yes" silently — exactly the same behavior the tests had before this change. The seven new tests written specifically for this change inject their own fake configurations, so they bypass the strip and exercise the real logic.

## Edge cases

- If Zernio re-creates a webhook subscription pointing at BlueMarlin in the future (during testing, debugging, or recovery), BlueMarlin can no longer pass the signature check because its signing secret is empty — the webhook is rejected before any of the allowlist logic even runs. Good outcome.

- If a future tenant is given the wrong API key by mistake, both the inbound and outbound guards block any cross-tenant activity in strict mode. In permissive mode, the message goes through but a warning is logged for someone to notice. This is a known trade-off: permissive mode is for tenants whose account IDs we don't yet know.

- Unboks is intentionally in permissive mode right now. During this bedding-in period, if a misrouted message reaches Unboks, it will still be processed and Calvin will still reply. That risk is accepted because the alternative — strict mode with an empty list — would block real customer messages. The window closes as soon as we capture the real account ID from the logs.

- The duplicate-check that marks a message as "seen" runs before the new guard. If a misrouted message reaches a tenant in strict mode, it's dropped, but the same message ID is now flagged as already-processed for that tenant. If the allowlist is widened later that same day to include the account, the original message won't be re-processed. This is acceptable: a misrouted message reaching this point is an anomaly, not a normal customer message worth retrying.

- The guard logs a truncated version of the account ID (first 24 characters) rather than the full string, matching the redaction style used elsewhere in the webhook handler.

- If a tenant's configuration file is missing the new section entirely, the guard stays silent and lets everything through. This is intentional backward-compatibility: tenants who don't opt in get the old behavior. All four current tenants have been opted in, but a future new tenant added without the section won't accidentally lock itself out.

- The brief originally carried number 200 in an older local checkout; the actual brief number is 238. Some comments and one server-side backup file still carry "brief200" in their names. Functionally identical, just a naming artifact noted in the commit message.

## What did NOT change

Marina's prompt, Calvin's prompt, the booking flow, the reply-generation path, customer data handling, and the AI's behavior on legitimate messages are all untouched. Adamus and Consulta Despertares continue to behave exactly as before — neither has live inbound messaging, so the new strict-mode guard is invisible to them in normal operation. The Zernio webhook signature verification, the deduplication logic, the typing indicator, and every downstream agent remain exactly as they were. The only behavioral changes are: misrouted webhooks now get dropped instead of processed, cross-tenant outbound sends now get refused instead of attempted, and BlueMarlin no longer holds the secrets it needed to talk to the outside world through Zernio, Meta, or Late.
