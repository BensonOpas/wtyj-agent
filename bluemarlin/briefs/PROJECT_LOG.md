# BlueMarlin Agent — Project Log
# Last updated: 2026-03-04
---
## Project Overview
Autonomous booking agent for boat tour companies in the Caribbean.
Handles customer inquiries end to end via email — no human needed
for routine bookings. Built to be deployable for multiple clients
via a single config file per client.
Client 1: BlueMarlin Tours Curaçao — hello@wetakeyourjob.com
Stack: Python 3.12.3, Node.js v22.22.0, Ubuntu VPS, Claude Sonnet API,
SQLite, Microsoft Outlook OAuth2, Google Calendar API, Google Sheets API
---
## Completed Work
### Phase A — Core Booking Loop
BRIEF 001 — claude_client.py
  Status: COMPLETE
  What: Created Anthropic API wrapper replacing OpenClaw
  Files: bluemarlin/src/claude_client.py
  Output: bluemarlin/briefs/OUTPUT_001.md
BRIEF 002 — marina_extractor.py
  Status: COMPLETE
  What: Replaced OpenClaw subprocess with claude_client.extract()
  Files: bluemarlin/src/marina_extractor.py
  Output: bluemarlin/briefs/OUTPUT_002.md
BRIEF 003 — social_drafter.py
  Status: COMPLETE
  What: Replaced OpenClaw subprocess with claude_client.complete()
  Files: bluemarlin/src/social_drafter.py
  Output: bluemarlin/briefs/OUTPUT_003.md
BRIEF 004 — state_registry.py
  Status: COMPLETE
  What: Migrated from JSON flat file to SQLite, fixed race condition
  Files: bluemarlin/src/state_registry.py
  Output: bluemarlin/briefs/OUTPUT_004.md
BRIEF 005 — email_poller.py ask_marina_llm
  Status: COMPLETE
  What: Replaced last OpenClaw call in ask_marina_llm()
  Files: bluemarlin/src/email_poller.py
  Output: bluemarlin/briefs/OUTPUT_005.md
BRIEF 006 — config paths
  Status: COMPLETE
  What: Fixed all hardcoded /root/.openclaw/ paths,
        fixed deprecated datetime.utcnow()
  Files: bluemarlin/src/email_poller.py, bluemarlin/src/bm_logger.py
  Output: bluemarlin/briefs/OUTPUT_006.md
BRIEF 007 — calendar.js fixes
  Status: COMPLETE
  What: Fixed KEY_PATH hardcoded path, fixed 4-hour timezone bug
  Files: bluemarlin/src/calendar.js
  Output: bluemarlin/briefs/OUTPUT_007.md
BRIEF 008 — end-to-end test
  Status: COMPLETE (manual test, no Claude Code execution)
  What: Full system test — 6 scenarios, 4 passed, 2 failed
  Issues found: date normalization, off-topic handling, complaint handling
  Output: documented in session, logged for Brief 009
BRIEF 009 — Marina intelligence
  Status: COMPLETE
  What: Claude 4-way intent classifier, dateparser date normalization,
        complaint handling, internal error leak removed
  Files: bluemarlin/src/email_poller.py
  Output: bluemarlin/briefs/OUTPUT_009.md
BRIEF 010 — systemd background service
  Status: COMPLETE
  What: email_poller runs 24/7, survives reboots, restarts on crash
  Files: /etc/systemd/system/bluemarlin.service (VPS only)
         /root/bluemarlin/config/bluemarlin.env (VPS only, gitignored)
  Output: bluemarlin/briefs/OUTPUT_010.md
### Phase B — Production Features
BRIEF 011 — special_requests field
  Status: COMPLETE
  What: Added special_requests as 8th extraction field in marina_extractor
  Files: bluemarlin/src/marina_extractor.py
  Output: bluemarlin/briefs/OUTPUT_011.md
BRIEF 012 — structured logging expansion
  Status: COMPLETE
  What: Added bm_logger calls for 6 events:
        hold_created, hold_failed, booking_attempted,
        missing_fields_requested, complaint_received, off_topic_received
  Files: bluemarlin/src/email_poller.py
  Output: bluemarlin/briefs/OUTPUT_012.md
BRIEF 013 — Google Sheets dashboard
  Status: COMPLETE
  What: Real-time event logging to Google Sheets — 3 tabs:
        Bookings, Complaints, All Events
  Files: bluemarlin/src/sheets_writer.py, bluemarlin/src/email_poller.py
  Output: bluemarlin/briefs/OUTPUT_013.md
  Spreadsheet: 1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE
BRIEF 014 — sheet formatting (initial)
  Status: COMPLETE
  What: Applied BlueMarlin navy color palette to dashboard
  Files: bluemarlin/src/format_sheets.py
  Output: bluemarlin/briefs/OUTPUT_014.md
  Note: Superseded by Brief 015
BRIEF 015 — sheet polish
  Status: COMPLETE
  What: Charcoal palette, tailored column widths, text wrap,
        alternating row banding, extra columns deleted,
        status color coding
  Files: bluemarlin/src/format_sheets.py
  Output: bluemarlin/briefs/OUTPUT_015.md
---
## Planned Work
BRIEF 016 — client.json config system
  Priority: HIGH
  What: Extract all client-specific values to single config file.
        Business name, email, timezone, packages, calendar IDs,
        Microsoft credentials reference, Google credentials reference.
        All source files read from config at startup.
  Why: Required to onboard second client without manual file edits.
       Highest leverage brief remaining.
  Files: bluemarlin/config/client.json (new),
         email_poller.py, marina_extractor.py, social_drafter.py,
         calendar.js, bm_logger.py, sheets_writer.py
BRIEF 017 — WhatsApp channel
  Priority: HIGH
  What: Extend booking agent to WhatsApp messages.
        Most Caribbean tourism customers use WhatsApp not email.
  Why: Likely larger booking channel than email for BlueMarlin.
  Dependencies: WhatsApp Business API access, Meta developer account
  Note: Requires platform research before brief can be written
BRIEF 018 — complaint escalation
  Priority: MEDIUM
  What: Forward complaints to configurable notification channel.
        Currently complaints are logged and replied to but no
        human is notified.
  Why: Real client liability — unhappy customer with no human follow-up
  Design: Escalation channel defined in client.json (email, WhatsApp,
          or webhook). Build when first client requires it.
  Dependencies: Brief 016 (client.json) must be complete first
BRIEF 019 — Instagram DM handling
  Priority: MEDIUM
  What: Extend booking agent to Instagram DMs
  Dependencies: Meta developer account, Instagram Graph API access,
                Brief 016 (client.json)
  Note: Requires platform research before brief can be written
BRIEF 020 — social posting
  Priority: LOW
  What: Connect social_drafter.py and post_executor.py to real
        Instagram and Facebook posting
  Note: Drafting already built. Needs real API connection.
  Dependencies: Brief 019 (Instagram DM) infrastructure
---
## Discarded / Deferred
Stripe payments
  Status: DEFERRED INDEFINITELY
  Reason: BlueMarlin handles payments themselves. Payment link in
          confirmation email is a placeholder pointing to demo.pay.
          Will be revisited if a client specifically requests
          online payment integration.
  Note: Stripe test keys were obtained (sandbox only).
        Netherlands entity required for Caribbean businesses on Stripe.
        BlueFinn Charters uses Caribbean Tours BV (Amsterdam) for Stripe.
systemd vs screen debate
  Decision: systemd
  Reason: Production grade, survives reboots, auto-restart on crash.
          screen considered for simpler debugging workflow but
          systemd chosen for reliability.
OpenClaw
  Status: FULLY REMOVED
  Removed in: Briefs 001-005
  Archived at: /root/_archive_old_system/ (VPS only)
---
## Known Issues — Logged, Not Yet Fixed
1. social_registry.py — SOCIAL_STATE_FILE resolves relative to
   working directory, not __file__. Will break if called from
   different directory. Fix when social posting is built.
2. social_registry.py — content_id keyed on generated text not
   input context. Duplicate drafts possible. Fix when social
   posting is built.
3. dateparser ambiguity — slash formats like 03/15 may be
   misinterpreted as DD/MM vs MM/DD. Monitor in production.
4. AI confidence visibility — when Claude intent classifier is
   uncertain it defaults to general silently. No logging of
   confidence level. Future improvement.
5. Confirmation email — special_requests acknowledged ✓ RESOLVED Brief 017
6. payment_stub.py — placeholder only, demo.pay links go nowhere.
   Deferred per client decision.
7. Sheet1 tab — default Google Sheets tab, not used, not deleted.
   Minor cosmetic issue. Clean up when convenient.
8. format_sheets.py test rows — test rows with test@example.com
   are live in the Bookings, Complaints, and All Events tabs.
   Should be manually deleted before client handoff.
9. Reply tone and variation — all static reply templates (safe_social_reply,
   safe_inquiry_reply, safe_change_request_reply, safe_out_of_scope_reply,
   safe_complaint_reply, and the confirmation email) are hardcoded strings.
   No variation, no dynamic tone, emojis feel templated. Marina needs to
   sound like a real person — different phrasing each time, natural emoji
   use, responses that adapt to the customer's energy. Fix in a dedicated
   brief after client.json is complete.
---
## Architecture Decisions Log
Decision: SQLite over JSON for state_registry
  Made: Brief 004
  Reason: Race condition in JSON flat file under concurrent access.
          SQLite INSERT OR IGNORE with WAL mode is atomic.
Decision: Claude intent classifier over keyword matching
  Made: Brief 009
  Reason: Keyword list too narrow — missed complaints, off-topic
          messages, and edge cases. Claude 4-way classifier handles
          natural language intent correctly.
Decision: dateparser over manual regex
  Made: Brief 009
  Reason: Manual regex only handled today/tomorrow/YYYY-MM-DD.
          dateparser handles natural language dates from any format.
Decision: Event-driven Sheets updates over polling
  Made: Brief 013
  Reason: At BlueMarlin's volume (~20 events/day) polling wastes
          API calls. Event-driven writes immediately on each event.
Decision: systemd over screen/tmux
  Made: Brief 010
  Reason: Production grade. Survives reboots. Auto-restart on crash.
Decision: Skip Stripe for now
  Made: Session 2026-03-04
  Reason: BlueMarlin handles payments themselves. No client requirement
          for online payments at this stage.
Decision: client.json before social media
  Made: Session 2026-03-04
  Reason: client.json unlocks clean multi-client deployment.
          Social media integrations should be built on top of
          a clean config system, not before it.
---
## Workflow Reference
Every change follows this loop:
1. Claude (this chat) writes a brief after reading current file state
2. Cowork saves brief to bluemarlin/briefs/
3. Claude Code reads CODEX_CONTEXT.md and executes the brief
4. Claude Code builds, tests, writes OUTPUT file
5. Cowork reads OUTPUT file and pastes here
6. Claude reads actual code (not just the report) and approves or fixes
7. Cowork updates SYSTEM_STATE.md
8. Mac commits and pushes, VPS pulls
9. VPS runs systemctl restart bluemarlin
Key rules:
- Nothing approved without reading actual code
- Nothing committed without passing tests
- Credentials never go to GitHub
- No brief written without reading current system state first
- Cowork saves and reads files — does not approve or make decisions
---
## Key Paths
VPS:
  Project:  /root/bluemarlin/
  Source:   /root/bluemarlin/src/
  Config:   /root/bluemarlin/config/
  Logs:     /root/bluemarlin/logs/
  Database: /root/bluemarlin/src/state_registry.db
  Service:  /etc/systemd/system/bluemarlin.service
Mac:
  Project:  ~/Projects/bluemarlin-agent/
  Source:   ~/Projects/bluemarlin-agent/bluemarlin/src/
GitHub: github.com/BensonOpas/bluemarlin-agent (private)
Branch: main
Google Sheet: BlueMarlin Operations Dashboard
Spreadsheet ID: 1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE
Service account: bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com
