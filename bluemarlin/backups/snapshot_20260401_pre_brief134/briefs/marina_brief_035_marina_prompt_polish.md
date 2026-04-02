# BRIEF 035 — Marina prompt polish: language adaptation + trip key mapping
**Status:** Draft | **Files:** `src/marina_agent.py`, `CLAUDE.md`, `briefs/SYSTEM_STATE.md` | **Depends on:** Brief 034 | **Blocks:** nothing

## Context
Marina's prompt has two demo-critical gaps identified in the /think session:

1. **No language adaptation instruction.** `client.json` lists English, Dutch, German, Spanish, Portuguese as business languages, and this is injected into the prompt — but Marina has no instruction to actually *use* the customer's language when replying. A Dutch customer gets an English reply.

2. **No trip name → trip_key mapping guidance.** The prompt says extract `trip_key` as "one of: klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski — only include if certain" but gives no guidance on how common customer phrasings ("snorkeling", "west coast", "sunset") map to those exact keys. Marina must guess, which risks silently returning a wrong or empty trip_key and breaking the booking flow.

Additionally, `CLAUDE.md`'s Known Open Issues section has three stale entries that are now resolved (thread key fixed in Brief 033, [VERIFY] items filled in Brief 034, payment_stub dropped by user decision). These are removed as housekeeping.

No logic changes — prompt text and documentation only.

**Note on the static fallback reply in marina_agent.py (lines 197–204):** The `fallback` dict contains a hardcoded reply string. This is a formally accepted architectural exception — recorded in CLAUDE.md Known Open Issues by Instruction 5 of this brief. It is a last-resort fail-safe activated only when the Claude API call itself fails entirely, not a routing template or language classifier. Rule 3 prohibits `safe_X_reply()` routing templates; the fallback is categorically different. It is not touched by this brief.

## Why This Approach
Language adaptation: the minimal instruction ("detect language, reply in same language") is sufficient — Claude already has multilingual capability. No new code paths, no language detection logic in Python (that would violate Architecture Rule 5). A single sentence in the prompt activates existing Claude behaviour.

Trip key mapping: a simple lookup table in the prompt is more reliable than asking Claude to infer. Explicit beats implicit. The 5 trip keys have stable, short aliases that won't change. The mapping table is data, not logic — it belongs in the prompt text alongside other prompt data.

CLAUDE.md cleanup rejected as a separate brief — it's doc-only, zero risk, and bundling it here keeps the issue list accurate without burning a brief number.

## Source Material

### marina_agent.py — relevant sections (read in full this session)

**File header (lines 1–5) — confirmed from file read this session:**
```python
# FILE: marina_agent.py
# CREATED: Brief 023
# LAST MODIFIED: Brief 031
# DEPENDS ON: claude_client.py (Brief 001), config_loader.py (Brief 022)
# IMPORTS FROM: config_loader.py (Brief 022)
```
Briefs 032, 033, 034 did NOT modify marina_agent.py. Header is confirmed at `Brief 031`.

**PERSONA line (line 68) — insertion point for LANGUAGE block:**
```python
    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'BlueFinn Charters Curaçao')}.

PERSONA: {csk.get('marina_persona', '')}
AGENT SIGNATURE: {signature}
TODAY (Curaçao time): {today}
```

**trip_key field description (line 173) — current text:**
```
    trip_key: exact key from the trips list — one of klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski — only include if certain
```

**Languages list injected at line 78:**
```python
  Languages: {', '.join(business.get('languages', []))}
```
Value from client.json: `["English", "Dutch", "German", "Spanish", "Portuguese"]`

### CLAUDE.md — Known Open Issues section (confirmed from file read this session, lines 159–171)
```
## KNOWN OPEN ISSUES

- Thread key breaks on subject change — fix: use Message-ID/In-Reply-To (not built)
- `slot_checked` not reset on date change — low priority, deferred
- Same-day booking UTC edge case (20:00–00:00 Curaçao time) — accepted for demo
- Escalations tab must be created manually in Google Sheet before first escalation
- Service account must be shared on all 5 BlueFinn calendars before live use
- `payment_stub.py` is a placeholder — not connected to a real payment processor
- `[VERIFY]` items remain in client.json: cancellation policy, private charter
  pricing, vessel names (snorkeling/west coast/sunset), shade on boats,
  snorkeling_3in1 duration

---
```

## Instructions

### 1. Add LANGUAGE block to marina_agent.py prompt

In `_build_prompt()`, after the `PERSONA:` line and before `AGENT SIGNATURE:`, insert a new line:

Find:
```python
PERSONA: {csk.get('marina_persona', '')}
AGENT SIGNATURE: {signature}
```

Replace with:
```python
PERSONA: {csk.get('marina_persona', '')}
LANGUAGE: Detect the language of the customer's inbound message and write your reply in that same language. Supported languages: {', '.join(business.get('languages', []))}. If the language is unclear or not in the supported list, default to English.
AGENT SIGNATURE: {signature}
```

### 2. Expand trip_key field description in marina_agent.py prompt

Find (exact text, line ~173):
```
    trip_key: exact key from the trips list — one of klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski — only include if certain
```

Replace with:
```
    trip_key: exact key from the trips list. Match the customer's wording to one of these keys:
      "Klein Curaçao", "Klein", "island trip", "day trip", "turtle trip" → klein_curacao
      "snorkeling", "snorkel", "3-in-1", "3 in 1", "snorkeling trip" → snorkeling_3in1
      "west coast", "beach trip", "west coast beach" → west_coast_beach
      "sunset", "sunset cruise", "evening cruise", "evening trip" → sunset_cruise
      "jet ski", "jetski", "jet-ski" → jet_ski
      Only include trip_key if certain. If the customer's description is ambiguous, omit it and ask.
```

### 3. Update file header in marina_agent.py

Find:
```python
# LAST MODIFIED: Brief 031
```

Replace with:
```python
# LAST MODIFIED: Brief 035
```

### 4. Update CLAUDE.md Active Source Files table

In the Active Source Files table, find:
```
| `src/marina_agent.py` | 031 | ~237 | Single Claude call per message. Returns structured JSON |
```

Replace with:
```
| `src/marina_agent.py` | 035 | ~237 | Single Claude call per message. Returns structured JSON |
```

### 5. Update CLAUDE.md Known Open Issues

Find the entire section including heading and trailing separator (exact text from file read):
```
## KNOWN OPEN ISSUES

- Thread key breaks on subject change — fix: use Message-ID/In-Reply-To (not built)
- `slot_checked` not reset on date change — low priority, deferred
- Same-day booking UTC edge case (20:00–00:00 Curaçao time) — accepted for demo
- Escalations tab must be created manually in Google Sheet before first escalation
- Service account must be shared on all 5 BlueFinn calendars before live use
- `payment_stub.py` is a placeholder — not connected to a real payment processor
- `[VERIFY]` items remain in client.json: cancellation policy, private charter
  pricing, vessel names (snorkeling/west coast/sunset), shade on boats,
  snorkeling_3in1 duration

---
```

Replace with (4 entries — keeping all non-resolved live-ops entries intact, removing only the 3 resolved code items):
```
## KNOWN OPEN ISSUES

- `slot_checked` not reset on date change — low priority, deferred
- Same-day booking UTC edge case (20:00–00:00 Curaçao time) — accepted for demo
- Escalations tab must be created manually in Google Sheet before first escalation
- Service account must be shared on all 5 BlueFinn calendars before live use
- Fallback reply in marina_agent.py (lines 194–208) is a hardcoded string — accepted exception for API failure path only, not a routing template. Rule 3 does not apply.

---
```

Items removed and why:
- "Thread key breaks on subject change" — fixed in Brief 033
- "[VERIFY] items remain in client.json" — all filled in Brief 034
- "payment_stub.py is a placeholder" — user dropped this issue (payment not needed for demo)

The "Fallback reply in marina_agent.py" line is added as the formal accepted-exception record, replacing the context-only note in this brief.

### 6. Update SYSTEM_STATE.md Decision Log

Append to the Decision Log at the end of `briefs/SYSTEM_STATE.md`:
```
Brief 035 — Marina prompt polish: language adaptation + trip key mapping
Decision: Add LANGUAGE detection instruction and trip_key mapping table to prompt. Remove 3 resolved items from CLAUDE.md Known Open Issues. No logic changes.
Outcome: pending
```

## Tests

Write as `bluemarlin/test_035_marina_prompt.py` and run it:

```python
#!/usr/bin/env python3
# bluemarlin/test_035_marina_prompt.py
# Brief 035 — Marina prompt polish: language + trip key mapping
# Run: cd bluemarlin && python3 test_035_marina_prompt.py

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import marina_agent

# Build a prompt using real data (no API call)
prompt = marina_agent._build_prompt(
    from_email="test@example.com",
    subject="Test",
    body="Hello",
    thread_fields={},
    thread_flags={},
)

# T1: LANGUAGE instruction is in the prompt
assert "LANGUAGE:" in prompt, f"T1 fail: LANGUAGE block missing from prompt"
print("T1 pass — LANGUAGE block present in prompt")

# T2: Language instruction mentions detecting the customer's language
assert "Detect the language" in prompt, f"T2 fail: language detection instruction missing"
print("T2 pass — language detection instruction present")

# T3: Prompt lists supported languages
assert "Dutch" in prompt and "German" in prompt and "Spanish" in prompt, \
    f"T3 fail: supported languages missing from prompt"
print("T3 pass — supported languages listed")

# T4: All 5 trip keys appear in the mapping table
for key in ["klein_curacao", "snorkeling_3in1", "west_coast_beach", "sunset_cruise", "jet_ski"]:
    assert key in prompt, f"T4 fail: trip key '{key}' missing from prompt"
print("T4 pass — all 5 trip keys present in prompt")

# T5: Mapping aliases are in the prompt
for alias in ["snorkeling", "west coast", "sunset", "jet ski", "Klein Curaçao"]:
    assert alias in prompt, f"T5 fail: alias '{alias}' missing from prompt"
print("T5 pass — trip key aliases present in prompt")

# T6: File header updated to Brief 035
with open(os.path.join(os.path.dirname(__file__), "src", "marina_agent.py")) as f:
    header = f.read(300)
assert "Brief 035" in header, f"T6 fail: file header not updated to Brief 035"
print("T6 pass — file header updated to Brief 035")

# T7: CLAUDE.md no longer contains the stale thread-key issue
claude_md_path = os.path.join(os.path.dirname(__file__), "..", "CLAUDE.md")
with open(claude_md_path) as f:
    claude_content = f.read()
assert "Thread key breaks on subject change" not in claude_content, \
    f"T7 fail: stale thread key issue still in CLAUDE.md"
print("T7 pass — stale thread key issue removed from CLAUDE.md")

# T8: CLAUDE.md no longer contains [VERIFY] open issue
# The bullet point text contains "items remain in client.json" — unique to that entry
assert "items remain in client.json" not in claude_content, \
    f"T8 fail: stale [VERIFY] issue still in CLAUDE.md"
print("T8 pass — stale [VERIFY] issue removed from CLAUDE.md")

# T9: Positive check — the 4 surviving known issues are still present
for expected in [
    "slot_checked",
    "Same-day booking UTC edge case",
    "Escalations tab must be created manually",
    "Service account must be shared on all 5 BlueFinn calendars",
]:
    assert expected in claude_content, \
        f"T9 fail: expected known issue missing from CLAUDE.md: '{expected}'"
print("T9 pass — all surviving known issues present in CLAUDE.md")

print("\nAll 9 tests passed.")
```

## Success Condition
All 9 tests pass. `_build_prompt()` output contains a LANGUAGE block with language-detection instruction and a trip_key section with a 5-entry mapping table. CLAUDE.md Known Open Issues contains 5 items (4 deferred + 1 accepted exception).

## Rollback
`git checkout HEAD~1 -- bluemarlin/src/marina_agent.py CLAUDE.md` restores both files to pre-035 state.
