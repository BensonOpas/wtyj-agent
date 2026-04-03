# BlueMarlin — Development Roadmap

**Owns:** The WHEN — what to build next, in what order, milestones and priorities.
**Related:** For the vision and product idea → `master_plan.md`. For infrastructure → `infra.md`. For brief history → `system_state.md`.

**Referenced from CLAUDE.md. Read this before any planning session.**
**Individual briefs get planned one at a time via /think → /brief.**

---

## Current State (Brief 066)

Marina (email booking agent) is complete and running in production.
50 E2E test scenarios, 90% pass rate, zero functional bugs.
See `marina_status_90.md` for full details.

---

## Phase 1 — Social Agent

**Goal:** WhatsApp DM Q&A + Instagram/Facebook auto-posting. Visible, demo-worthy feature.

### Milestone A: WhatsApp Q&A Live

**Delivers:** Customers message BlueFinn on WhatsApp, get instant answers about trips, pricing, availability. Booking requests redirected to email.

**Architecture:**
- Separate FastAPI process (`agents/social/webhook_server.py`), own systemd service (`bluemarlin-social`)
- nginx reverse proxy + Let's Encrypt on `api.wetakeyourjob.com` for Meta webhook HTTPS
- Own Claude prompt in `agents/social/social_agent.py` — Q&A focused, shorter replies, no booking flow
- Shared knowledge via `config_loader` (same trips, FAQ, business data as Marina)
- WhatsApp Cloud API (Meta) for send/receive
- Conversation tracking in `state_registry.py` (new `whatsapp_threads` table)
- Dedup by message ID, per-phone rate limiting, anti-loop guard

**Key files:**
- `agents/social/webhook_server.py` — FastAPI webhook receiver
- `agents/social/whatsapp_client.py` — parse inbound + send replies
- `agents/social/social_agent.py` — Claude-powered Q&A

**Risks:** Meta Business verification takes 1-5 business days. Start account setup first.

**Estimated briefs:** 6-8

> **Business milestone:** WhatsApp Q&A demo-ready. Show BlueFinn owner.

---

### Milestone B: Auto-Posting Live

**Delivers:** Automatic promotional content published to Instagram and Facebook on a schedule. Operator configures frequency and themes in client.json.

**Architecture:**
- Claude-powered content generation (`agents/social/content_agent.py`)
- Meta Graph API for Instagram Content Publishing + Facebook Pages
- Cron/systemd timer (not always-running — no inbound trigger)
- Posting schedule and rules in client.json (`social_content` section)
- Post tracking in `state_registry.py` (new `social_posts` table)

**Key files:**
- `agents/social/content_agent.py` — generates captions, hashtags, post ideas
- `agents/social/meta_publisher.py` — Instagram + Facebook publishing
- `agents/social/auto_poster.py` — cron-triggered scheduler

**Risks:** Meta App Review for `instagram_content_publish` takes 3-5 business days. Images must be at publicly accessible URLs.

**Estimated briefs:** 4-5

> **Business milestone:** Full social presence demo. WhatsApp Q&A + auto-posting both live.

---

### Milestone C: Social Hardening

**Delivers:** Production-ready social agent with monitoring, logging, and test coverage.

- WhatsApp booking redirect polish (warm message with email + summary)
- Structured logging (bm_logger pattern), heartbeat, error alerting
- Social agent test suite (minimum 20 scenarios)
- Cross-channel awareness (optional: store partial intent from WhatsApp so Marina recognizes returning customer)

**Estimated briefs:** 2-3

> **Business milestone:** Social agent production-hardened. Confident enough for client presentation.

---

## Phase 2 — Centralization + Containerization

**Goal:** Transform from handcrafted installation to deployable product template. Onboarding a new client takes under an hour and requires only client.json + .env.

*This is a direction, not a spec. Needs research before any brief.*

### Direction

- **One Google Workspace account (ours).** Each client gets sub-calendars and sheet tabs under our account, not their own Google account.
- **One email sending provider (Mailgun or SendGrid, TBD)** replacing per-client Azure/Microsoft setups entirely. Client-specific sending domains (e.g. bookings@bluefinn.com) configured as aliases.
- **One Meta Business Portfolio** for WhatsApp, multiple phone numbers underneath.
- **Zernio (Late) as unified social API.** Publishing to 14 platforms (IG, FB, X, LinkedIn, TikTok, YouTube, Threads, Reddit, Pinterest, Bluesky, Telegram, Snapchat, Google Business) + DMs on 7 platforms (IG, FB, WhatsApp, Telegram, X, Bluesky, Reddit). $29/mo per client (Build $19 + Inbox $10). Replaces per-platform API integrations. Decision made April 2026.
- **Docker container:** Same image for every client. client.json + .env mounted as volumes. Deploy = spin VPS, pull image, mount config, start container.
- **client.json is the only file that changes between clients.** Every business-specific value lives there.
- **gws CLI:** Prebuilt binary download for Docker image.

### Milestone D: Multi-Tenant Config

**Delivers:** Codebase is client-agnostic. client.json is the only thing that changes per client.

- Audit and parameterize all hardcoded client-specific values
- Azure OAuth credentials → env vars
- Prompt email addresses → config_loader
- Anti-loop reply trip names → generated from config
- Template `client.json.template` for new clients
- JSON schema validation in config_loader
- `requirements.txt` with pinned dependencies

**Estimated briefs:** 4-6

---

### Milestone E: Central Infrastructure

**Delivers:** Shared infrastructure owned by us, serving multiple clients.

- Email provider switch (Mailgun/SendGrid evaluation + migration)
- Google Workspace consolidation (one service account, per-client calendars/sheets)
- Meta Business Portfolio setup for multi-client WhatsApp
- Zernio integration: migrate social_publisher.py from Late SDK to Zernio unified API (publishing + DMs). Connect all platform accounts per client via Zernio dashboard. Set up DM webhooks (`message.received`) routed to Marina.

**Estimated briefs:** 5-7

---

### Milestone F: Docker + Deployment Automation

**Delivers:** Mechanical deployment. New client = fill in client.json + .env, run deploy script.

- Dockerfile (python:3.12-slim + gws CLI binary)
- docker-compose.yml (marina + social-webhook + social-poster services)
- `deploy.sh` — one-command deployment
- Migrate BlueFinn from systemd to Docker
- Target: < 1 hour from zero to running

**Estimated briefs:** 4-6

> **Business milestone:** Product template ready. First client invoice (setup fee + monthly). Start sales outreach to prospective clients.

---

## Phase 3 — Production + Second Client

**Goal:** Production-grade features, prove the template works, close the second sale.

### Milestone G: Production Features

- **Full audit/log trail** — append-only logging of every email, Claude call, state transition, booking lifecycle event. SQLite + JSONL, 6-month retention. Critical for dispute resolution once real money flows.
- **Real payment integration** — Stripe or Mollie (Mollie popular in NL/Curaçao). Payment link → webhook confirmation → automatic booking status update.
- **Operator dashboard (HTML)** — FastAPI web app on VPS subdomain. Status panels (today's bookings, upcoming manifests, pending escalations, system health). Live capacity checker (spots remaining per trip/date). Config editor (edit trips, prices, FAQ through web form). Password-protected.
- **Sheets testing** — verify all Sheets tabs are logging correctly end-to-end (Bookings, Escalations, All Events, Manifests). Automated tests against real sheet data.
- **Config automator** — tool/script that generates a valid client.json from a questionnaire or intake form. Validates required fields, sets up calendar IDs, generates template FAQ.

**Estimated briefs:** 8-12

---

### Milestone H: Second Client Onboarding

**Delivers:** Proof the template works. Deploy = client.json + .env + start container.

- Identify second client
- Onboarding checklist + template config
- Deploy using deploy.sh
- Fix issues discovered during onboarding (expect them)
- Multi-client monitoring (per-client health, cost tracking)

**Estimated briefs:** 3-5

> **Business milestone:** Second client live. Product proven. Scale sales.

---

## Phase 4 — Advanced Features

**Goal:** Expand capabilities after the product template is proven.

### Milestone I: WhatsApp Full Booking Flow

- Extract booking state machine from `email_poller.py` into `shared/booking_flow.py`
- Both email and WhatsApp channels share the same validation, capacity checking, calendar hold, payment link generation
- Biggest refactor in the project — requires comprehensive test coverage first

### Milestone J: Expansion

- Website form integration (webhook endpoint → agent → email reply)
- Operator notification system (configurable alerts via email + WhatsApp)
- Additional channels (Facebook Messenger, Instagram DMs)
- Additional platforms for auto-posting (X/Twitter)

---

## Summary

| Phase | Milestones | What it delivers | Estimated briefs |
|-------|------------|------------------|------------------|
| 1 | A, B, C | Social agent (WhatsApp Q&A + auto-posting) | 12-16 |
| 2 | D, E, F | Multi-tenant product template (Docker + centralized infra) | 11-16 |
| 3 | G, H | Production features + second client | 11-17 |
| 4 | I, J | Full WhatsApp booking + channel expansion | TBD |

**Brief numbering continues from 067.**

## Competitive Landscape (researched 2026-03-14)

### Direct Competitors

| | Visito | Yonder | BlueMarlin |
|---|---|---|---|
| Channel | WhatsApp + Instagram + web | Website + Messenger | Email + WhatsApp |
| Books IN chat | Yes | No (links out) | Yes |
| Calendar mgmt | Via hotel PMS | Via Rezdy/FareHarbor | Direct (Google Calendar) |
| Setup | Minutes (paste URL) | 1-4 weeks (their team) | Claude configures per client |
| Pricing | $49/mo+ | Usage-based | $300-1,000/mo |
| Target | Hotels | Tour operators | Small operators (any industry) |
| Auto-resolution | 97% | 65-98% | TBD — need to measure |
| Review mgmt | No | Yes (main differentiator) | No (future feature) |

### Our Edge
- Full booking lifecycle IN chat (calendar, capacity, holds, payment)
- Email + WhatsApp with shared state
- Escalation relay (semi + full)
- Custom per client, not template-based
- Multi-language Caribbean (EN, NL, DE, ES, PT)

### Our Gap
- No marketing, landing page, case studies
- No self-serve onboarding
- No review management
- No booking system integration (Rezdy, FareHarbor)

### Market Data
- WhatsApp: 98% open rate vs 20% email, 2.7B users
- Only 2% of consumers let AI book autonomously — Marina facilitates, doesn't replace
- AI in tourism: $3B → $30B this decade
- Yonder ROI: 2-month payback typical

### Strategic Actions
1. Track BlueFinn ROI (bookings, hours saved) — need real numbers for pitch
2. Add review management (post-trip auto-request) — simple, high value
3. Onboarding story: "give us your info, system live in a day"
4. Booking system integration (Rezdy, FareHarbor) for Phase 3
5. Sweet spot: small operators with no existing system (BlueFinn type)

### Open Items
- Add departure point addresses/directions to client.json (Mood Beach, Village Marina, Spanish Water) — Marina knows the names but can't give directions
- WhatsApp fallback on API failure still silent — need a solution that doesn't violate Rule 3 (no static reply templates)
- **Performance tracking / post analytics:** Late's free tier doesn't include analytics (402 error). Analytics add-on is $10/mo on top of Build plan ($19/mo) = $29/mo total. Alternative: use Instagram Graph API directly with the business account token (account has `instagram_business_manage_insights` permission via Late). For now, store post history (Instagram URL, post ID, publish date, content class) in SQLite — real engagement metrics (likes, reach, saves) plug in later when we upgrade or go direct API. This feeds into content planning optimization and weekly reports.
- **Content planning optimization:** Feed post performance data back into content generation — the bot learns which topics, content classes, and trip types drive engagement and adjusts its content mix. Blocked by: no performance metrics yet (requires Late analytics add-on $29/mo or direct Instagram Graph API insights). Once metrics exist, inject top-performing post patterns into the content agent's user prompt alongside rejection history.
- **Graphics engine overhaul (Brief 095 follow-up):** default Pillow font doesn't support Unicode (ñ, ç in Curaçao renders as placeholder boxes). Need a proper font (Inter/Montserrat .ttf with Latin Extended). Overall template quality needs work — better layouts, different templates per content class, premium look. Current output is functional but not demo-quality.
- **Facebook publishing:** Late account only has Instagram connected. Add Facebook Page to Late dashboard, update social_publisher.py to post to both.
- **Content pipeline scheduling:** auto_poster.py is manual CLI. Needs cron/systemd timer for automated daily generation + queued publishing after approval. Deferred — should be part of a main operator dashboard, not standalone cron.
- **Operator dashboard:** Web-based UI where the operator reviews drafts, approves/rejects, sees published posts, monitors metrics, triggers generation, manages learnings. Replaces the CLI workflow. All current CLI commands become dashboard features. This is the production approval workflow SR described.
- **Media library / photo intake:** Business owner uploads real photos (boat shots, sunsets, crew, guests) to a shared cloud folder (Google Drive or similar). The content agent pulls from this library when generating posts — real photos paired with AI-written captions instead of only branded graphics. Supports mixed-source media: operator-provided photos, crew shots, customer UGC (with permission). The system should tag/categorize photos (trip type, mood, subject) so the content agent can match the right photo to the right post. This is what makes posts look real instead of template-generated.
- **Brand voice learning from existing posts:** Scrape/ingest the client's existing Instagram/Facebook posts and feed them into the content agent prompt as style examples. The AI should learn how the business already communicates — tone, word choice, emoji usage, caption structure, hashtag patterns — and mirror that in generated drafts. This is separate from rejection learning (which teaches what NOT to do). This teaches what TO do. Critical for onboarding new clients who already have a social presence.

---

## The Payment and Booking Page Problem

There is a core problem that affects both payment processing and the
future booking website page. The problem is the same in both cases:
if the customer leaves our system to do something (pay on the client's
Stripe, book on the client's website), our dashboard never finds out
what happened. The booking sits at "pending payment" forever. Data
doesn't sync. The operator has to manually check and update things.

This matters because the dashboard is the product. If the dashboard
doesn't know the real status of a booking, it's useless. The operator
has to go check Stripe themselves, check their calendar themselves,
cross-reference manually. That's the manual work we're supposed to
be eliminating.

The same problem shows up in three places:

1. Payment: we send the customer a payment link. If that link goes to
the client's own payment page (their Stripe, their Mollie, their bank
transfer page), we never get a callback saying they paid. Our system
thinks the booking is still pending. The client knows they got paid
because they check their Stripe. But our dashboard doesn't.

2. Booking website: if the customer books on the client's existing
website instead of through our system, we never see the booking at
all. It doesn't show up in the dashboard, doesn't show up on the
calendar we manage, doesn't count toward capacity. Now the system
thinks there are more spots available than there really are.
Overbooking risk.

3. External changes: if the client manually adds a booking, cancels
one, or changes something outside our system, our data is stale.

The fix for all three is the same idea: we need to be the system of
record. Everything flows through us. Not because we want control, but
because the dashboard only works if it sees everything.

For payment specifically, the solution is Stripe Connect or Mollie
Connect. Here's how it works:

The client connects their Stripe (or Mollie) account to our platform.
This is a one-time OAuth setup — they click "connect," authorize us,
done. When a booking is confirmed, we create a payment link through
their connected account. The money goes directly to them — we never
touch it. But because the payment happens through our integration, we
get the webhook confirmation. Dashboard updates to "paid" automatically.
The client gets their money in their own Stripe. We get the data.

For the booking page, same principle: we host it. The customer goes to
a BlueMarlin-hosted page (branded with the client's colors and info
from their config). They fill in the form, it hits our API, our system
checks availability, creates the hold, and if payment is needed, it
goes through the Stripe Connect flow above. Everything stays in our
system. Dashboard sees it all.

This is not trivial to build. Stripe Connect requires: a Stripe
platform account on our end, OAuth integration for client onboarding,
webhook handlers for payment events (succeeded, failed, refunded),
and the hosted payment page. Mollie Connect is similar. Estimated
effort: 2-3 weeks for the first provider.

When to build this: when we onboard a client that needs payment
confirmation in the dashboard. BlueFinn currently uses demo payment
links and checks their own Stripe manually. That works for a demo.
It doesn't work for a real product. The moment we pitch a paying
client who expects their dashboard to show real payment status, we
need this.

For Tier 1 clients where payment timing is "none" (restaurants, real
estate), this isn't needed. For charters and tours where payment is
upfront, this is a requirement before they trust the system.

Current state: payment_stub.py generates fake demo.pay links. No real
money moves. No payment confirmation. This is accepted for the demo
phase. Real payment integration is Phase 3 (Milestone G in the
roadmap above) but may need to be pulled forward depending on which
client we sign first.

---

## Risks with Lead Time

| Risk | Lead Time | When to Act |
|------|-----------|-------------|
| Meta Business verification | 1-5 days | Start of Phase 1 |
| Meta App Review (publishing perms) | 3-5 days | During Milestone B |
| Email provider evaluation | Decision cycle | Start of Phase 2 |
| Domain DNS propagation | 1-24 hours | Start of Phase 1 |

---

## Client Tiers — Who we sell to and in what order

See feature_toggles_spec.md for what each tier needs toggled on/off.

### Tier 1 — Tourism (first clients, proven product)

Boat charters, tour operators, water sports, restaurants, beach clubs,
car and scooter rentals. 250+ potential clients in Curaçao alone.

These businesses all have the same pain: customers message on WhatsApp,
nobody answers because they're on the water or in the kitchen. They
lose bookings to whoever replies first.

What they need from us: full booking flow, payment, calendar, social
media content, multi-channel communication. This is what we've built.

Availability model: slot_capacity (already built). Car rentals will
eventually need date_range.

### Tier 2 — Local services (second wave, expand beyond tourism)

Hair salons, barbershops, fitness studios, personal trainers, dental
and medical clinics, photographers, spas. 200+ potential clients.

Same pain as Tier 1 but the booking model is different — appointments
with individual providers (stylists, doctors) instead of group slots.
No-shows are the biggest complaint. Automated reminders alone sell this.

What they need: full booking flow with open_window availability model,
payment at service or deposit, calendar, maybe social media.

Availability model: open_window (not built yet — build when first
salon client signs up).

### Tier 3 — Complex services (third wave, lead qualification product)

Real estate agencies, event venues, consulting firms, legal offices.
The AI can't replace the human here — the conversation IS the service.

What they need: Q&A, lead qualification (collect requirements, ask
qualifying questions, offer alternatives), then escalate to human with
full context. No booking flow. No payment. No calendar.

A real estate agent with 10 properties can manage 40 because the AI
filters the repetitive work — "is this available?", "can I see more
photos?", "do you have something with 3 bedrooms?" The agent only
talks to qualified, serious leads.

This is a different product from the booking system but uses the same
infrastructure (channels, escalation, dashboard).

### Tier 4 — Future expansion

Vacation rental managers (compete with Guesty), auto repair shops,
vet clinics, pet services, co-working spaces. Niche markets, longer
sales cycles, but the system works for them with minimal changes.
