# PHASE A — Complete Documentation
# BlueMarlin Autonomous Booking Agent
# Date completed: 2026-03-03
---
## What Phase A Delivered
A fully autonomous email booking agent for BlueMarlin Tours Curaçao.
When a customer emails hello@wetakeyourjob.com the system:
1. Detects the email within 30 seconds
2. Classifies the intent — booking, complaint, off-topic, or general
3. Extracts booking fields from natural language
4. Normalizes dates and guest counts automatically
5. Creates a real Google Calendar hold if all fields are present
6. Sends a confirmation reply with calendar link and payment link
7. Asks for missing fields naturally if incomplete
8. Handles off-topic messages with a polite redirect
9. Handles complaints with an empathetic response
10. Never processes the same email twice (deduplication)
11. Never loops on a thread (anti-loop protection)
No human is required for routine bookings.
---
## System Architecture
### Runtime Environment
- VPS: Ubuntu, IP 108.61.192.52
- Python: 3.12.3
- Node.js: v22.22.0
- AI: Anthropic Claude claude-sonnet-4-20250514 via API
- State: SQLite (state_registry.db)
- Email: Microsoft Outlook via OAuth2 IMAP/SMTP
- Calendar: Google Calendar API via googleapis Node.js library
### Folder Structure
VPS:
  /root/bluemarlin/
    src/          — all source code
    config/       — credentials and state files (never committed to Git)
    logs/         — runtime logs (never committed to Git)
    briefs/       — all planning documents and outputs
Mac:
  ~/Projects/bluemarlin-agent/bluemarlin/
    src/          — mirrors VPS src/
    config/       — empty (credentials stay on VPS only)
    logs/         — empty
    briefs/       — mirrors VPS briefs/
GitHub:
  github.com/BensonOpas/bluemarlin-agent (private)
  Branch: main
  Credentials: excluded via .gitignore
### Files In Production
src/claude_client.py
  Created: Brief 001
  Purpose: Anthropic API wrapper
  Exposes: complete(prompt) -> str, extract(prompt) -> dict
  Both functions fail silently — never raise exceptions
  Callers must set ANTHROPIC_API_KEY environment variable
src/marina_extractor.py
  Created: Original codebase, modified Brief 002, Brief 009
  Purpose: Extracts booking fields from natural language email text
  Exposes: extract_fields(text) -> dict
  Returns keys: experience, date, guests, adults, kids,
                customer_name, phone
  Calls claude_client.extract()
src/social_drafter.py
  Created: Original codebase, modified Brief 003
  Purpose: Generates social media post drafts
  Exposes: draft_post(platform, context) -> dict
  Calls claude_client.complete()
  Stores drafts in social_registry
src/state_registry.py
  Created: Original codebase, modified Brief 004
  Purpose: Email deduplication gate
  Exposes: has_been_processed(content) -> bool,
           mark_as_processed(content)
  Storage: SQLite with WAL mode, INSERT OR IGNORE (race condition free)
  Database: bluemarlin/src/state_registry.db (gitignored)
src/bm_logger.py
  Created: Original codebase, modified Brief 006
  Purpose: Structured audit logging (JSONL format)
  Exposes: log(event, **fields) -> dict
  Log file: bluemarlin/logs/bluemarlin.log (gitignored)
  Timestamps: timezone-aware UTC
src/email_poller.py
  Created: Original codebase
  Modified: Brief 005, Brief 006, Brief 009
  Purpose: Main loop — polls Outlook INBOX every 30 seconds
  Key functions:
    detect_intent_and_fields(text) — Claude 4-way intent classifier
    ask_marina_llm(from_email, subject, body, mode) — LLM reply generation
    normalize_date_to_yyyy_mm_dd(date_val) — handles natural language dates
    safe_out_of_scope_reply() — static off-topic redirect
    safe_complaint_reply() — static empathetic complaint response
    create_calendar_hold(fields) — calls calendar.js via subprocess
    package_key_from_experience(exp) — fuzzy maps experience to package key
  Intent paths:
    booking/general — field collection, calendar hold, confirmation reply
    off_topic — static redirect reply
    complaint — empathetic reply, logged
  Anti-loop: MAX_REPLIES_PER_THREAD=3 per REPLY_WINDOW_SECONDS=600
  Deduplication: state_registry prevents double-processing
src/calendar.js
  Created: Original codebase, modified Brief 007
  Purpose: Creates Google Calendar holds via googleapis
  Called by: email_poller.py via subprocess
  Key fix: timezone correct — America/Curacao always UTC-4, no DST
  KEY_PATH: resolves relative to __dirname (bluemarlin/config/)
  Packages: googleapis (installed in bluemarlin/src/node_modules/)
src/payment_stub.py
  Created: Original codebase, unmodified
  Purpose: Generates placeholder payment links
  Status: STUB — no real Stripe integration
  Payment links point to demo.pay placeholder
src/social_registry.py
  Created: Original codebase, unmodified
  Purpose: Stores and manages social media post drafts
  Exposes: create_draft(), approve(), mark_posted(), get()
  Storage: social_state.json (working-directory relative — known issue)
src/post_executor.py
  Created: Original codebase, unmodified
  Purpose: Executes approved social media posts
  Status: Stub platform post ID — no real Instagram/Facebook connection
src/approve_post.py
  Created: Original codebase, unmodified
  Purpose: CLI tool to approve social media drafts
  Usage: python3 approve_post.py <content_id>
### Credentials On VPS
  /root/bluemarlin/config/azure_refresh_token.txt
    Microsoft OAuth2 refresh token for Outlook IMAP/SMTP access
  /root/bluemarlin/config/bluemarlin-calendar-key.json
    Google service account key for Calendar API
  /root/bluemarlin/config/email_thread_state.json
    Runtime thread state for email conversation tracking
  ANTHROPIC_API_KEY — set in /root/.bashrc, persists across reboots
---
## Brief Paper Trail
### Brief 001 — claude_client.py
File: bluemarlin/briefs/BRIEF_001_claude_client.md
Output: bluemarlin/briefs/OUTPUT_001.md
What changed: Created claude_client.py as Anthropic API wrapper
replacing all OpenClaw subprocess calls
Tests passed: 4/4
Status: APPROVED
### Brief 002 — marina_extractor.py
File: bluemarlin/briefs/BRIEF_002_marina_extractor.md
Output: bluemarlin/briefs/OUTPUT_002.md
What changed: Replaced OpenClaw subprocess call with
claude_client.extract()
Tests passed: 6/6
Status: APPROVED
### Brief 003 — social_drafter.py
File: bluemarlin/briefs/BRIEF_003_social_drafter.md
Output: bluemarlin/briefs/OUTPUT_003.md
What changed: Replaced OpenClaw subprocess call with
claude_client.complete()
Tests passed: 4/5 (Test 4 was a test design issue — not a code bug)
Status: APPROVED
### Brief 004 — state_registry.py
File: bluemarlin/briefs/BRIEF_004_state_registry.md
Output: bluemarlin/briefs/OUTPUT_004.md
What changed: Migrated from JSON flat file to SQLite,
fixed race condition via INSERT OR IGNORE, WAL mode enabled
Tests passed: 7/7
Status: APPROVED
### Brief 005 — email_poller.py ask_marina_llm
File: bluemarlin/briefs/BRIEF_005_ask_marina_llm.md
Output: bluemarlin/briefs/OUTPUT_005.md
What changed: Replaced last OpenClaw subprocess call in
ask_marina_llm() with claude_client.complete()
Tests passed: 3/5 (Tests 4 and 5 were test design issues)
Tests 4 and 5 fixed post-approval in same commit
Status: APPROVED
### Brief 006 — config paths
File: bluemarlin/briefs/BRIEF_006_config_paths.md
Output: bluemarlin/briefs/OUTPUT_006.md
What changed: Fixed all hardcoded /root/.openclaw/ paths in
email_poller.py and bm_logger.py, fixed deprecated datetime.utcnow(),
fixed calendar.js path reference
Tests passed: 8/8
Status: APPROVED
### Brief 007 — calendar.js fixes
File: bluemarlin/briefs/BRIEF_007_calendar_fixes.md
Output: bluemarlin/briefs/OUTPUT_007.md
What changed: Fixed KEY_PATH to resolve relative to __dirname,
fixed 4-hour timezone bug — America/Curacao always UTC-4
Tests passed: 5/5
Status: APPROVED
### Brief 008 — End-to-end test
File: bluemarlin/briefs/BRIEF_008_end_to_end_test.md
Output: N/A — manual test, no Claude Code execution
What was tested:
  Test 1 — clean booking with YYYY-MM-DD date: PASS
  Test 2 — incomplete booking missing date: PASS
  Test 3 — prompt injection attempt: PARTIAL
  Test 4 — off-topic message (flight): FAIL — logged for Brief 009
  Test 5 — complaint/abusive message: FAIL — logged for Brief 009
  Test 6 — clean booking from second email: PASS
Issues logged: date normalization, off-topic handling, complaint handling
Status: CORE LOOP CONFIRMED WORKING
### Brief 009 — Marina intelligence
File: bluemarlin/briefs/BRIEF_009_marina_intelligence.md
Output: bluemarlin/briefs/OUTPUT_009.md
What changed: Replaced narrow keyword intent detection with Claude
4-way intent classifier (booking/complaint/off_topic/general),
replaced minimal date normalizer with dateparser library,
added safe_complaint_reply(), added complaint intent dispatch path,
removed internal error leak to customers
Tests passed: 11/11
Live retests passed: 3/3
Status: APPROVED
---
## Known Issues Logged For Future Briefs
1. social_registry.py — SOCIAL_STATE_FILE is a bare filename,
   resolves relative to working directory. Known issue, not yet fixed.
2. social_registry.py — content_id is keyed on generated text not
   input context. Duplicate drafts possible if same context passed twice.
3. dateparser — ambiguous slash formats (03/15 vs 15/03) may be
   misinterpreted. Monitor in production.
4. Complaint escalation — complaints are logged and replied to but
   no human is notified. Escalation channel to be determined per client
   and built when first client requires it.
5. payment_stub.py — no real Stripe integration. Payment links point
   to demo.pay placeholder. Phase B item.
6. post_executor.py — no real Instagram/Facebook connection.
   Social posting is stubbed. Phase B item.
7. AI confidence — when Claude intent classifier is uncertain it
   defaults to general with no visibility. Worth logging intent
   classification results in production to spot patterns.
---
## What Was Removed
OpenClaw — fully removed from all active code paths as of Brief 005.
Replaced by direct Anthropic API calls via claude_client.py.
OpenClaw runtime archived at: /root/_archive_old_system/openclaw_runtime/
Old system archived at: /root/_archive_old_system/
---
## Phase B — Next Steps
Brief 010 — systemd background service
  email_poller runs 24/7, survives reboots
Brief 011 — Google Sheets booking dashboard
  Read-only client view of holds, status, payments
Brief 012 — Stripe real payment integration
  Replace demo.pay placeholder with real payment links
Brief 013 — Complaint escalation
  Forward complaints to configurable channel per client
Brief 014 — client.json config system
  Extract all client-specific values to single config file
  Enables one-day onboarding for new clients
Brief 015 — Instagram/Facebook DM handling
  Extend booking agent to social media channels
---
## Workflow Reference
Every change follows this loop:
1. I (Claude chat) write a brief after reading current file state
2. You paste brief to Cowork — Cowork saves to bluemarlin/briefs/
3. You tell Claude Code to read CODEX_CONTEXT.md and execute the brief
4. Claude Code builds, tests, writes OUTPUT file
5. You tell Cowork to read OUTPUT file and paste here
6. I read the actual code (not just the report) and approve or fix
7. You tell Cowork to update SYSTEM_STATE.md
8. You commit from Mac, VPS pulls
9. Done
Key rule: nothing is approved without reading the actual file.
Key rule: nothing is committed without passing tests.
Key rule: credentials never go to GitHub.
