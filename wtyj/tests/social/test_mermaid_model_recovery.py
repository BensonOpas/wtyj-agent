"""Real buffered worker + SQLite; all model and customer provider calls stubbed."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agents.marina import marina_agent
from agents.social import mermaid_model_recovery as recovery
from agents.social import mermaid_reservation_workflow as workflow
from agents.social import webhook_server
from shared import state_registry
from test_mermaid_soft_review import CONVERSATION, _flush, _rows, _understood, review_runtime

_real_process_message = marina_agent.process_message

HUMAN_REQUESTS = {
    "en": "I want to speak to a real person.",
    "nl": "Ik wil een echte medewerker spreken.",
    "de": "Ich möchte mit einem echten Mitarbeiter sprechen.",
    "es": "Quiero hablar con una persona de verdad.",
    "pap": "Mi ke papia ku un hende di e tim.",
    "pt": "Quero falar com uma pessoa de verdade.",
}


def _locale(locale):
    state = state_registry.wa_get_booking_state(CONVERSATION)
    state["fields"]["mermaid_intake"]["language"] = locale
    state_registry.wa_save_booking_state(CONVERSATION, state["fields"], state["flags"])
    return state["fields"]["mermaid_intake"]


def _due():
    conn = state_registry._get_conn()
    conn.execute("UPDATE mermaid_model_events SET retry_at=0")
    conn.execute("UPDATE mermaid_model_circuit SET blocked_until=0")
    conn.execute("UPDATE inbound_processing_events SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE status='recovering'")
    conn.commit()
    conn.close()


@pytest.mark.parametrize("locale", HUMAN_REQUESTS)
def test_failed_event_recovers_once_without_caching_fallback(review_runtime, locale):
    model, send, _controls = review_runtime
    saved = _locale(locale)
    model.return_value = {"generation_failed": True, "reply": "English legacy fallback", "fields": {}}
    _flush("failure-one", "trip question")
    assert send.call_count == 1, _rows("SELECT status,reason,last_error FROM inbound_processing_events")
    assert send.call_args.args[3] == recovery.FAILURE_COPY[locale]
    fallback_key = send.call_args.kwargs["idempotency_key"]
    assert _rows("SELECT status FROM inbound_processing_events") == [("recovering",)]
    state = state_registry.wa_get_booking_state(CONVERSATION)
    assert state["fields"]["mermaid_intake"] == saved
    assert "failure-one" not in state["flags"].get("mermaid_seen_message_ids", [])
    assert not state["flags"].get("mermaid_cached_reply")
    _due()
    model.return_value = {**_understood("question", "Recovered answer"), "language": locale}
    assert webhook_server._recover_stale_ali_inbound_once(ali_workflow=False) == 1
    assert model.call_count == send.call_count == 2
    assert send.call_args.args[3] == "Recovered answer"
    assert send.call_args.kwargs["idempotency_key"] != fallback_key
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]
    assert webhook_server._recover_stale_ali_inbound_once(ali_workflow=False) == 0
    assert model.call_count == send.call_count == 2
    assert _rows("SELECT COUNT(*) FROM pending_notifications WHERE notification_type='technical'") == [(1,)]


@pytest.mark.parametrize("locale,text", HUMAN_REQUESTS.items())
def test_explicit_human_request_does_not_require_model_and_deduplicates(review_runtime, locale, text):
    model, send, _controls = review_runtime
    _locale(locale)
    model.side_effect = AssertionError("The offline human route must not call a model")
    _flush("human-one", text)
    _flush("human-two", text)
    assert model.call_count == 0
    assert send.call_count == 2
    from agents.social.mermaid_response_policy import copy as policy_copy
    assert send.call_args.args[3] == policy_copy('review_queued', locale)
    assert _rows("SELECT notification_type,mode FROM pending_notifications") == [("escalation", "soft")]
    assert not state_registry.get_ai_muted(CONVERSATION)
    assert state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"]["customer_name"] == "Test Guest"


def test_repeated_failure_sends_one_notice_and_attempts_are_bounded(review_runtime):
    model, send, _controls = review_runtime
    model.side_effect = TimeoutError("synthetic timeout")
    _flush("bounded", "trip question")
    for _ in range(4):
        _due()
        webhook_server._recover_stale_ali_inbound_once(ali_workflow=False)
    assert model.call_count == recovery.MAX_ATTEMPTS
    assert send.call_count == 1
    assert _rows("SELECT status FROM inbound_processing_events") == [("processing_failed",)]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(1,)]


@pytest.mark.parametrize("kind", ["billing", "credentials", "request_rejected"])
def test_permanent_outage_has_no_retries_or_alert_storm_and_new_messages_continue(review_runtime, kind):
    model, send, _controls = review_runtime
    model.return_value = {"generation_failed": True, "model_error": {"kind": kind, "retryable": False}}
    _flush("permanent-one", "trip question")
    _flush("permanent-two", "another question")
    assert model.call_count == 1
    assert send.call_count == 2
    assert _rows("SELECT status FROM inbound_processing_events") == [("processing_failed",), ("processing_failed",)]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(1,)]
    _flush("human-outage", HUMAN_REQUESTS["en"])
    assert model.call_count == 1
    assert state_registry.get_active_escalation_mode(CONVERSATION) == "soft"
    _due()
    model.return_value = _understood("question", "Food is included.")
    _flush("healthy-new", "What food is included?")
    assert model.call_count == 2
    assert send.call_args.args[3] == "Food is included."
    assert model.call_args.kwargs["thread_fields"]["human_review_pending"] is True


def test_concurrent_duplicate_event_has_only_one_generation(review_runtime):
    _model, _send, _controls = review_runtime
    started, release = Event(), Event()
    def generate():
        started.set()
        assert release.wait(3)
        return _understood("question", "Answer")
    model = Mock(side_effect=generate)
    message = {"from": CONVERSATION, "message_id": "same-event", "text": "trip question"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(recovery.generate, message, "en", model)
        assert started.wait(3)
        second = pool.submit(recovery.generate, message, "en", model).result(timeout=3)
        assert second["reply"] == ""
        release.set()
        assert first.result(timeout=3)["reply"] == "Answer"
    assert model.call_count == 1


def test_manual_mute_and_tenant_pause_block_offline_human_acknowledgement(review_runtime):
    model, send, controls = review_runtime
    state_registry.set_ai_muted(CONVERSATION, True)
    _flush("manual", HUMAN_REQUESTS["en"])
    assert not send.called and not model.called
    assert state_registry.get_ai_muted(CONVERSATION)
    state_registry.set_ai_muted(CONVERSATION, False)
    controls["feature_toggles"]["ai_auto_reply"]["value"] = False
    _flush("paused", HUMAN_REQUESTS["en"])
    assert not send.called and not model.called
    assert _rows("SELECT COUNT(*) FROM pending_notifications WHERE notification_type='escalation'") == [(0,)]


def test_ordinary_people_mentions_do_not_use_offline_route():
    for text in ("Does a person need to bring ID?", "I want to speak to a real person. Also change the price.", "How many people fit?"):
        assert recovery.explicit_human_request(text) is None


def test_retry_backoff_and_expired_worker_cannot_replace_new_generation(review_runtime, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(recovery, "time", SimpleNamespace(time=lambda: clock[0]))
    message = {"from": CONVERSATION, "message_id": "backoff", "text": "trip question"}
    model = Mock(side_effect=TimeoutError())
    first = recovery.generate(message, "en", model)
    assert first["generation_failure"]["retry_at"] == 1005
    clock[0] = 1004
    recovery.generate(message, "en", model)
    assert model.call_count == 1
    clock[0] = 1005
    second = recovery.generate(message, "en", model)
    assert second["generation_failure"]["retry_at"] == 1015
    assert _rows("SELECT blocked_until FROM mermaid_model_circuit") == [(1015.0,)]

    _due()
    started, release = Event(), Event()
    def slow():
        started.set()
        assert release.wait(3)
        return _understood("question", "Stale answer")
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(recovery.generate, {**message, "message_id": "expired"}, "en", slow)
        assert started.wait(3)
        clock[0] += recovery.GENERATION_LEASE_SECONDS + 1
        fresh = recovery.generate({**message, "message_id": "expired"}, "en", lambda: _understood("question", "Fresh answer"))
        release.set()
        stale = old.result(timeout=3)
    assert fresh["reply"] == "Fresh answer"
    assert stale["reply"] == ""
    assert stale["generation_failure"]["superseded"] is True
    assert recovery.generate({**message, "message_id": "expired"}, "en", Mock())["reply"] == "Fresh answer"


def test_newer_success_supersedes_old_failed_event_and_cached_legacy_failure_is_repaired(review_runtime):
    model, send, _controls = review_runtime
    model.side_effect = TimeoutError()
    _flush("old-failure", "trip question")
    _due()
    model.side_effect = None
    model.return_value = _understood("question", "New answer")
    _flush("new-success", "a safe followup")
    assert webhook_server._recover_stale_ali_inbound_once(ali_workflow=False) == 0
    assert model.call_count == send.call_count == 2
    assert _rows("SELECT status FROM inbound_processing_events WHERE message_id='old-failure'") == [("superseded",)]
    state = state_registry.wa_get_booking_state(CONVERSATION)
    state["flags"]["mermaid_cached_reply"] = {"message_id": "legacy", "reply": {"text": "Old cached failure"}}
    state_registry.wa_save_booking_state(CONVERSATION, state["fields"], state["flags"])
    reply = workflow.handle_demo_message({"from": CONVERSATION, "message_id": "legacy", "text": "trip question"}, include_media=True, use_model=True)
    assert reply["text"] == "New answer"
    assert model.call_count == 3


@pytest.mark.parametrize("status,body,kind,retryable", [
    (400, {"error": {"type": "invalid_request_error", "message": "Your credit balance is too low"}}, "billing", False),
    (401, {"error": {"type": "authentication_error"}}, "credentials", False),
    (429, {"error": {"type": "rate_limit_error"}}, "transient", True),
    (529, {"error": {"type": "overloaded_error"}}, "transient", True),
])
def test_provider_error_classification_and_no_sdk_retries(review_runtime, monkeypatch, status, body, kind, retryable):
    from agents.social import mermaid_understanding
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-key")
    monkeypatch.setattr(mermaid_understanding, "user_prompt", lambda *_args, **_kwargs: "Synthetic request", raising=False)
    error = Exception("Do not persist raw API errors or tokens")
    error.status_code, error.body = status, body
    client = Mock()
    client.messages.create.side_effect = error
    factory = Mock(return_value=client)
    monkeypatch.setattr(marina_agent.anthropic, "Anthropic", factory)
    reply = _real_process_message(from_email="synthetic", subject="test", body="question", thread_fields={}, thread_flags={}, response_contract="mermaid_reservation_demo")
    assert reply["model_error"] == {"kind": kind, "retryable": retryable}
    assert factory.call_args.kwargs["max_retries"] == 0
    assert factory.call_args.kwargs["timeout"] == 30.0
    assert client.messages.create.call_count == 1


def test_explicit_human_result_exposes_auditable_source_and_locale(review_runtime):
    result = workflow.handle_demo_message({"from": CONVERSATION, "message_id": "metadata", "text": HUMAN_REQUESTS["nl"]}, include_media=True, use_model=True)
    assert result["language"] == "nl"
    assert result["understanding_source"] == "explicit_human_request"


def test_failed_notice_delivery_never_marks_event_replied(review_runtime):
    model, send, _controls = review_runtime
    model.side_effect = TimeoutError()
    send.return_value = False
    _flush("notice-failed", "trip question")
    assert _rows("SELECT status FROM inbound_processing_events") == [("recovering",)]
    assert _rows("SELECT notice_sent FROM mermaid_model_events") == [(0,)]
    _due()
    model.side_effect = None
    model.return_value = _understood("question", "Recovered answer")
    send.return_value = True
    webhook_server._recover_stale_ali_inbound_once(ali_workflow=False)
    assert send.call_args.args[3] == "Recovered answer"
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]


def test_recovered_confirmation_creates_one_quote_and_provider_action(review_runtime, tmp_path, monkeypatch):
    from agents.social import mermaid_documents, mermaid_reservation_store
    model, send, _controls = review_runtime
    monkeypatch.setenv("MERMAID_DOCUMENT_ROOT", str(tmp_path / "documents"))
    monkeypatch.setenv("MERMAID_DEMO_SIGNING_SECRET", "synthetic-secret")
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://test.invalid")
    model.side_effect = TimeoutError()
    _flush("confirm-recovery", "Yes, correct.")
    _due()
    model.side_effect = None
    model.return_value = _understood("confirm_summary", "Confirmed")
    assert webhook_server._recover_stale_ali_inbound_once(ali_workflow=False) == 1
    reservation = mermaid_reservation_store.latest_for_conversation(CONVERSATION)
    assert reservation["state"] == "demo_payment_pending"
    assert _rows("SELECT COUNT(*) FROM mermaid_reservations") == [(1,)]
    assert len(mermaid_documents.documents_for_reservation(reservation["public_id"])) == 1
    assert send.call_count == model.call_count == 2
    assert send.call_args.kwargs["idempotency_key"].startswith("mermaid-delivery:")
    assert not state_registry.wa_claim_inbound_processing("confirm-recovery", CONVERSATION, "whatsapp")
    assert webhook_server._recover_stale_ali_inbound_once(ali_workflow=False) == 0
    assert send.call_count == model.call_count == 2


def test_missing_credentials_do_not_attempt_sdk_call(review_runtime, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    factory = Mock(side_effect=AssertionError("Missing credentials must not reach SDK"))
    monkeypatch.setattr(marina_agent.anthropic, "Anthropic", factory)
    reply = _real_process_message(from_email="synthetic", subject="test", body="question", thread_fields={}, thread_flags={}, response_contract="mermaid_reservation_demo")
    assert reply["model_error"] == {"kind": "credentials", "retryable": False}
    assert not factory.called


@pytest.mark.parametrize("malformed", [
    {"fields": ["not an object"]}, {"requires_human": "false"},
    {"reply": []}, {"mermaid_action": ["confirm_summary"]},
])
def test_malformed_structured_output_is_retryable_without_business_mutations(review_runtime, malformed):
    model, send, _controls = review_runtime
    original = _locale("es")
    model.return_value = {**_understood("confirm_summary", "Confirmed"), **malformed}
    _flush("malformed", "Yes")
    assert send.call_args.args[3] == recovery.FAILURE_COPY["es"]
    assert _rows("SELECT status FROM inbound_processing_events") == [("recovering",)]
    assert state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"] == original
