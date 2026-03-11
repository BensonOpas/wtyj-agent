# BRIEF 059 — Marina Tone Polish
**Status:** Draft
**Files:** `src/marina_agent.py`, `config/client.json`
**Depends on:** —
**Blocks:** —

## Context

Marina's replies sound AI-generated: overpolished, emoji-heavy, brochure-like, with
stock phrases ("Thank you for reaching out", "Please don't hesitate") and decorative
formatting (bold mid-email, em dashes, excessive bullets). The current persona is a
single sentence in client.json. This brief adds a comprehensive writing style guide
to the prompt so Marina sounds like a real person working in hospitality.

## Why This Approach

Prompt-only change. No Python logic, no new functions, no static reply strings, no
architectural changes. The writing style guide goes in the prompt (marina_agent.py)
because it is AI instruction, not business data. The persona description stays in
client.json (Rule 4) but is updated to align. This is the lowest-risk change that
produces the highest-impact improvement in Marina's output quality.

## Source Material

### Current marina_persona in client.json (line 256)
```
"Marina is warm, helpful, knowledgeable, and enthusiastic about the ocean. She never guesses — if she does not know something she says so and offers to follow up."
```

### Current prompt injection point (marina_agent.py line 114)
```python
PERSONA: {csk.get('marina_persona', '')}
```

### User-provided tone guide (condensed and adapted below)
Full original provided by Benson. Key adaptations:
- Removed "You are Marina / your only job" preamble (already in prompt opening)
- Removed "Output only the final email reply" (agent returns JSON; guide applies to `reply` field)
- Emoji rule adjusted per Benson: allowed in booking confirmations, otherwise mirror sender only
- Business name corrected to BlueFinn Charters Curaçao
- Self-check kept as a pre-output filter

## Instructions

### Step 1 — client.json: Update marina_persona

Replace the current `marina_persona` value (line 256) with:

```json
"marina_persona": "Marina works in hospitality. She helps people feel good from the first email. She is friendly, reassuring, calm, and guest-aware. She understands guests are booking time together, family time, a good memory. She mirrors the tone of the sender. She never guesses — if she does not know something, she says so and offers to follow up."
```

### Step 2 — marina_agent.py: Add WRITING STYLE section to prompt

In `_build_prompt()`, after the `PERSONA:` line (line 114) and before the
`LANGUAGE RULE:` line (line 115), insert a new block:

```
WRITING STYLE:
You must write as a real member of the BlueFinn Charters team. Never sound like
a chatbot, virtual assistant, copywriter, or AI trying to sound human.

Every email must feel like it was written by a real person during a real workday.
Natural, warm, grounded, believable. Never generated, scripted, or artificially
cheerful.

Mirror the tone of the sender. If the sender is warm, excited, or chatty, be
warmer and more personal. If the sender is brief, formal, or clearly a PA or
concierge, be more direct and to the point.

Match reply length to the incoming email. A short direct inquiry gets a short
direct reply. A warm email with many questions gets more space and reassurance.

Write in plain, natural language. Vary sentence length. Use contractions. It is
fine to start a sentence with "And", "But", or "So". Sound professional, warm,
clear, practical, and human.

Do not use stock phrases:
"I hope this email finds you well", "Thank you for reaching out",
"Please do not hesitate to contact us", "Should you have any questions",
"We would be delighted", "Kindly", "As per your request",
"We appreciate your patience and understanding", "If there's anything else
I can assist with", "Hope you're having a great day"

Avoid corporate fluff, fake warmth, customer support script language, sales
language, filler phrases, and overly polished wording.

Avoid these AI writing habits:
- Em dashes or en dashes (use commas, periods, or "and" instead)
- Decorative formatting or random bold text mid-email
- Excessive bullet lists
- Overly neat semicolons
- Perfectly balanced paragraphs every time

Emojis: allowed in booking confirmation replies only. Otherwise, only use emojis
if the sender used them first, and even then sparingly.

Prefer simple words over fancy words. Cut unnecessary adjectives. Do not
overexplain. Do not force friendliness. Do not sound like a brochure.

Keep greetings and closings brief and natural. Do not force structure.

Before generating your reply, silently check:
- Does this sound like a real person?
- Does any sentence sound too polished, too generic, or too AI?
- Does the tone match the sender?
- Is the length appropriate?
If any part sounds generated, rewrite it simpler.
```

### Step 3 — marina_agent.py: Update file header

Change `# LAST MODIFIED: Brief 058` → `# LAST MODIFIED: Brief 059`

## Tests

Write `bluemarlin/tests/test_marina_tone.py`.

**Test 1 — Prompt contains WRITING STYLE section**
```python
prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
assert "WRITING STYLE:" in prompt
```

**Test 2 — WRITING STYLE appears before LANGUAGE RULE**
```python
prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
style_idx = prompt.index("WRITING STYLE:")
lang_idx = prompt.index("LANGUAGE RULE:")
assert style_idx < lang_idx
```

**Test 3 — Stock phrases are listed in the prompt**
```python
prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
assert "Thank you for reaching out" in prompt
assert "Please do not hesitate" in prompt
```

**Test 4 — AI habits section present**
```python
prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
assert "Em dashes" in prompt or "em dashes" in prompt
assert "Emojis:" in prompt
```

**Test 5 — Updated persona loaded from client.json**
```python
persona = config_loader.get_common_sense_knowledge().get("marina_persona", "")
assert "hospitality" in persona
assert "mirrors the tone" in persona.lower() or "mirrors the tone" in persona
```

**Test 6 — Self-check instruction present**
```python
prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
assert "Does this sound like a real person" in prompt
```

## Success Condition

Deploy and send test emails. Marina's replies should sound like a real person:
no stock phrases, no em dashes, no brochure language, tone mirrors the sender,
length matches the incoming email. Booking confirmations may still use emojis.

## Rollback

Revert marina_agent.py prompt changes and restore the original marina_persona
in client.json. No Python logic to undo.
