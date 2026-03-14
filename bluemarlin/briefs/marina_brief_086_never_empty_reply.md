# BRIEF 086 — Never Leave Customer on Read
**Status:** Approved | **Files:** `agents/marina/marina_agent.py` | **Depends on:** 085 | **Blocks:** —

## Context
Claude intermittently returns empty `reply` fields for off-topic or ambiguous WhatsApp messages (e.g., "i was thinking of fishing a bit"). When this happens, the bot sends nothing — leaving the customer on read. This is unacceptable for a live service. Fishing is not even off-topic for a boat charter company.

Two root causes:
1. The prompt doesn't explicitly tell Claude to ALWAYS reply. Claude sometimes returns valid JSON with `reply: ""` for messages it can't classify.
2. The WhatsApp fallback in marina_agent.py is `""` — so even API failures result in silence.

## Why This Approach
Prompt-only fix. Add an explicit rule — never return an empty reply. If the message is off-topic, acknowledge it and redirect. This handles the normal case and ensures variety (Claude generates a different response each time).

The WhatsApp fallback (`""`) for API failures is left unchanged — adding a static string would violate Rule 3. API failures are rare; the prompt fix addresses the common case (Claude returning empty reply for off-topic messages).

## Source Material

### WhatsApp writing style block — marina_agent.py lines 82-134 (current, from Brief 085)
See current file — the RULES section needs one addition.

## Instructions

### Step 1 — Add "never empty" rule to WhatsApp writing style

In the RULES section of the WhatsApp writing style block (after the line `"- Match the sender's energy and length\n"`), add:

```python
            "- NEVER return an empty reply. Always respond, even for off-topic messages.\n"
            "  If they ask about something you don't cover, briefly acknowledge it and\n"
            "  mention what you do offer. Keep it natural and varied.\n"
```

### Step 2 — Add test verifying the prompt rule

Add a test in `tests/marina/test_marina_tone.py` before the final `if __name__` block:

```python
def test_whatsapp_prompt_never_empty_rule():
    """T13: WhatsApp prompt contains the never-empty-reply rule."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "NEVER return an empty reply" in prompt
```

## Tests

```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/marina/test_marina_tone.py -v && python3 -m pytest tests/social/ -q
```

Expected: 13/13 marina tone + 104/104 social pass.

## Success Condition
All unit tests pass. `test_whatsapp_prompt_never_empty_rule` confirms the new rule is in the prompt.

## Rollback
Remove the added rule line from the writing style block. Revert fallback to `""`.
