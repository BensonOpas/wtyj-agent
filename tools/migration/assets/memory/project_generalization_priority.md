---
name: Generalization — payment flag + hardcoded fixes before rename
description: Phase 2 priority shift. Payment timing flag + prompt cleanup needed before second client. Full rename deferred. DMs parked (working but tone needs tuning). Deadline April 15 2026.
type: project
---

**Decision (2026-04-01):** Pause DM work (Briefs 130-131b deployed, working end-to-end but AI tone needs tuning and Brief 132 dashboard multi-channel not done yet). Shift to generalization fixes needed for Phase 2 multi-tenant.

**Deadline:** April 15, 2026 — Phase 2 complete.

**What blocks a non-charter client RIGHT NOW (in priority order):**
1. No `payment.timing` flag — system always sends payment link. Quick fix.
2. Prompt examples mention "boat trips", "BBQ" — hardcoded in marina_agent.py. Move to client.json or strip.
3. `info@bluefinncharters.com` hardcoded in marina_agent.py lines 274, 294. Read from config.
4. Adult/child pricing assumed in booking summary (social_agent.py). Make config-driven.

**What does NOT block a client (defer):**
- Full rename (trip_key → service_key etc.) — invisible to users, do when it's worth a clean week
- Duration-based slot model — only needed for salons/clinics, not real estate/restaurants
- Multi-day booking — only needed for rentals
- DM tone tuning — parked, come back after Phase 2

**DM status (parked):**
- Briefs 130, 131b deployed and live on VPS
- Webhook registered, messages received and replied to
- DM agent has own Claude call (separate from Marina) — Q&A only, booking redirects to WA+email
- Brief 132 (dashboard multi-channel) not done yet — DM conversations visible but no channel badges
- AI tone still needs work — sounds too robotic/formal in DMs

**Why:** The terminology section + payment flag unblocks any business type. The rename is cosmetic for us. Ship what the client sees first.

**How to apply:** When planning next briefs, prioritize the 4 blockers above. Then Brief 132 + DM tone. Then rename if time permits before April 15.
