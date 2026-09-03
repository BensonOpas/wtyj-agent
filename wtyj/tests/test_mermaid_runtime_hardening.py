"""Safety regressions for tenant-bound WhatsApp runtime controls."""

import hashlib
import hmac
import json
import sqlite3
import threading
import time
from unittest.mock import patch

import pytest


def _zernio_message(message_id="mermaid-hardening-1"):
    return {
        "message_id": message_id,
        "conversation_id": "foreign-conversation",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "account_id": "foreign-account",
        "sender_id": "+15550000000",
        "sender_name": "Foreign customer",
        "text": "private customer payload",
    }


def _meta_payload(
    message_id="wamid.mermaid-hardening",
    text="private customer payload",
    *,
    phone_number_id="mermaid-phone-id",
    waba_id="mermaid-waba-id",
):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": waba_id,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "12232760075",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [
                                {
                                    "wa_id": "15550000000",
                                    "profile": {"name": "Private Guest"},
                                }
                            ],
                            "messages": [
                                {
                                    "from": "15550000000",
                                    "id": message_id,
                                    "timestamp": "1788446400",
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def test_foreign_zernio_event_is_rejected_before_dedup_or_payload_storage():
    from agents.social import webhook_server

    msg = _zernio_message()
    with (
        patch.object(webhook_server, "parse_zernio_webhook", return_value=msg),
        patch("shared.tenant_guard.is_account_allowed", return_value=False),
        patch.object(
            webhook_server.state_registry, "wa_claim_inbound_processing"
        ) as claim,
        patch.object(webhook_server, "_buffer_message") as buffer,
    ):
        webhook_server._process_zernio_event(
            {"event": "message.received", "data": {}}
        )

    claim.assert_not_called()
    buffer.assert_not_called()


def test_rejected_zernio_id_can_be_processed_after_correct_tenant_routing():
    from agents.social import webhook_server

    msg = _zernio_message("mermaid-hardening-replay")
    allowed = iter((False, True))
    with (
        patch.object(webhook_server, "parse_zernio_webhook", return_value=msg),
        patch(
            "shared.tenant_guard.is_account_allowed",
            side_effect=lambda *_args, **_kwargs: next(allowed),
        ),
        patch.object(
            webhook_server.icp_overrides,
            "whatsapp_inbox_enabled",
            return_value=True,
        ),
        patch.object(
            webhook_server.state_registry,
            "wa_claim_inbound_processing",
            return_value=True,
        ) as claim,
        patch.object(
            webhook_server.state_registry, "match_ignored_contact", return_value=None
        ),
        patch.object(webhook_server.state_registry, "get_blocked", return_value=False),
        patch.object(webhook_server, "send_typing_indicator"),
        patch.object(webhook_server, "_buffer_message") as buffer,
    ):
        payload = {"event": "message.received", "data": {}}
        webhook_server._process_zernio_event(payload)
        webhook_server._process_zernio_event(payload)

    claim.assert_called_once_with(
        "mermaid-hardening-replay",
        conversation_id="foreign-conversation",
        channel="whatsapp",
        payload=msg,
    )
    buffer.assert_called_once()


def test_disabled_zernio_whatsapp_inbox_stops_before_dedup_and_storage():
    from agents.social import webhook_server

    msg = _zernio_message("mermaid-hardening-channel-off")
    with (
        patch.object(webhook_server, "parse_zernio_webhook", return_value=msg),
        patch("shared.tenant_guard.is_account_allowed", return_value=True),
        patch.object(
            webhook_server.icp_overrides,
            "whatsapp_inbox_state",
            return_value=False,
        ),
        patch.object(
            webhook_server.state_registry, "wa_claim_inbound_processing"
        ) as claim,
        patch.object(webhook_server, "_buffer_message") as buffer,
    ):
        webhook_server._process_zernio_event(
            {"event": "message.received", "data": {}}
        )

    claim.assert_not_called()
    buffer.assert_not_called()


def test_disabled_meta_whatsapp_inbox_stops_before_dedup_and_storage():
    from agents.social import webhook_server

    msg = {
        "message_id": "mermaid-hardening-meta-off",
        "from": "+15550000000",
        "text": "private customer payload",
    }
    with (
        patch.object(webhook_server, "_maybe_run_cleanup"),
        patch.object(webhook_server, "parse_webhook_payload", return_value=[msg]),
        patch.object(
            webhook_server.icp_overrides,
            "whatsapp_inbox_state",
            return_value=False,
        ),
        patch.object(
            webhook_server.state_registry, "wa_claim_inbound_processing"
        ) as claim,
        patch.object(webhook_server, "_buffer_message") as buffer,
    ):
        webhook_server._process_whatsapp_event({"entry": []})

    claim.assert_not_called()
    buffer.assert_not_called()


def test_real_unavailable_nr3_bridge_stops_zernio_before_claim(
    monkeypatch,
):
    from agents.social import webhook_server

    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    monkeypatch.delenv("NR3_INTERNAL_OVERRIDES_URL", raising=False)
    monkeypatch.delenv("NR3_INTERNAL_API_TOKEN", raising=False)
    webhook_server.icp_overrides.clear_cache()
    msg = _zernio_message("mermaid-hardening-real-bridge-outage")
    with (
        patch.object(webhook_server, "parse_zernio_webhook", return_value=msg),
        patch("shared.tenant_guard.is_account_allowed", return_value=True),
        patch.object(
            webhook_server.state_registry, "wa_claim_inbound_processing"
        ) as claim,
        patch.object(webhook_server, "_buffer_message") as buffer,
    ):
        webhook_server._process_zernio_event(
            {"event": "message.received", "data": {}}
        )

    assert webhook_server.icp_overrides.whatsapp_inbox_enabled() is False
    claim.assert_not_called()
    buffer.assert_not_called()


def test_meta_webhook_requires_signature_and_exact_destination(monkeypatch):
    from fastapi.testclient import TestClient
    from agents.social import webhook_server

    secret = "mermaid-meta-test-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "mermaid-phone-id")
    monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "mermaid-waba-id")
    client = TestClient(webhook_server.app)
    payload = _meta_payload()
    body = json.dumps(payload, separators=(",", ":")).encode()
    valid_signature = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()

    assert client.post(
        "/webhooks/meta/whatsapp",
        content=body,
        headers={"content-type": "application/json"},
    ).status_code == 403
    assert client.post(
        "/webhooks/meta/whatsapp",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
        },
    ).status_code == 403

    wrong_destination = _meta_payload(phone_number_id="other-phone-id")
    wrong_body = json.dumps(wrong_destination, separators=(",", ":")).encode()
    wrong_signature = "sha256=" + hmac.new(
        secret.encode(), wrong_body, hashlib.sha256
    ).hexdigest()
    assert client.post(
        "/webhooks/meta/whatsapp",
        content=wrong_body,
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": wrong_signature,
        },
    ).status_code == 403


def test_disabled_signed_meta_webhook_never_logs_or_stores_customer_payload(
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from agents.social import webhook_server

    secret = "mermaid-meta-test-secret"
    private_text = "PRIVATE-TEXT-MUST-NOT-BE-LOGGED"
    monkeypatch.setenv("META_APP_SECRET", secret)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "mermaid-phone-id")
    monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "mermaid-waba-id")
    disabled = {
        "available": True,
        "feature_toggles": {"whatsapp_inbox": {"value": False}},
    }
    payload = _meta_payload(text=private_text)
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()

    with (
        patch.object(webhook_server, "_maybe_run_cleanup"),
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides",
            return_value=disabled,
        ),
        patch.object(webhook_server, "log") as logged,
        patch.object(
            webhook_server.state_registry, "wa_claim_inbound_processing"
        ) as claim,
        patch.object(webhook_server, "_buffer_message") as buffer,
    ):
        response = TestClient(webhook_server.app).post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "X-Hub-Signature-256": signature,
            },
        )

    assert response.status_code == 200
    assert private_text not in repr(logged.call_args_list)
    assert "15550000000" not in repr(logged.call_args_list)
    claim.assert_not_called()
    buffer.assert_not_called()


def test_strict_control_outage_returns_retryable_meta_error_before_claim(
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from agents.social import webhook_server

    secret = "mermaid-meta-test-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "mermaid-phone-id")
    monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "mermaid-waba-id")
    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    payload = _meta_payload(message_id="wamid.control-outage")
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    unavailable = {"available": False, "feature_toggles": {}}

    with (
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides",
            return_value=unavailable,
        ),
        patch.object(
            webhook_server.state_registry, "wa_claim_inbound_processing"
        ) as claim,
    ):
        response = TestClient(webhook_server.app).post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "X-Hub-Signature-256": signature,
            },
        )

    assert response.status_code == 503
    claim.assert_not_called()


def test_meta_normalization_log_excludes_customer_phone_and_text():
    from agents.social import webhook_server

    private_phone = "+15550009999"
    private_text = "PRIVATE-NORMALIZED-PAYLOAD"
    msg = {
        "message_id": "wamid.safe-log",
        "from": private_phone,
        "from_name": "Private Guest",
        "text": private_text,
        "message_type": "text",
    }
    with (
        patch.object(webhook_server, "_maybe_run_cleanup"),
        patch.object(webhook_server, "log") as logged,
        patch.object(webhook_server, "_buffer_message"),
    ):
        webhook_server._process_whatsapp_event(
            {"entry": []}, accepted_messages=[msg]
        )

    serialized_logs = repr(logged.call_args_list)
    assert private_phone not in serialized_logs
    assert private_text not in serialized_logs
    assert "wamid.safe-log" in serialized_logs


def test_meta_returns_retryable_error_before_ack_when_durable_claim_fails(
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from agents.social import webhook_server

    secret = "mermaid-meta-test-secret"
    monkeypatch.setenv("META_APP_SECRET", secret)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "mermaid-phone-id")
    monkeypatch.setenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "mermaid-waba-id")
    payload = _meta_payload(message_id="wamid.durable-failure")
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    with (
        patch.object(
            webhook_server.icp_overrides,
            "whatsapp_inbox_enabled",
            return_value=True,
        ),
        patch.object(
            webhook_server.state_registry,
            "wa_claim_inbound_processing",
            side_effect=sqlite3.OperationalError("disk unavailable"),
        ),
    ):
        response = TestClient(webhook_server.app).post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "X-Hub-Signature-256": signature,
            },
        )
    assert response.status_code == 503


def test_zernio_returns_retryable_error_before_ack_when_durable_claim_fails(
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from agents.social import webhook_server

    secret = "mermaid-zernio-test-secret"
    monkeypatch.setenv("ZERNIO_WEBHOOK_SECRET", secret)
    payload = {
        "event": "message.received",
        "data": {
            "id": "zernio-durable-failure",
            "text": "Can this be accepted safely?",
            "conversationId": "mermaid-durable-conversation",
            "platform": "whatsapp",
            "sender": {"id": "15550000000", "name": "Demo guest"},
            "accountId": "mermaid-account",
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    with (
        patch("shared.tenant_guard.is_account_allowed", return_value=True),
        patch.object(
            webhook_server.icp_overrides,
            "whatsapp_inbox_enabled",
            return_value=True,
        ),
        patch.object(
            webhook_server.state_registry,
            "wa_claim_inbound_processing",
            side_effect=sqlite3.OperationalError("disk unavailable"),
        ),
    ):
        response = TestClient(webhook_server.app).post(
            "/webhooks/zernio",
            content=body,
            headers={
                "content-type": "application/json",
                "X-Zernio-Signature": signature,
            },
        )
    assert response.status_code == 503


def test_foreign_zernio_failed_event_cannot_reconcile_local_state():
    from agents.social import webhook_server

    failed = {
        "conversation_id": "foreign-conversation",
        "message_id": "foreign-failed-message",
        "account_id": "foreign-account",
    }
    with (
        patch.object(
            webhook_server, "parse_zernio_failed_webhook", return_value=failed
        ),
        patch("shared.tenant_guard.is_account_allowed", return_value=False),
        patch.object(
            webhook_server.state_registry,
            "wa_claim_vehicle_recommendation_failure",
        ) as reconcile,
    ):
        webhook_server._process_zernio_event({"event": "message.failed"})

    reconcile.assert_not_called()


def test_nr3_outage_keeps_claimed_message_recoverable_without_ai_or_send(
    monkeypatch,
):
    from agents.social import webhook_server

    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")

    conversation_id = "mermaid-nr3-outage"
    message_id = "mermaid-hardening-nr3-outage"
    with webhook_server._buffer_lock:
        webhook_server._message_buffers[conversation_id] = {
            "messages": [
                {
                    "from": conversation_id,
                    "text": "Are seats available?",
                    "from_name": "Demo guest",
                    "message_id": message_id,
                    "_zernio_conversation_id": conversation_id,
                    "_zernio_account_id": "mermaid-account",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "Demo guest",
                }
            ],
            "timer": None,
            "started": time.time(),
        }

    processing_updates = []
    unavailable = {"available": False, "feature_toggles": {}}
    with (
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_all_terminal",
            return_value=False,
        ),
        patch.object(
            webhook_server.state_registry, "match_ignored_contact", return_value=None
        ),
        patch.object(webhook_server.state_registry, "get_blocked", return_value=False),
        patch.object(webhook_server.state_registry, "get_ai_muted", return_value=False),
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides_fresh",
            return_value=unavailable,
        ),
        patch(
            "agents.social.ali_reservation_v2_inbound.process_structural_text"
        ) as structural,
        patch.object(
            webhook_server.state_registry, "dm_store_inbound_message"
        ) as store,
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_bulk_update",
            side_effect=lambda *args, **kwargs: processing_updates.append(
                (args, kwargs)
            ),
        ),
        patch.object(webhook_server, "handle_incoming_whatsapp_message") as agent,
        patch.object(webhook_server, "send_reply") as send,
    ):
        webhook_server._flush_buffer(conversation_id)

    structural.assert_not_called()
    store.assert_not_called()
    assert any(
        args[1] == "processing"
        and kwargs.get("reason") == "tenant_runtime_controls_unavailable"
        for args, kwargs in processing_updates
    )
    agent.assert_not_called()
    send.assert_not_called()


def test_waiting_recovery_cannot_reset_or_resend_completed_turn():
    from agents.social import webhook_server

    conversation_id = "mermaid-terminal-race"
    message_id = "mermaid-terminal-race-message"
    enabled = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": True},
        },
    }
    first_model_started = threading.Event()
    release_first_model = threading.Event()
    failures = []
    terminal_checks = {"count": 0}
    processing_updates = []

    def install_buffer():
        with webhook_server._buffer_lock:
            webhook_server._message_buffers[conversation_id] = {
                "messages": [
                    {
                        "from": conversation_id,
                        "text": "Where do we meet?",
                        "from_name": "Demo guest",
                        "message_id": message_id,
                        "_zernio_conversation_id": conversation_id,
                        "_zernio_account_id": "mermaid-account",
                        "_zernio_channel": "whatsapp",
                        "_zernio_sender_name": "Demo guest",
                    }
                ],
                "timer": None,
                "started": time.time(),
            }

    def terminal_after_first_completion(_ids):
        terminal_checks["count"] += 1
        return terminal_checks["count"] > 1

    def blocking_model(_msg):
        first_model_started.set()
        assert release_first_model.wait(timeout=5)
        return "Fishermen's Pier at 06:45."

    def run_flush():
        try:
            webhook_server._flush_buffer(conversation_id)
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    install_buffer()
    with (
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides_fresh",
            return_value=enabled,
        ),
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides",
            return_value=enabled,
        ),
        patch.object(webhook_server, "_use_whatsapp_orchestrator", return_value=False),
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_all_terminal",
            side_effect=terminal_after_first_completion,
        ),
        patch.object(
            webhook_server.state_registry, "match_ignored_contact", return_value=None
        ),
        patch.object(webhook_server.state_registry, "get_blocked", return_value=False),
        patch.object(webhook_server.state_registry, "get_ai_muted", return_value=False),
        patch.object(webhook_server.state_registry, "dm_store_inbound_message"),
        patch.object(webhook_server.state_registry, "dm_store_message"),
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_bulk_update",
            side_effect=lambda *args, **kwargs: processing_updates.append(
                (args, kwargs)
            ),
        ),
        patch(
            "agents.social.ali_reservation_v2_inbound.process_structural_text",
            return_value={"handled": False},
        ),
        patch.object(webhook_server, "handle_incoming_dm", side_effect=blocking_model),
        patch.object(webhook_server, "send_reply", return_value=True) as send,
    ):
        first = threading.Thread(target=run_flush)
        first.start()
        assert first_model_started.wait(timeout=5)
        install_buffer()
        second = threading.Thread(target=run_flush)
        second.start()
        time.sleep(0.05)
        release_first_model.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert send.call_count == 1
    assert terminal_checks["count"] == 2
    assert sum(
        args[1] == "processing" and kwargs.get("reason") == "batch_flush_started"
        for args, kwargs in processing_updates
    ) == 1


def test_pause_during_model_work_blocks_final_provider_send(monkeypatch):
    from agents.social import webhook_server

    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    conversation_id = "mermaid-inflight-pause"
    message_id = "mermaid-inflight-pause-message"
    with webhook_server._buffer_lock:
        webhook_server._message_buffers[conversation_id] = {
            "messages": [
                {
                    "from": conversation_id,
                    "text": "What time do we meet?",
                    "from_name": "Demo guest",
                    "message_id": message_id,
                    "_zernio_conversation_id": conversation_id,
                    "_zernio_account_id": "mermaid-account",
                    "_zernio_channel": "whatsapp",
                    "_zernio_sender_name": "Demo guest",
                }
            ],
            "timer": None,
            "started": time.time(),
        }

    enabled = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": True},
        },
    }
    paused = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": False},
        },
    }
    processing_updates = []
    with (
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides_fresh",
            side_effect=[enabled, paused],
        ),
        patch.object(webhook_server.icp_overrides, "fetch_overrides", return_value=enabled),
        patch.object(webhook_server, "_use_whatsapp_orchestrator", return_value=False),
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_all_terminal",
            return_value=False,
        ),
        patch.object(
            webhook_server.state_registry, "match_ignored_contact", return_value=None
        ),
        patch.object(webhook_server.state_registry, "get_blocked", return_value=False),
        patch.object(webhook_server.state_registry, "get_ai_muted", return_value=False),
        patch.object(webhook_server.state_registry, "dm_store_inbound_message"),
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_bulk_update",
            side_effect=lambda *args, **kwargs: processing_updates.append(
                (args, kwargs)
            ),
        ),
        patch(
            "agents.social.ali_reservation_v2_inbound.process_structural_text",
            return_value={"handled": False},
        ),
        patch.object(
            webhook_server,
            "handle_incoming_dm",
            return_value="Meet at 06:45.",
        ) as model,
        patch.object(webhook_server, "send_reply") as send,
    ):
        webhook_server._flush_buffer(conversation_id)

    model.assert_called_once()
    send.assert_not_called()
    assert any(
        args[1] == "paused" and kwargs.get("reason") == "tenant_agent_paused"
        for args, kwargs in processing_updates
    )


def test_mermaid_recovery_reuses_provider_idempotency_after_post_send_crash(
    monkeypatch,
):
    from agents.social import webhook_server

    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    conversation_id = "mermaid-post-send-crash"
    message_id = "mermaid-post-send-crash-message"
    enabled = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": True},
        },
    }

    def install_recovered_buffer():
        with webhook_server._buffer_lock:
            webhook_server._message_buffers[conversation_id] = {
                "messages": [
                    {
                        "from": conversation_id,
                        "text": "Where do we meet?",
                        "from_name": "Demo guest",
                        "message_id": message_id,
                        "_zernio_conversation_id": conversation_id,
                        "_zernio_account_id": "mermaid-account",
                        "_zernio_channel": "whatsapp",
                        "_zernio_sender_name": "Demo guest",
                    }
                ],
                "timer": None,
                "started": time.time(),
            }

    provider_attempts = []
    provider_deliveries = set()

    def idempotent_provider(*_args, **kwargs):
        key = kwargs["idempotency_key"]
        provider_attempts.append((key, kwargs["confirm_delivery"]))
        provider_deliveries.add(key)
        return True

    persistence_calls = {"count": 0}

    def crash_first_assistant_persistence(*_args, **kwargs):
        persistence_calls["count"] += 1
        if persistence_calls["count"] == 1:
            raise SystemExit("simulated crash after provider acceptance")

    common_patches = (
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides_fresh",
            return_value=enabled,
        ),
        patch.object(webhook_server.icp_overrides, "fetch_overrides", return_value=enabled),
        patch.object(webhook_server, "_use_whatsapp_orchestrator", return_value=False),
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_all_terminal",
            return_value=False,
        ),
        patch.object(
            webhook_server.state_registry, "match_ignored_contact", return_value=None
        ),
        patch.object(webhook_server.state_registry, "get_blocked", return_value=False),
        patch.object(webhook_server.state_registry, "get_ai_muted", return_value=False),
        patch.object(webhook_server.state_registry, "dm_store_inbound_message"),
        patch.object(webhook_server.state_registry, "inbound_processing_bulk_update"),
        patch(
            "agents.social.ali_reservation_v2_inbound.process_structural_text",
            return_value={"handled": False},
        ),
        patch.object(
            webhook_server,
            "handle_incoming_dm",
            return_value="Fishermen's Pier at 06:45.",
        ),
        patch.object(webhook_server, "send_reply", side_effect=idempotent_provider),
        patch.object(
            webhook_server.state_registry,
            "dm_store_message",
            side_effect=crash_first_assistant_persistence,
        ),
    )
    with common_patches[0], common_patches[1], common_patches[2], common_patches[3], \
         common_patches[4], common_patches[5], common_patches[6], common_patches[7], \
         common_patches[8], common_patches[9], common_patches[10], common_patches[11], \
         common_patches[12]:
        install_recovered_buffer()
        with pytest.raises(SystemExit):
            webhook_server._flush_buffer(conversation_id)
        install_recovered_buffer()
        webhook_server._flush_buffer(conversation_id)

    assert len(provider_attempts) == 2
    assert provider_attempts[0] == provider_attempts[1]
    assert provider_attempts[0][1] is True
    assert provider_attempts[0][0].startswith("unboks-auto-reply-")
    assert len(provider_deliveries) == 1


@pytest.mark.parametrize(
    "branch,expected_reason",
    [
        ("structural", "structural reply failed"),
        ("document", "document acknowledgement failed"),
    ],
)
def test_empty_automated_reply_reaches_terminal_failure(branch, expected_reason):
    from agents.social import webhook_server

    conversation_id = f"mermaid-empty-{branch}"
    message = {
        "from": conversation_id,
        "text": "demo input",
        "from_name": "Demo guest",
        "message_id": f"mermaid-empty-{branch}-message",
        "_zernio_conversation_id": conversation_id,
        "_zernio_account_id": "mermaid-account",
        "_zernio_channel": "whatsapp",
        "_zernio_sender_name": "Demo guest",
    }
    if branch == "document":
        message["_zernio_attachments"] = [{"provider_attachment_id": "doc-1"}]
    with webhook_server._buffer_lock:
        webhook_server._message_buffers[conversation_id] = {
            "messages": [message],
            "timer": None,
            "started": time.time(),
        }
    enabled = {
        "available": True,
        "feature_toggles": {
            "whatsapp_inbox": {"value": True},
            "ai_auto_reply": {"value": True},
        },
    }
    structural = (
        {"handled": True, "continue_to_documents": False, "reply": ""}
        if branch == "structural"
        else {"handled": False}
    )
    with (
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides_fresh",
            return_value=enabled,
        ),
        patch.object(webhook_server.icp_overrides, "fetch_overrides", return_value=enabled),
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_all_terminal",
            return_value=False,
        ),
        patch.object(
            webhook_server.state_registry, "match_ignored_contact", return_value=None
        ),
        patch.object(webhook_server.state_registry, "get_blocked", return_value=False),
        patch.object(webhook_server.state_registry, "get_ai_muted", return_value=False),
        patch.object(webhook_server.state_registry, "dm_store_inbound_message"),
        patch.object(webhook_server.state_registry, "inbound_processing_bulk_update"),
        patch(
            "agents.social.ali_reservation_v2_inbound.process_structural_text",
            return_value=structural,
        ),
        patch(
            "agents.social.ali_reservation_v2_inbound.process_whatsapp_documents",
            return_value={"handled": True, "reply": ""},
        ),
        patch.object(webhook_server, "_mark_delivery_failed") as failed,
        patch.object(webhook_server, "send_reply") as send,
    ):
        webhook_server._flush_buffer(conversation_id)

    failed.assert_called_once()
    assert failed.call_args.args[-1] == expected_reason
    send.assert_not_called()


def test_atomic_inbound_claim_rolls_back_marker_when_ledger_write_fails(
    tmp_path, monkeypatch
):
    from shared import state_registry

    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    conn = state_registry._get_conn()
    conn.execute(
        "CREATE TRIGGER reject_inbound_test BEFORE INSERT "
        "ON inbound_processing_events BEGIN "
        "SELECT RAISE(ABORT, 'simulated ledger failure'); END"
    )
    conn.commit()
    conn.close()

    message_id = "mermaid-atomic-claim-replay"
    with pytest.raises(sqlite3.DatabaseError):
        state_registry.wa_claim_inbound_processing(
            message_id,
            "mermaid-conversation",
            "whatsapp",
            {"text": "recoverable payload"},
        )
    assert state_registry.wa_has_been_processed(message_id) is False

    conn = state_registry._get_conn()
    conn.execute("DROP TRIGGER reject_inbound_test")
    conn.commit()
    conn.close()
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        "mermaid-conversation",
        "whatsapp",
        {"text": "recoverable payload"},
    ) is True
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        "mermaid-conversation",
        "whatsapp",
        {"text": "recoverable payload"},
    ) is False
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT status, payload_json FROM inbound_processing_events "
        "WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    conn.close()
    assert row[0] == "received"
    assert json.loads(row[1])["text"] == "recoverable payload"


def test_recovery_quarantines_payload_when_provider_account_was_reassigned():
    from agents.social import webhook_server

    message_id = "mermaid-reassigned-account"
    claimed = [
        {
            "message_id": message_id,
            "conversation_id": "mermaid-old-conversation",
            "channel": "whatsapp",
            "payload": _zernio_message(message_id),
            "created_at": "2026-09-03T10:00:00+00:00",
            "heartbeat_sent_at": "",
            "attempt_count": 1,
            "recovery_reason": "",
            "recovery_error": "",
        }
    ]
    with (
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_claim_recoverable",
            return_value=claimed,
        ),
        patch("shared.tenant_guard.is_account_allowed", return_value=False),
        patch.object(
            webhook_server.state_registry, "inbound_processing_quarantine"
        ) as quarantine,
        patch.object(webhook_server, "_buffer_message") as buffer,
        patch.object(webhook_server, "_flush_buffer") as flush,
        patch.object(webhook_server, "send_reply") as send,
    ):
        recovered = webhook_server._recover_stale_ali_inbound_once(
            max_age_seconds=0,
            ali_workflow=True,
        )

    assert recovered == 0
    quarantine.assert_called_once_with(
        message_id, reason="recovery_account_not_allowlisted"
    )
    buffer.assert_not_called()
    flush.assert_not_called()
    send.assert_not_called()


@pytest.mark.parametrize(
    "inbox_state,auto_state,muted,expected_recovered,expected_status",
    [
        (None, None, False, 0, "processing"),
        (False, True, False, 0, "paused"),
        (True, False, False, 1, None),
        (True, True, True, 1, None),
    ],
)
def test_recovery_heartbeat_respects_controls_and_human_takeover(
    inbox_state,
    auto_state,
    muted,
    expected_recovered,
    expected_status,
):
    from agents.social import webhook_server

    message_id = "mermaid-recovery-control"
    conversation_id = "mermaid-recovery-conversation"
    payload = _zernio_message(message_id)
    payload["conversation_id"] = conversation_id
    payload["account_id"] = "mermaid-account"
    claimed = [
        {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "channel": "whatsapp",
            "payload": payload,
            "created_at": "2026-09-03T10:00:00+00:00",
            "heartbeat_sent_at": "",
            "attempt_count": 1,
            "recovery_reason": "",
            "recovery_error": "",
        }
    ]
    envelope = {"available": inbox_state is not None, "feature_toggles": {}}
    updates = []
    with (
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_claim_recoverable",
            return_value=claimed,
        ),
        patch("shared.tenant_guard.is_account_allowed", return_value=True),
        patch.object(
            webhook_server.icp_overrides,
            "fetch_overrides_fresh",
            return_value=envelope,
        ),
        patch.object(
            webhook_server.icp_overrides,
            "whatsapp_inbox_state",
            return_value=inbox_state,
        ),
        patch.object(
            webhook_server.icp_overrides,
            "auto_reply_state",
            return_value=auto_state,
        ),
        patch.object(
            webhook_server.state_registry, "get_ai_muted", return_value=muted
        ),
        patch.object(webhook_server.state_registry, "get_blocked", return_value=False),
        patch.object(
            webhook_server.state_registry,
            "inbound_processing_bulk_update",
            side_effect=lambda *args, **kwargs: updates.append((args, kwargs)),
        ),
        patch.object(webhook_server, "_buffer_message") as buffer,
        patch.object(webhook_server, "_flush_buffer") as flush,
        patch.object(webhook_server, "send_reply") as heartbeat,
    ):
        recovered = webhook_server._recover_stale_ali_inbound_once(
            max_age_seconds=0,
            ali_workflow=True,
        )

    assert recovered == expected_recovered
    heartbeat.assert_not_called()
    if expected_status:
        assert any(args[1] == expected_status for args, _kwargs in updates)
        buffer.assert_not_called()
        flush.assert_not_called()
    else:
        buffer.assert_called_once()
        flush.assert_called_once_with(conversation_id)


def test_recovery_quarantine_erases_customer_payload(tmp_path, monkeypatch):
    from shared import state_registry

    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    message_id = "mermaid-quarantine-payload"
    assert state_registry.wa_claim_inbound_processing(
        message_id,
        "old-conversation",
        "whatsapp",
        {"text": "private stale content", "account_id": "old-account"},
    ) is True

    state_registry.inbound_processing_quarantine(
        message_id, "recovery_account_not_allowlisted"
    )
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


def test_non_ali_runtime_recovers_durably_accepted_message_without_heartbeat(
    tmp_path, monkeypatch
):
    from agents.social import webhook_server
    from shared import state_registry

    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    msg = {
        "message_id": "mermaid-restart-recovery",
        "conversation_id": "mermaid-recovery-conversation",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "account_id": "mermaid-account",
        "sender_id": "15550000000",
        "sender_name": "Demo guest",
        "text": "What time do we meet?",
    }
    assert state_registry.wa_claim_inbound_processing(
        msg["message_id"],
        msg["conversation_id"],
        msg["channel"],
        msg,
    ) is True

    with (
        patch.object(webhook_server, "_buffer_message") as buffer,
        patch.object(webhook_server, "_flush_buffer") as flush,
        patch.object(webhook_server, "send_reply") as heartbeat,
    ):
        recovered = webhook_server._recover_stale_ali_inbound_once(
            max_age_seconds=0,
            ali_workflow=False,
        )

    assert recovered == 1
    buffer.assert_called_once()
    flush.assert_called_once_with("mermaid-recovery-conversation")
    heartbeat.assert_not_called()


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"slug": "mermaid"},
        {
            "slug": "mermaid",
            "channel_account_allowlist": {"mode": "permissive", "zernio_accounts": []},
        },
        {
            "slug": "mermaid",
            "channel_account_allowlist": {"mode": "strict"},
        },
        {
            "slug": "other",
            "channel_account_allowlist": {
                "mode": "strict",
                "zernio_accounts": ["mermaid-account"],
            },
        },
    ],
)
def test_required_tenant_allowlist_fails_closed_on_invalid_config(
    config, monkeypatch
):
    from shared import tenant_guard

    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "mermaid")
    with patch.object(tenant_guard.config_loader, "get_raw", return_value=config):
        assert tenant_guard.is_account_allowed("mermaid-account", "inbound") is False


def test_required_tenant_allowlist_accepts_only_exact_account(monkeypatch):
    from shared import tenant_guard

    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "mermaid")
    config = {
        "slug": "mermaid",
        "channel_account_allowlist": {
            "mode": "strict",
            "zernio_accounts": ["mermaid-account"],
        },
    }
    with patch.object(tenant_guard.config_loader, "get_raw", return_value=config):
        assert tenant_guard.is_account_allowed("mermaid-account", "inbound") is True
        assert tenant_guard.is_account_allowed("foreign-account", "inbound") is False


def test_required_allowlist_accepts_legacy_business_slug_without_top_level_slug(
    monkeypatch,
):
    from shared import tenant_guard

    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "unboks")
    config = {
        "business": {"slug": "unboks"},
        "channel_account_allowlist": {
            "mode": "strict",
            "zernio_accounts": ["unboks-account"],
        },
    }
    with patch.object(tenant_guard.config_loader, "get_raw", return_value=config):
        assert tenant_guard.is_account_allowed("unboks-account", "inbound") is True


def test_required_allowlist_rejects_conflicting_top_and_business_slugs(monkeypatch):
    from shared import tenant_guard

    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "mermaid")
    config = {
        "slug": "mermaid",
        "business": {"slug": "other"},
        "channel_account_allowlist": {
            "mode": "strict",
            "zernio_accounts": ["mermaid-account"],
        },
    }
    with patch.object(tenant_guard.config_loader, "get_raw", return_value=config):
        assert tenant_guard.is_account_allowed("mermaid-account", "inbound") is False


def test_legacy_tenant_without_required_policy_keeps_compatibility(monkeypatch):
    from shared import tenant_guard

    monkeypatch.delenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", raising=False)
    with patch.object(tenant_guard.config_loader, "get_raw", return_value={}):
        assert tenant_guard.is_account_allowed("legacy-account", "inbound") is True


def test_client_config_cache_reloads_atomic_replacement(tmp_path, monkeypatch):
    from shared import config_loader

    monkeypatch.delenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", raising=False)
    config_path = tmp_path / "client.json"
    config_path.write_text(
        json.dumps({"channel_account_allowlist": {"zernio_accounts": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    config_loader._invalidate_cache()
    assert config_loader.get_raw()["channel_account_allowlist"][
        "zernio_accounts"
    ] == []

    replacement = tmp_path / ".client.next"
    replacement.write_text(
        json.dumps(
            {
                "channel_account_allowlist": {
                    "mode": "strict",
                    "zernio_accounts": ["mermaid-account"],
                }
            }
        ),
        encoding="utf-8",
    )
    replacement.replace(config_path)

    assert config_loader.get_raw()["channel_account_allowlist"][
        "zernio_accounts"
    ] == ["mermaid-account"]


def test_client_config_cache_preserves_last_good_read_and_recovers(
    tmp_path, monkeypatch
):
    from shared import config_loader

    monkeypatch.delenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", raising=False)
    config_path = tmp_path / "client.json"
    config_path.write_text(json.dumps({"revision": "good-1"}), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    config_loader._invalidate_cache()
    assert config_loader.get_raw()["revision"] == "good-1"

    config_path.write_text('{"revision":', encoding="utf-8")
    assert config_loader.get_raw()["revision"] == "good-1"

    config_path.write_text(json.dumps({"revision": "good-2"}), encoding="utf-8")
    assert config_loader.get_raw()["revision"] == "good-2"


@pytest.mark.parametrize(
    "replacement",
    [
        {"slug": "mermaid"},
        {
            "slug": "other",
            "channel_account_allowlist": {
                "mode": "strict",
                "zernio_accounts": ["mermaid-account"],
            },
        },
        "malformed",
    ],
)
def test_strict_config_reload_invalidates_warm_allowlist_on_corruption(
    replacement,
    tmp_path, monkeypatch
):
    from shared import config_loader

    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "mermaid")
    config_path = tmp_path / "client.json"
    good = {
        "slug": "mermaid",
        "channel_account_allowlist": {
            "mode": "strict",
            "zernio_accounts": ["mermaid-account"],
        },
    }
    config_path.write_text(json.dumps(good), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    config_loader._invalidate_cache()
    assert config_loader.get_raw() == good

    replacement_path = tmp_path / ".client.partial"
    replacement_path.write_text(
        '{"slug":' if replacement == "malformed" else json.dumps(replacement),
        encoding="utf-8",
    )
    replacement_path.replace(config_path)
    assert config_loader.get_raw() == {}


def test_strict_config_cold_start_partial_document_returns_empty(
    tmp_path, monkeypatch
):
    from shared import config_loader

    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "mermaid")
    config_path = tmp_path / "client.json"
    config_path.write_text(json.dumps({"slug": "mermaid"}), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    config_loader._invalidate_cache()
    assert config_loader.get_raw() == {}


def test_strict_config_loader_accepts_legacy_business_slug(tmp_path, monkeypatch):
    from shared import config_loader

    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "unboks")
    config_path = tmp_path / "client.json"
    config = {
        "business": {"slug": "unboks"},
        "channel_account_allowlist": {
            "mode": "strict",
            "zernio_accounts": ["unboks-account"],
        },
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    config_loader._invalidate_cache()

    assert config_loader.get_raw() == config


def test_runtime_config_update_preserves_provider_write_under_shared_lock(
    tmp_path, monkeypatch
):
    from shared import config_loader

    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "mermaid")
    config_path = tmp_path / "client.json"
    initial = {
        "slug": "mermaid",
        "business": {"name": "Before"},
        "channel_account_allowlist": {
            "mode": "strict",
            "zernio_accounts": ["account-a"],
        },
    }
    config_path.write_text(json.dumps(initial), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config_path))
    config_loader._invalidate_cache()

    lock_stream = open(str(config_path) + ".lock", "a+")
    original_flock = config_loader._fcntl.flock
    original_flock(lock_stream.fileno(), config_loader._fcntl.LOCK_EX)
    attempted = threading.Event()

    def observed_flock(descriptor, operation):
        if operation & config_loader._fcntl.LOCK_EX:
            attempted.set()
        return original_flock(descriptor, operation)

    monkeypatch.setattr(config_loader._fcntl, "flock", observed_flock)
    outcome = {}
    worker = threading.Thread(
        target=lambda: outcome.setdefault(
            "ok", config_loader.update_business_field("name", "After")
        )
    )
    worker.start()
    assert attempted.wait(timeout=5)

    provider_update = dict(initial)
    provider_update["channel_account_allowlist"] = {
        "mode": "strict",
        "zernio_accounts": ["account-b"],
    }
    replacement = tmp_path / ".provider-update"
    replacement.write_text(json.dumps(provider_update), encoding="utf-8")
    replacement.replace(config_path)
    original_flock(lock_stream.fileno(), config_loader._fcntl.LOCK_UN)
    lock_stream.close()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert outcome["ok"] is True
    final = json.loads(config_path.read_text(encoding="utf-8"))
    assert final["business"]["name"] == "After"
    assert final["channel_account_allowlist"]["zernio_accounts"] == ["account-b"]


def test_whatsapp_outbound_converts_markdown_bold_to_native_formatting():
    from agents.social import webhook_server

    reply = "Meet at **Fishermen's Pier at 06:45**."

    assert webhook_server._sanitize_tenant_whatsapp_reply(
        reply, "whatsapp"
    ) == "Meet at *Fishermen's Pier at 06:45*."
    assert webhook_server._sanitize_tenant_whatsapp_reply(
        reply, "facebook_dm"
    ) == reply


@pytest.mark.parametrize(
    "source,expected",
    [
        ("**First** and **second**.", "*First* and *second*."),
        ("***bold italic***", "***bold italic***"),
        ("x = a**b; y = c**d", "x = a**b; y = c**d"),
        ("`**literal code**`", "`**literal code**`"),
        ("**unbalanced", "**unbalanced"),
        ("**line one\nline two**", "**line one\nline two**"),
        ("2 ** 3", "2 ** 3"),
    ],
)
def test_whatsapp_formatting_preserves_ambiguous_asterisks(source, expected):
    from agents.social import webhook_server

    assert webhook_server._sanitize_tenant_whatsapp_reply(
        source, "whatsapp"
    ) == expected
