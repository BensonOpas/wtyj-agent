#!/usr/bin/env python3
# bluemarlin/test_035_marina_prompt.py
# Brief 035 — Marina prompt polish: language + trip key mapping
# Run: cd bluemarlin && python3 test_035_marina_prompt.py

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
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
with open(os.path.join(os.path.dirname(__file__), "..", "src", "marina_agent.py")) as f:
    header = f.read(300)
assert "Brief 035" in header, f"T6 fail: file header not updated to Brief 035"
print("T6 pass — file header updated to Brief 035")

# T7: CLAUDE.md no longer contains the stale thread-key issue
claude_md_path = os.path.join(os.path.dirname(__file__), "..", "..", "CLAUDE.md")
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
