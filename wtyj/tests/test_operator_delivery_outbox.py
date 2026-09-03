"""Operator outbox proofs: durable preparation, fencing and atomic effects."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from dashboard import api, operator_delivery
from shared import state_registry


CONVERSATION = "a" * 24


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("TENANT_ID", "mermaid")
    monkeypatch.setattr(api, "_create_learning_from_operator_reply", lambda **_: None)
    conn = operator_delivery._connect()
    conn.close()


def rows(table):
    conn = operator_delivery._connect()
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def payload(text="Frozen reply"):
    return {"text": text, "role": "operator", "response": {"ok": True, "reply": text}}


def deliver(sender, prepare=lambda: payload(), request_id="action-1", original=None):
    return operator_delivery.deliver(
        conversation_id=CONVERSATION, scope="inbox:reply", original=original or {"text": "original"},
        prepare=prepare, sender=sender, request_id=request_id,
    )


def test_unconfirmed_retry_reuses_prepared_text_key_and_commits_once():
    prepared, sent = [], []

    def prepare():
        prepared.append(True)
        return payload(f"Generated version {len(prepared)}")

    def sender(conversation, text, **kwargs):
        sent.append((conversation, text, kwargs))
        return len(sent) > 1

    with pytest.raises(operator_delivery.OperatorDeliveryUnconfirmed):
        deliver(sender, prepare)
    assert rows("whatsapp_threads") == []
    assert json.loads(rows("operator_delivery_outbox")[0]["payload_json"])["text"] == "Generated version 1"
    result, replayed = deliver(sender, prepare)
    assert result == {"ok": True, "reply": "Generated version 1"}
    assert not replayed
    assert sent[0] == sent[1]
    assert sent[0][2]["confirm_delivery"] is True
    assert sent[0][2]["idempotency_key"].startswith("unboks-operator-")
    assert deliver(sender, prepare) == (result, True)
    assert prepared == [True]
    assert len(sent) == 2
    transcript = rows("whatsapp_threads")
    assert len(transcript) == 1
    assert transcript[0]["source_message_key"].startswith("operator-action:")
    assert rows("operator_delivery_outbox")[0]["status"] == "confirmed"


def test_request_id_reused_with_different_original_input_conflicts():
    deliver(lambda *_a, **_k: True)
    with pytest.raises(operator_delivery.OperatorDeliveryConflict):
        deliver(lambda *_a, **_k: pytest.fail("conflict was sent"), original={"text": "changed"})
    assert len(rows("whatsapp_threads")) == 1


def test_concurrent_duplicate_cannot_prepare_or_send_twice():
    entered, release = threading.Event(), threading.Event()
    calls = []

    def sender(*_args, **_kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(deliver, sender)
        assert entered.wait(5)
        try:
            with pytest.raises(operator_delivery.OperatorDeliveryBusy):
                deliver(lambda *_a, **_k: pytest.fail("duplicate POST"))
        finally:
            release.set()
        assert first.result(timeout=5)[0]["ok"] is True
    assert calls == [True]
    assert len(rows("whatsapp_threads")) == 1


def test_no_request_id_unconfirmed_action_survives_new_inbound_anchor():
    sends = []

    def sender(*args, **kwargs):
        sends.append((args, kwargs))
        return len(sends) > 1

    with pytest.raises(operator_delivery.OperatorDeliveryUnconfirmed):
        deliver(sender, request_id="")
    state_registry.wa_store_message(CONVERSATION, "user", "Another question")
    deliver(sender, request_id="")
    assert sends[0] == sends[1]
    assert len(rows("operator_delivery_outbox")) == 1


def test_confirmed_no_id_action_gets_new_identity_for_new_customer_turn():
    keys = []
    sender = lambda *_a, **kwargs: keys.append(kwargs["idempotency_key"]) or True
    deliver(sender, request_id="")
    state_registry.wa_store_message(CONVERSATION, "user", "New customer turn")
    deliver(sender, request_id="")
    assert len(set(keys)) == 2


def test_lease_reassignment_before_actual_provider_post_is_fenced(monkeypatch):
    from agents.social import zernio_dm_client
    from shared import tenant_guard

    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(tenant_guard, "is_account_allowed", lambda *_a, **_k: True)
    posts = []
    monkeypatch.setattr(zernio_dm_client.http_requests, "post", lambda *_a, **_k: posts.append(True))

    def sender(*_args, **_kwargs):
        conn = operator_delivery._connect()
        conn.execute("UPDATE operator_delivery_outbox SET claim_token = 'new-worker'")
        conn.commit()
        conn.close()
        return zernio_dm_client.send_dm_reply_with_attachment(
            CONVERSATION, "mermaid-account", "Image", "https://example.test/image.jpg",
        )

    with pytest.raises(operator_delivery.OperatorDeliveryBusy):
        deliver(sender)
    assert posts == []
    assert rows("whatsapp_threads") == []


def test_transcript_and_confirmed_marker_rollback_together_on_commit_failure(monkeypatch):
    original_finish = operator_delivery._finish
    original_connect = operator_delivery._connect

    def fail_finish(claim, prepared):
        conn = original_connect()
        conn.execute(
            "CREATE TRIGGER reject_confirmation BEFORE UPDATE OF status ON operator_delivery_outbox "
            "WHEN NEW.status = 'confirmed' BEGIN SELECT RAISE(FAIL, 'synthetic failure'); END"
        )
        conn.commit()
        conn.close()
        return original_finish(claim, prepared)

    monkeypatch.setattr(operator_delivery, "_finish", fail_finish)
    with pytest.raises(Exception, match="synthetic failure"):
        deliver(lambda *_a, **_k: True)
    assert rows("whatsapp_threads") == []
    assert rows("operator_delivery_outbox")[0]["status"] == "prepared"


@pytest.mark.parametrize("mode,guidance,media", [
    ("hard", False, False), ("hard", False, True), ("soft", False, False),
    ("soft", True, False), ("soft", True, True),
])
def test_escalation_paths_freeze_prepare_and_only_apply_confirmed_effects(
    monkeypatch, mode, guidance, media,
):
    conn = operator_delivery._connect()
    conn.execute(
        "INSERT INTO pending_notifications (id, notification_type, channel, customer_id, subject, body, created_at) "
        "VALUES (17, 'escalation', 'whatsapp', ?, 'Question', 'Body', '2026-09-03')", (CONVERSATION,),
    )
    conn.execute(
        "INSERT INTO photo_library (id, filename, original_filename, uploaded_at) "
        "VALUES (5, 'image.jpg', 'image.jpg', '2026-09-03')"
    )
    conn.commit()
    conn.close()
    state_registry.wa_save_booking_state(CONVERSATION, {"name": "Guest"}, {
        "awaiting_relay": True, "relay_token": "old-token", "preserved": True,
    })
    monkeypatch.setattr(api.state_registry, "get_all_escalations", lambda: [{
        "id": 17, "channel": "whatsapp", "customer_id": CONVERSATION, "mode": mode,
    }])
    resolutions, generations, sends = [], [], []
    monkeypatch.setattr(
        api, "_resolve_media_attachment_url",
        lambda media_id: resolutions.append(media_id) or ("https://example.test/image.jpg" if media_id else ""),
    )
    monkeypatch.setattr(
        api.marina_agent, "process_message",
        lambda *_a, **_k: generations.append(True) or {"reply": f"Generated {len(generations)}"},
    )

    def sender(*args, **kwargs):
        sends.append((args, kwargs))
        return len(sends) > 1

    monkeypatch.setattr(api, "send_whatsapp_message", sender)
    req = api.EscalationReplyRequest(
        message="  Exact operator input  ", media_id="5" if media else None, request_id="escalation-action",
    )
    endpoint = api.guidance_to_marina if guidance else api.reply_to_escalation
    with pytest.raises(HTTPException) as failed:
        asyncio.run(endpoint(17, req))
    assert failed.value.status_code == 502
    assert rows("whatsapp_threads") == []
    assert rows("pending_notifications")[0]["status"] == "pending"
    assert rows("photo_library")[0]["used_count"] == 0
    assert state_registry.wa_get_booking_state(CONVERSATION)["flags"]["awaiting_relay"]

    response = asyncio.run(endpoint(17, req))
    assert response["ok"] is True
    assert sends[0] == sends[1]
    assert sends[0][1]["confirm_delivery"] is True
    assert sends[0][1]["idempotency_key"].startswith("unboks-operator-")
    assert len(resolutions) == 1
    assert len(generations) == (0 if mode == "hard" else 1)
    assert rows("pending_notifications")[0]["status"] == "replied"
    assert rows("photo_library")[0]["used_count"] == int(media)
    assert len(rows("whatsapp_threads")) == 1 + int(guidance and media)
    assert rows("whatsapp_threads")[0]["text"] == (req.text if mode == "hard" else "Generated 1")
    assert asyncio.run(endpoint(17, req)) == response
    assert len(sends) == 2
    assert rows("photo_library")[0]["used_count"] == int(media)


def test_regular_inbox_preserves_request_identity_across_both_routes(monkeypatch):
    sends = []
    monkeypatch.setattr(api, "send_whatsapp_message", lambda *a, **k: sends.append((a, k)) or True)
    request = api.WhatsAppConversationReplyRequest(message="Exact text", request_id="inbox-action")
    first = asyncio.run(api.reply_to_whatsapp_conversation(CONVERSATION, request))
    second = asyncio.run(api.reply_to_whatsapp_conversation_direct(
        api.DirectWhatsAppConversationReplyRequest(
            conversation_id=CONVERSATION, message=request.message, request_id=request.request_id,
        ),
    ))
    assert first == second
    assert len(sends) == 1
    assert len(rows("whatsapp_threads")) == 1
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.reply_to_whatsapp_conversation(
            CONVERSATION, api.WhatsAppConversationReplyRequest(message="Changed", request_id="inbox-action"),
        ))
    assert error.value.status_code == 409


def test_guidance_generation_failure_does_not_freeze_or_send_booking_fallback(monkeypatch):
    monkeypatch.setattr(api.state_registry, "get_all_escalations", lambda: [{
        "id": 17, "channel": "whatsapp", "customer_id": CONVERSATION, "mode": "soft",
    }])
    monkeypatch.setattr(api, "_resolve_media_attachment_url", lambda _: "")
    generated = iter([
        {"generation_failed": True, "reply": "What date and how many guests?"},
        {"reply": "Your guide will help at the pier."},
    ])
    monkeypatch.setattr(api.marina_agent, "process_message", lambda *_a, **_k: next(generated))
    sent = []
    monkeypatch.setattr(api, "send_whatsapp_message", lambda *a, **k: sent.append((a, k)) or True)
    req = api.EscalationReplyRequest(guidance="Tell them where to meet", request_id="guidance-generation")
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.guidance_to_marina(17, req))
    assert error.value.status_code == 502
    assert sent == []
    assert rows("whatsapp_threads") == []
    assert rows("operator_delivery_outbox")[0]["payload_json"] == ""
    assert asyncio.run(api.guidance_to_marina(17, req))["reply"] == "Your guide will help at the pier."
    assert len(sent) == 1


@pytest.mark.parametrize("guidance", [False, True])
def test_soft_operator_input_is_relay_even_without_persisted_relay_state(monkeypatch, guidance):
    state_registry.wa_save_booking_state(CONVERSATION, {"name": "Guest"}, {"preserved": True})
    seen_flags = []

    def generate(_phone, _name, text, _fields, flags, **_kwargs):
        seen_flags.append(dict(flags))
        assert text == "Ask them to meet the guide at the pier"
        return {"reply": "Please meet your guide at the pier."}

    monkeypatch.setattr(api.marina_agent, "process_message", generate)
    monkeypatch.setattr(api, "_resolve_media_attachment_url", lambda _: "")
    prepared = api._prepare_whatsapp_operator_payload(
        CONVERSATION, 17,
        api.EscalationReplyRequest(message="Ask them to meet the guide at the pier"),
        hard=False, guidance=guidance,
    )
    assert seen_flags == [{"preserved": True, "awaiting_relay": True}]
    assert prepared["text"] == "Please meet your guide at the pier."
    assert state_registry.wa_get_booking_state(CONVERSATION)["flags"] == {"preserved": True}
