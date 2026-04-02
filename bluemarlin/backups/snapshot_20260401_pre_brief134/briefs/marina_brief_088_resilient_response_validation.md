# BRIEF 088 — Resilient Response Validation
**Status:** Approved | **Files:** `agents/marina/marina_agent.py` | **Depends on:** 087 | **Blocks:** —

## Context
Brief 087 logging revealed the root cause of silent drops: Claude returns valid JSON with a good reply but occasionally omits a non-critical field like `flags: {}`. The current validation requires ALL 8 fields to be present — if any one is missing, the ENTIRE response (including the reply) is discarded and the fallback fires. For WhatsApp, fallback reply is `""` → customer gets silence.

Example from logs (2026-03-14T13:22:42): Claude returned `intents`, `fields`, `confidence`, `reply` (with a perfect trip listing) but omitted `flags`. Validation rejected it. Customer got nothing.

## Why This Approach
Two changes:

1. **Default missing fields instead of rejecting.** Only `reply` is truly critical — without it, nothing to send. Everything else has safe defaults that the downstream code already handles via `.get()`. Replace the strict validation loop with defaults for missing fields.

2. **Prompt reinforcement.** Add a reminder to the JSON format instruction that all fields are required, including empty ones. Reduces how often Claude omits fields, but doesn't depend on it.

The alternative of only fixing the prompt was rejected — we can't guarantee Claude will always return all fields. An autonomous system must be resilient to its AI's imperfections.

## Source Material

### Validation constant — marina_agent.py lines 16-19
```python
_REQUIRED_RESPONSE_FIELDS = {
    "intents", "fields", "confidence", "reply",
    "clarifications_needed", "requires_human", "flags", "internal_note",
}
```

### Validation logic — marina_agent.py lines 498-514
```python
        if not isinstance(result, dict):
            bm_logger.log("claude_response_invalid", reason="not_a_dict",
                          raw_preview=raw[:200], channel=channel, from_id=from_email[:50])
            return fallback
        for field in _REQUIRED_RESPONSE_FIELDS:
            if field not in result:
                bm_logger.log("claude_response_invalid", reason=f"missing_field:{field}",
                              raw_preview=raw[:200], channel=channel, from_id=from_email[:50])
                return fallback

        if not result.get("reply"):
            bm_logger.log("claude_empty_reply",
                          intents=result.get("intents", []),
                          channel=channel, from_id=from_email[:50],
                          raw_preview=raw[:300])

        return result
```

### JSON format instruction — marina_agent.py line 247
```python
"The JSON must have exactly these fields:\n"
```

## Instructions

### Step 1 — Replace validation constant with defaults

Replace lines 16-19:
```python
_REQUIRED_RESPONSE_FIELDS = {
    "intents", "fields", "confidence", "reply",
    "clarifications_needed", "requires_human", "flags", "internal_note",
}
```
with:
```python
_RESPONSE_DEFAULTS = {
    "intents": ["inquiry"],
    "fields": {},
    "confidence": "medium",
    "reply": "",
    "clarifications_needed": [],
    "requires_human": False,
    "flags": {},
    "internal_note": "",
}
```

### Step 2 — Replace validation logic

Replace lines 498-514:
```python
        if not isinstance(result, dict):
            bm_logger.log("claude_response_invalid", reason="not_a_dict",
                          raw_preview=raw[:200], channel=channel, from_id=from_email[:50])
            return fallback
        for field in _REQUIRED_RESPONSE_FIELDS:
            if field not in result:
                bm_logger.log("claude_response_invalid", reason=f"missing_field:{field}",
                              raw_preview=raw[:200], channel=channel, from_id=from_email[:50])
                return fallback

        if not result.get("reply"):
            bm_logger.log("claude_empty_reply",
                          intents=result.get("intents", []),
                          channel=channel, from_id=from_email[:50],
                          raw_preview=raw[:300])

        return result
```
with:
```python
        if not isinstance(result, dict):
            bm_logger.log("claude_response_invalid", reason="not_a_dict",
                          raw_preview=raw[:200], channel=channel, from_id=from_email[:50])
            return fallback

        # Default missing fields instead of rejecting the entire response
        for field, default in _RESPONSE_DEFAULTS.items():
            if field not in result:
                result[field] = default
                bm_logger.log("claude_field_defaulted", field=field,
                              channel=channel, from_id=from_email[:50])

        # If reply is empty after defaults, fall back (preserves email fallback reply)
        if not result.get("reply"):
            bm_logger.log("claude_empty_reply",
                          intents=result.get("intents", []),
                          channel=channel, from_id=from_email[:50],
                          raw_preview=raw[:300])
            return fallback

        return result
```

### Step 3 — Strengthen JSON format instruction in prompt

In `_build_system_prompt`, change line 247:
```python
"The JSON must have exactly these fields:\n"
```
to:
```python
"The JSON must have ALL of these fields, even if empty (use {} for objects, [] for arrays, \"\" for strings, false for booleans):\n"
```

## Tests

Add a test in `tests/marina/test_marina_tone.py` before the `if __name__` block:

```python
def test_response_defaults_missing_fields():
    """T14: process_message defaults missing fields instead of rejecting."""
    from unittest.mock import patch, MagicMock
    # Simulate Claude returning valid JSON missing flags and internal_note
    incomplete_json = '{"intents": ["inquiry"], "fields": {}, "confidence": "high", ' \
                      '"reply": "We do boat trips!", "clarifications_needed": [], "requires_human": false}'
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=incomplete_json)]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
    with patch("agents.marina.marina_agent.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        result = marina_agent.process_message("test", "", "hello", {}, {})
    assert result["reply"] == "We do boat trips!"
    assert result["flags"] == {}
    assert result["internal_note"] == ""


def test_response_empty_reply_returns_fallback():
    """T15: process_message returns fallback when reply is empty, even if other fields present."""
    from unittest.mock import patch, MagicMock
    # Simulate Claude returning valid JSON with empty reply
    empty_reply_json = '{"intents": ["inquiry"], "fields": {}, "confidence": "high", ' \
                       '"reply": "", "clarifications_needed": [], "requires_human": false, ' \
                       '"flags": {}, "internal_note": ""}'
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=empty_reply_json)]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
    with patch("agents.marina.marina_agent.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        result = marina_agent.process_message("test", "", "hello", {}, {})
    # Email fallback should fire — non-empty reply
    assert "trip" in result["reply"].lower() or "guests" in result["reply"].lower()
```

Run:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/marina/test_marina_tone.py -v && python3 -m pytest tests/social/ -q
```

Expected: 15/15 marina + 104/104 social.

## Success Condition
All tests pass. T14 proves missing fields get defaulted and reply goes through. T15 proves empty reply still returns the fallback (email safety preserved).

## Rollback
Revert validation logic and constant in marina_agent.py. Remove new test.
