# BRIEF 087 — Comprehensive Logging: Never Fly Blind
**Status:** Approved | **Files:** `agents/marina/marina_agent.py`, `agents/social/social_agent.py` | **Depends on:** 086 | **Blocks:** —

## Context
When Claude returns empty replies or JSON parsing fails, there is ZERO visibility — the `except Exception` block silently returns a fallback, and when reply is empty in social_agent.py, it returns `""` with no log. During live testing, 10 messages were silently dropped across 2 users in one session. We couldn't diagnose the root cause because nothing was logged.

Current logging gaps:
1. **marina_agent.py** — `except Exception` swallows errors silently. No log of raw response, no log of the exception, no log when fallback fires.
2. **marina_agent.py** — `api_usage` has no context (which phone, which channel, what message).
3. **social_agent.py** — when `reply` is empty at line 338, returns `""` with no log. The customer gets silence with zero trace.
4. **social_agent.py** — no log of the inbound message being processed (can't correlate message → response).

## Why This Approach
Add logging at every decision point where something could go wrong. The goal: if a customer gets silence, the log tells us exactly WHY — was it a JSON parse failure, an API error, an empty reply from Claude, or something else. All events go through `bm_logger.log()` to the centralized JSONL log.

## Source Material

### marina_agent.py process_message() — lines 467-505 (the try/except block)
```python
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = _build_system_prompt(thread_flags, channel=channel)
        user_prompt = _build_user_prompt(from_email, subject, body, thread_fields, thread_flags,
                                          action_context, channel=channel, messages=messages)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()

        # Log API token usage
        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("api_usage",
                input_tokens=_usage.input_tokens,
                output_tokens=_usage.output_tokens,
                model="claude-sonnet-4-6")

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())

        result = json.loads(raw)

        if not isinstance(result, dict):
            return fallback
        for field in _REQUIRED_RESPONSE_FIELDS:
            if field not in result:
                return fallback

        return result

    except Exception:
        return fallback
```

### social_agent.py — lines 336-339 (empty reply early return)
```python
    reply = result.get("reply", "")

    if not reply:
        return ""
```

## Instructions

### Step 1 — Add context to api_usage in marina_agent.py

Change lines 485-488 from:
```python
            bm_logger.log("api_usage",
                input_tokens=_usage.input_tokens,
                output_tokens=_usage.output_tokens,
                model="claude-sonnet-4-6")
```
to:
```python
            bm_logger.log("api_usage",
                input_tokens=_usage.input_tokens,
                output_tokens=_usage.output_tokens,
                model="claude-sonnet-4-6",
                channel=channel,
                from_id=from_email[:50])
```

### Step 2 — Log empty reply from Claude in marina_agent.py

After `result = json.loads(raw)` succeeds and before `return result` (between lines 494 and 502), add logging for empty reply and validation failures:

Replace lines 496-502:
```python
        if not isinstance(result, dict):
            return fallback
        for field in _REQUIRED_RESPONSE_FIELDS:
            if field not in result:
                return fallback

        return result
```
with:
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

### Step 3 — Log exceptions in marina_agent.py

Change line 504-505:
```python
    except Exception:
        return fallback
```
to:
```python
    except Exception as _exc:
        bm_logger.log("claude_api_error",
                      error=str(_exc)[:200],
                      channel=channel, from_id=from_email[:50])
        return fallback
```

### Step 4 — Log empty reply early return in social_agent.py

Change lines 336-339:
```python
    reply = result.get("reply", "")

    if not reply:
        return ""
```
to:
```python
    reply = result.get("reply", "")

    if not reply:
        bm_logger.log("whatsapp_empty_reply", phone=phone,
                      intents=result.get("intents", []),
                      confidence=result.get("confidence", ""),
                      internal_note=result.get("internal_note", "")[:200])
        return ""
```

### Step 5 — Log inbound message processing in social_agent.py

After the `from_id` construction (line 247) and before the escalated guard (line 250), add:

```python
    bm_logger.log("whatsapp_processing", phone=phone, text=text[:100],
                  from_name=from_name)
```

## Tests

Run unit regression:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/ -q && python3 -m pytest tests/marina/test_marina_tone.py -q
```

Expected: 104/104 social + 13/13 marina tone pass. Logging changes don't affect behavior — they only add side effects to the log file.

## Success Condition
All tests pass. Every WhatsApp message produces at least one log entry (`whatsapp_processing`). Every empty reply produces a `whatsapp_empty_reply` or `claude_empty_reply` log entry. Every API failure produces a `claude_api_error` entry. Zero silent drops.

## Rollback
Remove the added bm_logger.log() calls. No behavioral changes to revert.
