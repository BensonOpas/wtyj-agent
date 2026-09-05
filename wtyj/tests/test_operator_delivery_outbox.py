"""Operator outbox proofs: durable preparation, fencing and atomic effects."""

import asyncio
import json
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from agents.marina import email_poller
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
    assert state_registry.get_active_escalation_mode(CONVERSATION) is None
    assert state_registry.get_conversation_status(CONVERSATION) == "resolved"
    assert rows("photo_library")[0]["used_count"] == int(media)
    assert len(rows("whatsapp_threads")) == 1 + int(guidance and media)
    assert rows("whatsapp_threads")[0]["text"] == (req.text if mode == "hard" else "Generated 1")
    assert asyncio.run(endpoint(17, req)) == response
    assert len(sends) == 2
    assert rows("photo_library")[0]["used_count"] == int(media)


def test_inbound_during_provider_send_closes_unchanged_answered_work_item():
    conn = operator_delivery._connect()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(id,notification_type,channel,customer_id,subject,body,status,created_at,mode) "
        "VALUES (18,'escalation','whatsapp',?,'Question','Original','pending','2026-09-04','hard')",
        (CONVERSATION,),
    )
    conn.commit()
    conn.close()
    state_registry.set_ai_muted(CONVERSATION, True)

    def sender(*_args, **_kwargs):
        state_registry.wa_store_message(CONVERSATION, "user", "One more detail")
        return True

    operator_delivery.deliver(
        conversation_id=CONVERSATION,
        scope="escalation:18:reply:hard",
        original={"text": "Answer"},
        request_id="inbound-during-send",
        prepare=lambda: {
            **payload("Answer"),
            "notification_id": 18,
        },
        sender=sender,
    )

    assert rows("pending_notifications")[0]["status"] == "replied"
    assert state_registry.get_active_escalation_mode(CONVERSATION) is None
    assert state_registry.get_ai_muted(CONVERSATION) is False
    assert rows("operator_delivery_outbox")[0]["status"] == "confirmed"


def test_reescalation_during_provider_send_preserves_new_revision_and_relay():
    state_registry.create_pending_notification(
        "escalation", "whatsapp", CONVERSATION, "Guest",
        "Original question", "Original body", mode="soft",
    )
    state_registry.wa_save_booking_state(
        CONVERSATION,
        {"name": "Guest"},
        {
            "awaiting_relay": True,
            "relay_token": "old-token",
            "relay_question": "Original question",
        },
    )
    notification_id = rows("pending_notifications")[0]["id"]

    def sender(*_args, **_kwargs):
        state_registry.wa_store_message(CONVERSATION, "user", "This is a different issue")
        state_registry.wa_save_booking_state(
            CONVERSATION,
            {"name": "Guest"},
            {
                "awaiting_relay": True,
                "relay_token": "new-token",
                "relay_question": "Different issue",
            },
        )
        assert state_registry.create_pending_notification(
            "escalation", "whatsapp", CONVERSATION, "Guest",
            "Different issue", "New body", mode="hard",
        ) == notification_id
        return True

    operator_delivery.deliver(
        conversation_id=CONVERSATION,
        scope=f"escalation:{notification_id}:reply:soft",
        original={"text": "Original answer"},
        request_id="reescalation-during-send",
        prepare=lambda: {
            **payload("Original answer"),
            "role": "assistant",
            "notification_id": notification_id,
            "clear_relay": True,
        },
        sender=sender,
    )

    notification = rows("pending_notifications")[0]
    assert notification["status"] == "pending"
    assert notification["subject"] == "Different issue"
    assert notification["content_revision"] == 2
    assert state_registry.get_active_escalation_mode(CONVERSATION) == "hard"
    flags = state_registry.wa_get_booking_state(CONVERSATION)["flags"]
    assert flags["awaiting_relay"] is True
    assert flags["relay_token"] == "new-token"
    assert flags["relay_question"] == "Different issue"


def test_stale_dashboard_revision_cannot_close_new_whatsapp_issue(monkeypatch):
    notification_id = state_registry.create_pending_notification(
        "escalation", "whatsapp", CONVERSATION, "Guest",
        "Original question", "Original body", mode="hard",
    )
    viewed_revision = rows("pending_notifications")[0]["content_revision"]
    assert viewed_revision == 1
    assert state_registry.create_pending_notification(
        "escalation", "whatsapp", CONVERSATION, "Guest",
        "New question", "New body", mode="hard",
    ) == notification_id
    sends = []
    monkeypatch.setattr(api, "send_whatsapp_message", lambda *a, **k: sends.append((a, k)))

    with pytest.raises(HTTPException) as failed:
        asyncio.run(api.reply_to_escalation(
            notification_id,
            api.EscalationReplyRequest(
                message="Answer based on the old screen",
                request_id="stale-wa-view",
                content_revision=viewed_revision,
            ),
        ))
    assert failed.value.status_code == 409
    assert "changed" in failed.value.detail
    assert sends == []
    notification = rows("pending_notifications")[0]
    assert notification["status"] == "pending"
    assert notification["content_revision"] == 2
    assert rows("operator_delivery_outbox") == []


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
    conn = operator_delivery._connect()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(id,notification_type,channel,customer_id,subject,body,status,created_at,mode) "
        "VALUES (17,'escalation','whatsapp',?,'Question','Body','pending','2026-09-04','soft')",
        (CONVERSATION,),
    )
    conn.commit()
    conn.close()
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


def _active_email_relay():
    conn = operator_delivery._connect()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(id,notification_type,relay_token,channel,customer_id,subject,body,status,created_at,mode) "
        "VALUES (29,'relay','abc123def456','whatsapp',?,'Question','Body','sent','2026-09-04','hard')",
        (CONVERSATION,),
    )
    conn.execute(
        "CREATE TABLE mermaid_reservations ("
        "tenant_slug TEXT,conversation_id TEXT,human_takeover INTEGER,updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO mermaid_reservations VALUES ('mermaid',?,1,'before')",
        (CONVERSATION,),
    )
    conn.commit()
    conn.close()
    state_registry.set_ai_muted(CONVERSATION, True)
    state_registry.wa_save_booking_state(
        CONVERSATION,
        {"name": "Guest"},
        {
            "awaiting_relay": True,
            "relay_token": "abc123def456",
            "relay_question": "Question",
            "fully_escalated": True,
            "preserved": True,
        },
    )
    return state_registry.get_relay_by_token("abc123def456")


def test_operator_email_whatsapp_relay_retries_one_frozen_payload_and_releases_mermaid(
    monkeypatch,
):
    relay = _active_email_relay()
    generations, sends = [], []
    monkeypatch.setattr(
        email_poller.marina_agent,
        "process_message",
        lambda *_a, **_k: generations.append(True)
        or {"reply": f"Prepared answer {len(generations)}"},
    )

    def sender(*args, **kwargs):
        sends.append((args, kwargs))
        return len(sends) > 1

    monkeypatch.setattr(email_poller, "send_whatsapp_message", sender)
    with pytest.raises(operator_delivery.OperatorDeliveryUnconfirmed):
        email_poller._deliver_whatsapp_operator_relay(relay, "Tell them the answer")

    assert generations == [True]
    assert rows("pending_notifications")[0]["status"] == "sent"
    assert rows("mermaid_reservations")[0]["human_takeover"] == 1
    assert state_registry.get_ai_muted(CONVERSATION) is True
    assert rows("whatsapp_threads") == []

    result, replayed = email_poller._deliver_whatsapp_operator_relay(
        relay, "Tell them the answer"
    )
    assert replayed is False
    assert result == {
        "ok": True,
        "reply": "Prepared answer 1",
        "channel": "whatsapp",
    }
    assert sends[0] == sends[1]
    assert sends[0][1]["confirm_delivery"] is True
    assert sends[0][1]["idempotency_key"].startswith("unboks-operator-")
    assert rows("pending_notifications")[0]["status"] == "replied"
    assert rows("mermaid_reservations")[0]["human_takeover"] == 0
    assert state_registry.get_ai_muted(CONVERSATION) is False
    flags = state_registry.wa_get_booking_state(CONVERSATION)["flags"]
    assert flags == {"fully_escalated": False, "preserved": True}
    assert [row["text"] for row in rows("whatsapp_threads")] == ["Prepared answer 1"]

    assert email_poller._deliver_whatsapp_operator_relay(
        relay, "Tell them the answer"
    ) == (result, True)
    assert generations == [True]
    assert len(sends) == 2
    assert len(rows("operator_delivery_outbox")) == 1


def test_operator_email_relay_requires_trusted_sender_and_actionable_whatsapp_row():
    relay = _active_email_relay()
    subject = "Re: [RELAY-abc123def456] Guest"
    assert email_poller._active_whatsapp_operator_relay(
        "Crew@Example.com", "crew@example.com", subject
    ) == relay
    assert email_poller._active_whatsapp_operator_relay(
        "attacker@example.com", "crew@example.com", subject
    ) is None
    state_registry.update_notification_status(relay["id"], "replied")
    assert email_poller._active_whatsapp_operator_relay(
        "crew@example.com", "crew@example.com", subject
    ) is None


def test_operator_email_relay_runs_before_customer_mail_guards():
    source = Path(email_poller.__file__).read_text()
    relay_branch = source.index("if _wa_operator_relay is not None:")
    assert relay_branch < source.index("# Per-sender rate limit", relay_branch)
    assert relay_branch < source.index("# ---- BM-003", relay_branch)
    assert relay_branch < source.index("# Anti-loop guard", relay_branch)


def test_dashboard_email_retry_after_local_failure_does_not_resend_and_releases_mermaid(
    monkeypatch, tmp_path,
):
    customer = "guest@example.com"
    thread_key = f"subj:{customer}:question"
    email_state_path = tmp_path / "email_thread_state.json"
    email_state_path.write_text(json.dumps({
        "threads": {
            thread_key: {
                "messages": [
                    {"role": "customer", "ts": "2026-09-04T10:00:00+00:00", "body": "Question"}
                ],
                "fields": {},
                "flags": {"fully_escalated": True},
            }
        }
    }))
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_state_path)
    )
    conn = operator_delivery._connect()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(id,notification_type,channel,customer_id,subject,body,status,created_at,mode) "
        "VALUES (41,'escalation','email',?,'Question','Body','pending','2026-09-04','hard')",
        (customer,),
    )
    conn.execute(
        "CREATE TABLE mermaid_reservations ("
        "tenant_slug TEXT,conversation_id TEXT,human_takeover INTEGER,updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO mermaid_reservations VALUES ('mermaid',?,1,'before')",
        (customer,),
    )
    conn.commit()
    conn.close()
    state_registry.set_ai_muted(customer, True)

    prepared, sends = [], []

    def prepare():
        prepared.append(True)
        return {
            "to": customer,
            "subject": "Re: Question",
            "text": "Exact operator answer",
            "role": "operator",
            "notification_id": 41,
            "response": {"ok": True, "reply": "Exact operator answer", "channel": "email"},
        }

    def sender(*args, **kwargs):
        sends.append((args, kwargs))

    original_append = state_registry.email_append_assistant_message
    append_calls = []

    def fail_after_first_append(*args, **kwargs):
        result = original_append(*args, **kwargs)
        append_calls.append(True)
        if len(append_calls) == 1:
            raise RuntimeError("synthetic local commit failure")
        return result

    monkeypatch.setattr(
        state_registry, "email_append_assistant_message", fail_after_first_append
    )
    delivery_args = dict(
        conversation_id=customer,
        scope="escalation:41:reply:email",
        original={"text": "Exact operator answer"},
        request_id="email-action-41",
        prepare=prepare,
        sender=sender,
    )
    with pytest.raises(RuntimeError, match="synthetic local commit failure"):
        operator_delivery.deliver_email(**delivery_args)

    assert prepared == [True]
    assert len(sends) == 1
    assert sends[0][1]["message_id"].startswith("<unboks-operator-")
    assert rows("operator_delivery_outbox")[0]["status"] == "provider_confirmed"
    assert rows("pending_notifications")[0]["status"] == "pending"

    result, replayed = operator_delivery.deliver_email(**delivery_args)
    assert replayed is False
    assert result == {"ok": True, "reply": "Exact operator answer", "channel": "email"}
    assert prepared == [True]
    assert len(sends) == 1
    assert rows("operator_delivery_outbox")[0]["status"] == "confirmed"
    assert rows("pending_notifications")[0]["status"] == "replied"
    assert rows("mermaid_reservations")[0]["human_takeover"] == 0
    assert state_registry.get_ai_muted(customer) is False
    stored = json.loads(email_state_path.read_text())["threads"][thread_key]
    outbound = [m for m in stored["messages"] if m.get("role") == "operator"]
    assert len(outbound) == 1
    assert outbound[0]["source_message_key"].startswith("operator-email-action:")
    assert stored["flags"]["fully_escalated"] is False

    assert operator_delivery.deliver_email(**delivery_args) == (result, True)
    assert len(sends) == 1


def test_email_flag_clear_failure_retries_after_effects_without_resending(
    monkeypatch, tmp_path,
):
    customer = "flag-retry@example.com"
    thread_key = f"subj:{customer}:question"
    email_state_path = tmp_path / "email_thread_state.json"
    email_state_path.write_text(json.dumps({
        "threads": {
            thread_key: {
                "messages": [{
                    "role": "customer",
                    "ts": "2026-09-04T10:00:00+00:00",
                    "body": "Question",
                }],
                "fields": {},
                "flags": {"fully_escalated": True},
            }
        }
    }))
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_state_path)
    )
    conn = operator_delivery._connect()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(id,notification_type,channel,customer_id,subject,body,status,created_at,mode) "
        "VALUES (42,'escalation','email',?,'Question','Body','pending','2026-09-04','hard')",
        (customer,),
    )
    conn.commit()
    conn.close()

    sends = []
    original_clear = state_registry.email_clear_fully_escalated_flag
    clear_calls = []

    def fail_first_clear(*args, **kwargs):
        clear_calls.append(True)
        if len(clear_calls) == 1:
            raise RuntimeError("synthetic sidecar clear failure")
        return original_clear(*args, **kwargs)

    monkeypatch.setattr(
        state_registry, "email_clear_fully_escalated_flag", fail_first_clear
    )
    delivery_args = dict(
        conversation_id=customer,
        scope="escalation:42:reply:email",
        original={"text": "Answer"},
        request_id="email-action-42",
        prepare=lambda: {
            "to": customer,
            "subject": "Re: Question",
            "text": "Answer",
            "role": "operator",
            "thread_key": thread_key,
            "notification_id": 42,
            "response": {"ok": True, "channel": "email"},
        },
        sender=lambda *args, **kwargs: sends.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="synthetic sidecar clear failure"):
        operator_delivery.deliver_email(**delivery_args)
    assert len(sends) == 1
    assert rows("operator_delivery_outbox")[0]["status"] == "effects_committed"
    assert rows("pending_notifications")[0]["status"] == "replied"

    result, replayed = operator_delivery.deliver_email(**delivery_args)
    assert result == {"ok": True, "channel": "email"}
    assert replayed is False
    assert len(sends) == 1
    assert rows("operator_delivery_outbox")[0]["status"] == "confirmed"
    stored = json.loads(email_state_path.read_text())["threads"][thread_key]
    assert stored["flags"]["fully_escalated"] is False


def test_email_reescalation_during_smtp_preserves_new_revision_and_freeze(
    monkeypatch, tmp_path,
):
    customer = "smtp-race@example.com"
    thread_key = f"subj:{customer}:question"
    email_state_path = tmp_path / "email_thread_state.json"
    email_state_path.write_text(json.dumps({
        "threads": {
            thread_key: {
                "messages": [{
                    "role": "customer",
                    "ts": "2026-09-04T10:00:00+00:00",
                    "body": "Original question",
                }],
                "fields": {},
                "flags": {"fully_escalated": True},
            }
        }
    }))
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_state_path)
    )
    notification_id = state_registry.create_pending_notification(
        "escalation", "email", customer, "Guest",
        "Original question", "Original body", mode="hard",
        email_thread_key=thread_key,
        email_reply_subject="Re: Question",
    )
    state_registry.set_ai_muted(customer, True, "email")

    def sender(*_args, **_kwargs):
        assert state_registry.create_pending_notification(
            "escalation", "email", customer, "Guest",
            "Updated question", "New body", mode="hard",
            email_thread_key=thread_key,
            email_reply_subject="Re: Question",
        ) == notification_id

    operator_delivery.deliver_email(
        conversation_id=customer,
        scope=f"escalation:{notification_id}:reply:email",
        original={"text": "Original answer"},
        request_id="smtp-reescalation",
        prepare=lambda: {
            "to": customer,
            "subject": "Re: Question",
            "text": "Original answer",
            "role": "operator",
            "thread_key": thread_key,
            "notification_id": notification_id,
            "response": {"ok": True, "channel": "email"},
        },
        sender=sender,
    )

    notification = rows("pending_notifications")[0]
    assert notification["status"] == "pending"
    assert notification["subject"] == "Updated question"
    assert notification["content_revision"] == 2
    assert state_registry.get_active_escalation_mode(customer) == "hard"
    assert state_registry.get_ai_muted(customer) is True
    stored = json.loads(email_state_path.read_text())["threads"][thread_key]
    assert stored["flags"]["fully_escalated"] is True
    assert len([m for m in stored["messages"] if m.get("role") == "operator"]) == 1
    assert rows("operator_delivery_outbox")[0]["status"] == "confirmed"


def test_stale_dashboard_revision_cannot_close_new_email_issue(monkeypatch, tmp_path):
    customer = "stale-view@example.com"
    thread_key = f"subj:{customer}:question"
    email_state_path = tmp_path / "email_thread_state.json"
    email_state_path.write_text(json.dumps({
        "threads": {
            thread_key: {
                "messages": [{
                    "role": "customer",
                    "ts": "2026-09-04T10:00:00+00:00",
                    "body": "Original question",
                }],
                "fields": {},
                "flags": {"fully_escalated": True},
            }
        }
    }))
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_state_path)
    )
    notification_id = state_registry.create_pending_notification(
        "escalation", "email", customer, "Guest",
        "Original question", "Original body", mode="hard",
        email_thread_key=thread_key,
        email_reply_subject="Re: Question",
    )
    viewed_revision = rows("pending_notifications")[0]["content_revision"]
    assert state_registry.create_pending_notification(
        "escalation", "email", customer, "Guest",
        "New question", "New body", mode="hard",
        email_thread_key=thread_key,
        email_reply_subject="Re: Question",
    ) == notification_id
    sends = []
    monkeypatch.setattr(api, "smtp_send", lambda *a, **k: sends.append((a, k)))

    with pytest.raises(HTTPException) as failed:
        asyncio.run(api.reply_to_escalation(
            notification_id,
            api.EscalationReplyRequest(
                message="Answer based on the old screen",
                request_id="stale-email-view",
                content_revision=viewed_revision,
            ),
        ))
    assert failed.value.status_code == 409
    assert "changed" in failed.value.detail
    assert sends == []
    notification = rows("pending_notifications")[0]
    assert notification["status"] == "pending"
    assert notification["content_revision"] == 2
    assert rows("operator_delivery_outbox") == []


def test_email_reescalation_immediately_before_sidecar_clear_stays_active(
    monkeypatch, tmp_path,
):
    customer = "pre-clear-race@example.com"
    thread_key = f"subj:{customer}:question"
    email_state_path = tmp_path / "email_thread_state.json"
    email_state_path.write_text(json.dumps({
        "threads": {
            thread_key: {
                "messages": [{
                    "role": "customer",
                    "ts": "2026-09-04T10:00:00+00:00",
                    "body": "Original question",
                }],
                "fields": {},
                "flags": {"fully_escalated": True},
            }
        }
    }))
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_state_path)
    )
    original_id = state_registry.create_pending_notification(
        "escalation", "email", customer, "Guest",
        "Original question", "Original body", mode="hard",
        email_thread_key=thread_key,
        email_reply_subject="Re: Question",
    )
    original_clear = state_registry.email_clear_fully_escalated_flag
    clear_calls = []

    def reescalate_then_clear(*args, **kwargs):
        clear_calls.append(True)
        state_registry.create_pending_notification(
            "escalation", "email", customer, "Guest",
            "New issue", "New issue body", mode="hard",
            email_thread_key=thread_key,
            email_reply_subject="Re: Question",
        )
        return original_clear(*args, **kwargs)

    monkeypatch.setattr(
        state_registry, "email_clear_fully_escalated_flag", reescalate_then_clear
    )
    operator_delivery.deliver_email(
        conversation_id=customer,
        scope=f"escalation:{original_id}:reply:email",
        original={"text": "Original answer"},
        request_id="pre-clear-reescalation",
        prepare=lambda: {
            "to": customer,
            "subject": "Re: Question",
            "text": "Original answer",
            "role": "operator",
            "thread_key": thread_key,
            "notification_id": original_id,
            "response": {"ok": True, "channel": "email"},
        },
        sender=lambda *_a, **_k: None,
    )

    notifications = rows("pending_notifications")
    assert [row["status"] for row in notifications] == ["replied", "pending"]
    assert clear_calls == [True]
    stored = json.loads(email_state_path.read_text())
    assert stored["threads"][thread_key]["flags"]["fully_escalated"] is True

    # SQLite is authoritative for both processing and dashboard projection,
    # even if an older sidecar writer has projected a stale false flag.
    stored["threads"][thread_key]["flags"]["fully_escalated"] = False
    email_state_path.write_text(json.dumps(stored))
    assert email_poller._has_fully_escalated_review(customer, {}) is True
    conversations = state_registry.email_list_conversations()
    assert conversations[0]["status"] == "escalated"


def test_stale_email_poller_save_preserves_concurrent_operator_transcript(
    monkeypatch, tmp_path,
):
    customer = "merge@example.com"
    thread_key = f"subj:{customer}:question"
    email_state_path = tmp_path / "email_thread_state.json"
    email_state_path.write_text(json.dumps({
        "threads": {
            thread_key: {
                "messages": [{
                    "role": "customer",
                    "ts": "2026-09-04T10:00:00+00:00",
                    "body": "Question",
                }],
                "fields": {},
                "flags": {},
            }
        },
        "message_id_index": {},
    }))
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_state_path)
    )
    email_poller._EMAIL_STATE_BASELINES.clear()
    stale = email_poller.load_json(
        str(email_state_path), {"threads": {}, "message_id_index": {}}
    )

    state_registry.email_append_assistant_message(
        customer,
        "Confirmed operator answer",
        role="operator",
        source_message_key="operator-email-action:merge-proof",
        strict=True,
        thread_key=thread_key,
    )
    stale["threads"][thread_key]["fields"]["language"] = "pap"
    stale["threads"][thread_key]["messages"].append({
        "role": "customer",
        "ts": "2026-09-04T10:01:00+00:00",
        "body": "Danki",
    })
    email_poller.save_json(str(email_state_path), stale)

    stored = json.loads(email_state_path.read_text())["threads"][thread_key]
    assert stored["fields"]["language"] == "pap"
    assert [message["body"] for message in stored["messages"]] == [
        "Question", "Confirmed operator answer", "Danki",
    ]


def test_email_escalation_keeps_original_subject_thread_when_sender_has_two(
    monkeypatch, tmp_path,
):
    customer = "multi-subject@example.com"
    escalated_key = f"subj:{customer}:wheelchair question"
    newer_key = f"subj:{customer}:unrelated question"
    email_state_path = tmp_path / "email_thread_state.json"
    email_state_path.write_text(json.dumps({
        "threads": {
            escalated_key: {
                "messages": [{"role": "customer", "ts": "2026-09-04T10:00:00Z", "body": "Help"}],
                "fields": {}, "flags": {"fully_escalated": True},
                "last_activity": "2026-09-04T10:00:00Z",
            },
            newer_key: {
                "messages": [{"role": "customer", "ts": "2026-09-04T11:00:00Z", "body": "Menu"}],
                "fields": {}, "flags": {},
                "last_activity": "2026-09-04T11:00:00Z",
            },
        }
    }))
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_state_path)
    )
    conn = operator_delivery._connect()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(id,notification_type,channel,customer_id,subject,body,status,created_at,mode,"
        "email_thread_key,email_reply_subject) "
        "VALUES (43,'escalation','email',?,'Internal alert','Body','pending','2026-09-04','hard',?,?)",
        (customer, escalated_key, "Re: Wheelchair question"),
    )
    conn.commit()
    conn.close()
    sends = []
    monkeypatch.setattr(api, "smtp_send", lambda *a, **k: sends.append((a, k)))

    result = asyncio.run(api.reply_to_escalation(
        43,
        api.EscalationReplyRequest(message="We can help.", request_id="exact-email-thread"),
    ))
    assert result == {"ok": True, "reply": "We can help.", "channel": "email"}
    assert sends[0][0][1] == "Re: Wheelchair question"
    state = json.loads(email_state_path.read_text())["threads"]
    assert len([m for m in state[escalated_key]["messages"] if m.get("role") == "operator"]) == 1
    assert [m for m in state[newer_key]["messages"] if m.get("role") == "operator"] == []


@pytest.mark.parametrize("route", ["reply", "guidance"])
def test_missing_exact_escalation_thread_never_falls_back_to_other_subject(
    monkeypatch, tmp_path, route,
):
    customer = "missing-thread@example.com"
    escalated_key = f"subj:{customer}:wheelchair question"
    unrelated_key = f"subj:{customer}:unrelated question"
    email_state_path = tmp_path / "email_thread_state.json"
    state = {
        "threads": {
            escalated_key: {
                "messages": [{"role": "customer", "ts": "2026-09-04T10:00:00Z", "body": "Help"}],
                "fields": {}, "flags": {"fully_escalated": True},
                "last_activity": "2026-09-04T10:00:00Z",
            },
            unrelated_key: {
                "messages": [{"role": "customer", "ts": "2026-09-04T11:00:00Z", "body": "Menu"}],
                "fields": {}, "flags": {},
                "last_activity": "2026-09-04T11:00:00Z",
            },
        }
    }
    email_state_path.write_text(json.dumps(state))
    monkeypatch.setattr(
        state_registry, "_get_email_state_path", lambda: str(email_state_path)
    )
    conn = operator_delivery._connect()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(id,notification_type,channel,customer_id,subject,body,status,created_at,mode,"
        "email_thread_key,email_reply_subject) "
        "VALUES (44,'escalation','email',?,'Internal alert','Body','pending','2026-09-04',?,?,?)",
        (customer, "soft", escalated_key, "Re: Wheelchair question"),
    )
    conn.commit()
    conn.close()

    # Simulate retention/manual cleanup removing only the exact source thread.
    del state["threads"][escalated_key]
    email_state_path.write_text(json.dumps(state))
    escalation = next(e for e in state_registry.get_all_escalations() if e["id"] == 44)
    assert escalation["email_thread_key"] == escalated_key
    assert escalation["phone"] == f"email::{escalated_key}"

    sends = []
    monkeypatch.setattr(api, "smtp_send", lambda *a, **k: sends.append((a, k)))
    endpoint = api.reply_to_escalation if route == "reply" else api.guidance_to_marina
    with pytest.raises(HTTPException) as failed:
        asyncio.run(endpoint(
            44,
            api.EscalationReplyRequest(
                message="Please answer the original question.",
                request_id=f"missing-exact-{route}",
            ),
        ))
    assert failed.value.status_code == 409
    assert "exact email thread" in failed.value.detail
    assert sends == []
    assert rows("pending_notifications")[0]["status"] == "pending"
    unrelated = json.loads(email_state_path.read_text())["threads"][unrelated_key]
    assert [m for m in unrelated["messages"] if m.get("role") in {"operator", "marina"}] == []
