# BRIEF 090 — Dynamic Client Context Injection
**Status:** Approved | **Files:** `shared/config_loader.py`, `agents/marina/marina_agent.py` | **Depends on:** 089 | **Blocks:** —

## Context
The prompt builder in marina_agent.py manually cherry-picks sections from client.json: BUSINESS, TRIPS, FAQ, BOOKING RULES, PAYMENT. It missed `cancellation_policy`, `private_charters`, and `fleet` — Marina couldn't answer questions about them. Every time client.json grows, someone has to update the prompt builder. This breaks the design principle: data change should never require code change.

## Why This Approach
Replace the manual section-by-section injection with a single function that reads ALL of client.json, filters internal keys, and auto-generates labeled sections from the top-level keys. New sections added to client.json are automatically visible to Marina. New client with different sections? Same code.

The trip alias injection in the system prompt is kept separately — it's part of the JSON output format instruction, not business data.

The alternative of dumping raw JSON was considered but labeled sections are more readable for Claude and maintain the current prompt style.

## Source Material

### config_loader.py — needs `get_raw()` added

### marina_agent.py `_build_user_prompt()` lines 386-414 — manual sections to replace
```python
    return f"""{returning_customer_section}...
TODAY (Curaçao time): {today}
TIMEZONE: {csk.get('curacao_timezone', ...)}
CURRENCY: {csk.get('currency', ...)}

BUSINESS:
  Email: {business.get('email', '')}
  ...

TRIPS (exact pricing and schedules):
{trips_text}

FAQ:
{faq_text}

BOOKING RULES:
  Required fields: ...

PAYMENT:
  Methods: ...

{action_context}
...
```

### Helper functions to remove — `_build_trips_text()` (line 26), `_build_faq_text()` (line 47)
These become dead code after the change.

## Instructions

### Step 1 — Add `get_raw()` to config_loader.py

Add after the existing `get_common_sense_knowledge()` function:

```python
def get_raw() -> dict:
    """Return the full parsed client.json. Used for dynamic prompt injection."""
    try:
        return dict(_load())
    except Exception:
        return {}
```

Update file header to Brief 090.

### Step 2 — Add `_build_client_context()` to marina_agent.py

Add after the `_filter_verify()` function (line 23), replacing `_build_trips_text()` and `_build_faq_text()`:

Remove `_filter_verify()` (dead code after this change), `_build_trips_text()`, and `_build_faq_text()`. Identify them by function name, not line number — they are between `_CURACAO_TZ` and `_build_trip_alias_text()`.

Add in their place:

```python
# Keys to exclude from the client context (internal system config, not customer-facing)
_INTERNAL_KEYS = {"spreadsheet_id", "demo_support_email", "agent_signature", "calendar_id"}
# Top-level keys to skip (already injected elsewhere or handled separately)
_SKIP_TOP_LEVEL = {"trip_aliases"}  # Already in system prompt via _build_trip_alias_text()


def _strip_verify(obj):
    """Recursively strip [VERIFY...] placeholder values from nested structures."""
    if isinstance(obj, dict):
        return {k: _strip_verify(v) for k, v in obj.items()
                if not (isinstance(v, str) and v.startswith("[VERIFY"))}
    if isinstance(obj, list):
        return [_strip_verify(i) for i in obj
                if not (isinstance(i, str) and i.startswith("[VERIFY"))]
    return obj


def _build_client_context() -> str:
    """Auto-generate labeled sections from all customer-facing data in client.json.
    Filters internal keys and [VERIFY] placeholders. New sections are automatically included."""
    raw = config_loader.get_raw()
    sections = []
    for key, value in raw.items():
        if key in _SKIP_TOP_LEVEL:
            continue
        # Clean internal keys from nested structures
        if isinstance(value, dict):
            clean = {}
            for k, v in value.items():
                if k in _INTERNAL_KEYS:
                    continue
                # Strip calendar_id from trip departures
                if isinstance(v, dict) and "departures" in v:
                    v = dict(v)
                    v["departures"] = [
                        {dk: dv for dk, dv in dep.items() if dk not in _INTERNAL_KEYS}
                        for dep in v.get("departures", [])
                    ]
                clean[k] = v
            clean = _strip_verify(clean)
            if clean:
                sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{json.dumps(clean, indent=2, ensure_ascii=False)}")
        elif isinstance(value, list):
            clean = _strip_verify(value)
            sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{json.dumps(clean, indent=2, ensure_ascii=False)}")
        elif isinstance(value, str) and key not in _INTERNAL_KEYS:
            if not value.startswith("[VERIFY"):
                sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{value}")
    return "\n\n".join(sections)
```

### Step 3 — Replace manual sections in `_build_user_prompt()`

In `_build_user_prompt()`, remove:
- Line 303: `business = config_loader.get_business()`
- Line 304: `booking_rules = config_loader.get_booking_rules()`
- Line 305: `payment = config_loader.get_payment()`
- Line 307: `csk = config_loader.get_common_sense_knowledge()`
- Lines 353-354: `trips_text = _build_trips_text()` and `faq_text = _build_faq_text()`

Replace with:
```python
    today = datetime.now(_CURACAO_TZ).strftime("%Y-%m-%d")
    csk = config_loader.get_common_sense_knowledge()
    client_context = _build_client_context()
```

Note: `csk` is kept for TIMEZONE and CURRENCY — these need to stay prominent at the top of the prompt for accurate date/price handling.

Replace the data sections in the return string (lines 386-414) from:
```python
    return f"""{returning_customer_section}...
TODAY (Curaçao time): {today}
TIMEZONE: {csk.get('curacao_timezone', 'America/Curacao (UTC-4, no DST)')}
CURRENCY: {csk.get('currency', 'USD')}

BUSINESS:
  Email: {business.get('email', '')}
  ...

TRIPS (exact pricing and schedules):
{trips_text}

FAQ:
{faq_text}

BOOKING RULES:
  Required fields: ...

PAYMENT:
  Methods: ...

{action_context}
```

with:
```python
    return f"""{returning_customer_section}{unknown_ref_section}{completed_bookings_section}{past_customer_bookings_section}{max_bookings_section}
TODAY (Curaçao time): {today}
TIMEZONE: {csk.get('curacao_timezone', 'America/Curacao (UTC-4, no DST)')}
CURRENCY: {csk.get('currency', 'USD')}

CLIENT DATA (source of truth for all customer-facing information):
{client_context}

{action_context}
```

Keep everything after `{action_context}` unchanged (thread context, history, inbound message).

### Step 4 — Update file headers

- config_loader.py: `# Last modified: Brief 090`
- marina_agent.py: `# Last modified: Brief 090`

## Tests

Add a test in `tests/marina/test_marina_tone.py` before `if __name__`:

```python
def test_client_context_includes_all_sections():
    """T16: All customer-facing client.json sections appear in the prompt."""
    from shared import config_loader
    raw = config_loader.get_raw()
    prompt = marina_agent._build_user_prompt("test@test.com", "Test", "Hello", {}, {})
    # Every top-level key (except skipped ones) should have a section
    skip = {"trip_aliases"}  # Already in system prompt
    for key in raw:
        if key in skip:
            continue
        section_header = key.upper().replace("_", " ")
        assert section_header in prompt, f"Section '{section_header}' missing from prompt (key: {key})"


def test_client_context_excludes_internal_keys():
    """T17: Internal keys (calendar_id, spreadsheet_id) are not in the prompt."""
    prompt = marina_agent._build_user_prompt("test@test.com", "Test", "Hello", {}, {})
    assert "spreadsheet_id" not in prompt.lower()
    assert "calendar_id" not in prompt.lower()
    assert "demo_support_email" not in prompt.lower()


def test_client_context_no_duplicate_aliases():
    """T18: trip_aliases not duplicated in user prompt (already in system prompt)."""
    prompt = marina_agent._build_user_prompt("test@test.com", "Test", "Hello", {}, {})
    assert "TRIP ALIASES" not in prompt
```

Run:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/marina/test_marina_tone.py -v && python3 -m pytest tests/social/ -q
```

Expected: 18/18 marina + 105/105 social.

## Success Condition
All tests pass. T16 proves every customer-facing client.json section is in the prompt. T17 proves internal keys are filtered. T18 proves trip_aliases isn't duplicated. Adding a new section to client.json requires zero code changes to be visible to Marina.

## Rollback
Revert config_loader.py and marina_agent.py. Restore `_build_trips_text()` and `_build_faq_text()`.
