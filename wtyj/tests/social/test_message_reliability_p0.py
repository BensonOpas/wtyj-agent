import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test_secret")

from agents.social.webhook_server import _buffer_message, _flush_buffer, _message_buffers, _buffer_lock
from shared import state_registry


def _cleanup(prefix: str):
    with _buffer_lock:
        for phone, buf in list(_message_buffers.items()):
            if phone.startswith(prefix) and buf.get("timer") is not None:
                buf["timer"].cancel()
            if phone.startswith(prefix):
                _message_buffers.pop(phone, None)
    conn = state_registry._get_conn()
    for table, column in (
        ("whatsapp_threads", "phone"),
        ("whatsapp_booking_state", "phone"),
        ("pending_notifications", "customer_id"),
        ("conversation_status", "conversation_id"),
        ("inbound_processing_events", "conversation_id"),
    ):
        conn.execute(f"DELETE FROM {table} WHERE {column} LIKE ?", (f"{prefix}%",))
    conn.execute("DELETE FROM inbound_processing_events WHERE message_id LIKE ?", (f"{prefix}%",))
    conn.commit()
    conn.close()


def _ledger(message_id: str):
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT status, reason, last_error FROM inbound_processing_events WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    return row


@patch("agents.social.webhook_server.send_text_message", return_value=False)
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message", return_value="Generated reply")
def test_meta_send_failure_does_not_store_assistant_reply(mock_handle, mock_send):
    prefix = "p0rel_meta_fail"
    phone = f"{prefix}_phone"
    msg_id = f"{prefix}_msg"
    _cleanup(prefix)
    try:
        _buffer_message({
            "from": phone,
            "text": "hello",
            "from_name": "Reliability Test",
            "message_id": msg_id,
        })
        with _buffer_lock:
            _message_buffers[phone]["timer"].cancel()
        _flush_buffer(phone)

        history = state_registry.wa_get_full_history(phone, limit=10)
        assert [m["role"] for m in history] == ["user"]
        assert history[0]["text"] == "hello"
        assert _ledger(msg_id)[0] == "send_failed"
        escalations = [
            e for e in state_registry.get_all_escalations()
            if e["customer_id"] == phone
        ]
        assert escalations
        assert escalations[0]["subject"].startswith("[DELIVERY FAILED]")
    finally:
        _cleanup(prefix)


@patch("agents.social.webhook_server.send_reply", return_value=True)
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message", side_effect=RuntimeError("model boom"))
def test_zernio_inbound_is_stored_before_processing_exception(mock_handle, mock_send):
    prefix = "p0rel_zernio_crash"
    conv = f"{prefix}_conv"
    msg_id = f"{prefix}_msg"
    _cleanup(prefix)
    try:
        _buffer_message({
            "from": conv,
            "text": "please help",
            "from_name": "Reliability Test",
            "message_id": msg_id,
            "_zernio_conversation_id": conv,
            "_zernio_account_id": "acct123",
            "_zernio_channel": "whatsapp",
            "_zernio_sender_name": "Reliability Test",
        })
        with _buffer_lock:
            _message_buffers[conv]["timer"].cancel()
        _flush_buffer(conv)

        history = state_registry.wa_get_full_history(conv, limit=10)
        assert [m["role"] for m in history] == ["user"]
        assert history[0]["text"] == "please help"
        status, reason, error = _ledger(msg_id)
        assert status == "processing_failed"
        assert reason == "exception"
        assert "model boom" in error
    finally:
        _cleanup(prefix)


@patch("agents.social.webhook_server.send_reply", return_value=True)
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message", return_value="Sure.")
def test_zernio_success_marks_inbound_replied_and_stores_once(mock_handle, mock_send):
    prefix = "p0rel_zernio_ok"
    conv = f"{prefix}_conv"
    msg_id = f"{prefix}_msg"
    _cleanup(prefix)
    try:
        _buffer_message({
            "from": conv,
            "text": "hello",
            "from_name": "Reliability Test",
            "message_id": msg_id,
            "_zernio_conversation_id": conv,
            "_zernio_account_id": "acct123",
            "_zernio_channel": "whatsapp",
            "_zernio_sender_name": "Reliability Test",
        })
        with _buffer_lock:
            _message_buffers[conv]["timer"].cancel()
        _flush_buffer(conv)

        history = state_registry.wa_get_full_history(conv, limit=10)
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[0]["text"] == "hello"
        assert history[1]["text"] == "Sure."
        assert _ledger(msg_id)[0] == "replied"
        assert mock_handle.call_args.kwargs["inbound_already_stored"] is True
    finally:
        _cleanup(prefix)


def test_stale_non_terminal_inbound_becomes_visible_failure():
    prefix = "p0rel_stale"
    msg_id = f"{prefix}_msg"
    _cleanup(prefix)
    try:
        state_registry.inbound_processing_record(
            msg_id, conversation_id=f"{prefix}_conv",
            channel="whatsapp", status="received")
        stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        conn = state_registry._get_conn()
        conn.execute(
            "UPDATE inbound_processing_events SET updated_at = ? WHERE message_id = ?",
            (stale, msg_id),
        )
        conn.commit()
        conn.close()

        changed = state_registry.inbound_processing_mark_stale_failures(max_age_seconds=300)

        assert changed >= 1
        status, reason, error = _ledger(msg_id)
        assert status == "processing_failed"
        assert reason == "stale_non_terminal_state"
        assert "terminal state" in error
    finally:
        _cleanup(prefix)
