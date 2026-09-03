"""Customer handoff promises require a current, durable operator item."""

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.social import dm_agent, webhook_server, zernio_dm_client
from shared import state_registry


@pytest.fixture
def handoff_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    config = {
        "slug": "mermaid",
        "business": {"name": "Mermaid", "agent_name": "TRACY"},
        "features": {"booking_flow": False},
        "agent_persona": {
            "unsupported_attachment_handoff": {
                "enabled": True,
                "reply": "Mermaid's team needs to review this attachment.",
            },
        },
    }
    enabled = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": True},
        },
    }
    monkeypatch.setattr(dm_agent.config_loader, "get_raw", lambda: config)
    monkeypatch.setattr(webhook_server.icp_overrides, "fetch_overrides", lambda: enabled)
    monkeypatch.setattr(webhook_server.icp_overrides, "fetch_overrides_fresh", lambda: enabled)
    monkeypatch.setattr(state_registry, "match_ignored_contact", lambda **_kw: None)
    monkeypatch.setattr(state_registry, "get_blocked", lambda *_a: False)
    monkeypatch.setattr(state_registry, "get_ai_muted", lambda *_a: False)
    monkeypatch.setattr(dm_agent.auto_block, "evaluate_inbound", lambda **_kw: {"action": "allow"})
    monkeypatch.setattr(webhook_server, "_use_whatsapp_orchestrator", lambda *_a: False)
    response = MagicMock()
    response.content = [MagicMock(text="Mermaid's team needs to review this.\n[ESCALATE]")]
    response.usage = None
    model = MagicMock()
    model.return_value.messages.create.return_value = response
    monkeypatch.setattr(dm_agent.anthropic, "Anthropic", model)
    with patch("shared.tenant_guard.account_access_state", return_value=True) as account:
        yield config, model, account
    with webhook_server._buffer_lock:
        for buffered in webhook_server._message_buffers.values():
            if buffered.get("timer") is not None:
                buffered["timer"].cancel()
        webhook_server._message_buffers.clear()


def _stage_handoff(text="Please ask a person", attachments=None):
    message_id = "handoff-test-message"
    conversation_id = "handoff-test-conversation"
    batch_id = hashlib.sha256(message_id.encode()).hexdigest()
    message = {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "platform": "whatsapp",
        "channel": "whatsapp",
        "account_id": "mermaid-account",
        "sender_id": "+15551234567",
        "sender_name": "Demo guest",
        "text": text,
        "attachments": attachments or [],
    }
    assert state_registry.wa_claim_inbound_processing(
        message_id, conversation_id, "whatsapp", payload=message,
        acceptance_batch_id=batch_id,
    )
    adapter = webhook_server.ZERNIO_CHANNELS["whatsapp"]
    webhook_server._buffer_message(adapter.from_zernio(message))
    with webhook_server._buffer_lock:
        buffered = webhook_server._message_buffers[conversation_id]
        buffered["timer"].cancel()
        batch_id = buffered["batch_id"]
    return message_id, conversation_id, batch_id


def _rows(sql):
    conn = state_registry._get_conn()
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [tuple(row) for row in rows]


def test_handoff_operator_item_exists_before_customer_send(handoff_runtime):
    _message_id, conversation_id, _batch_id = _stage_handoff()

    def send_after_commit(*_args, **_kwargs):
        assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(1,)]
        return True

    with patch.object(webhook_server, "send_reply", side_effect=send_after_commit) as send:
        webhook_server._flush_buffer(conversation_id)
    send.assert_called_once()
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]
    assert _rows("SELECT notification_type, mode FROM pending_notifications") == [("escalation", "soft")]


def test_handoff_persistence_failure_is_recoverable_and_never_sends(handoff_runtime):
    _message_id, conversation_id, _batch_id = _stage_handoff()
    with (
        patch.object(state_registry, "inbound_processing_commit_handoff", side_effect=RuntimeError("db down")),
        patch.object(webhook_server, "send_reply") as send,
    ):
        webhook_server._flush_buffer(conversation_id)
    send.assert_not_called()
    status, reason, payload = _rows("SELECT status, reason, payload_json FROM inbound_processing_events")[0]
    assert (status, reason) == ("recovering", "handoff_persistence_unavailable")
    assert json.loads(payload)["account_id"] == "mermaid-account"
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(0,)]


@pytest.mark.parametrize("account_state, expected", [(False, "ignored"), (None, "recovering")])
def test_handoff_rechecks_account_after_model(handoff_runtime, account_state, expected):
    _config, model, account = handoff_runtime
    _message_id, conversation_id, _batch_id = _stage_handoff()
    reply = model.return_value.messages.create.return_value

    def reassign_during_model(**_kwargs):
        account.return_value = account_state
        return reply

    model.return_value.messages.create.side_effect = reassign_during_model
    with patch.object(webhook_server, "send_reply") as send:
        webhook_server._flush_buffer(conversation_id)
    send.assert_not_called()
    assert _rows("SELECT status FROM inbound_processing_events") == [(expected,)]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(0,)]


@pytest.mark.parametrize("text", ["", "Please check this screenshot"])
def test_configured_unsupported_attachment_handoff_is_metadata_only(handoff_runtime, text):
    _config, model, _account = handoff_runtime
    _message_id, conversation_id, _batch_id = _stage_handoff(
        text, [{"type": "image", "url": "https://sensitive.invalid/private-token"}],
    )
    with patch.object(webhook_server, "send_reply", return_value=True) as send:
        webhook_server._flush_buffer(conversation_id)
    model.assert_not_called()
    send.assert_called_once()
    assert send.call_args.args[3] == "Mermaid's team needs to review this attachment."
    body = _rows("SELECT body FROM pending_notifications")[0][0]
    assert "private-token" not in body
    assert text or "[Attachment received]" in body


def test_unconfigured_attachment_does_not_change_legacy_qa(handoff_runtime):
    config, model, _account = handoff_runtime
    config["agent_persona"] = {}
    with patch.object(state_registry, "create_pending_notification"):
        reply = dm_agent.handle_incoming_dm({
            "conversation_id": "ordinary-tenant",
            "channel": "whatsapp",
            "text": "A caption",
            "attachments": [{"type": "image"}],
        })
    model.assert_called_once()
    assert isinstance(reply, str)


def test_handoff_commit_is_idempotent_and_rejects_stale_generation(handoff_runtime):
    message_id, conversation_id, batch_id = _stage_handoff()
    token_a = state_registry.inbound_processing_begin_batch([message_id], batch_id=batch_id)
    notification = {"channel": "whatsapp", "customer_id": conversation_id, "subject": "Help", "body": "Review"}

    def commit(token):
        return state_registry.inbound_processing_commit_handoff(
            [message_id], batch_id, token, account_id="mermaid-account", notification=notification,
        )

    first_id = commit(token_a)
    assert first_id and commit(token_a) == first_id
    assert state_registry.inbound_processing_bulk_update(
        [message_id], "recovering", reason="crash", processing_token=token_a,
    )
    reclaimed = state_registry.inbound_processing_claim_recoverable(max_age_seconds=0)
    assert len(reclaimed) == 1
    token_b = state_registry.inbound_processing_begin_batch(
        [message_id], batch_id=batch_id, recovering=True,
        recovery_token=reclaimed[0]["processing_token"],
    )
    assert token_b and token_b != token_a
    assert commit(token_a) is None
    assert commit(token_b) == first_id
    assert state_registry.inbound_processing_bulk_update(
        [message_id], "replied", processing_token=token_b,
    )
    assert commit(token_b) is None
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(1,)]


def test_handoff_dedup_marker_cannot_replace_a_deleted_operator_item(handoff_runtime):
    message_id, conversation_id, batch_id = _stage_handoff()
    token = state_registry.inbound_processing_begin_batch([message_id], batch_id=batch_id)
    notification = {"channel": "whatsapp", "customer_id": conversation_id, "subject": "Help", "body": "Review"}
    notification_id = state_registry.inbound_processing_commit_handoff(
        [message_id], batch_id, token, account_id="mermaid-account", notification=notification,
    )
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (notification_id,))
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="operator item is unavailable"):
        state_registry.inbound_processing_commit_handoff(
            [message_id], batch_id, token, account_id="mermaid-account", notification=notification,
        )
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(0,)]
    assert _rows("SELECT status FROM inbound_processing_events") == [("processing",)]


@pytest.mark.parametrize("hard_stop", ["get_blocked", "get_ai_muted"])
def test_final_send_guard_rechecks_local_hard_stop_after_controls(handoff_runtime, monkeypatch, hard_stop):
    message_id, conversation_id, batch_id = _stage_handoff()
    token = state_registry.inbound_processing_begin_batch([message_id], batch_id=batch_id)
    state = {"stopped": False}
    enabled = webhook_server.icp_overrides.fetch_overrides_fresh()
    monkeypatch.setattr(state_registry, hard_stop, lambda *_a: state["stopped"])

    def stop_during_control_read():
        state["stopped"] = True
        return enabled

    monkeypatch.setattr(webhook_server.icp_overrides, "fetch_overrides_fresh", stop_during_control_read)
    assert not webhook_server._automated_send_still_enabled(
        "whatsapp", conversation_id, [message_id], token, batch_id,
    )
    expected = "ignored" if hard_stop == "get_blocked" else "escalated"
    assert _rows("SELECT status FROM inbound_processing_events") == [(expected,)]


@pytest.mark.parametrize(
    "change,expected_status",
    [("controls", "processing"), ("control_exception", "processing"), ("account", "recovering"),
     ("foreign", "ignored"), ("muted", "escalated"), ("blocked", "ignored"),
     ("claim", "recovering")],
)
def test_provider_preflight_change_never_posts_or_terminalizes_as_delivery_failure(
    handoff_runtime, monkeypatch, change, expected_status,
):
    _config, model, account = handoff_runtime
    model.return_value.messages.create.return_value.content[0].text = "Routine answer."
    monkeypatch.setenv("LATE_API_KEY", "synthetic-provider-key")
    message_id, conversation_id, _batch_id = _stage_handoff()
    changed = {"value": False}
    if change == "controls":
        monkeypatch.setattr(webhook_server.icp_overrides, "auto_reply_state", lambda *_a: None if changed["value"] else True)
    if change == "control_exception":
        enabled = webhook_server.icp_overrides.fetch_overrides_fresh()

        def fail_fresh_controls():
            if changed["value"]:
                raise RuntimeError("synthetic control outage")
            return enabled

        monkeypatch.setattr(webhook_server.icp_overrides, "fetch_overrides_fresh", fail_fresh_controls)
    if change in {"muted", "blocked"}:
        attr = "get_ai_muted" if change == "muted" else "get_blocked"
        monkeypatch.setattr(state_registry, attr, lambda *_a: changed["value"])
    responses = [
        {"data": {"platform": "whatsapp"}},
        {"messages": [{"id": "incoming", "direction": "incoming", "createdAt": datetime.now(timezone.utc).isoformat()}]},
    ]

    def provider_read(*_args, **_kwargs):
        payload = responses.pop(0)
        if not responses:
            changed["value"] = True
            if change in {"account", "foreign"}:
                account.return_value = None if change == "account" else False
            if change == "claim":
                conn = state_registry._get_conn()
                conn.execute("UPDATE inbound_processing_events SET lease_expires_at = '2000-01-01T00:00:00+00:00'")
                conn.commit()
                conn.close()
                assert state_registry.inbound_processing_claim_recoverable(max_age_seconds=0)
        return SimpleNamespace(status_code=200, text="", json=lambda: payload)

    with (
        patch.object(zernio_dm_client.http_requests, "get", side_effect=provider_read),
        patch.object(zernio_dm_client.http_requests, "post") as post,
    ):
        webhook_server._flush_buffer(conversation_id)
    assert responses == []
    post.assert_not_called()
    assert _rows("SELECT status, provider_retry_count FROM inbound_processing_events") == [(expected_status, 0)]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(0,)]
    assert zernio_dm_client._provider_mutation_guard.get() is None


def test_recovery_heartbeat_rechecks_takeover_after_provider_reads(handoff_runtime, monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "synthetic-provider-key")
    _message_id, _conversation_id, _batch_id = _stage_handoff()
    with webhook_server._buffer_lock:
        webhook_server._message_buffers.clear()
    conn = state_registry._get_conn()
    conn.execute("UPDATE inbound_processing_events SET lease_expires_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()
    muted = {"value": False}
    monkeypatch.setattr(state_registry, "get_ai_muted", lambda *_a: muted["value"])
    monkeypatch.setattr(webhook_server, "_ali_recovery_heartbeat", lambda *_a: "Working on this.")
    responses = [
        {"data": {"platform": "whatsapp"}},
        {"messages": [{"id": "incoming", "direction": "incoming", "createdAt": datetime.now(timezone.utc).isoformat()}]},
    ]

    def provider_read(*_args, **_kwargs):
        payload = responses.pop(0)
        if not responses:
            muted["value"] = True
        return SimpleNamespace(status_code=200, text="", json=lambda: payload)

    with (
        patch.object(zernio_dm_client.http_requests, "get", side_effect=provider_read),
        patch.object(zernio_dm_client.http_requests, "post") as post,
    ):
        webhook_server._recover_stale_ali_inbound_once(max_age_seconds=0, ali_workflow=True)
    assert responses == []
    post.assert_not_called()
    assert _rows("SELECT status FROM inbound_processing_events") == [("escalated",)]
    assert zernio_dm_client._provider_mutation_guard.get() is None


@pytest.mark.parametrize("error", [
    zernio_dm_client.ZernioReplyError("provider did not confirm"),
    zernio_dm_client.http_requests.RequestException("synthetic network error"),
    None,
])
def test_confirmed_send_failure_is_terminal_only_with_visible_operator_item(handoff_runtime, error):
    _config, model, _account = handoff_runtime
    model.return_value.messages.create.return_value.content[0].text = "Routine answer."
    _message_id, conversation_id, _batch_id = _stage_handoff()
    with patch.object(webhook_server, "send_reply", side_effect=error, return_value=False):
        webhook_server._flush_buffer(conversation_id)
    assert _rows("SELECT status, reason FROM inbound_processing_events") == [("send_failed", "provider_send_failed")]
    assert _rows("SELECT notification_type, mode FROM pending_notifications") == [("escalation", "soft")]
    visible = state_registry.get_all_escalations()
    assert len(visible) == 1
    assert visible[0]["customer_id"] == conversation_id
    assert "DELIVERY FAILED" in visible[0]["subject"]
    assert _rows("SELECT role FROM whatsapp_threads") == [("user",)]


def test_delivery_failure_notification_and_terminal_transition_rollback_together(handoff_runtime):
    _config, model, _account = handoff_runtime
    model.return_value.messages.create.return_value.content[0].text = "Routine answer."
    _message_id, conversation_id, _batch_id = _stage_handoff()
    conn = state_registry._get_conn()
    conn.execute(
        "CREATE TRIGGER synthetic_terminal_write_failure BEFORE UPDATE ON inbound_processing_events "
        "WHEN NEW.status = 'send_failed' BEGIN SELECT RAISE(FAIL, 'synthetic terminal failure'); END"
    )
    conn.commit()
    conn.close()
    with patch.object(webhook_server, "send_reply", side_effect=zernio_dm_client.ZernioReplyError("unconfirmed")):
        webhook_server._flush_buffer(conversation_id)
    assert _rows("SELECT status, reason FROM inbound_processing_events") == [("recovering", "delivery_attention_persistence_unavailable")]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(0,)]
    assert _rows("SELECT role FROM whatsapp_threads") == [("user",)]


def _late_failed_event():
    return {
        "event": "message.failed",
        "conversation_id": "late-failure-conversation",
        "message_id": "late-provider-message",
        "account_id": "mermaid-account",
        "text": "Customer-visible text is not copied to the technical item",
        "failure_reason": "synthetic-provider-error",
    }


@pytest.mark.parametrize("paused", [False, True])
def test_unmatched_late_failure_is_visible_once_without_provider_send(handoff_runtime, monkeypatch, paused):
    if paused:
        monkeypatch.setattr(webhook_server.icp_overrides, "auto_reply_state", lambda *_a: False)
    failed = _late_failed_event()
    event_key, inserted = state_registry.zernio_failed_event_accept(failed)
    assert inserted
    with patch.object(webhook_server, "send_reply") as send:
        assert webhook_server._process_queued_zernio_failed_events_once() == 1
        assert state_registry.zernio_failed_event_accept(failed) == (event_key, False)
        assert webhook_server._process_queued_zernio_failed_events_once() == 0
    send.assert_not_called()
    assert _rows("SELECT status, payload_json, account_id FROM zernio_failed_event_queue") == [("completed", "{}", "")]
    assert _rows("SELECT notification_type, customer_id FROM pending_notifications") == [("escalation", failed["conversation_id"])]
    visible = state_registry.get_all_escalations()
    assert len(visible) == 1
    assert visible[0]["customer_id"] == failed["conversation_id"]
    assert visible[0]["mode"] == "soft"
    assert _rows("SELECT COUNT(*) FROM whatsapp_threads") == [(0,)]
    assert _rows("SELECT status FROM conversation_status") == [("open",)]


def test_late_failure_attention_and_completion_are_atomic_and_retryable(handoff_runtime):
    failed = _late_failed_event()
    state_registry.zernio_failed_event_accept(failed)
    conn = state_registry._get_conn()
    conn.execute(
        "CREATE TRIGGER synthetic_queue_completion_failure BEFORE UPDATE ON zernio_failed_event_queue "
        "WHEN NEW.status = 'completed' BEGIN SELECT RAISE(FAIL, 'synthetic terminal failure'); END"
    )
    conn.commit()
    conn.close()
    assert webhook_server._process_queued_zernio_failed_events_once() == 1
    assert _rows("SELECT status FROM zernio_failed_event_queue") == [("pending",)]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(0,)]
    conn = state_registry._get_conn()
    conn.execute("DROP TRIGGER synthetic_queue_completion_failure")
    conn.execute("UPDATE zernio_failed_event_queue SET available_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()
    assert webhook_server._process_queued_zernio_failed_events_once() == 1
    assert _rows("SELECT status FROM zernio_failed_event_queue") == [("completed",)]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(1,)]


def test_new_late_failure_reopens_archived_thread_but_duplicate_does_not(handoff_runtime):
    failed = _late_failed_event()
    conversation_id = failed["conversation_id"]
    state_registry.wa_store_message(conversation_id, "assistant", "Earlier reply")
    assert state_registry.wa_set_archived(conversation_id, True)
    event_key, inserted = state_registry.zernio_failed_event_accept(failed)
    assert inserted
    assert webhook_server._process_queued_zernio_failed_events_once() == 1
    visible = state_registry.get_all_escalations()
    assert len(visible) == 1
    assert visible[0]["customer_id"] == conversation_id
    assert _rows("SELECT deleted, status FROM conversation_status") == [(0, "open")]

    # Once an operator archives the reviewed failure, provider replay is a
    # dedup no-op: it must neither add an item nor reopen the conversation.
    assert state_registry.wa_set_archived(conversation_id, True)
    assert state_registry.zernio_failed_event_accept(failed) == (event_key, False)
    assert webhook_server._process_queued_zernio_failed_events_once() == 0
    assert state_registry.get_all_escalations() == []
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(1,)]
    assert _rows("SELECT deleted FROM conversation_status") == [(1,)]
