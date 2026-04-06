# OUTPUT 092 — Content Agent Core + Draft Store

**Brief:** marina_brief_092_content_agent_core.md
**Status:** Complete
**Date:** 2026-03-16

## What Was Done

1. **social_content config section** added to client.json — brand_voice, platforms, platform_priority, posting_frequency, max_posts_per_day, content_boundaries, cta_default, hashtag_style, emoji_style. All client-specific content rules live here, not in source code.

2. **content_drafts table** added to state_registry.py — stores generated drafts with content_class, instagram/facebook captions, hashtags, visual_suggestion, reasoning, status (pending/approved/rejected/published), rejection_reason, timestamps. CRUD functions: save_content_draft, get_content_drafts, update_draft_status.

3. **get_availability_summary()** added to state_registry.py — queries trip_bookings for all trip slots in the next N days. Parses days_available from config (daily, Fridays only, etc.) to determine which dates each trip operates. Returns trip_key, date, departure_time, booked_guests, capacity, spots_remaining. Avoids cross-agent import from gws_calendar.py.

4. **content_agent.py** created in agents/social/ — the content generation engine. Single Claude call (`claude-sonnet-4-6`, 4096 max tokens). System prompt reads brand_voice, content_boundaries, emoji_style, hashtag_style, cta_default from client.json social_content section. Structural rules (priority stack, classification definitions, platform rules, demand-state logic) stay in source. User prompt includes full client.json context, availability for next 7 days, recent drafts (dedup), and rejection history (learning). Response defaults for missing fields, content_class validation (A/B/C/D), empty draft filtering.

## Test Results
```
content agent tests: 14/14 PASSED
social regression: 121/121 PASSED
```

## Unexpected
Nothing unexpected.
