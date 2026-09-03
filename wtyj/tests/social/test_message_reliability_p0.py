import os
import sys
import threading
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
        assert _ledger(msg_id)[:2] == (
            "recovering", "provider_send_retry",
        )
    finally:
        _cleanup(prefix)


def test_provider_failed_ali_summary_recovers_and_commits_once():
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


def test_provider_failed_ali_summary_retries_are_bounded_and_technical():
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
            "UPDATE inbound_processing_events SET attempt_count = 3 "
            "WHERE message_id = ?",
            (msg_id,),
        )
        conn.commit()
        conn.close()
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
        stage.side_effect = lambda phone, batch_id, messages: (
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
