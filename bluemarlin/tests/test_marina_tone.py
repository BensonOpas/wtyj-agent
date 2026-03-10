# tests/test_marina_tone.py
# Brief 059 — Marina Tone Polish

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import marina_agent
import config_loader


def test_prompt_contains_writing_style_section():
    """WRITING STYLE section is present in the prompt."""
    prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    assert "WRITING STYLE:" in prompt


def test_writing_style_before_language_rule():
    """WRITING STYLE appears before LANGUAGE RULE in prompt order."""
    prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    style_idx = prompt.index("WRITING STYLE:")
    lang_idx = prompt.index("LANGUAGE RULE:")
    assert style_idx < lang_idx


def test_stock_phrases_listed_in_prompt():
    """Banned stock phrases are explicitly listed so Claude avoids them."""
    prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    assert "Thank you for reaching out" in prompt
    assert "Please do not hesitate" in prompt


def test_ai_habits_section_present():
    """AI writing habits (em dashes, emojis) are addressed in the prompt."""
    prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    assert "Em dashes" in prompt or "em dashes" in prompt
    assert "Emojis:" in prompt


def test_updated_persona_in_client_json():
    """marina_persona in client.json reflects the updated personality."""
    persona = config_loader.get_common_sense_knowledge().get("marina_persona", "")
    assert "hospitality" in persona
    assert "mirrors the tone" in persona


def test_self_check_instruction_present():
    """The pre-output self-check is in the prompt."""
    prompt = marina_agent._build_prompt("a@b.com", "test", "hi", {}, {})
    assert "Does this sound like a real person" in prompt


if __name__ == "__main__":
    tests = [
        test_prompt_contains_writing_style_section,
        test_writing_style_before_language_rule,
        test_stock_phrases_listed_in_prompt,
        test_ai_habits_section_present,
        test_updated_persona_in_client_json,
        test_self_check_instruction_present,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
    print(f"\n{passed}/{len(tests)} tests passed.")
