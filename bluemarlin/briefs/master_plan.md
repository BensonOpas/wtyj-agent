# BlueMarlin — Master Plan

**Owns:** The product vision — what BlueMarlin is, what it does, who it's for, how it makes money, and the long-term direction. This is the "unthought plan" — the idea in full detail, not the execution timeline.
**Related:** For execution order and milestones → `roadmap.md`. For infrastructure details → `infra.md`. For brief-level history → `system_state.md`.

---

## What BlueMarlin Is

BlueMarlin is an autonomous AI operations platform for businesses. It replaces the back-office staff that handles customer communication, booking/appointment processing, calendar management, payment collection, social media marketing, and content creation. The system runs 24/7 without human intervention.

A business gives us their information — what they sell, their prices, their schedule, their FAQ, their brand voice — and we deploy an AI agent that handles their customer-facing operations end to end. The customer never knows they're talking to AI. The operator sees everything in a dashboard and only intervenes for escalations, complaints, or edge cases.

The platform is not a chatbot. It's not a booking form with a personality. It is a full replacement for a customer service representative and a marketing assistant. The standard is human-quality communication — warm, practical, adaptive to the customer's tone and language. A customer spending real money on a service should never feel like they're talking to a machine.

---

## What It Does For a Client

When a business becomes a BlueMarlin client, they get:

### Customer Communication (all channels)
- **Email:** Agent reads inbound emails, understands intent, replies naturally. Handles booking inquiries, questions, complaints, cancellations, reschedules. Multi-language (English, Dutch, German, Spanish, Portuguese, French). Remembers conversation context across threads.
- **WhatsApp:** Same agent brain, different tone. Short, casual, conversational. Full booking flow — collects details, checks availability, confirms, sends payment link. Real-time via webhook.
- **Instagram/Facebook DMs:** Q&A only (for now). Answers questions about services, pricing, availability. Redirects booking requests to WhatsApp or email where the full booking flow runs.
- **Website form (planned):** A BlueMarlin-hosted booking page. Capacity checks, field collection, confirmation — all feeding into the same system. The third leg of the "booking trilogy" (WhatsApp + Email + Website).

### Booking / Appointment Processing
- Customer expresses interest → agent collects required fields through natural conversation
- System checks real-time availability (capacity per time slot)
- Creates a provisional hold (expires after configurable hours)
- Sends booking summary for customer confirmation
- On confirmation: creates calendar event, generates payment link (if applicable), sends confirmation with reference number
- Handles changes, cancellations, multi-booking conversations, returning customers
- Escalates to human operator when needed (complaints, refunds, edge cases)

### Calendar Management
- Google Calendar integration via service account
- One manifest event per time slot showing all passengers/appointments
- Real-time capacity tracking in SQLite
- Hold expiration enforcement
- Prevents double bookings

### Payment Handling
- Configurable per client: upfront payment link, deposit, pay-at-service, or no payment
- Currently demo stub — real payment provider (Stripe, Mollie) integration planned
- Payment timing driven by client.json config — the system adapts to any business model

### Social Media Marketing
- AI-generated content (captions, hashtags, visual suggestions) using Claude
- Branded graphics engine (Pillow — gradient backgrounds, text overlay, logo, brand colors)
- Publishing to Instagram and Facebook via Zernio/Late SDK (14 platforms supported)
- Content pipeline: generate → review → approve/reject → publish
- Rejection learning: operator feedback trains the system to match brand voice
- Scheduling: posts queue for optimal times
- Dashboard: operator reviews drafts, approves, sees published posts, manages brand training

### Operator Dashboard
- Web-based (React) hosted on Replit, backend API on VPS
- Pages: Overview, Social Media, Messages, Escalations, Create Post, Brand Training, Settings
- Messages: view all conversations across channels (WhatsApp, IG DM, FB DM) with channel badges
- Escalations: reply to semi-escalations (Marina reformulates), compose emails for full escalations
- Content: generate drafts, review, approve/reject, publish, see performance
- Settings: dry run mode, Google Drive photo sync, brand configuration

---

## Who It's For

### Primary target: small-to-medium businesses with repetitive customer communication and appointment/booking workflows.

The sweet spot is businesses where:
- Customers reach out to ask questions and book services
- There's a schedule with limited capacity
- The owner/staff spends hours daily on messages, bookings, and social media
- They don't have budget for a full-time customer service team
- They want a professional online presence but don't have time to maintain it

### Target sectors (proven or near-proven):

**Tourism / Charters / Tours** — The first vertical. BlueFinn Charters Curaçao is the live demo. Boats with departure times, capacity limits, adult/child pricing, seasonal variation. High message volume, multi-language (Caribbean tourism attracts Dutch, German, Spanish speakers).

**Restaurants** — Reservations are time-slotted with party size and table capacity. No payment at booking (usually). Dietary restrictions as special requests. FAQ about menu, hours, parking. Social media for daily specials and ambiance photos.

**Real Estate Agencies** — Property viewings are appointments with agent availability. No payment. Customer provides criteria (beds, budget, area). FAQ about neighborhoods, pricing trends. Social media for new listings.

**Salons / Barbershops** — Appointments per stylist, duration-based slot blocking. Payment at service or deposit. Customer picks service type and preferred stylist. FAQ about products, pricing, walk-ins.

**Fitness / Yoga Studios** — Class sign-ups with instructor and max capacity. Membership or per-class pricing. FAQ about class levels, what to bring. Social media for class schedules and motivation.

**Car / Scooter / Bike Rentals** — Vehicle inventory, pickup/return date ranges. Payment upfront. Customer provides license info, insurance preference. FAQ about fuel policy, damage deposit.

**Dental / Medical Clinics** — Appointments per practitioner. Patient info collection. Insurance questions. FAQ about procedures, preparation, costs.

**Spa / Wellness Centers** — Treatment bookings with therapist and room availability. Duration-based. Deposit or full prepayment. FAQ about treatments, contraindications.

**Photography Studios** — Session bookings. Location/style selection. Deposit at booking. Portfolio FAQ.

**Pet Grooming** — Appointment-based. Pet info (breed, size, temperament). FAQ about products, safety.

**Co-working / Meeting Rooms** — Room bookings with hourly/daily rates. Capacity per room. AV equipment add-ons.

**Driving Schools** — Lesson bookings per instructor per vehicle. Student info. License status.

### What all these share:
1. Customer sends a message expressing interest
2. Agent understands intent and collects required information
3. System checks availability
4. System creates a hold / provisional booking
5. Customer confirms
6. Confirmation sent with reference
7. Calendar event created
8. Operator has visibility

The booking flow is universal. What varies is terminology (trip vs appointment vs reservation), pricing model (upfront vs at-service vs none), capacity model (seats on a boat vs stylist availability vs table covers), and the fields to collect.

---

## How We Make Money

| | Range |
|---|---|
| Setup fee | $3,000 – $10,000 |
| Monthly maintenance | $300 – $1,000 / month |

Revenue streams:
- **System setup** — configure client.json, deploy, test, go live
- **Monthly maintenance** — hosting, monitoring, AI API costs, updates
- **Upgrades** — new channels, new features, custom automation
- **Custom work** — business-specific integrations (POS, PMS, etc.)

The economics work because:
- AI API costs are $5-20/month per client (Claude + optional image generation)
- Zernio is $29/month per client (publishing + DMs)
- VPS hosting is ~$10/month per client (shared infrastructure)
- Total cost per client: ~$50-60/month
- Revenue per client: $300-1,000/month
- Margin: 85-95%

The moat is not the technology — it's the operational knowledge of making AI agents work reliably in production for real businesses, and the client relationships.

---

## Architecture

### The Universal Booking Loop

Every business, regardless of type, follows this flow:

```
Customer Message (any channel)
     |
     v
[Channel Handler] — email_poller / social_agent / dm_agent
     |
     v
[AI Agent] — marina_agent (booking channels) / dm_agent (Q&A channels)
     |── Single Claude call per message
     |── Returns: intent, fields, reply, flags
     |
     v
[Python Orchestrator] — routes on structured output, never parses language
     |
     |── Booking flow → validate → check availability → hold → confirm → calendar → payment
     |── Inquiry → send Claude's reply as-is
     |── Escalation → semi (relay to team) or full (alert operator)
     |── Complaint → empathetic reply + operator notification
     |
     v
[Side Effects]
     |── Google Calendar: event per time slot
     |── Google Sheets: logging (Bookings, Escalations, Events, Manifests)
     |── SQLite: bookings, holds, capacity, dedup, conversation state
     |── Reply: email (SMTP) / WhatsApp (Meta API) / DM (Zernio API)
```

### What's Config-Driven (client.json)

Everything the agent needs to know about the business:
- Business name, contact info, languages, operating hours
- Services (what they sell), with pricing, capacity, schedule
- Service aliases (so customers can say "sunset cruise" or "evening trip" and match the same service)
- FAQ (questions and answers the agent can use)
- Booking rules (required fields, hold duration, group threshold)
- Payment settings (timing, methods, policies)
- Cancellation policy
- Brand voice and content guidelines (for social media)
- Seasonal calendar (for content relevance)

**New client = new client.json = system speaks for that business.** No code changes needed per client.

### Two Agent Types

**Marina (Booking Agent)** — handles email + WhatsApp. Full booking flow with field extraction, availability checking, calendar holds, payment links, escalation routing. Returns structured JSON with intents, fields, confidence, reply, and flags. Heavy prompt with booking schema.

**DM Agent (Q&A Agent)** — handles Instagram/Facebook/X DMs. Answers questions, redirects booking requests to the booking trilogy (WhatsApp + Email + Website). Own Claude call with a simple Q&A prompt. No booking logic, no field extraction, no JSON schema. Returns plain text.

Both agents read the same client.json data. Different prompts, same knowledge base.

### The Booking Trilogy

Three channels can handle full bookings:
1. **WhatsApp** — conversational booking via Meta Cloud API
2. **Email** — booking via Microsoft Outlook (IMAP/SMTP)
3. **Website** (planned) — BlueMarlin-hosted booking form

All three feed into the same system: same availability checks, same calendar, same dashboard, same data. Non-booking channels (IG/FB/X DMs) redirect customers to the trilogy.

The website is a BlueMarlin product — not the client's existing website. This ensures all bookings flow through our system and appear in the dashboard. Generic form driven by client.json (brand colors, service types, fields needed). Works for any business type.

---

## The Generalization Problem

The system was built for a charter company first. Some code assumes charter-specific concepts (trips, departures, vessels, adult/child pricing). Phase 2 (in progress) makes the system business-agnostic:

### What varies between business types

| Dimension | Charter | Restaurant | Salon | Real Estate |
|---|---|---|---|---|
| Service | Trip | Reservation | Treatment | Viewing |
| Party size | Guests | Diners | 1 (always) | 1-2 |
| Time slot | Fixed departures | 15-min windows | Duration-based | Agent availability |
| Resource | Vessel | Table/section | Stylist | Agent |
| Payment | Upfront | None | At service | None |
| Capacity | Seats/boat | Covers/window | 1/stylist | 1/agent |

### The generic config model

The `terminology` section in client.json tells the agent what to call things:
```json
"terminology": {
  "service_label": "trip",        // or "appointment", "reservation", "viewing"
  "party_size_label": "guests",   // or "diners", "attendees", "patients"
  "slot_label": "departure",      // or "time slot", "appointment time"
  "resource_label": "vessel",     // or "stylist", "room", "agent"
  "booking_ref_prefix": "BF"      // or "RS", "SA", or none (random ref)
}
```

The `availability.type` field on each service tells the orchestrator which capacity model to use:
- `slot_capacity` — fixed time slots with max capacity (charters, restaurants, fitness classes)
- `open_window` — any time within operating hours, blocked by duration (salons, clinics)
- `multi_day` — date range bookings (rentals, vacation stays)
- `none` — no availability check, just book it

Payment timing is already config-driven (`payment.timing`: upfront, deposit, at_service, none).

### What's left to generalize (Phase 2)
- Rename trips→services, trip_key→service_key across the codebase
- Add terminology section to client.json
- Make booking summary builder config-driven (reads whatever fields the service has)
- Add availability.type routing (currently only slot_capacity exists)
- Make charter-specific config sections optional (fleet/resources, transfers, dietary)
- Random alphanumeric booking reference (no prefix needed)

---

## The Real Goal

This is not about one booking bot for one charter company.

BlueMarlin is a platform that replaces small business back-office operations:
- Customer communication across all channels
- Booking and appointment management
- Marketing content creation and publishing
- Operator visibility and control

All autonomous. Any business. Any industry. Any language.

The business model scales: each new client is a client.json + deploy. The AI handles the rest. The operator intervenes only when the AI flags something it can't handle.

Every piece of documentation, every conversation log, every decision made in building this system is training data for a future custom LLM fine-tuned specifically for business operations. The archive of briefs, lessons, and system state is intentionally detailed for this purpose.
