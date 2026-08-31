# test_143_zernio_whatsapp.py — Zernio WhatsApp: Route WhatsApp Through Zernio
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from unittest.mock import patch, MagicMock
from shared import state_registry, config_loader


def _cleanup(conv_id):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv_id,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (conv_id,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (conv_id,))
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id LIKE 'test_143_%'")
    conn.commit()
    conn.close()


def _make_zernio_wa_payload(conversation_id, text, message_id=None):
    """Build a Zernio webhook payload for a WhatsApp message."""
    return {
        "event": "message.received",
        "account": {"id": "wa_acc_123"},
        "data": {
            "conversationId": conversation_id,
            "id": message_id or f"test_143_{conversation_id}_{text[:10]}",
            "text": text,
            "sender": {"name": "WA Tester"},
            "platform": "whatsapp",
        },
    }


# --- Test 1: WhatsApp channel is "whatsapp" not "whatsapp_dm" ---
def test_zernio_whatsapp_channel_is_whatsapp():
    from agents.social.zernio_dm_client import parse_zernio_webhook
    payload = _make_zernio_wa_payload("conv_143_channel", "hello")
    msg = parse_zernio_webhook(payload)
    assert msg is not None
    assert msg["channel"] == "whatsapp", f"Expected 'whatsapp', got '{msg['channel']}'"
    assert msg["platform"] == "whatsapp"


# --- Test 2: Instagram channel unchanged ---
def test_zernio_instagram_channel_unchanged():
    from agents.social.zernio_dm_client import parse_zernio_webhook
    payload = {
        "event": "message.received",
        "account": {"id": "ig_acc"},
        "data": {
            "conversationId": "conv_143_ig",
            "id": "test_143_ig_msg",
            "text": "hello",
            "sender": {"name": "IG User"},
            "platform": "instagram",
        },
    }
    msg = parse_zernio_webhook(payload)
    assert msg["channel"] == "instagram_dm", f"Expected 'instagram_dm', got '{msg['channel']}'"


# --- Test 3: WhatsApp via Zernio uses debounce buffer ---
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server._buffer_message")
def test_zernio_whatsapp_uses_debounce(mock_buffer, mock_typing):
    from agents.social.webhook_server import _process_zernio_event
    conv_id = "conv_143_debounce"
    _cleanup(conv_id)

    payload = _make_zernio_wa_payload(conv_id, "I want to book")
    _process_zernio_event(payload)

    # Should go through debounce buffer, not process immediately
    mock_buffer.assert_called_once()
    msg_arg = mock_buffer.call_args[0][0]
    assert msg_arg["from"] == conv_id
    assert msg_arg["_zernio_conversation_id"] == conv_id
    assert msg_arg["_zernio_account_id"] == "wa_acc_123"
    _cleanup(conv_id)


@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server._buffer_message")
def test_zernio_empty_text_native_picker_reply_is_not_ignored(
    mock_buffer, mock_typing,
):
    from agents.social.webhook_server import _process_zernio_event
    from agents.social.ali_vehicle_recommendations import vehicle_selection_payload

    conv_id = "conv_143_picker"
    _cleanup(conv_id)
    payload = _make_zernio_wa_payload(
        conv_id, "", message_id="test_143_picker_empty"
    )
    payload["data"]["metadata"] = {
        "interactiveType": "list_reply",
        "interactiveId": vehicle_selection_payload("vehicle-1"),
    }

    _process_zernio_event(payload)

    mock_buffer.assert_called_once()
    buffered = mock_buffer.call_args[0][0]
    assert buffered["text"] == ""
    assert buffered["_zernio_interactive_type"] == "list_reply"
    assert buffered["_zernio_interactive_id"] == vehicle_selection_payload(
        "vehicle-1"
    )
    _cleanup(conv_id)


# --- Test 4: Zernio WhatsApp reply goes via send_reply ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.send_text_message")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_zernio_whatsapp_reply_via_zernio(mock_orchestrator, mock_meta_send, mock_zernio_send):
    from agents.social.webhook_server import _flush_buffer, _message_buffers, _buffer_lock
    import threading

    conv_id = "conv_143_reply"
    _cleanup(conv_id)
    mock_orchestrator.return_value = "Booking confirmed!"

    # Simulate a buffered Zernio WhatsApp message
    with _buffer_lock:
        _message_buffers[conv_id] = {
            "messages": [{
                "from": conv_id,
                "text": "Book sunset cruise",
                "from_name": "WA Tester",
                "_zernio_conversation_id": conv_id,
                "_zernio_account_id": "wa_acc_123",
                "_zernio_channel": "whatsapp",
                "_zernio_sender_name": "WA Tester",
            }],
            "timer": None,
            "started": time.time(),
        }

    _flush_buffer(conv_id)

    # Reply via Zernio (not Meta)
    mock_zernio_send.assert_called_once()
    mock_meta_send.assert_not_called()
    assert mock_zernio_send.call_args[0][0] == "whatsapp"  # channel (Brief 187 — send_reply first arg)
    assert mock_zernio_send.call_args[0][1] == conv_id
    assert mock_zernio_send.call_args[0][3] == "Booking confirmed!"
    _cleanup(conv_id)


# --- Test 5: Debounce batches multiple messages ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_zernio_whatsapp_debounce_batches(mock_orchestrator, mock_send):
    from agents.social.webhook_server import _flush_buffer, _message_buffers, _buffer_lock

    conv_id = "conv_143_batch"
    _cleanup(conv_id)
    mock_orchestrator.return_value = "Got it!"

    # Simulate 2 buffered messages
    with _buffer_lock:
        _message_buffers[conv_id] = {
            "messages": [
                {
                    "from": conv_id, "text": "hey",
                    "from_name": "WA Tester",
                    "_zernio_conversation_id": conv_id,
                    "_zernio_account_id": "wa_acc_123",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "WA Tester",
                },
                {
                    "from": conv_id, "text": "I want to book sunset cruise",
                    "from_name": "WA Tester",
                    "_zernio_conversation_id": conv_id,
                    "_zernio_account_id": "wa_acc_123",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "WA Tester",
                },
            ],
            "timer": None,
            "started": time.time(),
        }

    _flush_buffer(conv_id)

    # Only one orchestrator call with combined text
    mock_orchestrator.assert_called_once()
    msg_arg = mock_orchestrator.call_args[0][0]
    assert "hey" in msg_arg["text"]
    assert "sunset cruise" in msg_arg["text"]
    _cleanup(conv_id)


# --- Test 6: booking_flow=false routes to DM agent ---
@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.handle_incoming_dm")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_zernio_whatsapp_booking_flow_off_uses_dm_agent(mock_orchestrator, mock_dm, mock_send):
    from agents.social.webhook_server import _flush_buffer, _message_buffers, _buffer_lock

    conv_id = "conv_143_flow_off"
    _cleanup(conv_id)
    mock_dm.return_value = "We have great trips!"
    mock_orchestrator.return_value = "Should not be called"

    raw = config_loader._cache
    original = raw.get("features", {}).get("booking_flow", True)
    original_workflow = raw.get("workflow")
    raw.setdefault("features", {})["booking_flow"] = False
    raw["workflow"] = {"type": "qa_only"}
    try:
        with _buffer_lock:
            _message_buffers[conv_id] = {
                "messages": [{
                    "from": conv_id, "text": "What trips do you have?",
                    "from_name": "WA Tester",
                    "_zernio_conversation_id": conv_id,
                    "_zernio_account_id": "wa_acc_123",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "WA Tester",
                }],
                "timer": None,
                "started": time.time(),
            }

        _flush_buffer(conv_id)

        # DM agent called, orchestrator NOT called
        mock_dm.assert_called_once()
        mock_orchestrator.assert_not_called()
        # Reply via Zernio
        mock_send.assert_called_once()
    finally:
        raw["features"]["booking_flow"] = original
        if original_workflow is None:
            raw.pop("workflow", None)
        else:
            raw["workflow"] = original_workflow
        _cleanup(conv_id)



def test_zernio_whatsapp_platform_is_case_normalized():
    from agents.social.zernio_dm_client import parse_zernio_webhook

    payload = _make_zernio_wa_payload("conv_163_case", "hello")
    payload["data"]["platform"] = " WhatsApp "

    msg = parse_zernio_webhook(payload)

    assert msg is not None
    assert msg["platform"] == "whatsapp"
    assert msg["channel"] == "whatsapp"


def test_ali_quote_whatsapp_selector_ignores_booking_flow_switch():
    from agents.social.webhook_server import _use_whatsapp_orchestrator

    raw = {
        "slug": "ali-car-rental",
        "workflow": {"type": "ali_quote"},
        "features": {"booking_flow": False},
    }
    with patch.object(config_loader, "get_raw", return_value=raw):
        assert _use_whatsapp_orchestrator("whatsapp") is True
        assert _use_whatsapp_orchestrator("WhatsApp") is True
        assert _use_whatsapp_orchestrator("instagram_dm") is False
        assert _use_whatsapp_orchestrator("facebook_dm") is False


@patch("agents.social.webhook_server.send_reply")
@patch("agents.social.webhook_server.handle_incoming_dm")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_ali_quote_zernio_ingress_uses_orchestrator_and_final_safety(
    mock_orchestrator, mock_dm, mock_send
):
    from agents.social.webhook_server import (
        _buffer_lock,
        _flush_buffer,
        _message_buffers,
    )

    conv_id = "conv_163_ali_quote"
    _cleanup(conv_id)
    mock_orchestrator.return_value = (
        "For bookings, please reach out on WhatsApp at wa.me/96777145 "
        "or email info@alicarrental.com, that's where we handle everything!"
    )
    raw = {
        "slug": "ali-car-rental",
        "workflow": {"type": "ali_quote"},
        "features": {
            "booking_flow": False,
            "ali_quote_automation": True,
        },
    }

    with patch.object(config_loader, "get_raw", return_value=raw):
        with _buffer_lock:
            _message_buffers[conv_id] = {
                "messages": [{
                    "from": conv_id,
                    "text": "My complete synthetic rental details",
                    "from_name": "Synthetic Calvin",
                    "_zernio_conversation_id": conv_id,
                    "_zernio_account_id": "wa_acc_123",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "Synthetic Calvin",
                }],
                "timer": None,
                "started": time.time(),
            }

        _flush_buffer(conv_id)

    mock_orchestrator.assert_called_once()
    mock_dm.assert_not_called()
    mock_send.assert_called_once()
    sent_text = mock_send.call_args[0][3]
    assert sent_text == (
        "I couldn't complete that step safely. "
        "Please try again here in a moment."
    )
    assert "wa.me" not in sent_text
    assert "@" not in sent_text
    _cleanup(conv_id)



@patch("agents.social.webhook_server.send_text_message")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_ali_quote_legacy_meta_outbound_boundary_sanitizes(
    mock_orchestrator, mock_send
):
    from agents.social.webhook_server import (
        _buffer_lock,
        _flush_buffer,
        _message_buffers,
    )

    phone = "synthetic_meta_163"
    _cleanup(phone)
    mock_orchestrator.return_value = (
        "For bookings, message us on WhatsApp at wa.me/96777145 "
        "or email info@alicarrental.com."
    )
    raw = {
        "slug": "ali-car-rental",
        "workflow": {"type": "ali_quote"},
        "features": {
            "booking_flow": False,
            "ali_quote_automation": True,
        },
    }

    with patch.object(config_loader, "get_raw", return_value=raw):
        with _buffer_lock:
            _message_buffers[phone] = {
                "messages": [{
                    "from": phone,
                    "text": "Complete synthetic rental details",
                    "from_name": "Synthetic Calvin",
                    "message_id": "test_143_meta_163",
                }],
                "timer": None,
                "started": time.time(),
            }

        _flush_buffer(phone)

    mock_orchestrator.assert_called_once()
    mock_send.assert_called_once()
    sent_text = mock_send.call_args.kwargs["text"]
    assert sent_text == (
        "I couldn't complete that step safely. "
        "Please try again here in a moment."
    )
    assert "wa.me" not in sent_text
    assert "@" not in sent_text
    _cleanup(phone)


def test_late_message_failed_event_reconciles_without_entering_nick(monkeypatch):
    from agents.social import webhook_server

    reconciled = []
    monkeypatch.setattr(
        webhook_server.state_registry,
        "wa_claim_vehicle_recommendation_failure",
        lambda conversation_id, message_id: (
            reconciled.append((conversation_id, message_id)) or {
                "matched": True,
                "already_handled": False,
                "failed_message_id": message_id,
                "hash": "a" * 64,
                "stage": "retry",
                "snapshot": {"text": "Here is one suitable car."},
                "account_id": "account-1",
            }
        ),
    )
    monkeypatch.setattr(
        webhook_server,
        "parse_zernio_webhook",
        lambda _payload: (_ for _ in ()).throw(
            AssertionError("failed delivery must not enter inbound parsing")
        ),
    )
    monkeypatch.setattr(
        webhook_server,
        "reconcile_quote_confirmation_failure",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("a known carousel part is not a quote-control failure")
        ),
    )
    recovered = []
    monkeypatch.setattr(
        webhook_server.config_loader,
        "get_raw",
        lambda: {"workflow": {"type": "ali_quote"}},
    )
    monkeypatch.setattr(
        webhook_server,
        "get_intake_catalog",
        lambda **_kwargs: {"catalogVersion": 13},
    )
    monkeypatch.setattr(
        webhook_server,
        "recover_dm_vehicle_recommendation",
        lambda conversation_id, account_id, recovery, catalog: (
            recovered.append((conversation_id, account_id, recovery, catalog))
            or {"success": True, "delivery": "carousel_retry"}
        ),
    )
    completed = []
    monkeypatch.setattr(
        webhook_server.state_registry,
        "wa_complete_vehicle_recommendation_recovery",
        lambda *args: completed.append(args) or True,
    )

    webhook_server._process_zernio_event({
        "event": "message.failed",
        "message": {
            "id": "provider-image-1",
            "conversationId": "conversation-1",
        },
    })

    assert reconciled == [("conversation-1", "provider-image-1")]
    assert len(recovered) == 1
    assert recovered[0][0:2] == ("conversation-1", "account-1")
    assert recovered[0][3] == {"catalogVersion": 13}
    assert len(completed) == 1


def test_quote_confirmation_fallback_uses_customer_language(monkeypatch):
    from agents.social import webhook_server

    monkeypatch.setattr(
        webhook_server.state_registry,
        "wa_get_booking_state",
        lambda _conversation_id: {
            "fields": {"conversation_language": "es"},
            "flags": {},
        },
    )

    fallback = webhook_server._quote_confirmation_fallback_text(
        "conversation-es", "Resumen actual del alquiler",
    )

    assert fallback == (
        "Resumen actual del alquiler\n\n"
        "Responde ENVIAR COTIZACIÓN para continuar o CAMBIAR DATOS "
        "para hacer una corrección."
    )
    assert webhook_server._quote_confirmation_fallback_text(
        "conversation-es", fallback,
    ) == fallback


def test_failed_plain_text_does_not_trigger_recursive_fallback(monkeypatch):
    from agents.social import webhook_server

    monkeypatch.setattr(
        webhook_server.config_loader,
        "get_raw",
        lambda: {"workflow": {"type": "ali_quote"}},
    )
    monkeypatch.setattr(
        webhook_server.state_registry,
        "wa_claim_vehicle_recommendation_failure",
        lambda *_args: {"matched": False},
    )
    sends = []
    monkeypatch.setattr(
        webhook_server,
        "send_reply",
        lambda *args, **kwargs: sends.append((args, kwargs)) or True,
    )

    webhook_server._process_zernio_event({
        "event": "message.failed",
        "message": {
            "id": "provider-text-fallback-1",
            "conversationId": "conversation-1",
            "accountId": "account-1",
            "message": "Here is one suitable car.",
            "deliveryError": {"message": "Synthetic text failure"},
        },
    })

    assert sends == []
