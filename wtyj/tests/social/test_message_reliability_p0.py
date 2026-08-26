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

from agents.social.webhook_server import (
    _buffer_message,
    _flush_buffer,
    _message_buffers,
    _buffer_lock,
    _recover_stale_ali_inbound_once,
)
from agents.social import ali_quote_workflow as workflow
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


def _stale(message_id: str, minutes: int = 10):
    stale = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE inbound_processing_events SET created_at = ?, updated_at = ? "
        "WHERE message_id = ?",
        (stale, stale, message_id),
    )
    conn.commit()
    conn.close()


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


def _summary_commit(action_id: str):
    return {
        "outbound_kind": "summary",
        "phase": "SUMMARY_PRESENTED",
        "primary_intent": "continue_intake",
        "reason_code": "initial_or_corrected_complete_draft",
        "action_id": action_id,
        "draft_hash": "a" * 64,
        "summary_hash": "b" * 64,
        "summary_version": 1,
        "quote_public_id": "",
    }


@patch("agents.social.webhook_server.send_reply", return_value=True)
def test_provider_success_atomically_anchors_summary_confirmation(mock_send):
    prefix = "p0rel_ali_anchor_ok"
    conv = f"{prefix}_conv"
    msg_id = f"{prefix}_msg"
    action_id = "c" * 64
    _cleanup(prefix)
    state_registry.wa_save_booking_state(conv, {}, {"ali_phase": "DISCOVERY"})
    try:
        with patch(
            "agents.social.webhook_server.handle_incoming_whatsapp_message",
            return_value={
                "text": "Synthetic summary",
                "media": None,
                "vehicle_recommendation": None,
                "ali_turn_commit": _summary_commit(action_id),
            },
        ):
            _buffer_message({
                "from": conv, "text": "details", "from_name": "Synthetic",
                "message_id": msg_id, "_zernio_conversation_id": conv,
                "_zernio_account_id": "acct123", "_zernio_channel": "whatsapp",
                "_zernio_sender_name": "Synthetic",
            })
            with _buffer_lock:
                _message_buffers[conv]["timer"].cancel()
            _flush_buffer(conv)

        state = state_registry.wa_get_booking_state(conv)
        history = state_registry.wa_get_full_history(conv, limit=10)
        assert state["flags"]["ali_presented_summary_hash"] == "b" * 64
        assert state["flags"]["ali_last_delivered_kind"] == "summary"
        assert state["flags"]["awaiting_quote_confirmation"] is True
        assert [item["role"] for item in history] == ["user", "assistant"]
        assert _ledger(msg_id)[0] == "replied"
        assert mock_send.call_args.kwargs["confirm_delivery"] is True
        assert mock_send.call_args.kwargs["idempotency_key"] == (
            f"ali-turn-{action_id}"
        )
    finally:
        _cleanup(prefix)


@patch("agents.social.webhook_server.send_reply", return_value=False)
def test_provider_failure_never_makes_summary_confirmable(mock_send):
    prefix = "p0rel_ali_anchor_fail"
    conv = f"{prefix}_conv"
    msg_id = f"{prefix}_msg"
    _cleanup(prefix)
    state_registry.wa_save_booking_state(conv, {}, {"ali_phase": "DISCOVERY"})
    try:
        with patch(
            "agents.social.webhook_server.handle_incoming_whatsapp_message",
            return_value={
                "text": "Synthetic summary",
                "media": None,
                "vehicle_recommendation": None,
                "ali_turn_commit": _summary_commit("d" * 64),
            },
        ):
            _buffer_message({
                "from": conv, "text": "details", "from_name": "Synthetic",
                "message_id": msg_id, "_zernio_conversation_id": conv,
                "_zernio_account_id": "acct123", "_zernio_channel": "whatsapp",
                "_zernio_sender_name": "Synthetic",
            })
            with _buffer_lock:
                _message_buffers[conv]["timer"].cancel()
            _flush_buffer(conv)

        state = state_registry.wa_get_booking_state(conv)
        history = state_registry.wa_get_full_history(conv, limit=10)
        assert "ali_presented_summary_hash" not in state["flags"]
        assert "awaiting_quote_confirmation" not in state["flags"]
        assert [item["role"] for item in history] == ["user"]
        assert _ledger(msg_id)[0] == "send_failed"
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


@patch("agents.social.webhook_server.send_reply", return_value=True)
@patch(
    "agents.social.webhook_server.handle_incoming_whatsapp_message",
    return_value="Recovered reply",
)
def test_stale_ali_turn_sends_one_heartbeat_and_recovers_once(mock_handle, mock_send):
    prefix = "p0rel_recover"
    conv = f"{prefix}_conv"
    msg_id = f"{prefix}_msg"
    _cleanup(prefix)
    payload = {
        "conversation_id": conv,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Synthetic Customer",
        "sender_id": "synthetic-sender",
        "text": "Which car is cheapest?",
        "message_id": msg_id,
        "account_id": "acct123",
        "interactive_type": "",
        "interactive_id": "",
    }
    try:
        state_registry.inbound_processing_record(
            msg_id, conv, "whatsapp", status="processing", payload=payload,
        )
        _stale(msg_id)
        claimed = [{
            "message_id": msg_id,
            "conversation_id": conv,
            "channel": "whatsapp",
            "payload": payload,
            "created_at": (
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat(),
            "heartbeat_sent_at": "",
            "attempt_count": 1,
        }]
        with patch(
            "agents.social.webhook_server.state_registry."
            "inbound_processing_claim_recoverable",
            side_effect=[claimed, []],
        ):
            conn = state_registry._get_conn()
            conn.execute(
                "UPDATE inbound_processing_events "
                "SET status = 'recovering', attempt_count = 1 "
                "WHERE message_id = ?",
                (msg_id,),
            )
            conn.commit()
            conn.close()

            assert _recover_stale_ali_inbound_once(max_age_seconds=40) == 1

        assert mock_handle.call_count == 1
        assert mock_send.call_count == 2
        heartbeat_call = mock_send.call_args_list[0]
        assert heartbeat_call.args[:3] == ("whatsapp", conv, "acct123")
        assert "still checking" in heartbeat_call.args[3]
        assert heartbeat_call.kwargs["confirm_delivery"] is True
        assert heartbeat_call.kwargs["idempotency_key"].startswith(
            "ali-turn-heartbeat-"
        )
        history = state_registry.wa_get_full_history(conv, limit=10)
        assert [(item["role"], item["text"]) for item in history] == [
            ("user", "Which car is cheapest?"),
            ("assistant", "Recovered reply"),
        ]
        conn = state_registry._get_conn()
        row = conn.execute(
            "SELECT status, heartbeat_sent_at, attempt_count "
            "FROM inbound_processing_events WHERE message_id = ?",
            (msg_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "replied"
        assert row[1]
        assert row[2] == 1

        _stale(msg_id)
        with patch(
            "agents.social.webhook_server.state_registry."
            "inbound_processing_claim_recoverable",
            return_value=[],
        ):
            assert _recover_stale_ali_inbound_once(max_age_seconds=40) == 0
        assert mock_handle.call_count == 1
        assert mock_send.call_count == 2
    finally:
        _cleanup(prefix)


def test_newer_outbound_supersedes_abandoned_inbound_recovery():
    prefix = "p0rel_superseded"
    conv = f"{prefix}_conv"
    msg_id = f"{prefix}_msg"
    _cleanup(prefix)
    try:
        state_registry.inbound_processing_record(
            msg_id,
            conv,
            "whatsapp",
            status="processing",
            payload={
                "conversation_id": conv,
                "platform": "whatsapp",
                "channel": "whatsapp",
                "message_id": msg_id,
            },
        )
        _stale(msg_id)
        state_registry.dm_store_message(
            conv, "whatsapp", "assistant", "A newer turn already replied.",
        )

        assert state_registry.inbound_processing_claim_recoverable(40) == []
        assert _ledger(msg_id)[:2] == (
            "superseded", "newer_outbound_exists",
        )
    finally:
        _cleanup(prefix)


def test_recovered_inbound_history_is_idempotent_by_provider_message_batch():
    prefix = "p0rel_history"
    conv = f"{prefix}_conv"
    _cleanup(prefix)
    try:
        assert state_registry.dm_store_inbound_message(
            conv, "whatsapp", "Hello", "Synthetic", ["msg-1", "msg-2"],
        ) is True
        assert state_registry.dm_store_inbound_message(
            conv, "whatsapp", "Hello", "Synthetic", ["msg-2", "msg-1"],
        ) is False
        history = state_registry.wa_get_full_history(conv, limit=10)
        assert [(item["role"], item["text"]) for item in history] == [
            ("user", "Hello"),
        ]
    finally:
        _cleanup(prefix)
