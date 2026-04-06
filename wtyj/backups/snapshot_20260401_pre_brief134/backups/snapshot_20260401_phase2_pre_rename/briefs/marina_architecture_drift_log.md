# ARCHITECTURE DRIFT LOG
# Written: 2026-03-04
# Trigger: RRR called during Brief 021 planning
# Purpose: Document what caused rule-engine creep, how to prevent it,
#          and what the correct architecture looks like.
---
## What Happened
The system started correctly. Briefs 001-009 built a clean foundation:
Claude handles language understanding, Python handles infrastructure.
Intent classification was Claude. Field extraction was Claude.
The architecture was right.
Then something shifted.
Brief 018 — past date guard. Reasonable, infrastructure concern.
Brief 019 — is_date_ambiguous(). First sign of drift. Python function
  to detect something Claude already understands natively.
Brief 020 — classify_date_input() with hardcoded VAGUE_PATTERNS and
  RESOLVABLE_PATTERNS lists, experience_is_clear(), guest count rules,
  large group threshold, 50+ lines of rule engine to patch gaps in
  Claude's extraction output.
Next planned brief — string-matching cross-validator to catch
hallucinated fields from marina_extractor.
That is the full drift arc: from AI-native to rule-engine-patching-AI.
---
## What Led To It
### Trigger 1 — A specific live bug
The past date bug was real and needed fixing. The fix was surgical and
correct. But it established a pattern: when Claude's output causes a
problem, write a Python rule to catch it.
### Trigger 2 — Test failures under artificial conditions
Six rapid-fire test emails collapsed into one thread due to subject
normalization. We diagnosed real bugs but also testing artifacts.
Urgency of "bugs found" pushed toward fixes without stepping back.
### Trigger 3 — Incremental brief writing
Each brief was scoped to one problem. No brief asked "is this the
right layer to fix this?" Each fix made local sense. The accumulation
was invisible until the RRR call.
### Trigger 4 — Spec written after drift started
MARINA_INTELLIGENCE_SPEC.md was written after Briefs 018-020 had
already introduced the rule engine. The spec would have prevented
the drift if it had existed first.
### Trigger 5 — Hardcoded reply templates
Once static reply strings existed, we needed routing logic to pick
one. Routing needed classification. Classification needed pattern
matching. One static template created a chain of complexity.
---
## The Core Architectural Error
We treated Claude as a field parser and built Python infrastructure
around its output.
The correct model is Claude as a reasoning layer that returns
structured decisions, not just extracted data.
Current architecture:
  Email
  → detect_intent_and_fields()
  → Python rules cascade (classify_date, experience_is_clear, etc.)
  → static reply template selected
  → smtp_send()
What it should be:
  Email
  → Claude(full context: persona + packages + thread state + today's date)
  → structured JSON {intents, fields, confidence, clarifications_needed, reply, flags}
  → Python sends reply, updates state, logs to sheets
  → smtp_send()
The difference: Claude reads the message, understands what is clear
and what is not, decides what to ask, drafts the reply — all in one
pass. Python sends the email and updates state. Python does not
understand language.
---
## Specific Things That Should Not Exist
These were written to compensate for Claude not being asked the
right question in the first place:
- classify_date_input() and its VAGUE_PATTERNS/RESOLVABLE_PATTERNS
- is_date_ambiguous() (removed in Brief 020, but existed in Brief 019)
- is_date_confirmation_yes() — Claude can determine this
- experience_is_clear() — Claude can determine this
- safe_date_past_reply() — static string, will never sound fully human
- safe_date_vague_reply() — static string, will never sound fully human
- safe_date_implausible_reply() — static string
- safe_date_confirmation_reply() — static string
- safe_experience_unclear_reply() — hardcoded package list, will go stale
- safe_social_reply() — static string
- safe_inquiry_reply() — static string
- safe_complaint_reply() — static string
- safe_change_request_reply() — static string
- safe_out_of_scope_reply() — static string
- GROUP_BOOKING_THRESHOLD = 15 — magic number substituting for judgment
- The date confirmation intercept state machine — 80 lines of Python
  managing conversation flow that Claude should manage
- The awaiting_date_confirmation flag system — conversation state
  that belongs in Claude's context, not in a JSON file
---
## What The Correct System Looks Like
One central Claude call per email.
System prompt contains:
- Marina's persona (from MARINA_INTELLIGENCE_SPEC.md)
- Available packages with full details
- Business rules (group threshold, hold duration, required fields)
- Today's date and day of week
- Current thread state (fields collected so far, flags, history)
- FAQ (from client.json when built)
Claude returns structured JSON:
{
  "intents": ["booking"],
  "extracted_fields": {
    "experience": "sunset cruise",
    "date": "2026-04-20",
    "guests": 2
  },
  "confidence": {
    "experience": "high",
    "date": "high - explicit year provided",
    "guests": "high"
  },
  "clarifications_needed": [
    "customer_name",
    "phone"
  ],
  "reply": "Hi Benson! Great choice — the Sunset Signature Cruise...",
  "flags": {
    "requires_human": false,
    "reason": null,
    "large_group": false,
    "past_date": false,
    "vague_date": false
  }
}
Python's job:
  1. Build the prompt with current context
  2. Call Claude
  3. Parse the JSON response
  4. Validate extracted_fields against ALLOWED_KEYS
  5. Update thread state with extracted fields and flags
  6. If clarifications_needed is empty and all REQUIRED_FIELDS present
     → create calendar hold
  7. Send reply from response.reply
  8. Log to bm_logger and sheets_writer
No pattern matching. No static templates. No rule cascades.
Claude handles all language decisions.
Python handles all infrastructure decisions.
---
## Why We Didn't Build It This Way Initially
The original codebase predated this architecture thinking. It was
built incrementally to get something working. That is appropriate
for early stage. The error was not reassessing the architecture
before Brief 018. The Marina Intelligence Spec, if written before
Brief 018, would have prevented the drift.
---
## Prevention Rules
### Rule 1 — Language decisions belong to Claude
If a brief adds Python code to understand, classify, or respond to
natural language — stop and ask if Claude should be doing that instead.
### Rule 2 — Static reply strings are a red flag
Every hardcoded safe_X_reply() function is a maintenance burden and
a ceiling on Marina's quality. Question every new one.
### Rule 3 — The spec is the architectural check
Before writing any brief that touches the response or extraction
layer, reread MARINA_INTELLIGENCE_SPEC.md. Ask: does this brief
move toward or away from the system described there?
### Rule 4 — Patch briefs require layer justification
When a bug appears, the question is not just "how do we fix this"
but "at which layer does this fix belong." A Python patch for a
language understanding failure is almost always wrong.
### Rule 5 — Periodic architecture review
Every 5 briefs, step back and look at what has accumulated.
RRR handles this at the conversation level. Apply the same
discipline at the architecture level.
---
## Decision Made — 2026-03-04
Option B chosen: Freeze the rule engine. Do not add more Python
logic to patch language understanding gaps. Complete client.json.
Then do one clean refactor that replaces the entire extraction and
response layer with the correct architecture — one Claude call,
structured JSON output, all static templates removed.
The refactor brief will incorporate: Marina persona, FAQ injection
from client.json, dynamic reply generation, confidence scoring,
human escalation flags, and structured output validation.
This is tracked as technical debt. The system is functional for
email testing. The refactor happens before WhatsApp is built.
---
## Technical Debt Inventory — Rule Engine Layer
Files containing rule-engine code that will be replaced in the
refactor brief:
email_poller.py:
  - classify_date_input() — ~65 lines
  - is_date_confirmation_yes() — ~20 lines
  - experience_is_clear() — 2 lines
  - safe_date_past_reply() — ~15 lines
  - safe_date_vague_reply() — ~20 lines
  - safe_date_implausible_reply() — ~15 lines
  - safe_date_confirmation_reply() — ~15 lines
  - safe_experience_unclear_reply() — ~20 lines
  - safe_social_reply() — ~10 lines
  - safe_inquiry_reply() — ~20 lines
  - safe_complaint_reply() — ~10 lines
  - safe_change_request_reply() — ~10 lines
  - safe_out_of_scope_reply() — ~10 lines
  - safe_large_group_reply() — ~15 lines
  - GROUP_BOOKING_THRESHOLD constant
  - Date confirmation intercept state machine — ~80 lines
  - Multi-label dispatch block — ~100 lines
  Total estimated: ~430 lines to be replaced
marina_extractor.py:
  - extract_fields() — will be absorbed into the unified Claude call
  Total: entire file becomes redundant
detect_intent_and_fields() in email_poller.py:
  - Will be replaced by the unified Claude call
---
## Refactor Brief Prerequisites
Before the refactor brief can be written:
  1. client.json must exist (Brief 018 per original roadmap, now
     renumbered — next after current work)
  2. MARINA_INTELLIGENCE_SPEC.md open questions must be resolved
     (see Open Questions section in that file)
  3. The unified Claude prompt must be designed and tested in
     isolation before being integrated
---
## Related Documents
- bluemarlin/briefs/MARINA_INTELLIGENCE_SPEC.md
- bluemarlin/briefs/SYSTEM_STATE.md
- bluemarlin/briefs/PROJECT_LOG.md
