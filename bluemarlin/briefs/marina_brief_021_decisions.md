# BRIEF 021 — Decisions record
# No Codex execution required.
# This brief records architectural and product decisions made on
# 2026-03-04 that affect all subsequent briefs.
# Cowork: update MARINA_INTELLIGENCE_SPEC.md and PROJECT_LOG.md
# as instructed below. No source files are touched.
---
## Decision 1 — Unknown question handling
When a customer asks something Marina does not have an answer for
(cancellation policy, pet policy, food options, anything not in
the FAQ or common sense knowledge):
Marina says: "I don't have that detail right now, but I'll make
sure someone from our team follows up with you shortly."
Then flags requires_human = true in the response.
She never redirects without acknowledging the question.
She never guesses at policy details.
She never ignores the question and pivots to booking.
Update MARINA_INTELLIGENCE_SPEC.md:
Find "## Open Questions" section, item 1, and replace with:
"1. RESOLVED — Unknown questions: Marina acknowledges, says she
   will have someone follow up, flags requires_human = true.
   Never redirects, never guesses, never ignores."
---
## Decision 2 — Escalation triggers
Marina hands off to a human (flags requires_human = true and
sends acknowledgement reply) when ANY of the following are true:
  - Large group: 15 or more guests
  - Complaint with no booking: customer is unhappy but not
    trying to book — no experience, date, or guests provided
  - Repeated question: customer asks the same question 3 or
    more times across the thread without receiving a satisfactory
    answer (detected by thread history, not pattern matching)
  - Explicit request: customer says they want to speak to a
    person, asks for a manager, or explicitly says Marina
    cannot help them
When requires_human = true:
  - Marina sends a warm acknowledgement reply
  - Event is logged to bm_logger and sheets_writer
  - Operator must check the Complaints/Events tab to action it
  - No automated email forward yet (deferred to Brief 028)
Update MARINA_INTELLIGENCE_SPEC.md:
Find "## Open Questions" section, item 2, and replace with:
"2. RESOLVED — Escalation triggers: large group (15+), complaint
   with no booking, same question asked 3+ times, explicit
   request to speak to a human. All set requires_human = true."
---
## Decision 3 — Confirmation email structure
Hybrid approach:
  - Claude generates the opener dynamically (warm greeting,
    social acknowledgement if applicable, excitement for the trip)
  - Fixed template for all booking details:
      Package: {experience}
      Date: {date}
      Guests: {guests}
      Special requests: {special_requests} (if present)
      Payment link: {payment_link}
      Calendar link: {html_link}
      Hold valid for 6 hours.
  - Claude generates the closing dynamically (warm sign-off,
    invitation to reply with questions)
  - Marina signature always fixed:
      Warm regards,
      Marina
      BlueMarlin Tours Curaçao
Rationale: Booking details are too important to risk hallucination.
Dynamic opener and closing provide warmth and variation without
touching the critical data fields.
Update MARINA_INTELLIGENCE_SPEC.md:
Find "## Open Questions" section, item 3, and replace with:
"3. RESOLVED — Confirmation email: hybrid. Claude generates opener
   and closing dynamically. Booking details (package, date, guests,
   payment link, calendar link) are fixed template. Marina signature
   always fixed."
---
## Decision 4 — Architecture freeze
The rule engine introduced in Briefs 018-020 is frozen.
No new Python logic will be added to handle language understanding.
All existing safe_X_reply() functions, classify_date_input(),
experience_is_clear(), is_date_confirmation_yes(), and the
date confirmation state machine are marked as technical debt.
Full refactor planned as Brief 024. See ARCHITECTURE_DRIFT_LOG.md.
Update PROJECT_LOG.md:
Add under "## Architecture Decisions":
"8. Rule engine frozen 2026-03-04 — Briefs 018-020 introduced
   Python logic for language understanding (date classification,
   experience matching, confirmation detection). This was drift
   from the correct architecture. Frozen as of Brief 021.
   Full refactor in Brief 024 will replace with unified Claude
   call returning structured JSON. See ARCHITECTURE_DRIFT_LOG.md."
---
## Brief plan locked — Phase C through E
Phase C — Foundation:
  Brief 021 — Decisions record (this brief)
  Brief 022 — client.json schema + config_loader.py
  Brief 023 — Unified Claude prompt isolated test
  Brief 024 — Full refactor of email_poller.py
  Brief 025 — Regression and live test suite
Phase D — Channels and Polish:
  Brief 026 — WhatsApp integration
  Brief 027 — Reply variation and tone
  Brief 028 — Complaint escalation (operator notification)
  Brief 029 — Booking reference numbers
Phase E — Multi-Client:
  Brief 030 — Second client onboarding
Gates:
  Brief 023 must pass all isolated tests before Brief 024 starts
  Brief 025 must pass all live tests before Brief 026 starts
Add this plan to PROJECT_LOG.md under "## Planned Work".
---
## No source files touched in this brief.
## No Codex execution required.
## Cowork updates MARINA_INTELLIGENCE_SPEC.md and PROJECT_LOG.md only.
