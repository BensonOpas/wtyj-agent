# BlueMarlin — Development Roadmap

**Source of truth for what to build next, in what order.**
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

**Estimated briefs:** 3-4

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

---

## Risks with Lead Time

| Risk | Lead Time | When to Act |
|------|-----------|-------------|
| Meta Business verification | 1-5 days | Start of Phase 1 |
| Meta App Review (publishing perms) | 3-5 days | During Milestone B |
| Email provider evaluation | Decision cycle | Start of Phase 2 |
| Domain DNS propagation | 1-24 hours | Start of Phase 1 |
