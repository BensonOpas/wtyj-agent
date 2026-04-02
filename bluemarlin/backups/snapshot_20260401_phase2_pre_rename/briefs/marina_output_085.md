# OUTPUT 085 — WhatsApp Tone V2: Greeting, Pricing, Formatting

**Brief:** marina_brief_085_whatsapp_tone_v2.md
**Status:** Complete
**Date:** 2026-03-13

## What Was Done

Updated WhatsApp writing style block in marina_agent.py with three changes:

1. **Greeting control** — "Greet ONLY on the first message of a new conversation. Check CONVERSATION HISTORY — if you already replied, skip the greeting."
2. **Pricing control** — "Do NOT include prices unless the customer explicitly asks about cost, price, or 'how much'."
3. **Formatting** — Changed from "One short paragraph. Not multiple." to "Use line breaks between distinct thoughts. Two to three short lines separated by blank lines."

## Test Results
```
social regression: 104/104 PASSED
marina tone tests: 12/12 PASSED
```

Note: test_035 and test_036 in tests/marina/ have pre-existing collection errors (checking for old prompt strings changed in earlier briefs). Not caused by this brief.

## Unexpected
Nothing unexpected.
