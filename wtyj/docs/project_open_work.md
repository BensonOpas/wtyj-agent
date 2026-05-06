# Open Work — backend extension agenda

Captured 2026-04-28 during system-plan reframe. Calvin shipped a formal product spec ("SOT spec" — Source of Truth) that defines what Unboks is and how it behaves. Backend (`wtyj-agent`) needs to extend `client.json` and code to match. Not yet started.

## HIGH PRIORITY — Google Workspace email support (added 2026-05-05)

`hello@unboks.org` is the new public contact email for the unboks tenant — calvin-csa needs to poll it and reply via the email channel. Mailbox is on **Google Workspace**, not Microsoft 365. Our `wtyj/agents/marina/email_poller.py` only knows Microsoft Azure OAuth + Outlook IMAP today (BlueMarlin and Adamus both run on Microsoft 365 via GoDaddy).

**Why this is high priority:** Benson's stated preference is Google email going forward — every future client onboarded after unboks will likely be Google Workspace. Microsoft was the historical accident (GoDaddy bundled it with the wetakeyourjob.com domain). Building Google support now unblocks unboks AND every client after.

**Approach (Option A from 2026-05-05 discussion):** add provider abstraction to `email_poller.py`. Env-var switch:
- `EMAIL_PROVIDER=microsoft` (default for backward compat) → existing Azure OAuth + outlook.office365.com IMAP path
- `EMAIL_PROVIDER=google` → new Google OAuth + imap.gmail.com:993 path

What needs building:
1. Google Cloud OAuth client (one-time, in our existing Google Cloud project per `reference_google_cloud.md`) — scopes: `https://mail.google.com/`
2. Interactive OAuth bootstrap script (mirrors the Microsoft `bootstrap_outlook_token.py` pattern) → writes refresh token to `/root/clients/unboks/config/google_refresh_token.txt`
3. Token-refresh helper: trade refresh token for access token via Google's token endpoint (`https://oauth2.googleapis.com/token`)
4. IMAP path that uses Gmail's XOAUTH2 SASL mechanism (different from Microsoft's XOAUTH2 — same name, different format)
5. Provider switch at the top of `email_poller.py` based on `os.environ["EMAIL_PROVIDER"]`
6. Tests: provider switch + token-refresh logic; live IMAP test against the real mailbox is manual

**Rejected alternatives:**
- App Password auth — Google deprecated/restricted; fragile
- Gmail API REST instead of IMAP — different code path entirely, more refactor

**Blocks:** unboks email channel going live. Until this ships, calvin-csa can only handle WhatsApp/IG/FB DMs for the unboks tenant.

**Estimated:** half-day brief. Single file (`email_poller.py`) + new `bootstrap_google_token.py` script + tests.

## Marina IS the template — but content stays per-tenant (clarified 2026-05-05)

**Marina (`wtyj/agents/marina/marina_agent.py`) IS the canonical template** — for code patterns: em-dash strip, escalation flags, customer record creation, language matching, prompt scaffolding shape, etc. Copy from Marina freely.

**What does NOT come along with the code copy: BlueMarlin's domain content.** The boat-charter language (trips, prices, FAQ, brand voice) lives in `clients/bluemarlin/config/client.json`, NOT in `marina_agent.py`. The code reads from `client.json` at call time — it is content-agnostic by design. So calvin-csa, sofia, etc. can use Marina's code patterns without inheriting boat terms; their content comes from THEIR own `client.json`.

The earlier "Marina is not a template" framing in this doc was wrong (Brief 201 wrote it). Corrected: Marina is the template. The thing to avoid is **bleeding BlueMarlin's content into other agents' configs** — which is already prevented by the per-tenant client.json architecture and doesn't need a new principle.

When refactoring a Marina pattern into a shared helper (e.g., later when the third agent also needs em-dash strip), it's still fine — that's just normal code factoring. But the default move is "copy from Marina," not "design a new base from scratch."

## SMTP "From" header hardcoded as Marina (added 2026-05-05, post Brief 204)

`wtyj/agents/marina/email_adapter.py:smtp_send()` builds the "From" header as `"Marina <{EMAIL_ADDR}>"` — hardcoded "Marina" string. This means when calvin-csa replies to emails on `hello@unboks.org`, the reply's From header says "Marina <hello@unboks.org>" instead of "Calvin <hello@unboks.org>".

**Fix:** read the agent name from `client.json` (`business.agent_name` or `agent_persona.name`) and use it in the From header. ~3 lines, no new tests strictly needed (or 1 test asserting From header includes the configured agent_name).

Tiny brief or quick-fix path. Low priority — recipient sees a slightly off display name but reply works correctly. Cosmetic UX.

## Frontend-side follow-ups from Brief 200 cutover (added 2026-05-05)

After the api.unboks.org cutover, two frontend-handling issues emerged. Both are SR's territory (frontend repo `calvin835/unboks-dashboard-api/artifacts/unboks/`); flagging here so the next session knows:

- **JWT expiration handling.** Our `_check_auth` dependency rejects expired tokens with 401. Frontend doesn't refresh tokens or redirect-on-401, so users see broken UI after idle. Fix on frontend: detect 401 in axios/fetch interceptor, clear stored token, redirect to login.
- **Detail view defensiveness.** `Inbox.tsx` line 64 reads `msg.content` directly with no fallback to `msg.text`. Brief 201 worked around by adding aliases backend-side. Frontend should mirror the `safePreview` defensive-read pattern in `MessageBubble` to handle backend shape variation gracefully going forward.

## The SOT spec (Calvin, paraphrased — full text in chat history)

- Core value: AI answers routine, escalates important.
- Channels: WhatsApp, Email, Instagram, Facebook, Telegram (deferred), Messenger.
- Escalation system:
  - **Hard escalation** (AI stops, human takes over): booking confirmed+paid, customer asks for human, complaint, refund/payment issue, booking problem, legal issue, persistent inappropriate/unethical behavior.
  - **Soft escalation** (AI asks human internally, then replies): operator answers via relay, AI uses that answer.
  - **No escalation** (low confidence): AI iterates, asks clarifying questions.
- Knowledge base sources: PDFs, text, FAQs, images, pricing, policies, website content, chat history.
- Communication style: defined during intake, not client-changeable; Unboks updates centrally.
- Bookings = escalations (architectural simplification — surfaces them in the same dashboard view).
- Structured data extraction: per-client fields defined during intake (customer name, contact, channel, date/time, count, service, payment status, special requests, notes).
- Pricing: per-client, not fixed.

→ Move this to `wtyj/docs/escalation_rules.md` (separate doc) when implementing, with byte-exact mapping to `marina_agent.py`.

## client.json extension agenda — five questions to settle before coding

### A. Schema gaps vs SOT
Things in the SOT spec NOT yet in `client.json`:
- **Channel toggles** (`features.channels.{whatsapp,email,instagram_dm,facebook_dm,messenger}`). Currently scattered: `features.booking_flow`, `features.content_pipeline`, plus `EMAIL_ADDRESS` env var implicitly gates email polling.
- **Structured escalation triggers** — currently the hard/soft logic is partly in `marina_agent.py` prompt and partly in Python (`_BOOKING_INTENTS` set, capacity guards).
- **Knowledge base sources** — only `faq` and `services` exist today. SOT mentions PDFs, images, policies, website content, chat history.
- **Intake-defined extraction fields** — no per-client extraction schema today; Marina's extractor uses fixed `ALLOWED_KEYS`.
- **Communication style mapping** — partial: `agent_persona.tone`, `language_register`, etc. exist, but SOT framing is broader.

### B. Config-driven vs hardcoded
Open question: should escalation rules become per-client config (e.g. each tenant defines their own "what triggers a hard escalation"), OR stay as universal Marina behavior with only `services`/`languages`/`brand_voice` per-client?

Default position: rules stay universal (Calvin defines them once for the platform); per-client only overrides what the SOT spec lets them override (services, languages, FAQ, brand voice, channel toggles, booking on/off).

### C. Validation
No JSON schema for `client.json` today. Malformed configs fail silently or crash at field access. Listed in `roadmap.md` as Phase 1.5 leftover ("JSON schema validation in config_loader"). Adding Zod or jsonschema validation alongside the modular extension makes the new fields enforceable.

### D. Backward compatibility
4 production tenants (bluemarlin/adamus/consultadespertares/unboks) have working configs. Decision needed:
- **Additive only** — new fields are optional; existing configs keep working untouched. Pro: zero migration risk. Con: schema becomes inconsistent.
- **Migrate** — write a one-time script to upgrade each tenant's `client.json` to the new shape. Pro: clean. Con: real work + needs verification.

### E. Defaults
When a field is missing, what should the backend do? Today: some fallbacks (e.g. `agent_name` defaults to "Marina"), some throw on access. Worth formalizing one rule: missing field → defined default in `config_loader.py`, never None propagating.

## DM-agent quality issues (surfaced 2026-05-03 by calvin-csa on unboks tenant)

These were caught from real-prospect-style messages on Calvin's WhatsApp after Brief 199 went live. Both are real bugs in the dm_agent path used by `booking_flow: false` tenants.

### F. Em-dash post-process strip
The `agent_persona.brand_voice_rules` in `client.json` says "Never use em-dashes or en-dashes" but Claude ignores it consistently — every reply calvin-csa sent in testing had at least one em-dash. Marina handled this for the marina_agent path with a backend strip post-LLM-call (replaces every `—` and `–` with `, ` or strips them). The `dm_agent` path (`wtyj/agents/social/dm_agent.py`) has no such strip — replies go out raw.

**Fix:** add a sanitize step in dm_agent before `send_reply()` that replaces `—` and `–` with `, `. ~3 lines, deterministic, no prompt-engineering uncertainty. Same pattern Marina uses.

### G. Hallucinated URLs
calvin-csa made up `https://unboks.com/contact` (real domain is `unboks.org`, no `/contact` page exists). When prospects ask "where can I book a call?" the AI invents URLs from training data. Bad — dead links lose leads.

**Fix:** add an explicit contact channel to `agent_persona` or a top-level `contact_methods` field in `client.json`. The AI should ONLY use what's defined there, never invent. Options to populate it with:
- A real Calendly link (if/when SR sets one up)
- "Reply with your email and we'll be in touch" (no URL)
- Direct WhatsApp number (recursive but works)
- A real `unboks.org/contact` page (if SR builds one)

Need decision from Benson on which contact mechanism to advertise.

## Personal-vs-promo contact filter (surfaced 2026-05-03)

SR's WhatsApp number is his real personal/business phone. calvin-csa now answers EVERY message — including SR's friends, family, existing contacts. Three options ranked elsewhere in this doc; recommended path is **Option E (separate WhatsApp number for the Unboks promo)** so personal/business stay isolated. Stopgap is `ignored_conversations` allowlist in `client.json` updated as friends accidentally get auto-replied. Not yet built.

## Where to start (when ready)
Most direct path:
1. Decide which channel toggles are in scope (skip Telegram per Benson, 2026-04-28).
2. Add `features.channels` block to `client.json` schema.
3. Wire backend gates: webhook handler skips disabled channels; email poller skips clients with email off.
4. Update existing 4 tenants' configs.
5. Write `wtyj/docs/escalation_rules.md` with the SOT escalation triggers + map to current code.
6. Validation as a fast follow.

Not started. Notes captured for the next time we resume this thread.
