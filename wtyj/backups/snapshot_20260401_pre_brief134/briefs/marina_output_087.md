# OUTPUT 087 — Comprehensive Logging: Never Fly Blind

**Brief:** marina_brief_087_comprehensive_logging.md
**Status:** Complete
**Date:** 2026-03-14

## What Was Done

Added logging at every failure point in marina_agent.py and social_agent.py:

1. **`api_usage`** — now includes `channel` and `from_id` for context
2. **`claude_response_invalid`** — fires when JSON parse succeeds but result isn't a dict or missing required fields. Includes raw_preview.
3. **`claude_empty_reply`** — fires when Claude returns valid JSON with empty `reply` field. Includes intents and raw_preview. This is the key diagnostic for the silent drop issue.
4. **`claude_api_error`** — fires in the except block. Includes the exception message. No more silent swallowing.
5. **`whatsapp_empty_reply`** — fires in social_agent.py when reply is empty and we return `""`. Includes intents, confidence, and internal_note.
6. **`whatsapp_processing`** — fires for every inbound WhatsApp message with phone, text (truncated), and from_name. Every message now has at least one log entry.

## Test Results
```
social regression: 104/104 PASSED
marina tone tests: 13/13 PASSED
```

## Unexpected
Nothing unexpected.
