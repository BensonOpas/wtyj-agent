# OUTPUT 084 — WhatsApp Reply Tone Polish

**Brief:** marina_brief_084_whatsapp_tone_polish.md
**Status:** Complete
**Date:** 2026-03-13

## What Was Done

1. Replaced WhatsApp writing style block in marina_agent.py with tighter rules: word count caps (50/80 words), good/bad examples, explicit phrase blacklist
2. Updated persona in client.json to shorter, more direct version
3. Updated test_persona_in_client_json assertion to match new persona

## Test Results
```
marina tone tests: 12/12 PASSED
social regression: 104/104 PASSED
live edge cases (VPS): 11/12 PASSED (1 intermittent empty reply — pre-existing Claude API issue)
```

## Before/After Examples

**Q: "Do you have a helicopter tour?"**
- Before: "We don't offer helicopter tours, that's not something we do! We run boat trips around Curaçao though — Klein Curaçao day trip, snorkeling, west coast beach, sunset cruise, and jet ski excursions. Happy to help with any of those!" (38 words, filler)
- After: "We don't offer helicopter tours — just boat trips. We do have a few things that could work for 4 people next Friday though. Want me to run through the options?" (31 words, direct)

**Q: "🚤🌊🎉"**
- Before: "🌊🎉 Hey! Looking to get out on the water?" (emoji echo)
- After: "Hey! Looking to book a trip or have a question?" (no forced emoji)

**Q: 16 guests**
- Before: "For groups of 15 or more, I need to pass you along to our team directly so they can arrange everything properly for you. I've flagged this and someone from info@bluefinncharters.com will be in touch shortly." (37 words)
- After: "For groups of 15 or more, I'll need to pass you to our team to sort out the best arrangement. I've flagged this and someone will be in touch at info@bluefinncharters.com shortly." (33 words)

**Q: past date**
- Before: "Just to flag — the Sunset Cruise runs on Tuesdays, Thursdays, Fridays, and Saturdays. Last Monday (March 9) doesn't fall on one of those days, so unfortunately we wouldn't have had a departure then." (34 words, over-explains)
- After: "Last Monday would be March 9, which has already passed. Did you mean an upcoming date? The Sunset Cruise runs Tuesdays, Thursdays, Fridays, and Saturdays — which date works for you?" (31 words, asks next question)

## Unexpected
Intermittent empty replies from Claude API (1/12 on one run, 2/12 on another, different tests each time). Pre-existing issue — same behavior observed in Brief 079 testing before any tone changes.
