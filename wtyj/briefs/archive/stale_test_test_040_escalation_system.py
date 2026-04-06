#!/usr/bin/env python3
"""Tests for Brief 040 — Escalation system."""
import sys
import os
import json
import unittest.mock as mock

from agents.marina import marina_agent
from agents.marina import sheets_writer


def test_semi_escalation_flag():
    """T1: Specific accessibility question not in FAQ → semi_escalation: true + relay_question."""
    # Wheelchair accessibility is definitively not in the FAQ — Marina cannot answer it
    result = marina_agent.process_message(
        "john@example.com",
        "Accessibility question",
        "Hi! My father uses a wheelchair. Is the boat accessible for wheelchair users, "
        "and is there a ramp or lift for boarding?",
        {"service_key": "klein_curacao", "service_name": "Klein Curaçao",
         "date": "2026-04-15", "guests": 3},
        {}
    )
    assert result.get("semi_escalation") is True, (
        f"Expected semi_escalation=True, got {result.get('semi_escalation')}. "
        f"Full result: {result}"
    )
    assert result.get("relay_question"), (
        f"Expected relay_question to be non-empty, got: {result.get('relay_question')!r}"
    )
    assert result.get("requires_human") is not True, (
        "semi_escalation must not also set requires_human"
    )
    assert result.get("reply"), "Customer holding reply must be non-empty"
    print(f"  T1 PASS: semi_escalation=True, relay_question={result['relay_question']!r}")


def test_relay_mode_reformulation():
    """T2: Relay mode — Marina reformulates human's answer in her own voice."""
    result = marina_agent.process_message(
        "john@example.com",
        "Re: Klein Curacao service",
        "Yes, cameras and underwater housings are welcome on board. "
        "We even have a freshwater rinse station on the back deck.",
        {"service_key": "klein_curacao", "service_name": "Klein Curaçao",
         "date": "2026-04-15", "guests": 2},
        {"awaiting_relay": True, "relay_question": "Can I bring my DSLR camera?"}
    )
    assert result.get("reply"), "Relay reply must be non-empty"
    assert result.get("requires_human") is not True, "Relay mode must not set requires_human"
    assert result.get("semi_escalation") is not True, "Relay mode must not set semi_escalation"
    assert result.get("flags", {}).get("booking_confirmed") is not True, \
        "Relay mode must not set booking_confirmed"
    assert result.get("flags", {}).get("awaiting_booking_confirmation") is not True, \
        "Relay mode must not set awaiting_booking_confirmation"
    # Check that the reply incorporates the camera/rinse station content
    reply_lower = result["reply"].lower()
    assert any(word in reply_lower for word in ["camera", "rinse", "welcome", "board"]), (
        f"Reply should incorporate relay answer content. Got: {result['reply'][:200]}"
    )
    print(f"  T2 PASS: relay reformulation reply={result['reply'][:100]!r}...")


def test_full_escalation_requires_human():
    """T3: Refund/complaint → requires_human: true + reply mentions info@bluefinncharters.com."""
    result = marina_agent.process_message(
        "john@example.com",
        "Refund request",
        "I want a full refund for my booking. The crew was rude and the boat was dirty.",
        {"service_key": "klein_curacao", "date": "2026-04-15", "guests": 2},
        {}
    )
    assert result.get("requires_human") is True, (
        f"Expected requires_human=True, got {result.get('requires_human')}"
    )
    assert "info@bluefinncharters.com" in result.get("reply", ""), (
        f"Reply must mention info@bluefinncharters.com. Got: {result.get('reply', '')[:200]}"
    )
    assert result.get("semi_escalation") is not True, \
        "requires_human path must not also set semi_escalation"
    print(f"  T3 PASS: requires_human=True, reply contains production email")


def test_fully_escalated_thread_holding_reply():
    """T4: fully_escalated=True in thread → Marina sends holding reply, no booking flags."""
    result = marina_agent.process_message(
        "john@example.com",
        "Follow up",
        "Has anyone gotten back to me yet? I'm still waiting.",
        {},
        {"fully_escalated": True}
    )
    assert result.get("reply"), "Fully escalated holding reply must be non-empty"
    assert result.get("flags", {}).get("booking_confirmed") is not True, \
        "Must not set booking_confirmed on fully escalated thread"
    assert result.get("flags", {}).get("awaiting_booking_confirmation") is not True, \
        "Must not set awaiting_booking_confirmation on fully escalated thread"
    assert result.get("requires_human") is not True, \
        "Must not re-escalate an already fully escalated thread"
    print(f"  T4 PASS: holding reply={result['reply'][:100]!r}...")


def test_log_escalation_has_messages_json_column():
    """T5: log_escalation writes 7 columns including messages_json as column 7."""
    captured = {}

    def mock_append(tab_name, row):
        captured[tab_name] = row

    with mock.patch.object(sheets_writer, '_append', side_effect=mock_append):
        sheets_writer.log_escalation({
            "customer_name": "John Test",
            "email": "john@example.com",
            "intent": "complaint",
            "fields_collected": {"service_key": "klein_curacao"},
            "internal_note": "Customer complained about service",
            "messages_json": json.dumps([
                {"role": "customer", "ts": "2026-03-08T10:00:00Z",
                 "body": "The service was terrible."},
                {"role": "marina", "ts": "2026-03-08T10:00:05Z",
                 "body": "I've passed this along to our customer care team."},
            ]),
        })

    assert "Escalations" in captured, "log_escalation must write to Escalations tab"
    row = captured["Escalations"]
    assert len(row) == 7, f"Escalations row must have 7 columns, got {len(row)}: {row}"
    assert "marina" in row[6], f"Column 7 (Chat Log) must contain messages JSON, got: {row[6][:100]}"
    print(f"  T5 PASS: Escalations row has {len(row)} columns, messages_json in col 7")


if __name__ == "__main__":
    print("Running Brief 040 tests...")
    test_semi_escalation_flag()
    test_relay_mode_reformulation()
    test_full_escalation_requires_human()
    test_fully_escalated_thread_holding_reply()
    test_log_escalation_has_messages_json_column()
    print("\nAll 5 tests passed.")
