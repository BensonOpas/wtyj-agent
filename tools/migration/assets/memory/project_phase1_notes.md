---
name: Phase 1 polish notes — Benson's review (2026-04-04)
description: Benson's notes on what needs fixing before Phase 2. Covers UX, tone, booking flow, logs, brand assets, DM experience.
type: project
---

## Status: Most items actioned. 5 open design questions in roadmap "Needs discussion" section.

### Done this session:
- Booking confirmation wording (Brief 141)
- Booking flow pacing (Brief 141)
- Client email config (Brief 141)
- Noreply email filter (quick fix)
- BlueFinn fallback defaults removed (quick fix)

### Open design questions (in roadmap with timestamp 2026-04-04):
1. Payment integration — universal design for any business type
2. Booking flow balance — email replies still thin, need tuning
3. Large group escalation — rework to full escalation via prompt
4. BlueMarlin-hosted booking page — concept for businesses without websites
5. Email routing — confirmed and implemented

These are Benson's thoughts from a full review session. Each item has context from the discussion.

## Items to do (roughly ordered by priority)

### 1. Noreply email filter (quick fix)
Marina replies to DMARC reports from noreply-dmarc-support@google.com. The filter checks `noreply@` prefix but misses `noreply-`. Fix the filter.

### 2. Booking confirmation wording (prompt change)
Marina says "Want me to go ahead and book this?" before checking availability. Customer thinks booking is final. If availability check fails, they feel jerked around. Change to "Let me check availability and hold a spot for you — sound good?" or similar. The word "book" implies finality. Prompt change in the action context (social_agent.py lines 93-104).

### 3. DM booking flow feels too fast (prompt change)
DMs enter the booking flow immediately. Feels like walking into a store with 2 shelves and a cashier — too transactional. Marina should give info about the service first, then offer: "Want to book here, or through email/WhatsApp?" Give the customer a choice and breathing room. This is a prompt change — add DM-specific instruction when channel is DM and booking intent is detected.

### 4. Large group escalation timing (code change)
Currently triggers at the START of Step 7 (Brief 140). Should trigger later — let Marina have the conversation first, collect details, THEN escalate. Should be a semi-escalation (Marina continues, operator notified) not a full escalation (conversation killed). Consider making Marina handle this in her prompt instead of Python.

### 5. AI tone (prompt + filter)
Marina still sounds AI-y. Specific issues: em-dashes (—), "I'd be happy to", over-eagerness, forced enthusiasm. Two fixes: (a) tighter prompt with more banned phrases, (b) post-processing filter for em-dashes. Need specific examples from Benson of bad replies to tune against.

### 6. Brand assets in config (config + dashboard)
- Logo and icon upload — needed for social media content
- Brand fonts — for content generation
- Brand colors — already in client.json for Pillow, keep for AI image prompts
- Client's website URL — add to business section, inject into Marina's prompt so she can reference it

### 7. Google Sheets status
Dashboard reads from SQLite, not Sheets. Sheets is a backup/audit log. Working but nobody looks at it. Keep for now, don't invest in fixing. Headers look correct after rename.

### 8. FAQ learning from relay (future)
When operator answers a relay question, store the answer as FAQ. New dashboard tab to manage learned FAQ. Noted for future — adds complexity, not needed right now.

### 9. Logs for live operations (Docker-era)
When live with 20 clients, need complete structured logs that Claude can read and diagnose from. Current JSONL format is fine. Need: per-client log isolation (Docker), extraction script or dashboard page, structured enough for Claude to parse. The workflow: something breaks → SR/JR tells Claude → Claude reads logs → Claude fixes.

### 10. Payment integration thinking
For the demo pitch: Option C — no real payment. Marina confirms booking, operator handles payment manually. Real payment (Stripe/Mollie Connect) is Phase 3. The demo sells the AI operations, not the payment flow.

### 11. Website situation
Multiple things called "website": (a) wetakeyourjob.com main site, (b) bluemarlincharters demo site, (c) dashboard at bluemarlindashboard.replit.app, (d) future BlueMarlin-hosted booking form. The booking form is Phase 3. For now, bookings happen through WhatsApp/email/DMs.

### 12. Graphics engine
Now that AI image generation exists (Claude image 1.5, DALL-E), the Pillow branded graphics engine is legacy. Don't fix the Unicode bug — consider replacing the whole engine with AI image gen later.
