# SNAPSHOT_PRE_GWS — System State Before GWS Integration
# Git tag: v0.31-pre-gws
# Captured after Brief 031. All briefs 001–031 executed and stable.

---

## RESTORATION

To restore all source files to this exact state:

```
git checkout v0.31-pre-gws
```

This restores the full state of bluemarlin/src/ and bluemarlin/config/
as of Brief 031, before any Google Workspace (GWS) integration work begins.

---

## FILE INVENTORY — bluemarlin/src/

All files listed with last-modified brief and line count.
Line counts from wc -l (actual file state on disk at snapshot time).

| File | Last Modified | Lines | Notes |
|------|--------------|-------|-------|
| email_poller.py | Brief 031 | 524 | Core orchestrator. IMAP poll → marina_agent → calendar → sheets → SMTP. |
| marina_agent.py | Brief 031 | 237 | Single Claude call per message. Returns 8-field structured JSON. |
| calendar.js | Brief 031 | 133 | Google Calendar via googleapis. Two commands: createHold, checkAvailability. |
| config_loader.py | Brief 022 | 93 | Read-only interface to client.json. Caches on first read. Never raises. |
| sheets_writer.py | Brief 028 | 160 | Google Sheets logging. Tabs: Bookings, Escalations, All Events. |
| marina_extractor.py | Brief 018 | 76 | Legacy field extractor (unused since Brief 024). Kept for reference. |
| claude_client.py | Brief 001 | 43 | Thin Anthropic API wrapper (unused since Brief 023). Kept for reference. |
| state_registry.py | Brief 004 | 57 | SQLite WAL deduplication. has_been_processed / mark_as_processed. |
| bm_logger.py | Original | 28 | Structured event logger. |
| social_drafter.py | Brief 003 | 45 | Draft social posts via claude_client. Separate from booking flow. |
| social_registry.py | Original | 94 | Social post registry. Separate from booking flow. |
| approve_post.py | Original | 26 | Social post approval. Separate from booking flow. |
| post_executor.py | Original | 57 | Social post execution. Separate from booking flow. |
| format_sheets.py | Original | 309 | Sheets formatting utilities. |
| payment_stub.py | Original | 57 | Payment stub. generate_payment_link returns demo URL. |
| state_registry.db | Brief 004 | — | SQLite database. Not a text file. |

---

## bluemarlin/config/client.json — FULL CONTENTS

```json
{
  "business": {
    "name": "BlueFinn Charters Curaçao",
    "email": "info@bluefinncharters.com",
    "phone": "+599 9690 3717",
    "whatsapp": "+599 9690 3717",
    "location": "Jan Thiel Beach, z/n, Willemstad, Curaçao",
    "languages": [
      "English",
      "Dutch",
      "German",
      "Spanish",
      "Portuguese"
    ],
    "operating_days": "7 days a week",
    "agent_name": "Marina",
    "agent_signature": "Marina\nBlueFinn Charters Curaçao"
  },
  "payment": {
    "methods": [
      "Credit card",
      "iDeal",
      "Apple Pay",
      "Google Pay",
      "Amex"
    ],
    "cash_policy": "Cash accepted at office only, minimum 24 hours in advance",
    "no_payment_at_boarding": true,
    "hold_duration_hours": 6
  },
  "booking_rules": {
    "advance_booking_typical_days": "4-7",
    "group_threshold_requires_human": 15,
    "required_fields": [
      "experience",
      "date",
      "guests"
    ],
    "extras_fields": [
      "customer_name",
      "phone"
    ],
    "transfers_available": true,
    "transfers_advance_notice_hours": 24,
    "dietary_advance_notice_days": 1
  },
  "cancellation_policy": {
    "summary": "[VERIFY: exact terms from bluefinncharters.com/cancellation-policy — page was inaccessible during research]",
    "full_refund_before_hours": "[VERIFY]"
  },
  "private_charters": {
    "available": true,
    "pricing": "[VERIFY: not published — contact BlueFinn directly]",
    "contact_for_booking": "info@bluefinncharters.com"
  },
  "trips": {
    "klein_curacao": {
      "display_name": "Klein Curaçao Trip",
      "price_adult_usd": 120,
      "price_child_usd": 65,
      "price_child_age_range": "4-12",
      "price_under_4": "free",
      "departures": [
        {
          "time": "08:00",
          "vessel": "BlueFinn2",
          "departure_point": "Jan Thiel Beach"
        },
        {
          "time": "08:30",
          "vessel": "BlueFinn1",
          "departure_point": "Jan Thiel Beach"
        }
      ],
      "duration_hours": 8,
      "returns_approx": "17:00",
      "days_available": "daily",
      "included": [
        "BBQ lunch",
        "premium open bar from lunch",
        "snorkel gear",
        "snorkel masks and pipe"
      ],
      "not_included": [
        "flippers"
      ],
      "notes": "Turtles very likely near Klein Curaçao. Cannot pet turtles — protected by law. Dolphins possible while sailing.",
      "calendar_id": "ed9e5c8b2357d2e21b99af2617c58836204443ed7e8d7352661426cca41cf4cb@group.calendar.google.com"
    },
    "snorkeling_3in1": {
      "display_name": "3-in-1 Snorkeling Trip",
      "price_adult_usd": 110,
      "departures": [
        {
          "time": "10:00",
          "vessel": "[VERIFY]",
          "departure_point": "Mood Beach pier"
        }
      ],
      "duration_hours": "[VERIFY]",
      "days_available": "Fridays only",
      "included": [
        "lunch",
        "3 snorkel sites"
      ],
      "snorkel_sites": [
        "Tugboat Saba wreck (open ocean)",
        "Tugboat Caracasbaai",
        "Caracasbaai pier"
      ],
      "requirements": "Good swimming skills required",
      "suitable_for_children": false,
      "calendar_id": "649576fb0d0eb17fc895981db2f5e2339ac045edf3a4292d40eff57786fa06db@group.calendar.google.com"
    },
    "west_coast_beach": {
      "display_name": "West Coast Beach Trip",
      "price_adult_usd": 120,
      "departures": [
        {
          "time": "09:00",
          "vessel": "[VERIFY]",
          "departure_point": "Mood/Tomatoes"
        }
      ],
      "duration_hours": 6,
      "days_available": "Wednesdays and Sundays",
      "included": [
        "open bar",
        "snorkel gear"
      ],
      "calendar_id": "a85ac414af5903971715705bb8f0975a0be07ca637017c1184f1ba7cd4ab1c00@group.calendar.google.com"
    },
    "sunset_cruise": {
      "display_name": "Sunset Cruise",
      "price_adult_usd": 79,
      "departures": [
        {
          "time": "17:30",
          "vessel": "[VERIFY]",
          "departure_point": "Village Marina/Mood pier"
        }
      ],
      "duration_hours": 2.5,
      "days_available": "Tuesday, Thursday, Friday, Saturday",
      "included": [
        "open bar (beer, wine, cocktails)",
        "snacks"
      ],
      "snacks": [
        "pineapple",
        "mozzarella-tomato-pesto sticks",
        "chicken satay",
        "pulled pork sandwich"
      ],
      "calendar_id": "a3df969d58e35c9603fe6ae6672446ec2f430ed3304f9c5aaf2178391e67defe@group.calendar.google.com"
    },
    "jet_ski": {
      "display_name": "Jet Ski Excursion",
      "price_adult_usd": 135,
      "departures": [
        {
          "time": "every hour",
          "vessel": "Jet ski",
          "departure_point": "Spanish Water"
        },
        {
          "time": "every hour",
          "vessel": "Jet ski",
          "departure_point": "Piscadera Bay"
        }
      ],
      "days_available": "daily",
      "calendar_id": "903f29c1161ed6d1378b7d4b1f7ef0597ce6707e2648fd98b82b081542919f08@group.calendar.google.com"
    }
  },
  "fleet": {
    "bluefinn1": {
      "display_name": "BlueFinn 1 (B&W)",
      "type": "sailing catamaran",
      "length_ft": 75,
      "max_guests": 65
    },
    "bluefinn2": {
      "display_name": "BlueFinn 2 (Apache)",
      "type": "sailing catamaran",
      "length_ft": 80,
      "max_guests": 95
    },
    "kailani": {
      "display_name": "Kailani",
      "type": "motor yacht",
      "length_ft": 42,
      "max_guests": 20,
      "speed_knots": 15,
      "scuba_equipped": true
    },
    "red_dragon": {
      "display_name": "Red Dragon",
      "type": "catamaran",
      "length_ft": 50,
      "max_guests": 40
    },
    "topcat": {
      "display_name": "TopCat",
      "type": "sailing catamaran",
      "max_guests": 30
    }
  },
  "faq": {
    "what_to_bring": "Towel, sunscreen, hat, sunglasses. Seasickness pill if you are prone.",
    "extra_costs": "No extra costs. Everything is included. Tips appreciated but not required.",
    "transfers": "Available via booking form. Guaranteed with 24 hours advance notice. Within 24 hours on request.",
    "dietary": "Vegetarian and other dietary needs accommodated if communicated at least 1 day in advance via the booking form.",
    "alcohol_policy": "Premium open bar from lunch. No alcohol served to guests under 18. ID may be requested.",
    "seasickness": "Best seat is at the back of the boat, outside, facing the horizon. Drink water. Avoid going to the toilet. Take a pill in advance. Crew will help.",
    "children": "All trips suitable for children except the 3-in-1 Snorkeling Trip, which requires good swimming skills in open sea.",
    "dolphins": "Dolphins are possible while sailing to Klein Curaçao.",
    "turtles": "Turtles are very likely near Klein Curaçao. You cannot pet them — they are protected by law.",
    "toilets": "Catamarans have 2 marine toilets. Kailani has 1. No toilets on Klein Curaçao island.",
    "swimming_ability": "Being comfortable in water is recommended. Life jackets and noodles are available. Guests can take the dinghy to the beach instead of swimming.",
    "scuba_diving": "Kailani is equipped for scuba. You can also join a 1-tank dive on BlueFinn1 for the Klein Curaçao trip. Contact Scuba Do separately: info@divecenterscubado.com",
    "local_student_rate": "Available via WhatsApp. Valid local ID or internship agreement required.",
    "private_charters": "Yes, private charters are available. Contact info@bluefinncharters.com for availability and pricing.",
    "sustainability": "BlueFinn uses reusable cups, solar panels, and a can pressing system.",
    "ride_duration_klein_curacao": "Approximately 1 hour 45 minutes by catamaran, approximately 1 hour 15 minutes by Kailani. Depends on weather.",
    "snorkel_gear_included": "Snorkel masks and pipe included. Flippers are not included.",
    "no_payment_at_boarding": "No payment is accepted at boarding. Payment must be completed in advance.",
    "cash_payment": "Cash is accepted at the office only, minimum 24 hours before the trip.",
    "booking_in_advance": "Booking fills up 4 to 7 days in advance on average. Book early to secure your spot.",
    "group_bookings": "For groups of 15 or more, contact the team directly for tailored arrangements.",
    "special_requests": "Special requests and dietary needs should be communicated via the booking form at least 1 day in advance.",
    "what_is_included": "All shared trips include the items listed per trip. No hidden costs.",
    "age_child_pricing": "Child pricing applies to guests aged 4 to 12. Children under 4 are free.",
    "klein_curacao_what_is_it": "Klein Curaçao is a small uninhabited island southeast of Curaçao, known for its white sand beach, lighthouse, and clear water.",
    "can_i_snorkel": "Yes. Snorkel masks and pipe are provided on all trips that include snorkeling.",
    "is_there_shade": "[VERIFY: not confirmed during research]",
    "what_if_seasick": "The crew will help. Best seat is at the back of the boat outside facing the horizon. Take a pill before departure if you are prone."
  },
  "common_sense_knowledge": {
    "curacao_timezone": "America/Curacao (UTC-4, no DST)",
    "currency": "USD for pricing. Local currency is ANG (Netherlands Antillean guilder).",
    "weather_season": "Curaçao is outside the hurricane belt. Dry season December to April. Wet season May to November. Generally sunny year-round.",
    "dress_code": "Casual beach attire. Swimwear appropriate.",
    "marina_persona": "Marina is warm, helpful, knowledgeable, and enthusiastic about the ocean. She never guesses — if she does not know something she says so and offers to follow up."
  }
}
```

---

## SYSTEM STATUS AS OF BRIEF 031

### WORKING (tested, stable)

**Core booking flow (end-to-end):**
- IMAP polling (Microsoft OAuth2 / XOAUTH2) — fetches UNSEEN, deduplicates via SHA256 + SQLite WAL
- marina_agent unified Claude call — one API call per message, returns structured JSON (8 fields), never raises
- Multi-turn field accumulation — fields merged across thread messages, non-empty values not overwritten
- Flag persistence — awaiting_booking_confirmation, booking_confirmed, hold_created, slot_checked, slot_available, event_id, event_link, payment_id, payment_link, payment_status, booking_ref
- Booking confirmation step — Marina sends summary, asks "Shall I lock this in?", hold only created after customer confirms
- Availability pre-check — calendar checked before summary sent; customer receives apology reply if slot taken
- Calendar hold creation — Google Calendar API via calendar.js subprocess, all five BlueFinn trip calendars configured with real IDs
- Hold failure handling — reply_hold_failed sent instead of false confirmation
- [PAYMENT_LINK] injection — placeholder replaced with real payment URL at send time
- Booking reference generation — format BF-YYYY-XXXXX, stored in thread flags and Sheets
- Google Sheets logging — Bookings tab (15 columns), Escalations tab (6 columns), All Events tab
- Escalation routing — complaints and cancellations set requires_human, route to log_escalation, Marina replies warmly with "The Crew will be in touch"
- Anti-loop guard — max 10 replies per thread per 60-minute window
- SMTP reply (Microsoft OAuth2) — threaded replies with In-Reply-To / References headers
- Vague date enforcement — Marina asks for specific date rather than guessing
- Departure time extraction — Marina extracts customer-chosen departure, falls back to first departure from config

**Configuration:**
- client.json — single source of truth for all business data, injected into prompt at call time
- config_loader.py — caches on first read, never raises, [VERIFY] filtering in _filter_verify()
- All five Google Calendar IDs injected (Brief 026)

### KNOWN BROKEN / NOT YET LIVE

**Manual actions required before live use:**
- Escalations tab must be created in Google Sheet before first escalation is logged
  (SPREADSHEET_ID: 1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE)
- Service account bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com must be
  shared on each of the five BlueFinn Google Calendars with "Make changes to events" access

**[VERIFY] items outstanding in client.json:**
- cancellation_policy.summary — exact terms not confirmed
- cancellation_policy.full_refund_before_hours — not confirmed
- private_charters.pricing — not published
- snorkeling_3in1 vessel name — not confirmed
- snorkeling_3in1 duration_hours — placeholder (4hrs used in calendar.js DURATIONS_HOURS)
- west_coast_beach vessel name — not confirmed
- sunset_cruise vessel name — not confirmed
- faq.is_there_shade — not confirmed

**payment_stub.py:**
- Generates demo payment links (https://demo.pay/bluemarlin/...) — not connected to a real payment processor
- A real payment integration brief is required before go-live

**Same-day booking edge case:**
- Past-date guard in create_calendar_hold uses UTC date comparison on VPS
- Valid same-day Curaçao booking in the 4-hour window before UTC midnight (20:00–00:00 Curaçao time) may be incorrectly rejected
- Accepted for demo system; fix required before full go-live

**slot_checked flag not reset on date change:**
- If a customer changes their date after slot_checked is set, the availability check will not re-run
- The hold trigger will correctly fail (booking_confirmed not set) but the UX will be slightly inconsistent
- Deferred — low probability in practice

### UNBUILT

- Real payment processor integration (Stripe or equivalent) — payment_stub is a placeholder
- GWS integration — Gmail, Google Sheets, and Google Calendar read-back via GWS CLI skills (planned next)
- Webhook / push notification alternative to IMAP polling
- Admin dashboard / operator view beyond Google Sheets
- Automated capacity management (max_guests enforcement per trip)
- Child pricing logic — client.json has price_child_usd but marina_agent does not extract child counts
- Social posting pipeline — social_drafter.py, approve_post.py, post_executor.py exist from original codebase but are not integrated into the booking flow and have not been tested in the current architecture
- Cancellation processing — Marina escalates correctly but there is no cancel_hold function in calendar.js to delete events
- Hold expiry — 6-hour hold duration is communicated to customer but there is no automated expiry job to delete unpaid holds from the calendar
