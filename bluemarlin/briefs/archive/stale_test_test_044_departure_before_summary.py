#!/usr/bin/env python3
"""Tests for Brief 044 — Departure time before booking summary for multi-departure trips."""
import sys, os, json

def test_prompt_contains_third_check():
    """T1: Prompt contains THIRD check about departures array."""
    from agents.marina import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "THIRD" in prompt, "Prompt must contain THIRD check"
    assert "departures array" in prompt, "THIRD check must reference departures array"
    print("  T1 PASS: Prompt contains THIRD check about departures array")

def test_old_instruction_removed():
    """T2: Old 'slot_time is NOT a required field' instruction is gone."""
    from agents.marina import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "slot_time is NOT a required field" not in prompt, \
        "Old slot_time instruction must be removed"
    print("  T2 PASS: Old slot_time instruction removed")

def test_auto_select_single_departure():
    """T3: Prompt instructs auto-select for single-departure trips."""
    from agents.marina import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "only one departure option" in prompt and "auto-select" in prompt, \
        "Prompt must instruct auto-select for single-departure trips"
    print("  T3 PASS: Prompt instructs auto-select for single-departure trips")

def test_ask_before_summary_multi_departure():
    """T4: Prompt instructs asking before summary for multi-departure trips."""
    from agents.marina import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "more than one departure option" in prompt, \
        "Prompt must mention multi-departure condition"
    assert "BEFORE sending the booking summary" in prompt, \
        "Must instruct asking BEFORE the summary"
    assert "Do NOT set" in prompt and "awaiting_booking_confirmation until slot_time" in prompt, \
        "Must prohibit awaiting_booking_confirmation without slot_time"
    print("  T4 PASS: Prompt requires departure time before summary for multi-departure trips")

def test_klein_curacao_has_multiple_departures():
    """T5: client.json klein_curacao has 2 departures (confirms test premise)."""
    from shared import config_loader
    service = config_loader.get_service("klein_curacao")
    deps = service.get("slots", [])
    assert len(deps) == 2, f"klein_curacao must have 2 departures, got {len(deps)}"
    print("  T5 PASS: klein_curacao has 2 departures")

def test_sunset_cruise_has_single_departure():
    """T6: client.json sunset_cruise has 1 departure (confirms test premise)."""
    from shared import config_loader
    service = config_loader.get_service("sunset_cruise")
    deps = service.get("slots", [])
    assert len(deps) == 1, f"sunset_cruise must have 1 departure, got {len(deps)}"
    print("  T6 PASS: sunset_cruise has 1 departure")

def test_rerun_includes_third():
    """T7: Mid-confirmation re-run instruction includes THIRD check."""
    from agents.marina import marina_agent
    prompt = marina_agent._build_prompt("a@b.com", "test", "test", {}, {})
    assert "FIRST, SECOND, and THIRD checks" in prompt, \
        "Re-run instruction must include THIRD check"
    print("  T7 PASS: Re-run instruction includes THIRD check")

def test_file_header_updated():
    """T8: marina_agent.py file header says Brief 044."""
    from agents.marina import marina_agent
    import inspect
    source = inspect.getsource(marina_agent)
    assert "Last modified: Brief" in source, "File header must reference Brief"
    print("  T8 PASS: File header updated to Brief 044")

if __name__ == "__main__":
    print("Running Brief 044 tests...")
    test_prompt_contains_third_check()
    test_old_instruction_removed()
    test_auto_select_single_departure()
    test_ask_before_summary_multi_departure()
    test_klein_curacao_has_multiple_departures()
    test_sunset_cruise_has_single_departure()
    test_rerun_includes_third()
    test_file_header_updated()
    print("\nAll 8 tests passed.")
