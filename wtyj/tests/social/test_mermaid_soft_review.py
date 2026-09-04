"""Mermaid review requests must not mute their own customer acknowledgement."""

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from agents.marina import marina_agent
from agents.social import mermaid_reservation_store as reservations
from agents.social import social_agent, webhook_server
from shared import config_loader, state_registry


CONVERSATION = "mermaid-review-guest"
ACKNOWLEDGEMENT = "Mermaid's team needs to confirm what assistance is possible. I've passed your question to them."
FOLLOWUP = "Breakfast, BBQ lunch and soft drinks are included."


def _understood(action="request_human", reply=ACKNOWLEDGEMENT):
    return {
        "language": "en", "mermaid_action": action, "reply": reply,
        "fields": {}, "requires_human": action == "request_human",
        "has_open_question": action == "question", "confidence": "high",
    }


@pytest.fixture
def review_runtime(tmp_path, monkeypatch):
    config = Path(__file__).resolve().parents[3] / "clients/mermaid/config/client.json"
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setenv("TENANT_ID", "mermaid")
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(state_registry, "_alert_dispatcher", None)
    monkeypatch.setattr(state_registry, "_summary_dispatcher", None)
    monkeypatch.setattr(social_agent.auto_block, "evaluate_inbound", lambda **_kw: {"action": "allow"})
    monkeypatch.setattr("shared.tenant_guard.account_access_state", lambda *_a, **_kw: True)
    controls = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True}, "ai_auto_reply": {"value": True},
        },
    }
    monkeypatch.setattr(webhook_server.icp_overrides, "fetch_overrides", lambda: controls)
    monkeypatch.setattr(webhook_server.icp_overrides, "fetch_overrides_fresh", lambda: controls)
    model = Mock(return_value=_understood())
    monkeypatch.setattr(marina_agent, "process_message", model)
    send = Mock(return_value=True)
    monkeypatch.setattr(webhook_server, "send_reply", send)
    state_registry.wa_save_booking_state(CONVERSATION, {"mermaid_intake": {
        "trip_date": "2026-09-06", "adults": 2, "children": 0, "infants": 0,
        "customer_name": "Test Guest", "pickup_preference": "pier",
        "language": "en", "phase": "awaiting_summary_confirmation",
    }}, {})
    yield model, send, controls
    with webhook_server._buffer_lock:
        for item in webhook_server._message_buffers.values():
            if item.get("timer"):
                item["timer"].cancel()
        webhook_server._message_buffers.clear()


def _rows(sql):
    conn = state_registry._get_conn()
    try:
        return [tuple(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _flush(message_id, text):
    payload = {
        "message_id": message_id, "conversation_id": CONVERSATION,
        "platform": "whatsapp", "channel": "whatsapp", "account_id": "mermaid-account",
        "sender_id": "+15551234567", "sender_name": "Test Guest", "text": text,
    }
    assert state_registry.wa_claim_inbound_processing(
        message_id, CONVERSATION, "whatsapp", payload=payload,
        acceptance_batch_id=hashlib.sha256(message_id.encode()).hexdigest(),
    )
    adapter = webhook_server.ZERNIO_CHANNELS["whatsapp"]
    webhook_server._buffer_message(adapter.from_zernio(payload))
    with webhook_server._buffer_lock:
        webhook_server._message_buffers[CONVERSATION]["timer"].cancel()
    webhook_server._flush_buffer(CONVERSATION)


def test_review_acknowledgement_and_safe_followup_both_deliver(review_runtime):
    model, send, _controls = review_runtime

    def verified_send(*_args, **_kwargs):
        assert _rows("SELECT notification_type, mode FROM pending_notifications") == [("escalation", "soft")]
        assert state_registry.get_ai_muted(CONVERSATION) is False
        return True

    send.side_effect = verified_send
    _flush("review-one", "Can someone with limited mobility get special assistance?")
    assert send.call_count == 1
    assert send.call_args.args[3] == ACKNOWLEDGEMENT
    model.return_value = _understood("question", FOLLOWUP)
    _flush("review-two", "What food is included?")
    assert model.call_count == send.call_count == 2
    assert send.call_args.args[3] == FOLLOWUP
    assert model.call_args.kwargs["thread_fields"]["human_review_pending"] is True
    assert _rows("SELECT status FROM inbound_processing_events ORDER BY message_id") == [("replied",), ("replied",)]
    intake = state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"]
    assert intake["trip_date"] == "2026-09-06"
    assert intake["customer_name"] == "Test Guest"
    assert intake["phase"] == "human_takeover"


@pytest.mark.parametrize("action", ["confirm_summary", "new_booking", "cancel"])
def test_pending_review_cannot_confirm_booking_decisions(review_runtime, action):
    model, send, _controls = review_runtime
    _flush("review-request", "I need help with boarding.")
    model.return_value = _understood(action, "I'll confirm it now.")
    _flush("review-yes", "Yes, book it.")
    assert model.call_count == send.call_count == 2
    assert reservations.latest_for_conversation(CONVERSATION) is None
    intake = state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"]
    assert intake["phase"] == "human_takeover"
    assert intake["trip_date"] == "2026-09-06"
    assert intake["customer_name"] == "Test Guest"
    assert "confirm it now" not in send.call_args.args[3]


def test_existing_reservation_stays_frozen_during_soft_review(review_runtime):
    _model, send, _controls = review_runtime
    intake = dict(state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"])
    intake["phase"] = "summary_confirmed"
    reservation = reservations.confirm_reservation(CONVERSATION, intake, idempotency_key="review-existing")
    _flush("review-existing-question", "Please ask the team about accessible boarding.")
    assert send.call_count == 1
    assert reservations.get_reservation(reservation["public_id"])["human_takeover"] is True
    with pytest.raises(reservations.MermaidReservationError, match="frozen"):
        reservations.transition(reservation["public_id"], "quote_ready", idempotency_key="review-quote", actor="system", reason="must stay frozen")


def test_review_blocks_existing_short_link_and_signed_payment(review_runtime, monkeypatch):
    from agents.social import mermaid_demo_payment as payment

    _model, send, _controls = review_runtime
    monkeypatch.setenv("MERMAID_DEMO_SIGNING_SECRET", "review-test-secret")
    payment_send = Mock(return_value=True)
    monkeypatch.setattr(payment, "send_reply", payment_send)
    intake = dict(state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"])
    intake["phase"] = "summary_confirmed"
    reservation = reservations.confirm_reservation(CONVERSATION, intake, idempotency_key="review-payment")
    for status in ("quote_ready", "demo_payment_pending"):
        reservation = reservations.transition(reservation["public_id"], status, idempotency_key=status, actor="system", reason="test checkout")
    token = payment.build_payment_url("https://checkout.test", reservation["public_id"], "review-test-secret").rsplit("/", 1)[-1]
    signed = payment.resolve_checkout_token(token)
    assert signed is not None
    _flush("review-payment-question", "Please ask the team about accessible boarding.")
    assert send.call_count == 1
    assert payment.resolve_checkout_token(token) is None
    assert payment.complete_short_checkout(token, "success").status_code == 404
    with pytest.raises(reservations.MermaidReservationError, match="frozen"):
        payment.complete_checkout(*signed, "success")
    assert payment_send.call_count == 0
    assert reservations.get_reservation(reservation["public_id"])["state"] == "demo_payment_pending"
    assert _rows("SELECT COUNT(*) FROM mermaid_demo_payments") == [(0,)]


def test_operator_takeover_during_model_blocks_send_and_retains_hard_mode(review_runtime):
    model, send, _controls = review_runtime

    def take_over(**_kwargs):
        state_registry.create_pending_notification(
            "escalation", "whatsapp", CONVERSATION, "Test Guest",
            "Operator takeover", "Operator is handling this conversation", mode="hard",
        )
        state_registry.set_ai_muted(CONVERSATION, True)
        return _understood()

    model.side_effect = take_over
    _flush("review-operator-race", "I need boarding assistance.")
    assert send.call_count == 0
    assert state_registry.get_ai_muted(CONVERSATION) is True
    assert state_registry.get_active_escalation_mode(CONVERSATION) == "hard"
    assert _rows("SELECT status, reason FROM inbound_processing_events") == [("escalated", "human_takeover_ai_muted")]
    _flush("review-operator-followup", "Are you there?")
    assert model.call_count == 1
    assert send.call_count == 0


def test_tenant_pause_during_model_still_blocks_review_acknowledgement(review_runtime):
    model, send, controls = review_runtime

    def pause_during_model(**_kwargs):
        controls["feature_toggles"]["ai_auto_reply"]["value"] = False
        return _understood()

    model.side_effect = pause_during_model
    _flush("review-pause-race", "Can the team check accessibility?")
    assert send.call_count == 0
    assert state_registry.get_ai_muted(CONVERSATION) is False
    assert _rows("SELECT status, reason FROM inbound_processing_events") == [("paused", "tenant_agent_paused")]
