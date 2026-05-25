"""Tests for deterministic appointment detection in normal chat flow."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


def test_detects_customer_confirmed_appointment_time():
    from shared import appointment_detector

    signal = appointment_detector.detect_appointment_signal(
        user_text="11:00 is fine, we have a deal and apointment",
        assistant_reply=(
            "Perfect, 11:00 tomorrow it is. I'll let the team know to expect you."
        ),
        history=[],
    )

    assert signal is not None
    assert signal["title"] == "Appointment request"
    assert signal["date_time_label"] == (
        "Perfect, 11:00 tomorrow it is"
    )
    assert signal["proposed_times"] == ["Perfect, 11:00 tomorrow it is"]


def test_detects_papiamentu_tomorrow_confirmation():
    from shared import appointment_detector

    signal = appointment_detector.detect_appointment_signal(
        user_text="ok bon",
        assistant_reply="Bon! Te ma\u00f1an na 11:00",
        history=[],
    )

    assert signal is not None
    assert signal["date_time_label"] == "Te ma\u00f1an na 11:00"


def test_upsert_writes_pending_appointment_from_normal_exchange(monkeypatch):
    from shared import appointment_detector

    captured = {}
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_get_by_conversation",
        lambda conversation_id: None,
    )
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_upsert",
        lambda **kw: captured.update(kw) or 123,
    )

    row_id = appointment_detector.upsert_pending_from_exchange(
        conversation_id="lawyer-conv-1",
        channel="whatsapp",
        customer_name="Calvin",
        user_text="11:00 is fine, we have a deal and apointment",
        assistant_reply="See you tomorrow at 11:00. The team will be ready for you.",
        history=[],
    )

    assert row_id == 123
    assert captured["conversation_id"] == "lawyer-conv-1"
    assert captured["channel"] == "whatsapp"
    assert captured["customer_name"] == "Calvin"
    assert captured["status"] == "pending_team_confirmation"
    assert captured["date_time_label"] == "See you tomorrow at 11:00"


def test_roberto_cita_request_creates_pending_without_fixed_time(monkeypatch):
    from shared import appointment_detector

    captured = {}
    monkeypatch.setenv("TENANT_SLUG", "clinica-roberto")
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_get_by_conversation",
        lambda conversation_id: None,
    )
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_upsert",
        lambda **kw: captured.update(kw) or 321,
    )

    row_id = appointment_detector.upsert_pending_from_exchange(
        conversation_id="roberto-wa-1",
        channel="whatsapp",
        customer_name="Paciente",
        user_text=(
            "Hola, estoy interesada en terapia EMDR. "
            "Me gustaria pedir cita en Leganes por la tarde."
        ),
        assistant_reply=(
            "Claro. Para revisar disponibilidad, dime tu nombre, "
            "telefono y el motivo de consulta."
        ),
        history=[],
    )

    assert row_id == 321
    assert captured["conversation_id"] == "roberto-wa-1"
    assert captured["status"] == "pending_team_confirmation"
    assert captured["title"].startswith("Consulta Despertares appointment request")
    assert captured["location"].lower() == "leganes"
    assert "pedir cita" in captured["date_time_label"].lower()


def test_roberto_cita_logic_is_tenant_scoped(monkeypatch):
    from shared import appointment_detector

    calls = []
    monkeypatch.setenv("TENANT_SLUG", "unboks")
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_get_by_conversation",
        lambda conversation_id: None,
    )
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_upsert",
        lambda **kw: calls.append(kw) or 321,
    )

    row_id = appointment_detector.upsert_pending_from_exchange(
        conversation_id="non-roberto-wa-1",
        channel="whatsapp",
        customer_name="Paciente",
        user_text="Hola, estoy interesada en terapia EMDR. Me gustaria pedir cita.",
        assistant_reply="Claro, te ayudo.",
        history=[],
    )

    assert row_id == 0
    assert calls == []


def test_roberto_price_only_question_does_not_create_booking(monkeypatch):
    from shared import appointment_detector

    calls = []
    monkeypatch.setenv("TENANT_SLUG", "clinica-roberto")
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_get_by_conversation",
        lambda conversation_id: None,
    )
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_upsert",
        lambda **kw: calls.append(kw) or 321,
    )

    row_id = appointment_detector.upsert_pending_from_exchange(
        conversation_id="roberto-wa-price",
        channel="whatsapp",
        customer_name="Paciente",
        user_text="Hola, cuanto cuesta la terapia individual?",
        assistant_reply="La terapia individual cuesta 50 euros.",
        history=[],
    )

    assert row_id == 0
    assert calls == []


def test_upsert_does_not_downgrade_confirmed_appointment(monkeypatch):
    from shared import appointment_detector

    calls = []
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_get_by_conversation",
        lambda conversation_id: {"status": "confirmed"},
    )
    monkeypatch.setattr(
        appointment_detector.state_registry,
        "appointment_upsert",
        lambda **kw: calls.append(kw) or 123,
    )

    row_id = appointment_detector.upsert_pending_from_exchange(
        conversation_id="lawyer-conv-confirmed",
        channel="whatsapp",
        customer_name="Calvin",
        user_text="11:00 is fine, we have a deal and apointment",
        assistant_reply="Perfect, 11:00 tomorrow it is.",
        history=[],
    )

    assert row_id == 0
    assert calls == []


def test_social_agent_runs_detector_after_reply(monkeypatch):
    from agents.social import social_agent

    captured = {}
    monkeypatch.setattr(
        social_agent.state_registry,
        "wa_get_booking_state",
        lambda phone: {"fields": {}, "flags": {}, "completed_bookings": []},
    )
    monkeypatch.setattr(social_agent.state_registry, "wa_get_history", lambda *a, **k: [])
    monkeypatch.setattr(social_agent.state_registry, "wa_save_booking_state", lambda *a, **k: None)
    monkeypatch.setattr(social_agent.state_registry, "set_conversation_status", lambda *a, **k: None)
    monkeypatch.setattr(
        social_agent.state_registry,
        "customer_lookup_or_create",
        lambda *a, **k: {"id": 1, "display_name": "Calvin"},
    )
    monkeypatch.setattr(social_agent.state_registry, "customer_get_full", lambda *a, **k: {})
    monkeypatch.setattr(social_agent.state_registry, "customer_record_interaction", lambda *a, **k: None)
    monkeypatch.setattr(social_agent.state_registry, "customer_add_identifier", lambda *a, **k: None)
    monkeypatch.setattr(social_agent.state_registry, "customer_update_display_name", lambda *a, **k: None)
    monkeypatch.setattr(
        social_agent.config_loader,
        "get_raw",
        lambda: {"features": {"booking_flow": True}},
    )
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **kw: {
            "reply": "Perfect, 11:00 tomorrow it is. The team will be ready.",
            "intents": ["inquiry"],
            "fields": {},
            "flags": {},
        },
    )
    monkeypatch.setattr(
        social_agent.appointment_detector,
        "upsert_pending_from_exchange",
        lambda **kw: captured.update(kw) or 123,
    )

    reply = social_agent.handle_incoming_whatsapp_message(
        {
            "from": "lawyer-conv-social",
            "text": "11:00 is fine, we have a deal and apointment",
            "from_name": "Calvin",
        },
        channel="whatsapp",
    )

    assert reply.startswith("Perfect")
    assert captured["conversation_id"] == "lawyer-conv-social"
    assert captured["channel"] == "whatsapp"
    assert captured["customer_name"] == "Calvin"
    assert captured["user_text"] == "11:00 is fine, we have a deal and apointment"
    assert "11:00 tomorrow" in captured["assistant_reply"]
