# OUTPUT 059 — Marina Tone Polish

## What was done

### Step 1 — client.json: Updated marina_persona
Replaced the one-sentence persona with a richer description: hospitality focus,
guest-awareness (booking time together, family, memories), tone mirroring, and
the existing "never guesses" trait.

### Step 2 — marina_agent.py: Added WRITING STYLE section
Inserted a ~40-line WRITING STYLE block after PERSONA and before LANGUAGE RULE in
`_build_prompt()`. Covers:
- Write as a real person, not a chatbot
- Mirror sender tone (warm→warmer, formal→direct)
- Match reply length to incoming email complexity
- Banned stock phrases (10 listed explicitly)
- Banned AI habits (em dashes, decorative bold, excessive bullets, semicolons)
- Emoji rule: allowed in booking confirmations only, otherwise mirror sender
- Self-check before output: "Does this sound like a real person?"

### Step 3 — File header updated
marina_agent.py: Brief 058 → Brief 059

## Files changed
- `config/client.json` — marina_persona value
- `src/marina_agent.py` — WRITING STYLE prompt section + header

## Test results
```
PASS: test_prompt_contains_writing_style_section
PASS: test_writing_style_before_language_rule
PASS: test_stock_phrases_listed_in_prompt
PASS: test_ai_habits_section_present
PASS: test_updated_persona_in_client_json
PASS: test_self_check_instruction_present

6/6 tests passed.
```

## Anything unexpected
Nothing unexpected. Prompt-only change, no Python logic modified.
