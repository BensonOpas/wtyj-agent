# BlueMarlin Dashboard — Full Context for Development

This document contains everything needed to build the operator dashboard for BlueMarlin's autonomous operations system. The backend API is built and deployed. This document covers: what the system does, what data exists, what the API endpoints are, what the dashboard needs to show, and what's planned for the future so the dashboard can be designed to grow.

---

## What BlueMarlin Is

An autonomous AI system that runs a business's operations without human staff. Currently deployed for BlueFinn Charters Curaçao (boat charter company). The system handles:

- **Customer communication** — AI agent (Marina) reads emails and WhatsApp messages, understands what the customer wants, and replies naturally in their language (English, Dutch, German, Spanish, Portuguese)
- **Booking processing** — extracts trip, date, guests from messages, checks calendar capacity, creates holds, sends payment links, confirms bookings with reference numbers
- **Calendar management** — creates manifest events on Google Calendar, tracks capacity per trip per departure slot
- **Social media content** — AI generates Instagram posts, creates branded graphics, publishes via Late API, learns from operator rejection feedback
- **Escalation handling** — detects complaints/refunds, routes to human operator, relays answers back through AI

The first client is BlueFinn Charters Curaçao. The system is designed to be client-agnostic — all business-specific data (trips, prices, FAQ, brand voice, seasonal events) lives in one config file (client.json). Switching clients means swapping that file, not changing code.

The business model: setup fee ($3,000-$10,000) + monthly maintenance ($300-$1,000/month).

---

## What the Dashboard Needs to Do

The dashboard is the operator's window into the system. The operator is a business owner or their staff — non-technical. They need to:

1. See what's happening (bookings today, content pipeline status, system health)
2. Approve or reject AI-generated social media posts before they go live
3. Check trip capacity and availability
4. Manage the AI's learned brand rules
5. Eventually: see booking details, escalation status, WhatsApp conversations, analytics

The dashboard replaces a CLI tool that currently requires SSH access to a server. Everything the CLI does, the dashboard should do through a web interface.

---

## What's Built Right Now

### Backend API (deployed, working)

Base URL: `https://api.wetakeyourjob.com/dashboard/api`

All endpoints require authentication except login. Auth flow:
1. POST `/login` with `{"password": "..."}` → returns `{"token": "abc123..."}`
2. All other requests include header: `Authorization: Bearer abc123...`

### Content Pipeline Endpoints

The social media content pipeline is the most developed part. Here's what it does:

**The flow:**
Claude AI reads the business data (trips, prices, FAQ, fleet, calendar availability, seasonal events) and generates draft social media posts. Each draft has an Instagram caption, Facebook caption, hashtags, a visual suggestion (text describing what image would work), and a reasoning note explaining why this post at this time. A branded graphic (navy gradient background, Inter Bold font, gold accent bar, business name at bottom) is automatically generated from the caption text.

The operator reviews each draft — approves or rejects with a reason. Approved posts are published to Instagram via Late API (a social media publishing service). The system stores every rejection reason and periodically analyzes them to learn brand rules ("never use urgency language", "keep sunset posts about the experience not the price"). These rules are fed back into future content generation.

**Draft states:** pending → approved → published (or pending → rejected). Published posts can be deleted (removed from Instagram, marked as "deleted" in DB).

**Content classes:**
- Class A — Evergreen brand content (experience highlights, tips, destination facts)
- Class B — Commercial (promotions, low-booking support, availability pushes)
- Class C — Operational (sold-out redirects, weather, schedule changes)
- Class D — Reactive (holidays, local events, timely content)

**Endpoints:**

```
POST /login
  Body: {"password": "..."}
  Response: {"token": "..."}

GET /status
  Response: {
    "pending": 3,
    "approved": 1,
    "rejected": 2,
    "published": 6,
    "deleted": 0,
    "learnings": 2,
    "season": "Season: Low season — awareness building, occupancy support\nNo events in the next 30 days."
  }

GET /drafts
  Query params: ?status=pending&limit=20 (both optional)
  Response: [
    {
      "id": 7,
      "content_class": "A",
      "instagram_caption": "Crystal-clear waters and white sand...",
      "facebook_caption": "There's a small uninhabited island...",
      "hashtags": ["#KleinCuracao", "#BlueFinnCharters"],
      "visual_suggestion": "aerial shot of Klein Curaçao beach",
      "reasoning": "Class A evergreen — showcases flagship experience",
      "status": "pending",
      "rejection_reason": "",
      "created_at": "2026-03-16T22:00:00+00:00",
      "approved_at": null,
      "published_at": null,
      "image_path": "/root/bluemarlin/data/graphics/draft_7.jpg",
      "late_post_id": "",
      "instagram_url": ""
    }
  ]

GET /drafts/{id}
  Response: single draft object (same shape as above)

POST /drafts/generate
  Body: {"count": 3}
  Response: {"drafts": [...], "count": 3}
  Note: This calls Claude AI — takes 5-10 seconds. Show a loading state.

POST /drafts/{id}/approve
  Response: {"ok": true}

POST /drafts/{id}/reject
  Body: {"reason": "too salesy"}
  Response: {"ok": true}

POST /drafts/{id}/publish
  Response: {"ok": true, "post_url": "https://instagram.com/p/..."}
  Note: Uploads image + publishes to Instagram — takes 10-20 seconds. Show loading.

POST /drafts/{id}/graphics
  Response: {"ok": true, "image_path": "/path/to/draft_7.jpg"}
  Note: Generates the branded graphic image for a draft.

DELETE /drafts/{id}
  Response: {"ok": true}
  Note: Deletes a published post from Instagram. Only works on published drafts.

GET /drafts/{id}/image
  Response: JPEG file (the branded graphic)
  Content-Type: image/jpeg
  Note: Use this URL as an <img> src to display the graphic preview.
```

### Brand Learnings Endpoints

```
GET /learnings
  Response: [
    {
      "id": 1,
      "rule": "Never use urgency language like 'last spots' or 'don't miss out'",
      "source_draft_ids": [3, 5, 8],
      "created_at": "2026-03-16T23:00:00+00:00"
    }
  ]

POST /learnings/distill
  Response: {"learnings": [...], "count": 2}
  Note: Analyzes all rejected drafts, finds patterns, saves new rules. Calls Claude — takes 5-10 seconds.

DELETE /learnings/{id}
  Response: {"ok": true}
  Note: Deactivates a learning rule (it stops influencing future generation).
```

### Data Endpoints

```
GET /availability?days=7
  Response: [
    {
      "trip_key": "klein_curacao",
      "date": "2026-03-17",
      "departure_time": "08:00",
      "booked_guests": 12,
      "capacity": 30,
      "spots_remaining": 18
    },
    ...
  ]
  Note: Returns every trip slot for the next N days with booking counts.

GET /config
  Response: {"context": "=== BUSINESS ===\n{...}\n\n=== TRIPS ===\n{...}\n..."}
  Note: Full business configuration as formatted text. Read-only.
```

### Error Responses

All errors return JSON with an HTTP status code:
```
401: {"detail": "Missing token"} or {"detail": "Invalid token"} or {"detail": "Wrong password"}
404: {"detail": "Draft not found"}
400: {"detail": "Draft must be approved before publishing"}
500: {"detail": "Publish failed"} or {"detail": "Image upload failed"}
```

---

## The Business Data (client.json)

The system's knowledge comes from one config file. Here's what the dashboard has access to (via GET /config):

**Business info:** BlueFinn Charters Curaçao, email, phone, WhatsApp number, location, supported languages (English, Dutch, German, Spanish, Portuguese)

**5 trips:**
- Klein Curaçao Trip — $120/adult, $65/child, daily, 2 departures (08:00 BlueFinn2, 08:30 BlueFinn1), 8 hours, capacity 30
- 3-in-1 Snorkeling Trip — $110/adult, Fridays only, 4 hours, capacity 20
- West Coast Beach Trip — $120/adult, Wed + Sun, 6 hours, capacity 25
- Sunset Cruise — $79/adult, Tue/Thu/Fri/Sat, 2.5 hours, capacity 20
- Jet Ski Excursion — $135/adult, daily, 1 hour, capacity 4, hourly slots 08:00-19:00

**Fleet:** BlueFinn 1 (75ft catamaran), BlueFinn 2 (80ft catamaran), Kailani (42ft motor yacht), Red Dragon (50ft catamaran), TopCat (sailing catamaran)

**FAQ:** 25+ answers covering what to bring, dietary needs, alcohol policy, children, seasickness, turtles, dolphins, snorkel gear, transfers, payment methods

**Seasonal calendar:** High season Dec-Apr, Low season May-Nov. Events: New Year's, Carnival (45 days starting Feb 1), King's Day (Apr 27), Dia di Rincon (Apr 30), Labour Day, Flag Day (Jul 2), Curaçao Day (Oct 10), Christmas/New Year week

**Social content config:** Brand voice (premium, confident, clear, aspirational), platforms (Instagram primary, Facebook secondary), posting frequency (3-5/week), content boundaries (never competitors, politics, religion), default CTA, hashtag style, emoji style

**Brand graphics config:** Primary color [27, 58, 92] (navy), gradient bottom [15, 30, 50] (darker navy), text color white, accent color [212, 168, 83] (gold), font: Inter Bold

---

## Dashboard Pages — What Each Should Show

### 1. Overview / Home
- Status cards: Pending, Approved, Published, Rejected counts (from GET /status)
- Current season text (from GET /status → season field)
- Recent published posts (GET /drafts?status=published&limit=5) — show image thumbnail + caption preview + Instagram link
- Quick action buttons: Generate New Drafts, Review Pending

### 2. Content Pipeline
- Table of all drafts (GET /drafts)
- Filterable by status (pending/approved/rejected/published/deleted)
- Sortable by date
- Content class shown as colored badge (A=blue, B=green, C=orange, D=purple)
- Status as colored badge (pending=yellow, approved=green, rejected=red, published=blue, deleted=gray)
- Click a row to open detail panel:
  - Full Instagram caption
  - Full Facebook caption
  - Hashtags as tags
  - Visual suggestion text
  - Reasoning text
  - Generated graphic image (GET /drafts/{id}/image)
  - Action buttons: Approve (green), Reject (red → opens reason input), Publish (blue), Generate Graphic
- "Generate Drafts" button at top → count selector → calls POST /drafts/generate → shows loading → refreshes table

### 3. Published Posts
- Grid of cards, each showing:
  - Generated graphic thumbnail (GET /drafts/{id}/image)
  - Caption preview (first 100 chars)
  - Instagram link (clickable, opens in new tab)
  - Publish date
  - Delete button (red, confirms before calling DELETE /drafts/{id})

### 4. Brand Learnings
- List of active rules as cards (GET /learnings)
- Each card shows the rule text + created date
- Deactivate button per card (DELETE /learnings/{id})
- "Distill New Learnings" button at top → calls POST /learnings/distill → shows loading → refreshes list
- Could show rejection history below (GET /drafts?status=rejected)

### 5. Capacity Checker
- Table of trip availability (GET /availability?days=7)
- Columns: Trip Name, Date, Day of Week, Departure Time, Spots Remaining, Total Capacity
- Color coding per row: green (>50%), yellow (25-50%), red (<25%), black/dark (0 spots)
- Days selector (3, 7, 14 days)
- Group by trip or by date toggle

### 6. Settings
- Business info displayed as clean cards (name, email, phone, location, languages)
- Trip info as expandable cards (name, price, schedule, capacity, included items)
- Seasonal calendar as a visual timeline or list
- Brand colors shown as swatches
- All read-only for now — editing comes later

---

## Design Direction

**From the client's operating brief (SR wrote this):**

The dashboard must feel premium, polished, intentional. It represents the product — this is what we demo to prospective clients. Dark mode. Clean. No clutter. Every element should feel purposeful.

**Color scheme:**
- Background: dark navy (#1B3A5C fading to #0F1E32)
- Text: white (#FFFFFF)
- Accent: gold (#D4A853)
- Status colors: green (approved/available), yellow (pending/partial), red (rejected/low), blue (published)

**Tech stack decided:** React + Tailwind + shadcn/ui. Sidebar navigation.

---

## Dashboard Feature Status

### Built and live:
- **Overview page** — status cards, season, recent posts
- **Content pipeline** — generate, review, approve/reject, publish, delete
- **Messages page** — WhatsApp + IG/FB DM conversations (all channels)
- **Escalation center** — pending escalations, semi-escalation relay, operator reply, email compose
- **Brand training** — rejection learnings, distill rules
- **Capacity checker** — availability by service/date
- **Photo library** — upload, browse, tag, Google Drive sync
- **Settings** — dry run toggle, config view
- **Suggest reply** — Claude-powered email drafting for escalations

### Not yet built:
- **Booking management** — today's bookings list, search by ref/name, payment status
- **Channel badges** — DMs show in messages but no IG/FB/WA icons (Brief 132)
- **Analytics** — post performance (blocked by Late $29/mo), booking analytics, system health
- **Multi-client view** — client switcher for when we have multiple clients

---

## Deployment

**Current infrastructure:**
- VPS: Ubuntu at 108.61.192.52
- Domain: api.wetakeyourjob.com (SSL via Let's Encrypt)
- nginx reverse proxy → FastAPI on port 8001
- Dashboard frontend hosted on Replit: bluemarlindashboard.replit.app
- Two systemd services: `bluemarlin` (email poller) + `bluemarlin-social` (webhook server + dashboard API)

---

## Key Principle

The dashboard is not just for BlueFinn. It's a product feature sold to every client. Design it so the business name, colors, and data change per client — but the dashboard itself stays the same. Think of it as a white-label operator panel. The gold accent and navy colors are BlueFinn's brand — another client might have different colors. The sidebar, layout, and functionality should work regardless of which business is using it.
