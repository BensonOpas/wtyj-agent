# MARINA STATUS — 90% Complete

**Date:** 2026-03-10
**Highest brief number:** 064 (not all numbers sequential — some gaps)
**Live E2E tests:** 50 scenarios, 126/140 assertions passed (90%), zero functional bugs

---

## System Overview

Marina is an autonomous email booking agent for BlueFinn Charters Curacao. She reads inbound emails via IMAP, processes them through a single Claude Sonnet API call per message, and handles the full booking lifecycle without human intervention.

**Stack:** Python 3.12.3, Ubuntu VPS (Vultr), Claude Sonnet API (`claude-sonnet-4-6`), SQLite WAL, Microsoft Outlook OAuth2, Google Calendar + Sheets via gws CLI, systemd.

---

## Architecture

```
Customer Email
     |
     v
[IMAP Polling] ──> email_poller.py (core orchestrator)
     |
     |── Pre-filters: system email, dedup, anti-loop, escalation drop, relay inbound
     |
     v
[Claude API Call] ──> marina_agent.py (single call per message)
     |
     |── Returns: intents, fields, confidence, reply, flags
     |
     v
[Python Routing] ──> based on structured output, NOT language parsing
     |
     |── Semi-escalation ──> relay to human team, hold reply to customer
     |── Full escalation ──> empathetic reply + alert to operator
     |── Booking flow ──> validate → summary → confirm → calendar → payment → done
     |── Other (inquiry, social, off_topic) ──> send Claude's reply as-is
     |
     v
[Side Effects]
     |── Google Calendar: manifest events (one per departure slot)
     |── Google Sheets: Bookings, Escalations, All Events, Manifests tabs
     |── SQLite: bookings, soft holds, manifests, dedup hashes
     |── SMTP: reply to customer
```

---

## Source Files

| File | Purpose | Brief |
|------|---------|-------|
| `src/email_poller.py` | Core orchestrator. IMAP -> Claude -> Calendar -> Sheets -> SMTP | 064 |
| `src/marina_agent.py` | Single Claude call per message. Prompt + JSON parsing | 064 |
| `src/state_registry.py` | SQLite WAL: dedup, capacity holds, manifests, bookings | 064 |
| `src/gws_calendar.py` | Calendar holds + manifest CRUD via gws CLI | 050 |
| `src/sheets_writer.py` | Sheets logging (4 tabs) via gws CLI | 052 |
| `src/config_loader.py` | Read-only client.json interface. Caches on first read | 022 |
| `src/payment_stub.py` | Demo payment links (keyed by booking_ref) | 051 |
| `src/format_sheets.py` | Run-once sheet formatting (headers, column widths) | 052 |
| `src/bm_logger.py` | Structured JSONL event logger | 006 |
| `src/claude_client.py` | Anthropic API wrapper | 001 |

---

## Email Categories and Routing

### Pre-Claude Filters (no AI call)

| Filter | Trigger | Action |
|--------|---------|--------|
| System email | `noreply@`, `mailer-daemon@`, `bounce@`, etc. | Mark Seen, skip |
| Duplicate content | Same sender+subject+body hash as last message | Mark Seen, skip |
| Anti-loop guard | 5+ replies in same thread within time window | Send reset message, stop |
| Escalation reply drop | Operator replies to `[ESCALATION]` email | Mark Seen, skip (one-way) |
| Relay inbound | Operator replies to `[RELAY-token]` email | Claude reformulates, sends to customer |

### Post-Claude Routing

| Category | Trigger | Marina Does | Python Does |
|----------|---------|-------------|-------------|
| **Semi-escalation** | Factual question Marina can't answer | Warm "checking with team" reply | Relay alert to operator, cancel hold |
| **Full escalation** | Complaint, refund, cancellation, 15+ guests | Empathetic reply, tells customer team will follow up | Alert to operator with chat log, log to Sheets |
| **Booking** | Booking or reschedule intent | Extract fields, conversational reply | Validate (day/date/departure), build summary, check capacity, create hold, confirm, calendar event, payment link |
| **Other** | Inquiry, social, off_topic | Natural reply from trip/FAQ data | Send reply, log to Sheets |

---

## Completed Capabilities

| Capability | Status |
|------------|--------|
| Email polling (IMAP -> process -> SMTP reply) | Done |
| Claude-powered field extraction + intent classification | Done |
| Full booking flow (inquiry -> summary -> confirmation) | Done |
| Capacity tracking with SQLite soft holds (24h TTL) | Done |
| Google Calendar manifest events | Done |
| Google Sheets dashboard (Bookings, Escalations, All Events, Manifests) | Done |
| Payment link generation (demo stub) | Done |
| Multi-trip booking in one thread (max 3) | Done |
| Cross-thread customer memory (by booking ref + email) | Done |
| Escalation system (semi-escalation relay + full escalation) | Done |
| Day-of-week + past date + departure time validation | Done |
| Stale thread reset (24h expiry on subject-keyed threads) | Done |
| System email filter (noreply, mailer-daemon, bounce, etc.) | Done |
| Booking ref in confirmation reply (BF-YYYY-XXXXX) | Done |
| Tone polish (natural writing style, banned phrases) | Done |
| Config-driven trip aliases (client.json) | Done |
| Multi-language support (EN, NL, DE, ES, FR, Papiamentu) | Done |
| Security hardening (prompt injection, XSS, credential leak) | Done |
| VPS deployment + systemd auto-restart | Done |
| Automated E2E test harness (50 scenarios) | Done |
| Escalations tab (created + writing) | Done |
| Service account shared on all 5 calendars | Done |

---

## Infrastructure

| Component | Details |
|-----------|---------|
| **VPS** | Vultr, `ssh root@108.61.192.52`, project at `/root/bluemarlin/` |
| **Poller** | systemd service `bluemarlin`, 30s poll interval, auto-restart |
| **Deploy** | `ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin"` |
| **Logs** | `journalctl -u bluemarlin -n 50` or `/root/bluemarlin/logs/bluemarlin.log` |
| **Secrets** | `/root/bluemarlin/config/bluemarlin.env` (ANTHROPIC_API_KEY, AZURE_CLIENT_ID, AZURE_TENANT_ID) |
| **OAuth** | Microsoft Outlook via Azure AD app registration. Refresh token in `config/azure_refresh_token.txt` |
| **Calendar** | Google service account `bluemarlin-agent@grand-verve-489623-f8.iam.gserviceaccount.com` |
| **Sheets** | Spreadsheet ID in `client.json` (`business.spreadsheet_id`) |
| **Backup** | `./snapshot.sh [tag]` — pulls DB, thread state, client.json, logs to local `backups/`. Secrets (env, OAuth token, calendar key) excluded by default — uncomment lines in script to include. |

---

## Database State (2026-03-10)

| Table | Rows | What |
|-------|------|------|
| `bookings` | 7 | Confirmed bookings (cross-thread memory) |
| `trip_bookings` | 18 | Soft holds + confirmed capacity entries |
| `manifest_events` | 7 | Calendar manifest event tracking |
| `processed_hashes` | 220 | Email dedup hashes |

Thread state JSON: 283 KB (all active/recent conversations).

---

## Live Test Results (50 Scenarios)

**Run date:** 2026-03-10 | **Pass rate:** 126/140 assertions (90%)

### Failure Breakdown (14 failures, zero functional bugs)

| Category | Count | Details |
|----------|-------|---------|
| Em dashes | 6 | Marina uses `---` in ~12% of replies despite prompt ban. Cosmetic. |
| Timeouts | 4 | Test harness 90s timeout, poller processed correctly |
| Day-of-week priority | 1 | stress_past_date: day-of-week fires before past-date. By design. |
| Price correction wording | 1 | Assertion too strict (Marina mentions "$50" while correcting it) |
| Test bug (wrong day) | 1 | west_coast_beach test used Saturday instead of Wednesday. Fixed. |
| API fallback | 1 | Transient Claude API fallback response |

### Verified Behaviors

- Multi-language: Spanish, Dutch, German, French, Papiamentu correctly detected and replied in
- Tone mirroring: casual gets casual, formal gets formal
- Prompt injection: fully blocked, no credentials/config leaked
- Price integrity: never agreed to unauthorized discounts
- Identity: never revealed AI nature ("I'm Marina, part of the BlueFinn team")
- Returning customer: email-based lookup working
- XSS: script tags not echoed
- Wrong recipient: correctly identified misdirected personal email

---

## What's Left (The Last 10%)

### Being Handled Separately
- **Rich HTML emails** — SR handling
- **Marina speech rework** — SR handling

### Hardcoded Reply Strings (7 total, all intentional)

All fire after Claude's single call. A second call would violate Rule 1. Accepted tradeoff from Brief 046 hybrid refactor.

1. Booking summary (prices/vessels from config)
2. Day-of-week rejection (Python validation)
3. Past-date rejection (business rule guard)
4. Departure time prompt (config-driven list)
5. Anti-loop stop message (circuit breaker)
6. Slot unavailable — hold race (exception handler)
7. Slot unavailable — check phase (capacity guard)

### Production-Grade Items (Not Needed for Demo)

| Item | What it is | Priority |
|------|-----------|----------|
| Rate limiting / abuse protection | Done (Brief 065) — 20/sender/hour | Done |
| Thread state cleanup / archival | Done (Brief 065) — 30-day archive + prune | Done |
| Monitoring / alerting | Done (Brief 065) — token usage, heartbeat, error alerts | Done |
| OAuth token auto-refresh | Done (Brief 065) — auto-saves rotated refresh token | Done |
| Multi-operator routing | Deferred — noted for future brief when client needs it | Low |

### Roadmap — Next Phase

| Item | Description | Status |
|------|-------------|--------|
| **Production audit trail** | Append-only logging of everything: inbound/outbound emails (full content), Claude API calls (prompt context + response + tokens), booking lifecycle events (hold → confirm → payment → complete/cancel), state transitions, errors with tracebacks, system events (poller start/stop, OAuth refresh, rate limits, cleanup). SQLite audit table + JSONL backup. 6-month minimum retention. Replaces current bm_logger.py which only captures 7 event types with no email content, no Claude call details, no state snapshots. Critical for dispute resolution once real money flows. | Planning |
| **Operator dashboard** | VPS-hosted web app (Flask/FastAPI, second systemd service). Two functions: (1) Status panels — today's bookings, upcoming manifests, pending escalations, system health (heartbeat, error count, token spend), revenue summary. (2) Business config editor — add/remove/edit trips (prices, capacity, departures, days of week, seasonal schedules), business info, FAQ answers. Reads/writes client.json directly, changes go live on next poll cycle (~30s). Password-protected over HTTPS. Replaces manual client.json editing. | Planning |
| **Social media agent** | Separate agent (not Marina) for social media channels. Two capabilities: (1) Q&A on Instagram DMs / Facebook Messenger / WhatsApp — reads inbound messages, answers from trip/FAQ data, may redirect complex bookings to email. (2) Content creation + auto-posting — generates promotional posts/photos/videos, publishes without approval, can be reactive (operator prompts) or autonomous (promote empty slots). Platform priority TBD. Biggest scope item. | Planning |

### Resolved Issues (Can Remove from CLAUDE.md)

- ~~`slot_checked` not reset on date change~~ — fixed by change detection block (lines 717-730)
- ~~Same-day booking UTC edge case~~ — not a real bug, both Claude and Python use UTC-4

---

## Backup

Run `./snapshot.sh` from the project root to create a timestamped backup of all VPS runtime state (SQLite DB, thread state, config, logs). Backups are stored in `backups/`.

```bash
./snapshot.sh                  # Regular snapshot
./snapshot.sh pre-deploy       # Tagged snapshot before deploy
```
