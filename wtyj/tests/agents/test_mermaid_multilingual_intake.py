"""Issue 328: deterministic multilingual Mermaid WhatsApp intake."""

import json
from pathlib import Path

import pytest

from agents.social import mermaid_reservation_workflow as workflow
from shared import config_loader, state_registry


REPO_ROOT = Path(__file__).resolve().parents[3]
MERMAID_CONFIG = REPO_ROOT / "clients" / "mermaid" / "config" / "client.json"


@pytest.fixture(autouse=True)
def isolated_mermaid(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(MERMAID_CONFIG))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))


@pytest.mark.parametrize(
    "message,locale,needle",
    [
        ("I want to book", "en", "What date"),
        ("Ik wil graag reserveren", "nl", "Welke datum"),
        ("Ich möchte bitte buchen", "de", "welchem Datum"),
        ("Quiero reservar", "es", "Qué fecha"),
        ("Mi ke hasi un reservashon", "pap", "Ki fecha"),
        ("Quero reservar", "pt", "que data"),
    ],
)
def test_six_language_opening(message, locale, needle):
    result = workflow.process_intake_turn(f"guest-{locale}", message, message_id="1")
    assert result.locale == locale
    assert needle in result.text
    assert "TRACY" in result.text


def test_multi_fact_message_preserves_facts_and_asks_only_one_question():
    result = workflow.process_intake_turn(
        "guest-multi",
        "My name is Ana Silva. Date 2026-09-05, 2 adults, 1 child, 0 infants. We will meet at the pier.",
        message_id="one",
    )
    assert result.phase == "collecting"
    result = workflow.process_intake_turn("guest-multi", "+1 202 555 0123", message_id="contact")
    assert result.phase == "awaiting_summary_confirmation"
    assert result.text.count("?") == 1
    assert "Ana Silva" in result.text
    assert "2 adult fares, 1 child (4-12)" in result.text
    assert "Saturday 5 September 2026" in result.text


def test_ambiguous_party_size_asks_one_composition_question():
    result = workflow.process_intake_turn(
        "guest-three", "We are three people and want to book", message_id="one"
    )
    assert result.text.count("?") == 1
    assert "adults, children aged 4 to 12" in result.text


def test_question_is_answered_before_next_intake_question():
    result = workflow.process_intake_turn(
        "guest-question", "What is included?", message_id="one"
    )
    assert result.text.index("Breakfast") < result.text.index("What date")
    assert result.text.count("?") == 1


def test_summary_requires_explicit_confirmation_and_allows_one_field_correction():
    phone = "guest-correct"
    workflow.process_intake_turn(
        phone,
        "My name is Ana Silva. Date 2026-09-05, 2 adults, 0 children, 0 infants, meet at pier.",
        message_id="one",
    )
    workflow.process_intake_turn(phone, "+1 202 555 0123", message_id="contact")
    hesitation = workflow.process_intake_turn(phone, "hmm 🙂", message_id="two")
    assert hesitation.phase == "awaiting_summary_confirmation"
    assert hesitation.action is None

    correction = workflow.process_intake_turn(phone, "Actually 3 adults", message_id="three")
    assert correction.phase == "awaiting_summary_confirmation"
    assert "3 adult fares" in correction.text
    state = state_registry.wa_get_booking_state(phone)["fields"]["mermaid_intake"]
    assert state["children"] == 0
    assert state["customer_name"] == "Ana Silva"

    confirmed = workflow.process_intake_turn(phone, "yes", message_id="four")
    assert confirmed.action == "summary_confirmed"
    assert confirmed.phase == "summary_confirmed"


def test_duplicate_inbound_does_not_advance_or_reply_twice():
    first = workflow.process_intake_turn("guest-duplicate", "I want to book", message_id="same")
    duplicate = workflow.process_intake_turn("guest-duplicate", "I want to book", message_id="same")
    assert first.text
    assert duplicate.text == ""
    assert duplicate.duplicate is True


def test_human_review_stays_soft_and_preserves_progress(monkeypatch):
    muted = []
    notices = []
    monkeypatch.setattr(state_registry, "set_ai_muted", lambda phone, value, channel: muted.append((phone, value, channel)))
    monkeypatch.setattr(state_registry, "create_pending_notification", lambda *args, **kwargs: notices.append((args, kwargs)))
    workflow.process_intake_turn("guest-human", "Date 2026-09-05", message_id="one")
    result = workflow.process_intake_turn("guest-human", "I want a human", message_id="two")
    assert result.action == "human_takeover"
    assert muted == []
    assert len(notices) == 1
    assert notices[0][1]["mode"] == "soft"
    assert notices[0][1]["preserve_hard_mode"] is True
    state = state_registry.wa_get_booking_state("guest-human")["fields"]["mermaid_intake"]
    assert state["trip_date"] == "2026-09-05"


def test_customer_can_cancel_before_payment():
    result = workflow.process_intake_turn("guest-cancel", "cancel", message_id="one")
    assert result.action == "cancel"
    assert result.phase == "cancellation_requested"
    assert result.text == ""
    reply = workflow.handle_demo_message({"from": "guest-cancel", "text": "cancel", "message_id": "one"})
    assert reply == workflow.COPY["en"]["cancelled"]
    assert "No payment" in reply
