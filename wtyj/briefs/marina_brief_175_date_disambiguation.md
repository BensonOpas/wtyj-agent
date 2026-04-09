# BRIEF 175 — Marina date disambiguation ("next [day]" semantic fix)
**Status:** Draft | **Files:** marina_agent.py, test_175 (new) | **Depends on:** 174 | **Blocks:** —

## Context

Research mode and Brief 174 exposed a secondary issue alongside the parser bug on Anne-Sophie Hammar's stuck email thread. When she wrote *"Klein curacao, next Saturday, 7 people"* on Thursday April 9, 2026, Claude Sonnet 4.6 interpreted "next Saturday" as **April 18** (one week after the coming Saturday) instead of **April 11** (the immediately upcoming Saturday). I verified this live twice — once during the research replay and again during Brief 174's tool-use spot-test. In both cases, Claude reasoned through the ambiguity out loud then committed to April 18.

Anne-Sophie almost certainly meant April 11. When tourists say "next Saturday" on a Thursday, the dominant English interpretation in a booking context is "the coming Saturday" (2 days away), not "the Saturday after that" (9 days away). Tourists are usually making plans for the near-term during their trip, not nine days out. Even in dialects where "next Saturday" can mean "a week from this coming Saturday", the ambiguity demands confirmation, not a silent guess.

Brief 174 fixed the parser so Marina can successfully emit a response — but the response will still contain the wrong date on any "next [day]" query. Customer asks for April 11, Marina books April 18, customer has to correct, round-trip of confusion.

**This is a semantic issue, not a format issue.** Brief 174 gave Marina a reliable output channel. Brief 175 teaches Marina how to interpret ambiguous dates correctly within that channel.

The current BOOKING VALIDATION block at `wtyj/agents/marina/marina_agent.py:469-490` has no rule on ambiguous date phrases. The FIELD EXTRACTION RULES block I added in Brief 174 at lines ~588-608 says *"Convert any natural language date ('April 20', 'next Saturday', 'in two weeks') to YYYY-MM-DD using today's date as reference"* — it acknowledges "next Saturday" as a thing to convert but gives no guidance on HOW to resolve the ambiguity.

## Why This Approach

**Chosen — prompt rule with two parts: default interpretation + transparent confirmation.**

Tell Marina that "next [day]" defaults to the NEAREST upcoming instance, AND whenever she resolves an ambiguous date phrase, she must state her interpretation clearly in her reply so the customer can correct it without another round-trip of "what date did you mean?".

Example behavior after the fix (replay of Anne-Sophie's message):
- Customer: *"Klein curacao, next Saturday, 7 people"*
- Marina's internal resolution: `date = 2026-04-11` (nearest upcoming Saturday from Thursday April 9)
- Marina's reply: *"The Klein Curaçao Trip runs daily, so Saturday April 11 works. I'm reading 'next Saturday' as this coming Saturday (April 11) — let me know if you meant a different date. It's a full-day trip... There are two departures from Jan Thiel Beach: 08:00 aboard BlueMarlin 2, 08:30 aboard BlueMarlin 1. Which works better for your group?"*

The customer sees the interpretation inline. If they meant April 18, one correction reply fixes it. If they meant April 11 (the common case), the booking proceeds. Either way, no silent error.

**Considered and rejected alternatives:**

1. **Ask for clarification before resolving.** Would work but costs a round-trip EVEN IN THE COMMON CASE where the customer meant the nearest Saturday. That's 2x worse UX for ~80% of users to protect ~20%. Transparent confirmation is better: guess right for the majority, expose the guess so the minority can correct cheaply.

2. **Hardcode a date-parsing library (dateparser, parsedatetime).** Python-side natural language date parsing. Rejected because (a) violates Rule 2 (no Python interpretation of customer text) — the whole point of Marina is that Claude handles language, Python handles structure; (b) dateparser has the same "next Saturday" ambiguity and would need the same disambiguation rule; (c) adds a new dependency for one prompt rule.

3. **Tool schema constraint.** Add a description like *"date: YYYY-MM-DD, must be the nearest upcoming instance when the customer used a relative phrase"*. Tool schema descriptions ARE respected by Claude, but they're better for format constraints than semantic rules. A dedicated prompt section is clearer.

4. **Add to BOOKING VALIDATION as rule 2.5.** That section has numbered validation checks. I considered adding "2.5 AMBIGUOUS DATE" but the existing checks are about REJECTING or ASKING (past date, wrong day, multi-departure). The new rule is about RESOLVING. Different operation, different section. Cleaner as a standalone rule after BOOKING VALIDATION but before HARD REFUSAL RULES.

The chosen approach: add a new DATE AMBIGUITY RESOLUTION block between BOOKING VALIDATION and HARD REFUSAL RULES in `_build_system_prompt`.

## Instructions

### Step 1: Add the DATE AMBIGUITY RESOLUTION block

**File:** `wtyj/agents/marina/marina_agent.py`

Find the existing BOOKING VALIDATION section ending at `STATE MANAGEMENT: Python still manages awaiting_booking_confirmation, hold creation, and booking_confirmed. Do not set these flags yourself unless an ACTION instruction in the user prompt explicitly tells you to.` (around line 490), which is followed by a blank line and then `HARD REFUSAL RULES —` (around line 492).

Insert a new DATE AMBIGUITY RESOLUTION block between `STATE MANAGEMENT` and `HARD REFUSAL RULES`. The exact text to insert:

```

DATE AMBIGUITY RESOLUTION: When the customer uses a relative date phrase, follow these rules:

- **"next [day]"** (e.g. "next Saturday", "next Friday", "next Tuesday") = the NEAREST upcoming instance of that day. If today is Thursday and the customer says "next Saturday", that means THIS coming Saturday (2 days away), NOT the Saturday of the following week. This is the dominant interpretation in a booking context — tourists are making near-term plans.

- **"this [day]"** = same as "next [day]": the nearest upcoming instance.

- **"[day] week"** or **"a week from [day]"** (e.g. "Saturday week", "a week from Friday") = 7 days AFTER the nearest upcoming instance of that day. Only use this interpretation when the customer is explicit about "week".

- **"in [N] days"**, **"in [N] weeks"**, **"[N] days from now"** = add N days/weeks to today. Straightforward math.

- **"tomorrow"** / **"day after tomorrow"** = today + 1 or today + 2.

- **"this weekend"** without a specific day = ambiguous (could be Saturday or Sunday). Resolve to the nearest upcoming Saturday AND mention both options in your reply.

WHEN YOU RESOLVE AN AMBIGUOUS DATE, you MUST state your interpretation inline in your reply so the customer can correct you without another round-trip. Example phrasings (translate to the customer's language):

- "I'm reading 'next Saturday' as April 11 — let me know if you meant a different date."
- "Going with Saturday the 11th. Let me know if that's wrong."
- "Saturday April 11 it is — shout if I misread that."

Do NOT resolve ambiguity silently. Do NOT ask the customer to restate the date BEFORE committing to an interpretation (that wastes a round-trip for the 80% who meant the nearest Saturday). Always guess the most likely interpretation AND expose the guess.

If the date phrase is so vague that you genuinely cannot guess (e.g. "sometime next month", "in the summer", "soon"), omit the date field entirely and ask for a specific date in clarifications_needed — that's the existing behaviour from FIELD EXTRACTION RULES below.

```

Note the leading and trailing blank lines — they separate the new block from `STATE MANAGEMENT` above and `HARD REFUSAL RULES` below. Match the formatting of the existing sections (bold-free, no markdown headers, uppercase section names followed by a colon and prose).

### Step 2: Tests

**File:** `wtyj/tests/marina/test_175_date_disambiguation.py` (new)

Three tests. Two are prompt-content checks verifying the new block is present and covers the key cases. One is an integration test that replays Anne-Sophie's message against a mocked Claude that returns April 11 (the correct interpretation), verifying the dict flows through with the right date.

```python
"""Tests for Brief 175 — Marina date disambiguation ('next [day]' semantic fix)."""
import os
from unittest.mock import patch, MagicMock

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent


# --- Prompt content tests ---

def test_system_prompt_has_date_ambiguity_rule():
    """Brief 175: the system prompt must contain the DATE AMBIGUITY RESOLUTION block."""
    prompt = marina_agent._build_system_prompt({}, channel="email")
    assert "DATE AMBIGUITY RESOLUTION" in prompt
    # The key interpretation rule for "next [day]"
    assert "NEAREST upcoming instance" in prompt
    # The confirmation-in-reply rule
    assert "state your interpretation inline" in prompt


def test_system_prompt_has_next_saturday_example():
    """Brief 175: the rule must include a Thursday → 'next Saturday' = 2 days away
    example, since that's the exact ambiguity Anne-Sophie hit."""
    prompt = marina_agent._build_system_prompt({}, channel="email")
    assert "next Saturday" in prompt
    assert "2 days away" in prompt or "coming Saturday" in prompt


# --- Integration test: Anne-Sophie scenario with correct date ---

def _mock_tool_use_response(tool_input, output_tokens=100):
    """Build a MagicMock Anthropic response containing a single tool_use block."""
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
def test_ash9772_replay_with_corrected_date(mock_cls):
    """Brief 175: replay Anne-Sophie's message with a mocked Claude that resolves
    'next Saturday' correctly (as April 11, not April 18). Verify the dict flows
    through process_message with the correct date and the inline confirmation
    phrasing in the reply."""
    mock_resp = _mock_tool_use_response({
        "intents": ["booking"],
        "fields": {
            "service_name": "Klein Curaçao Trip",
            "service_key": "klein_curacao",
            "date": "2026-04-11",  # the corrected nearest-Saturday interpretation
            "guests": 7,
            "customer_name": "Anne-Sophie Hammar",
            "email": "ash9772@gmail.com",
            "phone": "+599 9 686 5664",
        },
        "confidence": "high",
        "reply": (
            "The Klein Curaçao Trip runs daily, so Saturday April 11 works. "
            "I'm reading 'next Saturday' as this coming Saturday (April 11) — "
            "let me know if you meant a different date. "
            "There are two departures from Jan Thiel Beach: 08:00 aboard "
            "BlueMarlin 2, 08:30 aboard BlueMarlin 1. Which works better?"
        ),
        "clarifications_needed": ["Which departure time?"],
        "requires_human": False,
        "flags": {},
        "internal_note": "Resolved 'next Saturday' as April 11 (nearest upcoming).",
    })
    mock_cls.return_value.messages.create.return_value = mock_resp

    result = marina_agent.process_message(
        "ash9772@gmail.com", "Re: Request",
        "Next Saturday and the trip to Klein curacao",
        {}, {}, channel="email",
    )
    assert result["fields"]["date"] == "2026-04-11"
    assert result["fields"]["service_key"] == "klein_curacao"
    assert result["fields"]["guests"] == 7
    # Inline confirmation phrasing — the customer can correct without round-trip
    assert "April 11" in result["reply"]
    assert "let me know" in result["reply"].lower() or "shout if" in result["reply"].lower()
```

### Step 3: Run tests + regression

```bash
python3 -m pytest wtyj/tests/marina/test_175_date_disambiguation.py -v --tb=short
python3 -m pytest wtyj/tests/ -q --tb=line
```

Expected: 3 new tests pass, **828 total passing** (825 baseline from Brief 174 + 3 new).

### Step 4: Commit + push source BEFORE deploy

```bash
git add wtyj/agents/marina/marina_agent.py \
        wtyj/tests/marina/test_175_date_disambiguation.py \
        wtyj/briefs/marina_brief_175_date_disambiguation.md
git commit -m "Brief 175: Marina date disambiguation ('next [day]' rule)"
git push origin main
```

### Step 5: Background deploy

```
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

With `run_in_background: true`. Proceed to step 6/7/8 while it runs.

### Step 6: Write marina_output_175.md

~250 words, template-compliant. See `.claude/commands/brief.md` for the template.

### Step 7: Append system_state.md

One paragraph, max ~200 words.

### Step 8: Write lessons entry

This is a **smooth brief** (prompt-only change, no refactor, independent of upstream work). 3-5 lines per the calibrated rules: decision + outcome + any non-obvious technique.

### Step 9: Verify deploy + commit post-exec docs

Check BashOutput. If healthy on both containers, commit post-exec docs and push.

### Step 10: TLDR

## Success Condition

1. `DATE AMBIGUITY RESOLUTION` block present in the output of `_build_system_prompt({}, channel="email")`
2. Block contains the "NEAREST upcoming instance" rule and the "state your interpretation inline" requirement
3. The "next Saturday" example is present
4. 3 new tests passing in `test_175_date_disambiguation.py`
5. Full regression: **828 passing, 0 failures** (825 baseline + 3 new)
6. Both containers healthy post-deploy

## Rollback

Single commit. `git revert <sha> && git push` removes the prompt addition cleanly. No schema changes, no data migration, no risk to existing customers.
