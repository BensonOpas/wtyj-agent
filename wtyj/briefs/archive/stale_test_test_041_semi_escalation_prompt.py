#!/usr/bin/env python3
"""Tests for Brief 041 — Semi-escalation prompt fix."""
import sys
import os

from agents.marina import marina_agent


def test_weight_limit_triggers_semi_escalation():
    """T1: Weight limit question → semi_escalation: true, no contact info in reply."""
    result = marina_agent.process_message(
        "john@example.com",
        "Jet ski question",
        "What is the maximum weight limit per person for the jet ski?",
        {"service_key": "jet_ski", "service_name": "jet ski"},
        {}
    )
    assert result.get("semi_escalation") is True, (
        f"Expected semi_escalation=True, got {result.get('semi_escalation')}.\n"
        f"Reply was: {result.get('reply', '')[:300]}"
    )
    relay_q = result.get("relay_question", "")
    assert relay_q, "relay_question must be non-empty"
    assert any(w in relay_q.lower() for w in ["weight", "limit", "kg", "kg ", "kilo"]), (
        f"relay_question should mention weight/limit. Got: {relay_q!r}"
    )
    reply = result.get("reply", "")
    assert "info@bluefinncharters.com" not in reply, (
        f"Reply must NOT contain contact email. Reply: {reply[:300]}"
    )
    assert "+599" not in reply, (
        f"Reply must NOT contain phone number. Reply: {reply[:300]}"
    )
    print(f"  T1 PASS: semi_escalation=True, no contact info in reply")
    print(f"         relay_question: {relay_q!r}")
    print(f"         reply: {reply[:150]!r}")


def test_latex_allergy_triggers_semi_escalation():
    """T2: Latex allergy question → semi_escalation: true, no contact info."""
    result = marina_agent.process_message(
        "sarah@example.com",
        "Allergy question",
        "My daughter has a severe latex allergy. Do your life jackets or snorkel gear contain latex?",
        {},
        {}
    )
    assert result.get("semi_escalation") is True, (
        f"Expected semi_escalation=True, got {result.get('semi_escalation')}.\n"
        f"Reply was: {result.get('reply', '')[:300]}"
    )
    relay_q = result.get("relay_question", "")
    assert relay_q, "relay_question must be non-empty"
    assert any(w in relay_q.lower() for w in ["latex", "allergy", "life jacket", "snorkel", "gear"]), (
        f"relay_question should mention latex/allergy/gear. Got: {relay_q!r}"
    )
    reply = result.get("reply", "")
    assert "info@bluefinncharters.com" not in reply, (
        f"Reply must NOT contain contact email. Reply: {reply[:300]}"
    )
    assert "+599" not in reply, (
        f"Reply must NOT contain phone number. Reply: {reply[:300]}"
    )
    print(f"  T2 PASS: semi_escalation=True, no contact info in reply")
    print(f"         relay_question: {relay_q!r}")


def test_complaint_still_uses_requires_human():
    """T3: Complaint still triggers requires_human (not semi_escalation)."""
    result = marina_agent.process_message(
        "angry@example.com",
        "Terrible experience",
        "I want a refund. The service was cancelled last minute and ruined our holiday.",
        {},
        {}
    )
    assert result.get("requires_human") is True, (
        f"Expected requires_human=True, got {result.get('requires_human')}"
    )
    assert result.get("semi_escalation") is not True, \
        "Complaint must use requires_human, not semi_escalation"
    assert "info@bluefinncharters.com" in result.get("reply", ""), (
        "Complaint reply SHOULD contain the escalation contact (team will email customer)"
    )
    print(f"  T3 PASS: complaint → requires_human=True, contact email present in reply")


def test_normal_inquiry_no_semi_escalation():
    """T4: Question answerable from FAQ → no semi_escalation, no requires_human."""
    result = marina_agent.process_message(
        "curious@example.com",
        "Trip question",
        "How long is the Klein Curacao service and what time does it depart?",
        {},
        {}
    )
    assert result.get("semi_escalation") is not True, (
        f"Answerable question must not trigger semi_escalation. "
        f"Reply: {result.get('reply', '')[:200]}"
    )
    assert result.get("requires_human") is not True, \
        "Normal inquiry must not trigger requires_human"
    assert result.get("reply"), "Must have a reply"
    print(f"  T4 PASS: normal inquiry handled directly, no escalation")
    print(f"         reply: {result['reply'][:150]!r}")


if __name__ == "__main__":
    print("Running Brief 041 tests...")
    test_weight_limit_triggers_semi_escalation()
    test_latex_allergy_triggers_semi_escalation()
    test_complaint_still_uses_requires_human()
    test_normal_inquiry_no_semi_escalation()
    print("\nAll 4 tests passed.")
