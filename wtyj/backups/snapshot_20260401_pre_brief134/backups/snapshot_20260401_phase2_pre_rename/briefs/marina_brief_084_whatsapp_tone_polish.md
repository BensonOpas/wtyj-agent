# BRIEF 084 — WhatsApp Reply Tone Polish
**Status:** Approved | **Files:** `agents/marina/marina_agent.py`, `config/client.json`, `tests/marina/test_marina_tone.py` | **Depends on:** 083 | **Blocks:** —

## Context
Marina's WhatsApp replies are functionally correct but too polished — they sound like customer support software, not a real person texting from work. Replies are often 80-120 words when 30-50 would do. Filler phrases like "No worries at all! If you'd like to look at something else or come back to it later, just let me know 😊" should be "No worries! Let me know if you want something else."

## Why This Approach
The WhatsApp writing style is controlled by ONE block in `_build_system_prompt()` (marina_agent.py lines 83-97). Replacing this block with tighter rules — word count caps, good/bad examples, and an explicit phrase blacklist — changes how Claude writes without touching any behavioral logic. The email style block is untouched. No new files, no structural changes.

The alternative (separate prompt file) was rejected — it would strip out the shared behavioral rules (booking, escalation, JSON format) and break the agent entirely.

## Source Material

### Current WhatsApp writing style block — marina_agent.py lines 83-97
```python
    if channel == "whatsapp":
        writing_style_block = (
            "WRITING STYLE — WHATSAPP:\n"
            "This is WhatsApp, not email. Keep replies short and natural.\n"
            "- Simple question → 1-2 sentences\n"
            "- Detailed question → short paragraph, no more\n"
            "- No signatures, no sign-offs, no \"Warm regards\"\n"
            "- No greeting unless the customer greeted first\n"
            "- Use contractions. Be casual. Match the sender's energy.\n"
            "- Emojis: sparingly, only if the sender used them first or if it genuinely fits\n"
            "\n"
            "Mirror the sender's tone and length. Short question gets a short answer.\n"
            "\n"
            "AVOID: em dashes, en dashes, \"Shall I\", \"I'd be happy to\", \"Great choice\",\n"
            "\"Amazing\", \"Absolutely\", forced enthusiasm, reasoning out loud."
        )
```

### Current persona — client.json line 279
```json
"marina_persona": "Marina works in hospitality. She helps people feel good from the first email. She is friendly, reassuring, calm, and guest-aware. She understands guests are booking time together, family time, a good memory. She mirrors the tone of the sender. She never guesses — if she does not know something, she says so and offers to follow up."
```

## Instructions

### Step 1 — Replace WhatsApp writing style block in marina_agent.py

Replace lines 83-97 (the `if channel == "whatsapp":` branch content) with:

```python
    if channel == "whatsapp":
        writing_style_block = (
            "WRITING STYLE — WHATSAPP:\n"
            "You are texting from work, not writing an email. Sound like a real person.\n"
            "\n"
            "LENGTH:\n"
            "- Normal reply: under 50 words\n"
            "- Booking flow: under 80 words\n"
            "- Only go longer if the customer asked multiple direct questions\n"
            "\n"
            "RULES:\n"
            "- One short paragraph. Not multiple.\n"
            "- Answer first, then ask the next needed question\n"
            "- No greetings unless they greeted first\n"
            "- No sign-offs, no signatures\n"
            "- No bullet points unless listing trip options or departures\n"
            "- Use contractions naturally\n"
            "- Match the sender's energy and length\n"
            "\n"
            "GOOD REPLIES (tone reference, do not copy content or values):\n"
            "\"Yep, $120 per person. When were you thinking?\"\n"
            "\"That one's Fridays only. Next Friday work?\"\n"
            "\"All set! Ref [BOOKING_REF], here's your payment link: [PAYMENT_LINK]. See you Saturday!\"\n"
            "\"No worries! Let me know if you want something else.\"\n"
            "\n"
            "BAD REPLIES (never write like this):\n"
            "\"Thank you for reaching out! We would be delighted to assist you.\"\n"
            "\"Please do not hesitate to contact us for further information.\"\n"
            "\"That's a great choice! The Klein Curacao trip is an amazing experience!\"\n"
            "\n"
            "NEVER USE: \"We would be delighted\", \"Please do not hesitate\", \"Kindly advise\",\n"
            "\"Great choice\", \"Amazing\", \"Absolutely\", \"I'd be happy to\", \"Shall I\",\n"
            "\"wonderful\", \"fantastic\", \"certainly\", em dashes, en dashes, forced enthusiasm,\n"
            "reasoning out loud (\"that means...\", \"so that would be...\").\n"
            "\n"
            "Emojis: only in booking confirmations. Otherwise skip them."
        )
```

### Step 2 — Update persona in client.json

Change the `marina_persona` value (line 279) from the current long version to:

```json
"marina_persona": "Marina is warm, calm, practical, and guest-aware. She mirrors the sender's tone. She is human, clear, and never overexplains. She never guesses facts. If she does not know, she says so and offers to check."
```

### Step 3 — Update persona test in tests/marina/test_marina_tone.py

Change lines 125-128 from:
```python
def test_persona_in_client_json():
    """T12: marina_persona in client.json has hospitality reference."""
    persona = config_loader.get_common_sense_knowledge().get("marina_persona", "")
    assert "hospitality" in persona
    assert "mirrors the tone" in persona
```
to:
```python
def test_persona_in_client_json():
    """T12: marina_persona in client.json has core persona traits."""
    persona = config_loader.get_common_sense_knowledge().get("marina_persona", "")
    assert "warm" in persona
    assert "mirrors" in persona
    assert "never guesses" in persona or "never overexplains" in persona
```

## Tests

Run marina unit tests (includes the updated persona test):
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/marina/test_marina_tone.py -v
```

Run social unit regression:
```bash
python3 -m pytest tests/social/ -q
```

Expected: all pass.

Run live edge case tests on VPS:
```bash
cd /root/bluemarlin && export $(grep -v '^#' config/bluemarlin.env | xargs) && python3 -m pytest tests/social/live_test_whatsapp_083.py -v -s --tb=short
```

Expected: 12/12 pass.

## Success Condition
All unit tests pass (marina + social). All 12 live edge case tests pass. The persona test asserts the new traits.

## Rollback
Revert the writing style block in marina_agent.py (15 lines) and the persona line in client.json.
