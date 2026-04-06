# OUTPUT 089 — Store User Message Before Reply Check

**Brief:** marina_brief_089_store_user_message_always.md
**Status:** Complete
**Date:** 2026-03-14

## What Was Done

Moved `wa_store_message(phone, "user", combined_text)` out of the `if reply_text:` block in webhook_server.py. User messages are now always stored in conversation history, even when Marina returns empty. Placed AFTER processing to avoid duplicating the message in Claude's prompt.

## Test Results
```
test_077 suite: 13/13 PASSED (12 existing + 1 new)
social regression: 105/105 PASSED
```

New test: `test_user_message_stored_on_empty_reply` — simulates _flush_buffer with an empty reply, asserts user message is in history and send was not called.

## Unexpected
Nothing unexpected.
