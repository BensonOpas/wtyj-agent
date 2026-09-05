"""Mermaid must persist the generic 24-hour reset before its early handler."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from unittest.mock import Mock
import pytest

from agents.marina import marina_agent
from agents.social import (
    mermaid_crew_assistance,
    mermaid_reservation_store,
    mermaid_reservation_workflow,
    social_agent,
)
from shared import config_loader, mermaid_catalog, state_registry


def test_stale_non_mermaid_tenant_does_not_persist_mermaid_session_flag(
    monkeypatch,
):
    phone = "stale-unrelated-tenant"
    saved = {}
    monkeypatch.setattr(
        state_registry,
        "wa_get_booking_state",
        lambda _phone: {
            "fields": {"old": "value"},
            "flags": {"old_flag": True},
            "completed_bookings": [],
            "last_activity": "old",
        },
    )
    monkeypatch.setattr(
        social_agent, "_maybe_reset_stale_conversation", lambda *_args: True
    )
    monkeypatch.setattr(
        mermaid_catalog, "reservation_demo_enabled", lambda: False
    )
    monkeypatch.setattr(state_registry, "wa_store_message", lambda *_args: None)

    def capture_reset(_phone, fields, flags, completed):
        saved.update({"fields": dict(fields), "flags": dict(flags)})
        raise RuntimeError("stop after reset persistence")

    monkeypatch.setattr(state_registry, "wa_save_booking_state", capture_reset)

    with pytest.raises(RuntimeError, match="stop after reset persistence"):
        social_agent.handle_incoming_whatsapp_message(
            {
                "from": phone,
                "from_name": "Other Tenant Guest",
                "message_id": "new-message",
                "text": "Hello",
            },
            inbound_already_stored=True,
        )

    assert "mermaid_session_started_at" not in saved["flags"]


def test_stale_mermaid_intake_is_cleared_before_tenant_handler_rereads_state(
    tmp_path, monkeypatch
):
    config = Path(__file__).resolve().parents[3] / "clients/mermaid/config/client.json"
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))

    phone = "stale-mermaid-session"
    state_registry.wa_save_booking_state(
        phone,
        {
            "mermaid_intake": {
                "language": "pap",
                "phase": "human_takeover",
                "trip_date": "2026-09-06",
                "accessibility_notes": "A guest uses a wheelchair.",
            }
        },
        {"mermaid_seen_message_ids": ["old-message"]},
        [],
    )
    conn = state_registry._get_conn()
    try:
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        conn.execute(
            "UPDATE whatsapp_booking_state SET last_activity=? WHERE phone=?",
            (old, phone),
        )
        conn.commit()
    finally:
        conn.close()

    observed = {}

    def tenant_handler(message, include_media=False, use_model=False):
        observed.update(state_registry.wa_get_booking_state(phone))
        return "fresh Mermaid reply"

    monkeypatch.setattr(mermaid_catalog, "reservation_demo_enabled", lambda: True)
    monkeypatch.setattr(
        mermaid_reservation_workflow, "handle_demo_message", tenant_handler
    )

    reply = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "from_name": "Synthetic Guest",
            "message_id": "new-message",
            "text": "Bon dia",
        },
        inbound_already_stored=True,
    )

    assert reply == "fresh Mermaid reply"
    assert observed["fields"] == {}
    assert observed["last_activity"] != old


def test_stale_session_with_historical_reservation_gets_a_fresh_welcome(
    tmp_path, monkeypatch
):
    config = Path(__file__).resolve().parents[3] / "clients/mermaid/config/client.json"
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(state_registry, "_alert_dispatcher", None)
    monkeypatch.setattr(state_registry, "_summary_dispatcher", None)

    phone = "stale-mermaid-with-reservation"
    historical = {
        "trip_date": "2026-09-12",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "pap",
        "phase": "summary_confirmed",
    }
    reservation = mermaid_reservation_store.confirm_reservation(
        phone, historical, idempotency_key="historical-confirmation"
    )
    state_registry.wa_save_booking_state(
        phone,
        {"mermaid_intake": historical | {"phase": "human_takeover"}},
        {"mermaid_seen_message_ids": ["old-message"]},
        [],
    )
    state_registry.dm_store_message(
        phone, "whatsapp", "assistant", "Old session reply"
    )
    conn = state_registry._get_conn()
    try:
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        conn.execute(
            "UPDATE whatsapp_booking_state SET last_activity=? WHERE phone=?",
            (old, phone),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        marina_agent,
        "process_message",
        Mock(
            return_value={
                "language": "pap",
                "mermaid_action": "details",
                "fields": {
                    "accessibility_notes": "A guest uses a wheelchair.",
                    "wheelchair_relationship": "unspecified",
                },
                "reply": "Model reply",
                "confidence": "high",
                "requires_human": False,
                "has_open_question": True,
                "guest_question_excerpt": "Boso por yuda ku e stul?",
                "calendar_request": "none",
                "status_request": "none",
                "assistance_request": "wheelchair_note",
                "security_event": "none",
                "other_question_reply": "",
            }
        ),
    )

    reply = social_agent.handle_incoming_whatsapp_message(
        {
            "from": phone,
            "from_name": "Synthetic Guest",
            "message_id": "new-wheelchair-message",
            "text": "Mi ta usa stul di rueda. Boso por yuda ku e stul?",
        },
        inbound_already_stored=True,
        include_media=True,
    )

    assert reply["text"].startswith(
        mermaid_reservation_workflow.WELCOME_COPY["pap"]
    )
    assert mermaid_reservation_workflow.WHEELCHAIR_COPY["pap"] in reply["text"]
    assert mermaid_crew_assistance.for_reservation(reservation["public_id"])
