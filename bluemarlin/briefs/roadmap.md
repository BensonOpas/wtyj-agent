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

## Phase 1 — Social Agent — COMPLETE

**Goal:** WhatsApp DM Q&A + Instagram/Facebook auto-posting + full booking flow on all channels.

### Milestone A: WhatsApp Q&A Live — COMPLETE
WhatsApp webhook, Q&A agent, full booking orchestrator (availability, holds, payment, confirmation), escalation system (semi + full), relay bridge, debouncing, rate limiting, returning customer detection, multi-booking conversations. Briefs 067-089.

### Milestone B: Auto-Posting Live — COMPLETE
Content agent, branded graphics engine, Instagram + Facebook publishing via Zernio/Late SDK, rejection learning, photo library, scheduling. Briefs 092-098.

### Milestone C: Social Hardening — COMPLETE
Structured logging, 624 tests, IG/FB DM integration (Zernio webhooks), DM booking through orchestrator, booking flow guard on all channels, feature toggles, terminology system, manifest error handling. Briefs 099-139.

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

### Milestone D: Multi-Tenant Config — COMPLETE

**Status:** Done (Briefs 133-138). Codebase is fully client-agnostic.

Completed:
- All hardcoded values parameterized (email, prompt examples, booking ref prefix)
- Renamed trips→services across entire codebase + DB + dashboard frontend
- Feature toggles: booking_flow on/off, payment timing, terminology system
- Booking flow guard on all channels (WhatsApp, email, DMs)
- DM booking through orchestrator when booking_flow=true
- Restaurant and real estate configs tested and working

Still TODO (non-blocking):
- Template `client.json.template` for new clients
- JSON schema validation in config_loader
- `requirements.txt` with pinned dependencies

---

### Milestone E: Central Infrastructure

**Delivers:** Shared infrastructure owned by us, serving multiple clients.

**Status:** Partially done. Zernio replaces per-platform API integrations. Rest deferred — not needed for Path A (one VPS per client with Docker).

Done:
- Zernio integration: publishing + DMs on IG/FB, webhook active

Deferred (build when Path A hits limits):
- Email provider switch (Mailgun/SendGrid evaluation + migration)
- Google Workspace consolidation (one service account, per-client calendars/sheets)
- Meta Business Portfolio setup for multi-client WhatsApp

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

Done:
- **Operator dashboard** — React app live at bluemarlindashboard.replit.app. Overview, messages, escalations, content pipeline, brand training, capacity checker, settings, photo library.
- **Structured logging** — bm_logger JSONL logging of all events.

Still TODO:
- **Real payment integration** — Stripe or Mollie Connect. Payment link → webhook confirmation → automatic booking status update.
- **Config automator** — tool/script that generates a valid client.json from a questionnaire or intake form.
- **Full audit/log trail** — append-only logging of every booking lifecycle event. 6-month retention. Critical for dispute resolution once real money flows.

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

### Milestone I: Booking Flow Unification

Done:
- WhatsApp has full booking flow (Brief 070+)
- Email has full booking flow (original)
- IG/FB DMs have full booking flow (Brief 138)
- All three channels share the same booking_flow toggle

Still TODO:
- Extract shared booking state machine from `email_poller.py` and `social_agent.py` into `shared/booking_flow.py` — reduces duplication, makes maintenance easier
- Website form integration (BlueMarlin-hosted booking page)

### Milestone J: Expansion

Done:
- Instagram + Facebook DMs via Zernio (Briefs 130-131, 138)
- Instagram + Facebook publishing via Zernio

Still TODO:
- Operator notification system (configurable alerts via email + WhatsApp)
- Additional publishing platforms (X/Twitter, LinkedIn, TikTok — all supported by Zernio, just need connecting)
- Comment handling via Zernio

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

**Blocking (for April 15 deadline):**
- Docker setup (Milestone F) — the one deliverable left

**Prompt / UX (before or alongside Docker):**
- Booking confirmation wording — Marina says "want me to book?" before checking availability. Change to "let me check availability" vibe. Prompt change in action context.
- Booking flow too fast on all channels — Marina jumps to field collection. Should give info about the service first, be conversational, then naturally flow into booking.
- Large group escalation — change from pre-check to full escalation with warm handoff. "That's a big group, let me connect you with the team." Not a Python override, let Marina handle it in prompt.
- AI tone tuning — em-dashes, "I'd be happy to", over-eagerness. More banned phrases in prompt + post-filter. Later development.
- FAQ learning from relay answers — when operator answers a relay question, store as FAQ for future. New dashboard tab. Later development.

**Brand / Config:**
- Brand assets in client config — logo, icon, fonts, colors for AI content generation + dashboard white-labeling
- Client website URL in config — Marina references it in conversations
- Deprecate Pillow graphics engine — AI image generation replaces it. Deactivate, don't delete yet.

**Polish:**
- [PAYMENT_LINK] cosmetic bug — blank line when payment.timing="none"
- Client email config — business.email should be the customer-facing inbox (hello@wetakeyourjob.com for demo), business.support_email for escalations (info@bluefinncharters.com). Verify both are used correctly.

**Content pipeline:**
- Post analytics — blocked by Late $29/mo add-on or direct Instagram Graph API
- Content planning optimization — blocked by analytics
- Brand voice learning from existing posts — scrape client's IG, learn their style
- Photo matching — content agent picks from photo library

**Future platform work:**
- BlueMarlin-hosted booking page — branded form per client, reads from config. For businesses without a website.
- Channel toggle per client (which channels active)
- Content toggle per client (on/off)
- Escalation routing config (where notifications go)
- Open schedule availability model (salons, clinics — build when first Tier 2 client signs)
- Date range availability model (rentals — build when needed)
- Dashboard channel badges (Brief 132)
- Dashboard booking management page
- Dashboard analytics page
- Dashboard multi-client view
- Payment integration — Stripe Connect webhook (we watch transactions, never touch money). Must work for any business type including no-payment businesses.

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
