# BRIEF 174 — Marina tool use migration (structured output via API schema)
**Status:** Draft | **Files:** marina_agent.py, test_069_whatsapp_agent.py, test_marina_tone.py, test_174 (new) | **Depends on:** — | **Blocks:** 175, 176

## Context

Research mode on 2026-04-09 surfaced a stuck email thread for `ash9772@gmail.com` (Anne-Sophie Hammar, Curaçao Klein charter booking). Customer sent four messages over three hours trying to book "Klein curacao, next Saturday, 7 people". Marina replied five times: two real replies, three generic fallbacks. Customer stopped replying. Thread is dead.

**Direct evidence from `bluemarlin.log`:**

```
2026-04-09T14:09:44 api_usage input_tokens=9996 output_tokens=480 channel=email from_id=ash9772@gmail.com
2026-04-09T14:09:44 claude_api_error error="Expecting value: line 1 column 1 (char 0)" channel=email
2026-04-09T15:01:40 api_usage input_tokens=10018 output_tokens=664 channel=email from_id=ash9772@gmail.com
2026-04-09T15:01:40 claude_api_error error="Expecting value: line 1 column 1 (char 0)" channel=email
2026-04-09T16:51:59 api_usage input_tokens=10060 output_tokens=694 channel=email from_id=ash9772@gmail.com
2026-04-09T16:51:59 claude_api_error error="Expecting value: line 1 column 1 (char 0)" channel=email
```

Three Claude calls with substantial output tokens (480, 664, 694) all failed to parse at char 0 — meaning Claude returned content but the first character wasn't `{`.

**Root cause, verified live:** I replayed msg #8 of the ash9772 thread against Claude Sonnet 4.6 inside the wtyj-bluemarlin container (see the research report earlier in this session). Claude returned 1904 characters: 1036 characters of free-text reasoning ("Let me work through the validation checks: Today is 2026-04-09 (Thursday)... 'Next Saturday' = April 19... wait let me reconsider...") followed by a ```json code fence with perfectly valid JSON. The parser at `wtyj/agents/marina/marina_agent.py:713-729` reads `response.content[0].text.strip()`, strips `^```(?:json)?\s*` from position 0 (no match — the text starts with "L"), strips `\s*```$` from the end, then calls `json.loads(raw)` on the reasoning text. `json.loads` fails at char 0 because "L" is not valid JSON. The JSON at position 1036 is never read.

Marina's prompt at `marina_agent.py:495` explicitly says *"Respond with ONLY a JSON object. No explanation. No markdown. No code fences. Just the JSON."* Claude Sonnet 4.6 ignores this instruction on ambiguous queries ("next Saturday" is genuinely ambiguous English — Claude wants to reason through which Saturday). The instruction is a suggestion; Claude overrides it when it thinks careful reasoning matters more than format compliance.

**This is not a one-off.** The pattern will recur on any customer message with ambiguity that Claude wants to reason through. It's a latent issue waiting to hit any thread with a vague date, a nested question, or a customer disagreement. Three stuck calls in a single day for one customer is the signal.

**Why the current parser fix attempts are all workarounds.** Options I considered and rejected:

- **First-brace to last-brace slice:** tolerates Claude's bad output. Doesn't prevent it. Still leaves invalid JSON, truncated JSON, and other string-parsing failure modes unhandled.
- **Assistant prefill:** forces Claude to start with `{`. Eliminates preamble but Marina still parses strings; malformed JSON still fails.
- **Stronger "no preamble" prompt language:** Claude ignores the same instruction in a thousand other prompts. Doesn't work.
- **Retry with corrective follow-up:** adds Claude calls to a broken contract. Violates Rule 1.

The root problem: **Marina's contract with Claude is "text in, text out, we parse". It's enforced by convention, not protocol.** Claude can break the convention any time and we have no recourse. The fix is to replace the convention with a protocol that the Anthropic API enforces.

**Spot-test verified the fix works.** Before writing this brief, I replayed the same msg #8 against Claude Sonnet 4.6 using `tools=[MARINA_TOOL]` with `tool_choice={"type": "tool", "name": "marina_response"}`. Result:

```
STOP REASON: tool_use
CONTENT BLOCKS: 1
  block 0: type=tool_use
    name=marina_response
    input:
{
  "intents": ["booking"],
  "fields": {
    "service_name": "Klein Curaçao Trip",
    "service_key": "klein_curacao",
    "date": "2026-04-18",
    "guests": 7,
    "customer_name": "Anne-Sophie Hammar",
    "email": "ash9772@gmail.com",
    "phone": "+599 9 686 5664"
  },
  "confidence": "high",
  "reply": "The Klein Curaçao Trip runs daily, so Saturday the 18th works. It's a full-day trip — around 8 hours, with BBQ lunch, premium open bar, and snorkel gear included... There are two departures from Jan Thiel Beach: 08:00 aboard BlueMarlin 2, 08:30 aboard BlueMarlin 1. Which one works better for your group?",
  "clarifications_needed": ["Which departure time do you prefer — 08:00 (BlueMarlin 2) or 08:30 (BlueMarlin 1)?"],
  "requires_human": false,
  "flags": {},
  "internal_note": "Customer selected Klein Curaçao Trip for Saturday April 18, 2026, party of 7. Awaiting departure time selection before showing booking summary."
}
USAGE: 10748 in / 412 out
```

Zero reasoning preamble. Single tool_use block. Valid dict ready for use. 412 output tokens vs 694 in the broken case (Claude stopped writing reasoning because the protocol doesn't allow a text channel). **The date is still April 18** — that's the separate semantic issue Brief 175 will fix, independent of this brief.

## Why This Approach

**Tool use migrates Marina from a convention-based contract to a protocol-enforced contract.** Before: Marina sends a prompt asking for JSON, hopes Claude complies, parses the text response, handles every possible failure mode. After: Marina defines a JSON schema as a tool, forces Claude to call that tool, receives a dict that's already validated by the Anthropic API.

What this structurally eliminates (not mitigates — eliminates):
1. Reasoning preamble before the JSON (the immediate bug)
2. Markdown code fences around the JSON
3. Trailing explanation text after the JSON
4. Invalid JSON syntax (missing commas, unclosed strings)
5. Wrong types (string where array expected, etc.)
6. Missing required fields (the API errors if the tool input is incomplete)
7. Claude ignoring "ONLY JSON" instructions — there is no text channel to ignore into

**What still needs its own brief** (not covered here, called out as follow-ups):
- **Brief 175 (Marina date disambiguation):** Claude's choice of April 18 vs April 11 for "next Saturday" is a SEMANTIC issue. Brief 174 doesn't address it — Claude is now structurally forced into the correct output format but can still misinterpret the input. Brief 175 adds a prompt rule on how to resolve "next [day]".
- **Brief 176 (context-aware fallback):** even with tool use, the fallback fires on genuine API-level failures (rate limit, timeout, outage). The current fallback reply ignores `thread_fields` and gaslights returning customers. Brief 176 rewrites the fallback to acknowledge what Marina already knows.

All three briefs together fully address the Anne-Sophie failure pattern, but they're independent and ship in sequence. Brief 174 is the root fix; 175 and 176 are adjacent improvements.

**Rejected alternatives:**

- **First-brace to last-brace parser tolerance.** Band-aid. Doesn't address the structural fragility of string parsing. Deferred forever because tool use is the right answer.
- **Assistant prefill with `{`.** 70% solution — fixes preamble but not invalid JSON, truncation, or missing fields. Tool use is the 99% solution at similar effort.
- **Leave the prompt alone, add a robust parser.** Same as above — tolerates bad output instead of preventing it.
- **Move the response format from text to a pydantic model and validate post-parse.** Solves validation but still requires parsing the text channel. Tool use solves both at once.

Tradeoff carried by tool use: slightly larger per-call token cost because the schema is sent with every request (~1500 tokens). This is offset by Claude writing FEWER output tokens (no reasoning preamble wasted). Net cost-per-call is roughly neutral or slightly cheaper. The latency impact is negligible — the schema is small and Anthropic's API handles it efficiently.

## Instructions

### Step 1: Add the MARINA_TOOL schema constant in marina_agent.py

**File:** `wtyj/agents/marina/marina_agent.py`

Add a module-level constant after the existing `_RESPONSE_DEFAULTS` dict (around line 25). This is the single source of truth for Marina's response structure.

```python
# Brief 174: tool use schema for Marina's structured response.
# Replaces the "Respond with ONLY a JSON object" text contract with a
# protocol-enforced schema. Claude Sonnet 4.6 (and later) MUST emit a
# tool_use block matching this schema when called with tool_choice forced
# to marina_response. No string parsing, no preamble, no markdown fences.
#
# Only `intents`, `confidence`, `reply`, `requires_human` are REQUIRED;
# the rest default via _RESPONSE_DEFAULTS + inline defaults in process_message.
# Keeping the required set minimal matches the pre-Brief-174 behaviour where
# Claude could emit a subset of fields and the parser filled in the rest.
MARINA_TOOL = {
    "name": "marina_response",
    "description": (
        "Emit a structured response to the customer's message. This is the "
        "ONLY way to reply — do not emit free text. Populate the fields you "
        "have evidence for; leave others at their defaults. The `reply` field "
        "is what the customer sees."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intents": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["booking", "inquiry", "cancellation", "reschedule",
                             "complaint", "social", "off_topic"],
                },
                "description": "One or more intent labels for this message.",
            },
            "fields": {
                "type": "object",
                "description": "Extracted booking fields. Only include fields with explicit evidence from the customer.",
                "properties": {
                    "service_name": {"type": "string"},
                    "service_key": {"type": "string", "description": "Exact key from the services list."},
                    "date": {"type": "string", "description": "YYYY-MM-DD format."},
                    "guests": {"type": "integer"},
                    "customer_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "special_requests": {"type": "string"},
                    "slot_time": {"type": "string", "description": "HH:MM format."},
                },
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "reply": {
                "type": "string",
                "description": "The actual reply text shown to the customer. Write naturally, in the customer's language.",
            },
            "reply_hold_failed": {
                "type": "string",
                "description": "Optional — only when setting booking_confirmed=true. Apologetic message if the slot is unavailable.",
            },
            "clarifications_needed": {
                "type": "array",
                "items": {"type": "string"},
            },
            "requires_human": {
                "type": "boolean",
                "description": "Set true for complaints, refunds, cancellations, or explicit human requests.",
            },
            "flags": {
                "type": "object",
                "description": "Internal state flags Marina uses for orchestration.",
                "properties": {
                    "booking_confirmed": {"type": "boolean"},
                    "awaiting_booking_confirmation": {"type": "boolean"},
                    "needs_child_ages": {"type": "boolean"},
                    "needs_escalation_email": {"type": "boolean"},
                    "large_group": {"type": "boolean"},
                },
            },
            "semi_escalation": {
                "type": "boolean",
                "description": "Set true only for specific factual questions Marina cannot answer from available context.",
            },
            "relay_question": {
                "type": "string",
                "description": "Exact question to relay to the human team. Only present when semi_escalation is true.",
            },
            "internal_note": {
                "type": "string",
                "description": "One sentence for the operator log. Never shown to the customer.",
            },
        },
        "required": ["intents", "confidence", "reply", "requires_human"],
    },
}
```

### Step 2: Rewrite `process_message` to use tool use

**File:** `wtyj/agents/marina/marina_agent.py`
**Location:** the `try:` block inside `process_message`, currently at lines 700-757.

Replace the existing block (lines 700-757) with this structure. Keep the outer function signature, fallback dict, and exception path identical. Only the try body changes.

Replace these lines:
```python
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
            bm_logger.log("api_usage", ...)

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())

        result = json.loads(raw)

        if not isinstance(result, dict):
            bm_logger.log("claude_response_invalid", ...)
            return fallback
```

With this:
```python
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            tools=[MARINA_TOOL],
            tool_choice={"type": "tool", "name": "marina_response"},
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Log API token usage
        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("api_usage",
                input_tokens=_usage.input_tokens,
                output_tokens=_usage.output_tokens,
                model="claude-sonnet-4-6",
                channel=channel,
                from_id=from_email[:50])

        # Brief 174: tool_choice forces Claude to emit a single tool_use block.
        # Extract its input — already a dict, no parsing needed.
        tool_use_block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if tool_use_block is None:
            # Should be impossible with forced tool_choice, but guard anyway.
            bm_logger.log("claude_no_tool_use_block",
                          content_types=[b.type for b in response.content],
                          channel=channel, from_id=from_email[:50])
            return fallback
        result = dict(tool_use_block.input)
```

Keep these lines IMMEDIATELY AFTER the new `result = dict(tool_use_block.input)` block (they already exist, unchanged):

```python
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
                          channel=channel, from_id=from_email[:50])
            return fallback

        return result
```

Note: the `raw_preview=raw[:300]` argument on `claude_empty_reply` must be removed (there is no `raw` anymore). Replace with `input_preview=str(result)[:200]` for debuggability.

### Step 3: Preserve service aliases + delete the JSON format block from the prompt

**File:** `wtyj/agents/marina/marina_agent.py`

**CRITICAL CONTEXT (from reviewer round 1):** the JSON format block at lines 495-534 contains `{_build_service_alias_text()}` at line 522. This is the ONLY place in the file where that helper is invoked — `_SKIP_TOP_LEVEL` at line 32 explicitly excludes `service_aliases` from auto-injection via `_build_client_context()` because it's already injected via the format block. If I just delete the block, Marina loses the customer-wording → service_key mapping ("klein" → `klein_curacao`, "sunset" → `sunset_cruise`, all 21 aliases from `clients/bluemarlin/config/client.json`). This would silently break `service_key` extraction — ironically breaking the exact capability ash9772's stuck case needs.

**Fix:** replace the JSON format block with a new SERVICE ALIASES section that preserves the helper invocation. The tool schema replaces the field spec; the alias text gets its own dedicated section.

**Edit 3a:** replace the JSON format block. Find the text starting with `"Respond with ONLY a JSON object. No explanation. No markdown. No code fences. Just the JSON."` in `_build_system_prompt`. Using text-based find-and-replace (do NOT rely on line numbers):

Locate the existing block starting with `Respond with ONLY a JSON object.` and ending with the `}}"""` that closes the f-string. Replace the entire section (from `Respond with ONLY a JSON object...` through `}}` immediately before `"""`) with:

```
SERVICE ALIASES: When populating the service_key field in your tool call, use the exact key from this mapping. Match the customer's wording to the closest key:

{_build_service_alias_text()}

Only include service_key if you're certain. If the customer's description is ambiguous, omit it and ask.
"""
```

Critical:
- Keep the final `"""` that terminates the f-string. Only the BODY inside the triple-quote changes.
- Keep `{_build_service_alias_text()}` as an f-string interpolation (unescaped single braces).
- The new section uses single `{...}` for the helper call, not `{{...}}`.
- All OTHER prompt sections (AGENT PERSONA, BOOKING BEHAVIOUR, BOOKING VALIDATION, CONFIRMATION WORDING, HARD REFUSAL RULES, SEMI-ESCALATION, etc.) stay exactly as they are — only the "Respond with ONLY a JSON object..." spec + the JSON body template are removed.

After the edit, verify with grep:
```bash
grep -n "_build_service_alias_text" wtyj/agents/marina/marina_agent.py
```
Should still show ONE occurrence (the f-string interpolation in the new SERVICE ALIASES section) plus the function definition itself. If it shows zero invocations, the edit broke the interpolation — fix it.

**Edit 3b:** remove `import re` at line 7. After Step 2's parser rewrite, `re.sub` is no longer called anywhere in marina_agent.py (`re.` appears nowhere else in the file — verified by grep before drafting this brief). Deleting the import cleans the file without affecting behaviour.

Keep `import json` at line 5 — `json.dumps` is still used in `_build_client_context` and `_build_user_prompt` for serializing sections. Verify with `grep -n "json\." wtyj/agents/marina/marina_agent.py` — expected: multiple `json.dumps(...)` invocations, zero `json.loads(...)` after Step 2.

### Step 4: New test file `wtyj/tests/marina/test_174_tool_use.py`

```python
"""Tests for Brief 174 — Marina tool use migration.

Covers:
- MARINA_TOOL schema shape (required fields, enum constraints)
- process_message extracts tool_use input correctly
- process_message applies defaults for optional fields missing from tool_use
- process_message falls back on empty reply after defaults
- process_message falls back on Anthropic exception (unchanged behaviour)
- process_message logs a warning when no tool_use block returned (shouldn't happen with tool_choice forced)
"""
import os
from unittest.mock import patch, MagicMock

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent


def test_marina_tool_schema_has_required_fields():
    """Brief 174: the schema must mark intents, confidence, reply, requires_human as required."""
    schema = marina_agent.MARINA_TOOL
    assert schema["name"] == "marina_response"
    required = schema["input_schema"]["required"]
    assert set(required) == {"intents", "confidence", "reply", "requires_human"}


def test_marina_tool_schema_intents_enum():
    """Brief 174: intents field must restrict to the known intent labels."""
    schema = marina_agent.MARINA_TOOL
    intents_prop = schema["input_schema"]["properties"]["intents"]
    assert intents_prop["type"] == "array"
    assert set(intents_prop["items"]["enum"]) == {
        "booking", "inquiry", "cancellation", "reschedule",
        "complaint", "social", "off_topic",
    }


def test_marina_tool_schema_confidence_enum():
    schema = marina_agent.MARINA_TOOL
    conf_prop = schema["input_schema"]["properties"]["confidence"]
    assert set(conf_prop["enum"]) == {"high", "medium", "low"}


def test_marina_tool_schema_has_all_fields_from_old_format():
    """Brief 174: schema properties must cover every field the old JSON format emitted.
    If a field is missing from the schema, Marina cannot emit it — breaks downstream code."""
    props = marina_agent.MARINA_TOOL["input_schema"]["properties"]
    # Top-level keys from the old prompt JSON format
    expected_top_level = {
        "intents", "fields", "confidence", "reply", "reply_hold_failed",
        "clarifications_needed", "requires_human", "flags",
        "semi_escalation", "relay_question", "internal_note",
    }
    assert expected_top_level.issubset(set(props.keys()))
    # Nested fields in `fields`
    field_props = props["fields"]["properties"]
    expected_fields = {
        "service_name", "service_key", "date", "guests",
        "customer_name", "phone", "email", "special_requests", "slot_time",
    }
    assert expected_fields.issubset(set(field_props.keys()))
    # Nested flags
    flag_props = props["flags"]["properties"]
    expected_flags = {
        "booking_confirmed", "awaiting_booking_confirmation",
        "needs_child_ages", "needs_escalation_email", "large_group",
    }
    assert expected_flags.issubset(set(flag_props.keys()))


def _mock_tool_use_response(tool_input, output_tokens=100):
    """Build a MagicMock that looks like an Anthropic response with a single tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "marina_response"
    tool_block.input = tool_input

    resp = MagicMock()
    resp.content = [tool_block]
    resp.usage = MagicMock(input_tokens=500, output_tokens=output_tokens)
    resp.stop_reason = "tool_use"
    return resp


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_extracts_tool_use_input(mock_cls):
    """Brief 174: process_message returns the tool_use input dict directly."""
    mock_resp = _mock_tool_use_response({
        "intents": ["inquiry"],
        "fields": {"customer_name": "Alice"},
        "confidence": "high",
        "reply": "Hello Alice! How can I help?",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "Greeting",
    })
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = marina_agent.process_message("alice@test.com", "Hi", "Hello", {}, {})
    assert result["reply"] == "Hello Alice! How can I help?"
    assert result["intents"] == ["inquiry"]
    assert result["fields"]["customer_name"] == "Alice"


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_defaults_missing_optional_fields(mock_cls):
    """Brief 174: if Claude's tool_use omits an optional field (like 'clarifications_needed'),
    process_message defaults it via _RESPONSE_DEFAULTS. Claude only has to fill required fields."""
    mock_resp = _mock_tool_use_response({
        "intents": ["inquiry"],
        "confidence": "high",
        "reply": "Our trips run daily.",
        "requires_human": False,
        # No 'fields', 'flags', 'internal_note', or 'clarifications_needed'
    })
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = marina_agent.process_message("x@y.com", "Hi", "When do you run?", {}, {})
    # Required field preserved
    assert result["reply"] == "Our trips run daily."
    # Optional fields defaulted
    assert result["fields"] == {}
    assert result["flags"] == {}
    assert result["clarifications_needed"] == []
    assert result["internal_note"] == ""


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_falls_back_on_empty_reply(mock_cls):
    """Brief 174: if the tool_use has an empty reply field (even though it's required),
    process_message returns the fallback — an empty reply is useless to the customer."""
    mock_resp = _mock_tool_use_response({
        "intents": ["inquiry"],
        "confidence": "low",
        "reply": "",  # empty
        "requires_human": False,
    })
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = marina_agent.process_message("x@y.com", "Hi", "hello", {}, {})
    # Fallback reply (email default from fallback dict)
    assert "service" in result["reply"].lower() or "guests" in result["reply"].lower()


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_falls_back_on_anthropic_exception(mock_cls):
    """Brief 174: preserve the existing behaviour where an API exception triggers fallback."""
    mock_cls.return_value.messages.create.side_effect = Exception("API down")
    result = marina_agent.process_message("x@y.com", "Hi", "hello", {}, {})
    assert result["intents"] == ["inquiry"]
    # Email channel fallback
    assert "service" in result["reply"].lower() or "guests" in result["reply"].lower()


@patch("agents.marina.marina_agent.anthropic.Anthropic")
def test_process_message_falls_back_when_no_tool_use_block(mock_cls):
    """Brief 174: defensive — if Claude somehow returns a text block instead of tool_use
    (shouldn't happen with tool_choice forced, but guard the code path)."""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "some text"
    resp = MagicMock()
    resp.content = [text_block]
    resp.usage = MagicMock(input_tokens=500, output_tokens=50)
    mock_cls.return_value.messages.create.return_value = resp

    result = marina_agent.process_message("x@y.com", "Hi", "hello", {}, {})
    # Fallback, no crash
    assert result["internal_note"] == "Fallback response — Claude API call failed or returned unparseable output."
```

### Step 5: Update the existing tests that mock the Anthropic SDK at the text level

Three tests in two files need the mock updated to return a tool_use block instead of a text block. The tests' assertions (what they check) don't need to change — only the mock shape.

**File:** `wtyj/tests/social/test_069_whatsapp_agent.py`

Find `test_process_message_whatsapp_success` (around line 88). Current mock:
```python
mock_resp = MagicMock()
mock_resp.content = [MagicMock(text=json.dumps({
    "intents": ["inquiry"], "fields": {}, "confidence": "high",
    "reply": "Klein Curacao is $120 per adult!",
    "clarifications_needed": [], "requires_human": False,
    "flags": {}, "internal_note": ""
}))]
```

Replace with a tool_use-shaped mock:
```python
tool_block = MagicMock()
tool_block.type = "tool_use"
tool_block.name = "marina_response"
tool_block.input = {
    "intents": ["inquiry"], "fields": {}, "confidence": "high",
    "reply": "Klein Curacao is $120 per adult!",
    "clarifications_needed": [], "requires_human": False,
    "flags": {}, "internal_note": ""
}
mock_resp = MagicMock()
mock_resp.content = [tool_block]
```

The assertion `assert result["reply"] == "Klein Curacao is $120 per adult!"` stays identical.

Note: remove `import json` from the top of the test file IF it's only used for this mock. Check first.

**File:** `wtyj/tests/marina/test_marina_tone.py`

Find `test_response_defaults_missing_fields` (around line 70) and `test_response_empty_reply_returns_fallback` (around line 87). Both use the same pattern:
```python
mock_response = MagicMock()
mock_response.content = [MagicMock(text=some_json_string)]
```

Replace with the tool_use pattern from test_069 above. The `some_json_string` value gets parsed into a dict and passed as `tool_block.input`.

**Also in test_marina_tone.py:** delete `test_system_prompt_contains_json_format` (around line 23). This test asserts the system prompt contains `'"intents"'` and `'"reply"'` — after step 3 removes the JSON format section, those strings won't appear in the prompt anymore. The test's intent ("the response format spec exists") is now covered by the schema tests in test_174. Delete the function entirely.

**ALSO:** there is an `if __name__ == "__main__":` block at lines 134-152 of `test_marina_tone.py` that lists tests for direct-script execution. Line 138 references `test_system_prompt_contains_json_format` in the `tests = [...]` list. Delete that line as part of the same edit, otherwise running the file directly (`python test_marina_tone.py`) will raise NameError. pytest discovery won't hit this guard, so the regression suite still passes — but direct execution would break without this fix.

### Step 6: Run tests + regression

```bash
python3 -m pytest wtyj/tests/marina/test_174_tool_use.py -v --tb=short
python3 -m pytest wtyj/tests/social/test_069_whatsapp_agent.py -v --tb=short
python3 -m pytest wtyj/tests/marina/test_marina_tone.py -v --tb=short
python3 -m pytest wtyj/tests/ -q --tb=line
```

Expected: 817 baseline - 1 deleted test (`test_system_prompt_contains_json_format`) + 9 new tests = **825 total passing, 0 failures**.

Test count breakdown:
- 4 schema tests: `has_required_fields`, `intents_enum`, `confidence_enum`, `has_all_fields_from_old_format`
- 1 happy-path extraction: `extracts_tool_use_input`
- 1 defaults test: `defaults_missing_optional_fields`
- 1 empty-reply fallback: `falls_back_on_empty_reply`
- 1 exception fallback: `falls_back_on_anthropic_exception`
- 1 defensive guard: `falls_back_when_no_tool_use_block`
= **9 new tests**.

### Step 7: Commit source + push BEFORE deploying

Per the calibrated workflow in `.claude/commands/brief.md:75-82`: commit and push source first, THEN fire background deploy. The VPS `git pull` needs the new commit on origin.

```bash
cd /Users/benson/Projects/bluemarlin-agent
git add wtyj/agents/marina/marina_agent.py \
        wtyj/tests/marina/test_174_tool_use.py \
        wtyj/tests/marina/test_marina_tone.py \
        wtyj/tests/social/test_069_whatsapp_agent.py \
        wtyj/briefs/marina_brief_174_tool_use_migration.md
git commit -m "Brief 174: Marina tool use migration (root fix for parse failures)"
git push origin main
```

### Step 8: Background deploy

Using `Bash` with `run_in_background: true`:
```
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

While it runs (~90s), proceed to step 9/10/11 in parallel.

### Step 9: Write marina_output_174.md

Per `.claude/commands/brief.md:52-70`: ~250 words, template-compliant. What was done (paragraph), test results (one line), unexpected findings (only if any), deployment commit SHA.

### Step 10: Append system_state.md entry

~200 words max. Decision in 2-3 sentences, outcome in 2-3 sentences.

### Step 11: Add lessons entry to marina_lessons.md

This is a **problem brief** (real customer got stuck, root cause hunt, protocol-level fix). The lessons entry must be 10+ lines per the workflow rule. Cover: what happened (Anne-Sophie thread stuck), why it failed (Claude preamble vs convention-based contract), what we did (tool use migration), the principle (prefer protocol enforcement over convention), what to watch for (any future API contract based on "Claude will obey the prompt" is fragile — prefer schema enforcement).

### Step 12: Verify deploy succeeded before committing post-exec docs

Check BashOutput on the deploy job. If still running, WAIT. Once complete:
```bash
ssh root@108.61.192.52 "curl -s http://localhost:8001/health && curl -s http://localhost:8002/health"
```
Both must return `{"status":"ok"}`. If either fails: STOP, fix, re-run. Do NOT commit post-exec docs claiming success.

### Step 13: Commit post-exec docs

```bash
git add wtyj/briefs/marina_output_174.md \
        wtyj/briefs/system_state.md \
        wtyj/briefs/marina_lessons.md
git commit -m "Brief 174 post-execution: output + system_state + lessons"
git push origin main
```

### Step 14: TLDR

Per workflow rule 17. Plain English. What changed (files), what it does now, what the user should notice.

## Tests

Full list already spec'd inline above. Summary:

**New (`test_174_tool_use.py`, 8 tests):**
1. `test_marina_tool_schema_has_required_fields` — schema declares correct required set
2. `test_marina_tool_schema_intents_enum` — intents field restricts to known labels
3. `test_marina_tool_schema_confidence_enum` — confidence field restricts to high/medium/low
4. `test_marina_tool_schema_has_all_fields_from_old_format` — no field lost in migration
5. `test_process_message_extracts_tool_use_input` — happy path, dict flows through
6. `test_process_message_defaults_missing_optional_fields` — sparse tool_use gets defaults
7. `test_process_message_falls_back_on_empty_reply` — empty reply → fallback
8. `test_process_message_falls_back_on_anthropic_exception` — API exception → fallback (unchanged behaviour)
9. `test_process_message_falls_back_when_no_tool_use_block` — defensive no-crash guard

(9 tests total, corrected count)

**Updated:**
- `test_069_whatsapp_agent.py::test_process_message_whatsapp_success` — mock reshape to tool_use
- `test_marina_tone.py::test_response_defaults_missing_fields` — mock reshape
- `test_marina_tone.py::test_response_empty_reply_returns_fallback` — mock reshape

**Deleted:**
- `test_marina_tone.py::test_system_prompt_contains_json_format` — the checked strings no longer in prompt after step 3

Must-not-regress: all 15+ tests that mock `marina_agent.process_message` at the function boundary (test_068, test_070, test_077, test_125, test_135, etc.) continue to pass unchanged because they mock the return value, not the internals.

## Success Condition

1. `MARINA_TOOL` constant exists in marina_agent.py with all 11 top-level schema properties
2. `process_message` calls `client.messages.create` with `tools=[MARINA_TOOL]` and `tool_choice={"type": "tool", "name": "marina_response"}`
3. `json.loads` removed from the success path in `process_message`
4. Markdown-fence-stripping regexes removed from the success path
5. "Respond with ONLY a JSON object. No explanation. No markdown..." section deleted from `_build_system_prompt`
6. 9 new tests passing in test_174_tool_use.py
7. 3 updated tests (test_069 + 2 in test_marina_tone) passing with new mock shape
8. 1 deleted test (test_system_prompt_contains_json_format)
9. Full regression: **825 passing, 0 failures** (817 baseline + 9 new - 1 deleted)
10. Both VPS containers healthy post-deploy (`/health` returns `{"status":"ok"}`)
11. A live inbound for ash9772@gmail.com with the exact same customer message would now receive a proper reply instead of the generic fallback. (Verified via spot-test before writing this brief; Marina now returns a tool_use block with the correct dict.)

## Rollback

Single commit. `git revert <sha> && git push` restores the pre-Brief-174 state cleanly. No schema migration to reverse, no data change. If the deploy is broken, also run `git revert` on the VPS and rebuild containers. The git tag `pre-brief-174-tool-use` can be added before committing for extra rollback safety.
