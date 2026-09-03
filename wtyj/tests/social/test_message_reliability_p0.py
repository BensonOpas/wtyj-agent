import json
import os
import sys
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("WHATSAPP_BUSINESS_ACCOUNT_ID", "test-waba")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test_secret")

from agents.social.webhook_server import (
    _buffer_message,
    _acceptance_batch_bindings,
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
        "UPDATE inbound_processing_events SET created_at = ?, updated_at = ?, "
        "lease_expires_at = ? "
        "WHERE message_id = ?",
        (stale, stale, stale, message_id),
    )
    conn.commit()
    conn.close()


def _durably_buffer(message: dict):
    if not message.get("_zernio_conversation_id"):
        message.setdefault(
            "business_account_id",
            os.environ["WHATSAPP_BUSINESS_ACCOUNT_ID"],
        )
        message.setdefault(
            "phone_number_id",
            os.environ["WHATSAPP_PHONE_NUMBER_ID"],
        )
    conversation_id = str(
        message.get("_zernio_conversation_id") or message.get("from") or ""
    )
    channel = str(message.get("_zernio_channel") or "whatsapp")
    state_registry.inbound_processing_record(
        message["message_id"],
        conversation_id,
        channel,
        status="received",
        payload=message,
    )
    _buffer_message(message)


@patch("agents.social.webhook_server.send_text_message", return_value=False)
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message", return_value="Generated reply")
def test_meta_send_failure_does_not_store_assistant_reply(mock_handle, mock_send):
    prefix = "p0rel_meta_fail"
    phone = f"{prefix}_phone"
    msg_id = f"{prefix}_msg"
    _cleanup(prefix)
    try:
        _durably_buffer({
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
        _durably_buffer({
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
        _durably_buffer({
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
            _durably_buffer({
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
            _durably_buffer({
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
        assert _ledger(msg_id)[:2] == (
            "recovering", "provider_send_retry",
        )
    finally:
        _cleanup(prefix)


def test_provider_failed_ali_summary_recovers_and_commits_once(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    prefix = "p0rel_ali_retry_ok"
    conv = f"{prefix}_conv"
    msg_id = f"{prefix}_msg"
    payload = {
        "conversation_id": conv,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Synthetic Customer",
        "sender_id": "synthetic-sender",
        "text": "complete details",
        "message_id": msg_id,
        "account_id": "acct123",
        "interactive_type": "",
        "interactive_id": "",
    }
    _cleanup(prefix)
    state_registry.wa_save_booking_state(conv, {}, {"ali_phase": "DISCOVERY"})
    try:
        state_registry.inbound_processing_record(
            msg_id,
            conv,
            "whatsapp",
            status="recovering",
            reason="provider_send_retry",
            payload=payload,
        )
        _stale(msg_id)
        with patch(
            "agents.social.webhook_server.handle_incoming_whatsapp_message",
            return_value={
                "text": "Synthetic recovered summary",
                "media": None,
                "vehicle_recommendation": None,
                "ali_turn_commit": _summary_commit("e" * 64),
            },
        ), patch(
            "agents.social.webhook_server.send_reply",
            side_effect=[True, True],
        ) as mock_send:
            assert _recover_stale_ali_inbound_once(max_age_seconds=40) == 1

        state = state_registry.wa_get_booking_state(conv)
        history = state_registry.wa_get_full_history(conv, limit=10)
        assert state["flags"]["ali_presented_summary_hash"] == "b" * 64
        assert state["flags"]["awaiting_quote_confirmation"] is True
        assert [item["role"] for item in history] == ["user", "assistant"]
        assert _ledger(msg_id)[0] == "replied"
        assert mock_send.call_count == 2
    finally:
        _cleanup(prefix)


def test_provider_failed_ali_summary_retries_are_bounded_and_technical(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    prefix = "p0rel_ali_retry_exhausted"
    conv = f"{prefix}_conv"
    msg_id = f"{prefix}_msg"
    payload = {
        "conversation_id": conv,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Synthetic Customer",
        "sender_id": "synthetic-sender",
        "text": "complete details",
        "message_id": msg_id,
        "account_id": "acct123",
    }
    _cleanup(prefix)
    try:
        state_registry.inbound_processing_record(
            msg_id,
            conv,
            "whatsapp",
            status="recovering",
            reason="provider_send_retry",
            error="quote_confirmation",
            payload=payload,
        )
        conn = state_registry._get_conn()
        conn.execute(
            "UPDATE inbound_processing_events SET provider_retry_count = 4 "
            "WHERE message_id = ?",
            (msg_id,),
        )
        conn.commit()
        conn.close()
        assert state_registry.inbound_processing_update(
            msg_id,
            "processing",
            reason="tenant_runtime_controls_unavailable",
        ) is True
        _stale(msg_id)

        with patch("agents.social.webhook_server.send_reply") as mock_send:
            assert _recover_stale_ali_inbound_once(max_age_seconds=40) == 0

        assert mock_send.call_count == 0
        assert _ledger(msg_id)[:2] == (
            "send_failed", "provider_send_failed",
        )
        conn = state_registry._get_conn()
        notification = conn.execute(
            "SELECT notification_type, subject FROM pending_notifications "
            "WHERE customer_id = ?",
            (conv,),
        ).fetchone()
        conn.close()
        assert notification[0] == "technical"
        assert notification[1].startswith(
            "[ALI QUOTE CONFIRMATION DELIVERY FAILED]"
        )
    finally:
        _cleanup(prefix)


def test_control_outage_recovery_cycles_do_not_consume_provider_retry_budget(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    conversation_id = "provider-retry-budget-conversation"
    message_id = "provider-retry-budget-message"
    payload = {
        "conversation_id": conversation_id,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Synthetic Customer",
        "sender_id": "synthetic-sender",
        "text": "Retry after controls recover",
        "message_id": message_id,
        "account_id": "acct123",
    }
    state_registry.inbound_processing_record(
        message_id,
        conversation_id,
        "whatsapp",
        status="received",
        payload=payload,
    )
    batch_id = state_registry.inbound_processing_join_batch(message_id)
    assert batch_id
    assert state_registry.inbound_processing_update(
        message_id,
        "processing",
        reason="tenant_runtime_controls_unavailable",
    ) is True

    for _ in range(4):
        claimed = state_registry.inbound_processing_claim_recoverable(
            max_age_seconds=0,
        )
        assert len(claimed) == 1
        assert claimed[0]["provider_retry_count"] == 0
        assert state_registry.inbound_processing_bulk_update(
            [message_id],
            "processing",
            reason="tenant_runtime_controls_unavailable",
            processing_token=claimed[0]["processing_token"],
        ) is True

    # The first actual provider failure starts its independent retry budget;
    # the four earlier control-outage claims remain telemetry only.
    assert state_registry.inbound_processing_update(
        message_id,
        "recovering",
        reason="provider_send_retry",
        error="quote_confirmation",
    ) is True
    enabled = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": True},
        },
    }
    with (
        patch("shared.tenant_guard.account_access_state", return_value=True),
        patch(
            "agents.social.webhook_server.icp_overrides.fetch_overrides_fresh",
            return_value=enabled,
        ),
        patch(
            "agents.social.webhook_server._stage_recovered_batch",
            return_value="provider-retry-budget-buffer",
        ) as stage,
        patch("agents.social.webhook_server._flush_buffer") as flush,
        patch("agents.social.webhook_server._mark_delivery_failed") as failed,
        patch(
            "agents.social.webhook_server._mark_ali_structured_delivery_failed"
        ) as structured_failed,
    ):
        assert _recover_stale_ali_inbound_once(
            max_age_seconds=0,
            ali_workflow=False,
        ) == 1

    stage.assert_called_once()
    flush.assert_called_once_with("provider-retry-budget-buffer")
    failed.assert_not_called()
    structured_failed.assert_not_called()
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT attempt_count, provider_retry_count "
        "FROM inbound_processing_events WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 5
    assert row[1] == 1


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
    durable_batch_id = state_registry._inbound_processing_batch_id(msg_id)
    recovery_token = "a" * 64
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
            "batch_id": durable_batch_id,
            "batch_position": 0,
            "processing_token": recovery_token,
        }]
        with patch(
            "agents.social.webhook_server.state_registry."
            "inbound_processing_claim_recoverable",
            side_effect=[claimed, []],
        ):
            conn = state_registry._get_conn()
            conn.execute(
                "UPDATE inbound_processing_events "
                "SET status = 'recovering', attempt_count = 1, "
                "batch_id = ?, batch_position = 0, processing_token = ? "
                "WHERE message_id = ?",
                (durable_batch_id, recovery_token, msg_id),
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

        claimed = state_registry.inbound_processing_claim_recoverable(40)
        assert all(item["message_id"] != msg_id for item in claimed)
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


def test_recovery_claim_limit_never_splits_or_merges_durable_batches(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    conversation_id = "durable-batch-conversation"
    message_ids = ["durable-batch-1", "durable-batch-2", "durable-batch-3"]
    for index, message_id in enumerate(message_ids):
        assert state_registry.wa_claim_inbound_processing(
            message_id,
            conversation_id,
            "whatsapp",
            {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "platform": "whatsapp",
                "channel": "whatsapp",
                "account_id": "account-1",
                "text": f"message {index + 1}",
            },
        ) is True

    first_batch_id = state_registry.inbound_processing_join_batch(message_ids[0])
    assert state_registry.inbound_processing_join_batch(
        message_ids[1], first_batch_id, 1,
    ) == first_batch_id
    second_batch_id = state_registry.inbound_processing_join_batch(message_ids[2])
    assert second_batch_id != first_batch_id
    _stale(message_ids[0], minutes=20)
    _stale(message_ids[1], minutes=20)
    _stale(message_ids[2], minutes=10)

    first_claim = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=40, limit=1,
    )
    second_claim = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=40, limit=1,
    )

    assert [item["message_id"] for item in first_claim] == message_ids[:2]
    assert {item["batch_id"] for item in first_claim} == {first_batch_id}
    assert [item["batch_position"] for item in first_claim] == [0, 1]
    assert [item["message_id"] for item in second_claim] == message_ids[2:]
    assert {item["batch_id"] for item in second_claim} == {second_batch_id}


def test_recovery_never_resurrects_terminal_member_of_partial_batch(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    conversation_id = "partial-terminal-conversation"
    message_ids = ["partial-terminal-1", "partial-terminal-2"]
    for message_id in message_ids:
        assert state_registry.wa_claim_inbound_processing(
            message_id,
            conversation_id,
            "whatsapp",
            {"message_id": message_id, "text": message_id},
        ) is True
    batch_id = state_registry.inbound_processing_join_batch(message_ids[0])
    state_registry.inbound_processing_join_batch(message_ids[1], batch_id, 1)
    _stale(message_ids[0])
    _stale(message_ids[1])
    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE inbound_processing_events SET status = 'replied' "
        "WHERE message_id = ?",
        (message_ids[0],),
    )
    conn.commit()
    conn.close()

    claimed = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=40,
    )

    assert claimed == []
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT message_id, status, reason FROM inbound_processing_events "
        "ORDER BY batch_position",
    ).fetchall()
    conn.close()
    assert [tuple(row) for row in rows] == [
        (message_ids[0], "replied", ""),
        (message_ids[1], "processing_failed", "incomplete_durable_batch"),
    ]


def test_recovery_batch_claim_is_atomic_across_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    conversation_id = "atomic-batch-claim-conversation"
    message_ids = ["atomic-batch-claim-1", "atomic-batch-claim-2"]
    for message_id in message_ids:
        assert state_registry.wa_claim_inbound_processing(
            message_id,
            conversation_id,
            "whatsapp",
            {"message_id": message_id, "text": message_id},
        ) is True
    batch_id = state_registry.inbound_processing_join_batch(message_ids[0])
    state_registry.inbound_processing_join_batch(message_ids[1], batch_id, 1)
    _stale(message_ids[0])
    _stale(message_ids[1])

    start = threading.Barrier(3)
    outcomes = []
    failures = []

    def claim():
        try:
            start.wait(timeout=5)
            outcomes.append(state_registry.inbound_processing_claim_recoverable(
                max_age_seconds=40, limit=1,
            ))
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    workers = [threading.Thread(target=claim) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait(timeout=5)
    for worker in workers:
        worker.join(timeout=5)

    assert not failures
    assert all(not worker.is_alive() for worker in workers)
    nonempty = [outcome for outcome in outcomes if outcome]
    assert len(nonempty) == 1
    assert [item["message_id"] for item in nonempty[0]] == message_ids
    assert len([outcome for outcome in outcomes if not outcome]) == 1


def test_fresh_unleased_processing_is_not_stolen_by_old_created_at(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    message_id = "fresh-processing-old-created"
    batch_id = "f" * 64
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        "fresh-processing-conversation",
        "whatsapp",
        {"message_id": message_id, "text": "Still working"},
        acceptance_batch_id=batch_id,
    ) is True
    old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE inbound_processing_events SET status = 'processing', "
        "created_at = ?, updated_at = ?, lease_expires_at = '' "
        "WHERE message_id = ?",
        (old, fresh, message_id),
    )
    conn.commit()
    conn.close()

    assert state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=40,
    ) == []

    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE inbound_processing_events SET updated_at = ? "
        "WHERE message_id = ?",
        (old, message_id),
    )
    conn.commit()
    conn.close()
    claimed = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=40,
    )
    assert [item["message_id"] for item in claimed] == [message_id]


def test_long_debounce_lease_blocks_recovery_until_explicit_expiry(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    phone = "long-debounce-lease-conversation"
    message_id = "long-debounce-lease-message"
    message = {
        "from": phone,
        "from_name": "Lease Test",
        "message_id": message_id,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "text": "Please wait for the rest",
    }
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        phone,
        "whatsapp",
        message,
    ) is True
    long_timing = {
        "message_batching_enabled": True,
        "mode": "custom",
        "preset": "balanced",
        "delay_seconds": 300.0,
        "max_wait_seconds": 300.0,
        "custom_delay_seconds": 300.0,
        "random_min_seconds": 10.0,
        "random_max_seconds": 20.0,
        "source": "lease_test",
    }
    try:
        with patch(
            "agents.social.webhook_server._response_timing_for_message",
            return_value=long_timing,
        ):
            _buffer_message(message)
        with _buffer_lock:
            _message_buffers[phone]["timer"].cancel()

        old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        conn = state_registry._get_conn()
        row = conn.execute(
            "SELECT lease_expires_at FROM inbound_processing_events "
            "WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        assert datetime.fromisoformat(row[0]) > (
            datetime.now(timezone.utc) + timedelta(seconds=290)
        )
        conn.execute(
            "UPDATE inbound_processing_events SET created_at = ?, updated_at = ? "
            "WHERE message_id = ?",
            (old, old, message_id),
        )
        conn.commit()
        conn.close()

        assert state_registry.inbound_processing_claim_recoverable(
            max_age_seconds=40,
        ) == []

        conn = state_registry._get_conn()
        conn.execute(
            "UPDATE inbound_processing_events SET lease_expires_at = ? "
            "WHERE message_id = ?",
            (old, message_id),
        )
        conn.commit()
        conn.close()
        claimed = state_registry.inbound_processing_claim_recoverable(
            max_age_seconds=40,
        )
        assert [item["message_id"] for item in claimed] == [message_id]
    finally:
        with _buffer_lock:
            buffered = _message_buffers.pop(phone, None)
            if buffered and buffered.get("timer") is not None:
                buffered["timer"].cancel()


def test_crash_before_buffer_remains_promptly_recoverable(tmp_path, monkeypatch):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    message_id = "crash-before-buffer"
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        "crash-before-buffer-conversation",
        "whatsapp",
        {"message_id": message_id, "text": "Accepted only"},
    ) is True
    _stale(message_id)

    claimed = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=40,
    )

    assert [item["message_id"] for item in claimed] == [message_id]


def test_recovering_retry_replaces_processing_lease_and_cleanup_honors_lease(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    message_id = "processing-to-recovering-lease"
    batch_id = "r" * 64
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        "processing-to-recovering-conversation",
        "whatsapp",
        {"message_id": message_id, "text": "Retry me"},
        acceptance_batch_id=batch_id,
    ) is True
    processing_token = state_registry.inbound_processing_begin_batch(
        [message_id], batch_id=batch_id,
    )
    assert processing_token
    old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE inbound_processing_events SET created_at = ?, updated_at = ? "
        "WHERE message_id = ?",
        (old, old, message_id),
    )
    conn.commit()
    conn.close()

    assert state_registry.inbound_processing_mark_stale_failures(
        max_age_seconds=0,
    ) == 0
    state_registry.inbound_processing_bulk_update(
        [message_id],
        "recovering",
        reason="provider_send_retry",
        processing_token=processing_token,
    )
    claimed = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=40,
    )
    assert [item["message_id"] for item in claimed] == [message_id]


def test_stale_cleanup_leaves_expired_payload_lease_for_recovery_claim(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    expired_id = "cleanup-expired-processing-lease"
    active_id = "cleanup-active-processing-lease"
    for message_id, batch_id in ((expired_id, "e" * 64), (active_id, "a" * 64)):
        assert state_registry.wa_claim_inbound_processing(
            message_id,
            "cleanup-expiry-conversation-" + message_id,
            "whatsapp",
            {"message_id": message_id, "text": message_id},
            acceptance_batch_id=batch_id,
        ) is True
        assert state_registry.inbound_processing_begin_batch(
            [message_id], batch_id=batch_id,
        )

    now = datetime.now(timezone.utc)
    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE inbound_processing_events SET lease_expires_at = ? "
        "WHERE message_id = ?",
        ((now - timedelta(seconds=1)).isoformat(), expired_id),
    )
    conn.execute(
        "UPDATE inbound_processing_events SET lease_expires_at = ? "
        "WHERE message_id = ?",
        ((now + timedelta(minutes=1)).isoformat(), active_id),
    )
    conn.commit()
    conn.close()

    # Cleanup may run on an incoming request just before the five-second
    # recovery loop. It must not terminalize a row whose preserved payload can
    # still be replayed.
    assert state_registry.inbound_processing_mark_stale_failures(
        max_age_seconds=3600,
    ) == 0
    claimed = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=3600,
    )
    assert [item["message_id"] for item in claimed] == [expired_id]
    assert _ledger(expired_id)[0] == "recovering"
    assert _ledger(active_id)[0] == "processing"


def test_stale_cleanup_terminalizes_payloadless_recovering_and_legacy_rows(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    retry_id = "cleanup-payloadless-recovering"
    legacy_id = "cleanup-payloadless-legacy"
    active_id = "cleanup-payloadless-active"
    state_registry.inbound_processing_record(
        retry_id, "cleanup-retry", "whatsapp", status="recovering",
    )
    state_registry.inbound_processing_record(
        legacy_id, "cleanup-legacy", "whatsapp", status="processing",
    )
    state_registry.inbound_processing_record(
        active_id, "cleanup-active", "whatsapp", status="recovering",
    )
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=10)).isoformat()
    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE inbound_processing_events SET updated_at = ? "
        "WHERE message_id = ?",
        (old, legacy_id),
    )
    conn.execute(
        "UPDATE inbound_processing_events SET lease_expires_at = ? "
        "WHERE message_id = ?",
        ((now + timedelta(minutes=1)).isoformat(), active_id),
    )
    conn.commit()
    conn.close()

    assert state_registry.inbound_processing_mark_stale_failures(
        max_age_seconds=300,
    ) == 2
    assert _ledger(retry_id)[0] == "processing_failed"
    assert _ledger(legacy_id)[0] == "processing_failed"
    assert _ledger(active_id)[0] == "recovering"
    assert state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=0,
    ) == []


@pytest.mark.parametrize(
    "corrupt_payload",
    [
        "not-json",
        json.dumps({"message_id": "corrupt-recovery", "platform": "whatsapp"}),
    ],
)
def test_recovery_terminalizes_malformed_or_unroutable_payload(
    tmp_path, monkeypatch, corrupt_payload,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    message_id = "corrupt-recovery"
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        "corrupt-recovery-conversation",
        "whatsapp",
        {
            "message_id": message_id,
            "platform": "whatsapp",
            "channel": "whatsapp",
            "from": "corrupt-recovery-conversation",
            "business_account_id": "current-waba",
            "phone_number_id": "current-phone",
            "text": "Recover me",
        },
    ) is True
    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE inbound_processing_events SET payload_json = ? "
        "WHERE message_id = ?",
        (corrupt_payload, message_id),
    )
    conn.commit()
    conn.close()
    _stale(message_id)

    with (
        patch("shared.tenant_guard.account_access_state") as account_state,
        patch("agents.social.webhook_server._stage_recovered_batch") as stage,
        patch("agents.social.webhook_server._flush_buffer") as flush,
    ):
        recovered = _recover_stale_ali_inbound_once(
            max_age_seconds=40,
            ali_workflow=False,
        )

    assert recovered == 0
    account_state.assert_not_called()
    stage.assert_not_called()
    flush.assert_not_called()
    assert _ledger(message_id)[:2] == (
        "processing_failed", "invalid_recovery_payload",
    )


def test_control_unavailable_relinquishes_lease_but_terminal_status_clears_it(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    retry_id = "control-unavailable-processing"
    terminal_id = "terminal-clears-processing-lease"
    processing_tokens = {}
    for message_id, batch_id in ((retry_id, "u" * 64), (terminal_id, "t" * 64)):
        assert state_registry.wa_claim_inbound_processing(
            message_id,
            "lease-transition-conversation-" + message_id,
            "whatsapp",
            {"message_id": message_id, "text": message_id},
            acceptance_batch_id=batch_id,
        ) is True
        processing_tokens[message_id] = state_registry.inbound_processing_begin_batch(
            [message_id], batch_id=batch_id,
        )
        assert processing_tokens[message_id]

    state_registry.inbound_processing_bulk_update(
        [retry_id],
        "processing",
        reason="tenant_runtime_controls_unavailable",
        processing_token=processing_tokens[retry_id],
    )
    state_registry.inbound_processing_bulk_update(
        [terminal_id],
        "paused",
        reason="tenant_agent_paused",
        processing_token=processing_tokens[terminal_id],
    )
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT message_id, lease_expires_at FROM inbound_processing_events "
        "ORDER BY message_id",
    ).fetchall()
    conn.close()
    leases = {str(row[0]): str(row[1]) for row in rows}
    assert leases[terminal_id] == ""
    assert datetime.fromisoformat(leases[retry_id]) <= datetime.now(timezone.utc)

    claimed = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=40,
    )
    assert [item["message_id"] for item in claimed] == [retry_id]


def test_debounce_buffer_persists_one_identity_for_every_original_member(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    conversation_id = "buffer-membership-conversation"
    message_ids = ["buffer-membership-1", "buffer-membership-2"]
    for message_id in message_ids:
        assert state_registry.wa_claim_inbound_processing(
            message_id,
            conversation_id,
            "whatsapp",
            {"message_id": message_id, "text": message_id},
        ) is True

    try:
        for message_id in message_ids:
            _buffer_message({
                "from": conversation_id,
                "text": message_id,
                "from_name": "Batch Test",
                "message_id": message_id,
            })
        with _buffer_lock:
            buffered = _message_buffers[conversation_id]
            buffered["timer"].cancel()
            in_memory_batch_id = buffered["batch_id"]
        conn = state_registry._get_conn()
        rows = conn.execute(
            "SELECT message_id, batch_id, batch_position "
            "FROM inbound_processing_events ORDER BY batch_position",
        ).fetchall()
        conn.close()

        assert in_memory_batch_id
        assert [tuple(row) for row in rows] == [
            (message_ids[0], in_memory_batch_id, 0),
            (message_ids[1], in_memory_batch_id, 1),
        ]
    finally:
        with _buffer_lock:
            buffered = _message_buffers.pop(conversation_id, None)
            if buffered and buffered.get("timer") is not None:
                buffered["timer"].cancel()


def test_flush_reorders_interleaved_memory_by_durable_batch_position(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "current-waba")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "current-phone")
    phone = "deterministic-batch-order-conversation"
    messages = [
        {
            "from": phone,
            "from_name": label,
            "message_id": f"deterministic-batch-{label.lower()}",
            "platform": "whatsapp",
            "channel": "whatsapp",
            "text": label,
            "business_account_id": "current-waba",
            "phone_number_id": "current-phone",
        }
        for label in ("A", "B", "C")
    ]
    bindings = _acceptance_batch_bindings(messages)
    batch_id = bindings[messages[0]["message_id"]][0]
    for message in messages:
        durable_batch_id, position = bindings[message["message_id"]]
        assert state_registry.wa_claim_inbound_processing(
            message["message_id"],
            phone,
            "whatsapp",
            message,
            acceptance_batch_id=durable_batch_id,
            acceptance_position=position,
        ) is True

    seen = []

    def capture_model(message, **_kwargs):
        seen.append(dict(message))
        return ""

    try:
        # Simulate background-task scheduling that appends C before B even
        # though the signed webhook's durable order is A, B, C.
        for index in (0, 2, 1):
            _buffer_message(messages[index])
        with _buffer_lock:
            buffered = _message_buffers[phone]
            buffered["timer"].cancel()
            assert [item["text"] for item in buffered["messages"]] == [
                "A", "C", "B",
            ]
            assert buffered["batch_id"] == batch_id

        with (
            patch(
                "agents.social.webhook_server._whatsapp_inbox_still_enabled",
                return_value=True,
            ),
            patch(
                "agents.social.webhook_server.icp_overrides.auto_reply_state",
                return_value=True,
            ),
            patch(
                "agents.social.webhook_server.state_registry.get_blocked",
                return_value=False,
            ),
            patch(
                "agents.social.webhook_server.state_registry.get_ai_muted",
                return_value=False,
            ),
            patch(
                "agents.social.webhook_server.handle_incoming_whatsapp_message",
                side_effect=capture_model,
            ),
            patch("agents.social.webhook_server.send_text_message") as send,
        ):
            _flush_buffer(phone)

        assert len(seen) == 1
        assert seen[0]["text"] == "A\nB\nC"
        assert seen[0]["from_name"] == "C"
        send.assert_not_called()
        history = state_registry.wa_get_full_history(phone)
        assert [(item["role"], item["text"]) for item in history] == [
            ("user", "A\nB\nC"),
        ]
    finally:
        with _buffer_lock:
            buffered = _message_buffers.pop(phone, None)
            if buffered and buffered.get("timer") is not None:
                buffered["timer"].cancel()


def test_pre_ack_batch_survives_partial_background_buffer_and_recovers_whole(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    phone = "pre-ack-partial-background"
    messages = [
        {
            "from": phone,
            "from_name": "Batch Test",
            "message_id": f"pre-ack-partial-{index}",
            "platform": "whatsapp",
            "channel": "whatsapp",
            "text": text,
            "business_account_id": "waba-current",
            "phone_number_id": "phone-current",
        }
        for index, text in enumerate(("First", "Second"), start=1)
    ]
    bindings = _acceptance_batch_bindings(messages)
    acceptance_batch_id = bindings[messages[0]["message_id"]][0]
    assert [bindings[item["message_id"]] for item in messages] == [
        (acceptance_batch_id, 0),
        (acceptance_batch_id, 1),
    ]
    for message in messages:
        batch_id, position = bindings[message["message_id"]]
        assert state_registry.wa_claim_inbound_processing(
            message["message_id"],
            phone,
            "whatsapp",
            message,
            acceptance_batch_id=batch_id,
            acceptance_position=position,
        ) is True

    try:
        # Simulate FastAPI running only the first background task before the
        # process dies. The second member must already share its durable turn.
        _buffer_message(messages[0])
        with _buffer_lock:
            buffered = _message_buffers[phone]
            buffered["timer"].cancel()
            assert buffered["batch_id"] == acceptance_batch_id

        conn = state_registry._get_conn()
        rows = conn.execute(
            "SELECT message_id, status, batch_id, batch_position, "
            "lease_expires_at "
            "FROM inbound_processing_events ORDER BY batch_position",
        ).fetchall()
        conn.close()
        assert [tuple(row[:4]) for row in rows] == [
            (messages[0]["message_id"], "received", acceptance_batch_id, 0),
            (messages[1]["message_id"], "received", acceptance_batch_id, 1),
        ]
        assert len({str(row[4]) for row in rows}) == 1
        assert datetime.fromisoformat(rows[0][4]) > datetime.now(timezone.utc)

        # A surviving timer only knows about member one. It must fail closed,
        # leaving both durable rows available for whole-batch recovery.
        with (
            patch(
                "agents.social.webhook_server.handle_incoming_whatsapp_message"
            ) as model,
            patch("agents.social.webhook_server.send_text_message") as send,
        ):
            _flush_buffer(phone)
        model.assert_not_called()
        send.assert_not_called()
        for message in messages:
            _stale(message["message_id"])
        recovered = state_registry.inbound_processing_claim_recoverable(
            max_age_seconds=40,
        )
        assert [item["message_id"] for item in recovered] == [
            message["message_id"] for message in messages
        ]
        assert {item["batch_id"] for item in recovered} == {
            acceptance_batch_id
        }
    finally:
        with _buffer_lock:
            buffered = _message_buffers.pop(phone, None)
            if buffered and buffered.get("timer") is not None:
                buffered["timer"].cancel()


def test_claimed_batch_guards_require_exact_membership_and_one_outbound_attempt(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    conversation_id = "exact-batch-guards"
    message_ids = ["exact-batch-1", "exact-batch-2"]
    batch_id = "e" * 64

    assert state_registry.inbound_processing_begin_batch(
        ["missing-all"], batch_id=batch_id,
    ) is False
    assert state_registry.inbound_processing_claim_outbound_attempt(
        ["missing-all"], "meta-auto-reply-missing", batch_id,
    ) is False

    assert state_registry.wa_claim_inbound_processing(
        message_ids[0],
        conversation_id,
        "whatsapp",
        {"message_id": message_ids[0], "text": "First"},
        acceptance_batch_id=batch_id,
        acceptance_position=0,
    ) is True
    assert state_registry.inbound_processing_begin_batch(
        message_ids, batch_id=batch_id,
    ) is False
    assert state_registry.inbound_processing_claim_outbound_attempt(
        message_ids, "meta-auto-reply-partial", batch_id,
    ) is False

    assert state_registry.wa_claim_inbound_processing(
        message_ids[1],
        conversation_id,
        "whatsapp",
        {"message_id": message_ids[1], "text": "Second"},
        acceptance_batch_id=batch_id,
        acceptance_position=1,
    ) is True
    assert state_registry.inbound_processing_begin_batch(
        message_ids[:1], batch_id=batch_id,
    ) is False
    processing_token = state_registry.inbound_processing_begin_batch(
        message_ids, batch_id=batch_id,
    )
    assert processing_token

    assert state_registry.inbound_processing_claim_outbound_attempt(
        message_ids[:1], "meta-auto-reply-subset", batch_id,
        processing_token=processing_token,
    ) is False
    assert state_registry.inbound_processing_claim_outbound_attempt(
        message_ids, "meta-auto-reply-wrong-batch", "f" * 64,
        processing_token=processing_token,
    ) is False

    start = threading.Barrier(3)
    outcomes = []

    def claim_outbound():
        start.wait(timeout=5)
        outcomes.append(state_registry.inbound_processing_claim_outbound_attempt(
            message_ids,
            "meta-auto-reply-exact",
            batch_id,
            processing_token=processing_token,
        ))

    workers = [threading.Thread(target=claim_outbound) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait(timeout=5)
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert sorted(outcomes) == [False, True]
    state_registry.inbound_processing_bulk_update(
        message_ids,
        "replied",
        reason="provider_send_ok",
        processing_token=processing_token,
    )
    assert state_registry.inbound_processing_begin_batch(
        message_ids, batch_id=batch_id,
    ) is False

    late_id = "exact-batch-late"
    late_batch_id = "1" * 64
    assert state_registry.wa_claim_inbound_processing(
        late_id,
        conversation_id,
        "whatsapp",
        {"message_id": late_id, "text": "Late"},
        acceptance_batch_id=late_batch_id,
    ) is True
    assert state_registry.inbound_processing_join_batch(
        late_id, batch_id, 2,
    ) == late_batch_id


def test_processing_generation_fences_reclaimed_worker_and_terminal_state(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    message_id = "generation-fence-message"
    conversation_id = "generation-fence-conversation"
    batch_id = "g" * 64
    payload = {
        "message_id": message_id,
        "from": conversation_id,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "text": "Fence this turn",
        "business_account_id": "waba-generation",
        "phone_number_id": "phone-generation",
    }
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        conversation_id,
        "whatsapp",
        payload,
        acceptance_batch_id=batch_id,
    ) is True

    worker_a = state_registry.inbound_processing_begin_batch(
        [message_id],
        batch_id=batch_id,
        processing_lease_seconds=0,
    )
    assert worker_a
    recovered = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=0,
    )
    assert len(recovered) == 1
    recovery_token = recovered[0]["processing_token"]
    assert recovery_token and recovery_token != worker_a
    worker_b = state_registry.inbound_processing_begin_batch(
        [message_id],
        batch_id=batch_id,
        recovering=True,
        recovery_token=recovery_token,
    )
    assert worker_b and worker_b not in {worker_a, recovery_token}

    assert state_registry.inbound_processing_is_current(
        [message_id], batch_id, worker_a,
    ) is False
    assert state_registry.inbound_processing_claim_outbound_attempt(
        [message_id],
        "stale-worker-send",
        batch_id,
        processing_token=worker_a,
    ) is False
    assert state_registry.inbound_processing_claim_outbound_attempt(
        [message_id],
        "current-worker-send",
        batch_id,
        processing_token=worker_b,
    ) is True
    assert state_registry.inbound_processing_bulk_update(
        [message_id],
        "replied",
        reason="current_worker_completed",
        processing_token=worker_b,
    ) is True
    assert state_registry.inbound_processing_bulk_update(
        [message_id],
        "recovering",
        reason="stale_worker_resumed",
        processing_token=worker_a,
    ) is False
    assert state_registry.inbound_processing_quarantine_batch(
        [message_id],
        "stale_worker_quarantine",
        processing_token=worker_a,
    ) is False

    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT status, reason, processing_token "
        "FROM inbound_processing_events WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    assert tuple(row) == ("replied", "current_worker_completed", "")


def test_ali_delivery_commit_rejects_reclaimed_processing_generation(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    message_id = "ali-generation-fence-message"
    conversation_id = "ali-generation-fence-conversation"
    batch_id = "a" * 64
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        conversation_id,
        "whatsapp",
        {"message_id": message_id, "text": "Fence the Ali commit"},
        acceptance_batch_id=batch_id,
    ) is True
    state_registry.wa_save_booking_state(
        conversation_id, {}, {"ali_phase": "DISCOVERY"},
    )

    worker_a = state_registry.inbound_processing_begin_batch(
        [message_id],
        batch_id=batch_id,
        processing_lease_seconds=0,
    )
    assert worker_a
    recovered = state_registry.inbound_processing_claim_recoverable(
        max_age_seconds=0,
    )
    assert len(recovered) == 1
    worker_b = state_registry.inbound_processing_begin_batch(
        [message_id],
        batch_id=batch_id,
        recovering=True,
        recovery_token=recovered[0]["processing_token"],
    )
    assert worker_b and worker_b != worker_a
    delivery = {
        "outbound_kind": "agent_reply",
        "phase": "DISCOVERY",
        "primary_intent": "other",
        "reason_code": "generation_fence_test",
        "action_id": "b" * 64,
    }

    assert workflow.commit_ali_turn_delivery(
        conversation_id,
        delivery,
        "Stale worker reply",
        [message_id],
        inbound_processing_token=worker_a,
    ) is False
    assert state_registry.wa_get_full_history(conversation_id, limit=10) == []
    assert state_registry.wa_get_booking_state(conversation_id)["flags"] == {
        "ali_phase": "DISCOVERY"
    }

    assert workflow.commit_ali_turn_delivery(
        conversation_id,
        delivery,
        "Current worker reply",
        [message_id],
        inbound_processing_token=worker_b,
    ) is True
    history = state_registry.wa_get_full_history(conversation_id, limit=10)
    assert [(item["role"], item["text"]) for item in history] == [
        ("assistant", "Current worker reply")
    ]
    assert _ledger(message_id)[:2] == ("replied", "provider_send_ok")


def test_processing_lease_covers_two_model_calls_and_provider_commit(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    message_id = "processing-lease-duration"
    batch_id = "l" * 64
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        "processing-lease-conversation",
        "whatsapp",
        {"message_id": message_id, "text": "Long-running turn"},
        acceptance_batch_id=batch_id,
    ) is True

    started = datetime.now(timezone.utc)
    processing_token = state_registry.inbound_processing_begin_batch(
        [message_id], batch_id=batch_id,
    )
    assert processing_token
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT lease_expires_at, processing_token "
        "FROM inbound_processing_events WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    lease_seconds = (datetime.fromisoformat(row[0]) - started).total_seconds()
    assert 1319 <= lease_seconds <= 1322
    assert row[1] == processing_token


@pytest.mark.parametrize(
    "destination_change,expected_status,expected_reason,payload_is_scrubbed",
    [
        (
            "unavailable",
            "recovering",
            "tenant_account_control_unavailable",
            False,
        ),
        (
            "reassigned",
            "ignored",
            "send_meta_destination_reassigned",
            True,
        ),
    ],
)
def test_direct_meta_revalidates_destination_after_model_before_send(
    destination_change,
    expected_status,
    expected_reason,
    payload_is_scrubbed,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "captured-waba")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "captured-phone")
    phone = f"direct-meta-final-fence-{destination_change}"
    message_id = f"direct-meta-final-fence-message-{destination_change}"
    message = {
        "from": phone,
        "from_name": "Destination fence customer",
        "message_id": message_id,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "text": "Do not send this to a reassigned destination",
        "business_account_id": "captured-waba",
        "phone_number_id": "captured-phone",
    }
    enabled = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": True},
        },
    }

    def change_destination_after_model(*_args, **_kwargs):
        if destination_change == "unavailable":
            monkeypatch.delenv("WHATSAPP_BUSINESS_ACCOUNT_ID", raising=False)
            monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
        else:
            monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "new-waba")
            monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "new-phone")
        return "Generated reply for the captured destination"

    _durably_buffer(message)
    with _buffer_lock:
        _message_buffers[phone]["timer"].cancel()
    try:
        with (
            patch(
                "agents.social.webhook_server.icp_overrides.fetch_overrides",
                return_value=enabled,
            ),
            patch(
                "agents.social.webhook_server._whatsapp_inbox_still_enabled",
                return_value=True,
            ),
            patch(
                "agents.social.webhook_server._automated_send_still_enabled",
                return_value=True,
            ),
            patch(
                "agents.social.webhook_server.state_registry.get_blocked",
                return_value=False,
            ),
            patch(
                "agents.social.webhook_server.state_registry.get_ai_muted",
                return_value=False,
            ),
            patch(
                "agents.social.webhook_server.handle_incoming_whatsapp_message",
                side_effect=change_destination_after_model,
            ) as model,
            patch(
                "agents.social.webhook_server.send_text_message",
                return_value=True,
            ) as send,
        ):
            _flush_buffer(phone)
    finally:
        with _buffer_lock:
            _message_buffers.pop(phone, None)

    model.assert_called_once()
    send.assert_not_called()
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT status, reason, payload_json, conversation_id, channel "
        "FROM inbound_processing_events WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    assert tuple(row[:2]) == (expected_status, expected_reason)
    if payload_is_scrubbed:
        assert tuple(row[2:]) == ("{}", "", "")
    else:
        assert json.loads(row[2])["text"] == message["text"]
        assert tuple(row[3:]) == (phone, "whatsapp")


def test_direct_meta_recovery_quarantines_reassigned_destination(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "current-waba")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "current-phone")
    phone = "15550001111"
    message_id = "direct-meta-old-destination"
    payload = {
        "from": phone,
        "from_name": "Former tenant customer",
        "message_id": message_id,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "text": "private old-tenant message",
        "business_account_id": "old-waba",
        "phone_number_id": "old-phone",
    }
    batch_id = _acceptance_batch_bindings([payload])[message_id][0]
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        phone,
        "whatsapp",
        payload,
        acceptance_batch_id=batch_id,
    ) is True
    _stale(message_id)

    with (
        patch("agents.social.webhook_server._stage_recovered_batch") as stage,
        patch("agents.social.webhook_server._flush_buffer") as flush,
        patch("agents.social.webhook_server.send_text_message") as send,
    ):
        recovered = _recover_stale_ali_inbound_once(
            max_age_seconds=40,
            ali_workflow=False,
        )

    assert recovered == 0
    stage.assert_not_called()
    flush.assert_not_called()
    send.assert_not_called()
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT status, reason, payload_json, conversation_id, channel "
        "FROM inbound_processing_events WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    assert tuple(row) == (
        "ignored",
        "recovery_account_not_allowlisted",
        "{}",
        "",
        "",
    )


def test_direct_meta_recovery_defers_when_destination_control_is_unavailable(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.delenv("WHATSAPP_BUSINESS_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    phone = "15550001112"
    message_id = "direct-meta-destination-control-outage"
    payload = {
        "from": phone,
        "from_name": "Current tenant customer",
        "message_id": message_id,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "text": "recover this after controls return",
        "business_account_id": "current-waba",
        "phone_number_id": "current-phone",
    }
    batch_id = _acceptance_batch_bindings([payload])[message_id][0]
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        phone,
        "whatsapp",
        payload,
        acceptance_batch_id=batch_id,
    ) is True
    _stale(message_id)

    with (
        patch("agents.social.webhook_server._stage_recovered_batch") as stage,
        patch("agents.social.webhook_server._flush_buffer") as flush,
        patch("agents.social.webhook_server.send_text_message") as send,
    ):
        recovered = _recover_stale_ali_inbound_once(
            max_age_seconds=40,
            ali_workflow=False,
        )

    assert recovered == 0
    stage.assert_not_called()
    flush.assert_not_called()
    send.assert_not_called()
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT status, reason, payload_json, conversation_id, channel "
        "FROM inbound_processing_events WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    assert row[0] == "recovering"
    assert row[1] == "tenant_account_control_unavailable"
    assert json.loads(row[2])["text"] == payload["text"]
    assert tuple(row[3:]) == (phone, "whatsapp")


def test_direct_meta_post_send_crash_does_not_repeat_provider_attempt(
    tmp_path, monkeypatch,
):
    from agents.social import webhook_server

    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "current-waba")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "current-phone")
    phone = "15550002222"
    message_id = "direct-meta-post-send-crash"
    payload = {
        "from": phone,
        "from_name": "Crash Test",
        "message_id": message_id,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "text": "Can you help?",
        "business_account_id": "current-waba",
        "phone_number_id": "current-phone",
    }
    batch_id = _acceptance_batch_bindings([payload])[message_id][0]
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        phone,
        "whatsapp",
        payload,
        acceptance_batch_id=batch_id,
    ) is True
    provider_attempts = []
    model_user_counts = []

    def accepted_then_crash(*, to, text):
        provider_attempts.append((to, text))
        raise SystemExit("simulated process death after provider acceptance")

    def recovered_answer(*_args, **_kwargs):
        model_user_counts.append(sum(
            item["role"] == "user"
            for item in state_registry.wa_get_full_history(phone)
        ))
        return "Recovered answer"

    enabled = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": True},
        },
    }
    try:
        with (
            patch.object(
                webhook_server,
                "_whatsapp_inbox_still_enabled",
                return_value=True,
            ),
            patch.object(
                webhook_server,
                "_automated_send_still_enabled",
                return_value=True,
            ),
            patch.object(
                webhook_server.icp_overrides,
                "fetch_overrides",
                return_value=enabled,
            ),
            patch.object(
                webhook_server.icp_overrides,
                "fetch_overrides_fresh",
                return_value=enabled,
            ),
            patch.object(
                webhook_server.icp_overrides,
                "whatsapp_inbox_state",
                return_value=True,
            ),
            patch.object(
                webhook_server.icp_overrides,
                "auto_reply_state",
                return_value=True,
            ),
            patch.object(state_registry, "get_blocked", return_value=False),
            patch.object(state_registry, "get_ai_muted", return_value=False),
            patch.object(
                webhook_server,
                "handle_incoming_whatsapp_message",
                side_effect=recovered_answer,
            ) as model,
            patch.object(
                webhook_server,
                "send_text_message",
                side_effect=accepted_then_crash,
            ),
        ):
            _buffer_message(payload)
            with _buffer_lock:
                _message_buffers[phone]["timer"].cancel()
            with pytest.raises(SystemExit):
                _flush_buffer(phone)

            _stale(message_id)
            assert _recover_stale_ali_inbound_once(
                max_age_seconds=40,
                ali_workflow=False,
            ) == 1

        assert model.call_count == 2
        assert model_user_counts == [1, 1]
        assert provider_attempts == [(phone, "Recovered answer")]
        conn = state_registry._get_conn()
        row = conn.execute(
            "SELECT status, reason, outbound_idempotency_key "
            "FROM inbound_processing_events WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        transcript = conn.execute(
            "SELECT role, text, source_message_key FROM whatsapp_threads "
            "WHERE phone = ? ORDER BY id",
            (phone,),
        ).fetchall()
        conn.close()
        assert tuple(row) == (
            "send_failed",
            "provider_send_failed",
            f"meta-auto-reply-{batch_id}",
        )
        assert len(transcript) == 1
        assert tuple(transcript[0][:2]) == ("user", "Can you help?")
        assert transcript[0][2]
    finally:
        with _buffer_lock:
            for key, buffered in list(_message_buffers.items()):
                if buffered.get("phone") == phone:
                    if buffered.get("timer") is not None:
                        buffered["timer"].cancel()
                    _message_buffers.pop(key, None)


def test_recovery_keeps_two_batches_for_same_conversation_isolated():
    conversation_id = "two-recovery-batches-conversation"

    def recovered_item(message_id, batch_id, position):
        payload = {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "platform": "whatsapp",
            "channel": "whatsapp",
            "account_id": "account-1",
            "sender_id": "15550000000",
            "sender_name": "Batch Test",
            "text": message_id,
        }
        return {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "channel": "whatsapp",
            "payload": payload,
            "created_at": f"2026-09-03T10:00:0{position}+00:00",
            "heartbeat_sent_at": "",
            "attempt_count": 1,
            "recovery_reason": "",
            "recovery_error": "",
            "batch_id": batch_id,
            "batch_position": position,
            "processing_token": (
                "a" * 64 if batch_id == "a" * 64 else "b" * 64
            ),
        }

    claimed = [
        recovered_item("batch-a-1", "a" * 64, 0),
        recovered_item("batch-a-2", "a" * 64, 1),
        recovered_item("batch-b-1", "b" * 64, 0),
    ]
    with (
        patch.object(
            state_registry, "inbound_processing_claim_recoverable",
            return_value=claimed,
        ),
        patch("shared.tenant_guard.is_account_allowed", return_value=True),
        patch(
            "agents.social.webhook_server.icp_overrides.fetch_overrides_fresh",
            return_value={"available": True},
        ),
        patch(
            "agents.social.webhook_server.icp_overrides.whatsapp_inbox_state",
            return_value=True,
        ),
        patch(
            "agents.social.webhook_server.icp_overrides.auto_reply_state",
            return_value=True,
        ),
        patch.object(state_registry, "get_ai_muted", return_value=False),
        patch.object(state_registry, "get_blocked", return_value=False),
        patch("agents.social.webhook_server._stage_recovered_batch") as stage,
        patch("agents.social.webhook_server._flush_buffer") as flush,
        patch("agents.social.webhook_server.send_reply") as heartbeat,
    ):
        stage.side_effect = lambda phone, batch_id, messages, **_kwargs: (
            f"{phone}\x1erecovery-batch:{batch_id}"
        )
        recovered = _recover_stale_ali_inbound_once(
            max_age_seconds=40, ali_workflow=False,
        )

    assert recovered == 3
    assert [(call.args[1], len(call.args[2])) for call in stage.call_args_list] == [
        ("a" * 64, 2),
        ("b" * 64, 1),
    ]
    assert [call.args[0] for call in flush.call_args_list] == [
        f"{conversation_id}\x1erecovery-batch:{'a' * 64}",
        f"{conversation_id}\x1erecovery-batch:{'b' * 64}",
    ]
    heartbeat.assert_not_called()


def test_outbound_dashboard_event_is_exactly_once_by_source_key():
    prefix = "p0rel_outbound_once"
    conv = f"{prefix}_conv"
    _cleanup(prefix)
    try:
        assert state_registry.dm_store_message_once(
            conv,
            "whatsapp",
            "assistant",
            "✅ Your official quote was sent successfully. Quote: ALI-TEST",
            "ali-quote-delivered:quote-test",
        ) is True
        assert state_registry.dm_store_message_once(
            conv,
            "whatsapp",
            "assistant",
            "This retry must not create another row.",
            "ali-quote-delivered:quote-test",
        ) is True

        history = state_registry.wa_get_full_history(conv, limit=10)
        assert [(item["role"], item["text"]) for item in history] == [
            (
                "assistant",
                "✅ Your official quote was sent successfully. "
                "Quote: ALI-TEST",
            ),
        ]
    finally:
        _cleanup(prefix)
