# Blue Marlin — Master Plan

**Source of truth for the project vision, scope, and architecture.**
**Referenced from CLAUDE.md. Read this before any planning session.**

---

## 1. The Core Idea

You and Jr are building a company that delivers autonomous AI operations systems for businesses.

The system replaces manual back-office work:
- customer communication
- booking / appointment processing
- calendar management
- payment requests
- social media marketing
- content creation
- posting and scheduling

The system operates 24/7 without human staff.

BlueFinn Charters Curaçao is the first live client — proof that the platform works. The demo is running in production today.

After proving the system, you sell it to other businesses — any industry, not just tourism.

You charge:
- setup fee
- monthly maintenance

The business is: you build and operate autonomous AI systems for companies.

---

## 2. Why BlueFinn Charters

BlueFinn is the perfect first client because:
- clear product (boat charters + jet skis)
- simple booking structure
- high customer message volume
- heavy social media marketing
- manual processes today

Their workflow is predictable:

Customer → message → booking → payment → calendar → tour → social media promotion

This is ideal for automation.

---

## 3. What the System Must Do

The system replaces a front desk + marketing assistant.

### Customer Communication

**Done (email):**
- Email via Microsoft Outlook (IMAP polling + SMTP reply)
- Agent reads the message, understands intent, replies naturally
- Collects booking info, prevents duplicate replies, remembers conversations
- Multi-language: English, Dutch, German, Spanish, French, Papiamentu
- Cross-thread customer memory by email address

**Planned:**
- Instagram DMs
- Facebook Messenger
- WhatsApp (later)
- Website form

### Booking Processing

**Done.** The agent extracts:
- trip (trip_key)
- date
- number of guests
- name
- phone/email
- departure time
- special requests

Actual trips (from client.json):
- Klein Curaçao Trip
- 3-in-1 Snorkeling Trip
- West Coast Beach Trip
- Sunset Cruise
- Jet Ski Excursion

The system then:
1. validates day-of-week, past dates, departure time
2. checks capacity (SQLite soft holds)
3. creates a provisional hold
4. builds a manifest event on Google Calendar
5. sends booking summary with payment link
6. sends confirmation with booking reference (BF-YYYY-XXXXX)

### Calendar Management

**Done.** The system connects to Google Calendar via gws CLI + Google service account.

For each booking:
- creates/updates a manifest event (one per departure slot, all passengers listed)
- stores event ID in SQLite
- prevents double bookings via capacity tracking
- enforces hold expiration

Hold rule (from client.json):

```
Hold duration: 6 hours
If unpaid → release slot
```

### Payment Handling

**Demo stage.** The system sends a demo payment link (payment_stub.py).

Accepted methods (from client.json): Credit card, iDeal, Apple Pay, Google Pay, bank transfer.

Workflow:

Customer confirms → payment link sent → payment confirmed → booking finalized.

Real payment provider integration (Stripe, Mollie, etc.) still to be connected.

### Social Media Marketing

**Planned.** A separate agent (not Marina) will generate and publish marketing content.

Content includes:
- photos
- reels
- captions
- hashtags

Platforms:
- Instagram
- Facebook
- X

The agent will:
- generate captions
- schedule posts
- publish automatically
- create promotional content (potentially including video)
- handle Q&A on social DMs

### Content Creation

**Planned.** The social media agent will generate:
- captions
- promo scripts
- short videos / reel ideas
- story posts

---

## 4. Architecture

### Current Architecture (Live)

Single-agent system. One Python process, one Claude API call per inbound email.

```
Customer Email
     |
     v
[IMAP Polling] → email_poller.py (core orchestrator)
     |
     |── Pre-filters: system email, dedup, anti-loop, rate limit,
     |                 escalation drop, relay inbound
     |
     v
[Claude API Call] → marina_agent.py (single call per message)
     |
     |── Returns: intents, fields, confidence, reply, flags
     |
     v
[Python State Machine] → routes on structured output, never parses language
     |
     |── Semi-escalation → relay to human team, hold reply to customer
     |── Full escalation → empathetic reply + alert to operator
     |── Booking flow → validate → summary → confirm → calendar → payment → done
     |── Other (inquiry, social, off_topic) → send Claude's reply as-is
     |
     v
[Side Effects]
     |── Google Calendar: manifest events (one per departure slot)
     |── Google Sheets: Bookings, Escalations, All Events, Manifests tabs
     |── SQLite: bookings, soft holds, manifests, dedup hashes
     |── SMTP: reply to customer
```

### Future Architecture (Multi-Channel)

Two agents, each with its own process, Claude prompt, and channel:

**Marina (Email Agent)** — Done. One process (email_poller.py), one Claude call per inbound email. Orchestrates the full booking lifecycle using Python modules:
- Calendar module (gws_calendar.py) — manifest events, capacity tracking
- Payment module (payment_stub.py) — demo links, real provider pending
- Sheets module (sheets_writer.py) — operator dashboard logging
- Escalation routing — semi-escalation (relay) + full escalation (complaint/refund)

**Social Agent (WhatsApp + Auto-Posting)** — Planned. Separate process (FastAPI webhook server). Two capabilities:
- WhatsApp Q&A — answers customer messages from trip/FAQ data, redirects bookings to email
- Auto-posting — generates and publishes promotional content to Instagram and Facebook on a schedule

Both agents share the same business knowledge via `config_loader.py` (client.json) and the same state layer via `state_registry.py` (SQLite).

---

## 5. Technology Stack

### Current (Live)

- **Language:** Python 3.12.3
- **AI Model:** Claude Sonnet (`claude-sonnet-4-6`) via Anthropic API — single call per inbound message
- **Database:** SQLite WAL (dedup, capacity, manifests, bookings, cross-thread memory)
- **Email:** Microsoft Outlook OAuth2 (IMAP + SMTP)
- **Calendar:** Google Calendar via gws CLI + service account
- **Sheets:** Google Sheets via gws CLI (operator dashboard)
- **VPS:** Ubuntu (Vultr), systemd service, 30s poll interval
- **Payment:** Demo stub (real provider TBD)

### Planned Integrations

- Social media APIs (Meta Graph API for Instagram/Facebook, X API)
- WhatsApp Business API
- Payment gateway (Stripe, Mollie, or similar)
- Operator web dashboard (Flask/FastAPI on VPS)
- Production audit trail (SQLite + JSONL, append-only)

---

## 6. Demo Scenario

This works today, live, in production.

Customer sends email:

"Hi, I'd like a sunset cruise tomorrow for 6 people."

System automatically:
1. Reads email (IMAP)
2. Extracts fields (Claude: trip=sunset_cruise, date=tomorrow, guests=6)
3. Validates day-of-week and date (Python)
4. Checks capacity (SQLite)
5. Sends booking summary with price breakdown
6. Customer confirms → creates calendar manifest + payment link
7. Sends confirmation with booking reference (BF-2026-XXXXX)

All without human involvement. Multi-language. Handles follow-ups, changes, multi-trip bookings.

---

## 7. Business Model

You offer this system to businesses.

Pricing example:

| | Range |
|---|---|
| Setup fee | $3,000 – $10,000 |
| Monthly maintenance | $300 – $1,000 / month |

Revenue streams:
- system setup
- monthly maintenance
- upgrades
- custom automation

---

## 8. Long Term Vision

BlueFinn Charters is the first live client.

Target sectors in Curaçao:
- boat charters
- tour companies
- car rentals
- restaurants
- real estate
- hotels

Each business can run on the same agent infrastructure.

Target sectors beyond Curaçao: any business with repetitive customer communication, bookings, or marketing.

You become the company that builds autonomous business systems.

---

## 9. The Real Goal

This is not about one booking bot.

You and Jr are building:

**A platform that replaces small business back-office operations.**

- Customer communication
- Booking management
- Marketing automation

All autonomous. Any business. Any industry.
