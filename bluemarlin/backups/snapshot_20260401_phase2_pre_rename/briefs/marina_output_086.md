# OUTPUT 086 — Never Leave Customer on Read

**Brief:** marina_brief_086_never_empty_reply.md
**Status:** Complete
**Date:** 2026-03-14

## What Was Done

Added "NEVER return an empty reply" rule to the WhatsApp writing style block in marina_agent.py. The rule tells Claude to always respond — for off-topic messages, briefly acknowledge and mention what we do offer. Keeps responses natural and varied.

WhatsApp API failure fallback left as `""` (unchanged) — adding a static string would violate Rule 3.

## Test Results
```
marina tone tests: 13/13 PASSED (12 existing + 1 new)
social regression: 104/104 PASSED
```

New test: `test_whatsapp_prompt_never_empty_rule` — asserts "NEVER return an empty reply" is in the WhatsApp system prompt.

## Unexpected
Nothing unexpected.
