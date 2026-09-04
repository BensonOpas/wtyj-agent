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
    # This malformed output is local to the message, not a provider outage.
    assert _rows("SELECT COUNT(*) FROM pending_notifications WHERE notification_type='technical'") == [(0,)]


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


@pytest.mark.parametrize("locale,text", HUMAN_REQUESTS.items())
def test_offline_human_route_skips_enabled_summary_model_and_alerts_once(review_runtime, monkeypatch, locale, text):
    model, send, _controls = review_runtime
    _locale(locale)
    model.side_effect = AssertionError("No understanding model during offline handover")
    summary = Mock(side_effect=AssertionError("No hidden summary model during offline handover"))
    alert = Mock()
    monkeypatch.setattr(state_registry, "_summary_dispatcher", summary)
    monkeypatch.setattr(state_registry, "_alert_dispatcher", alert)
    _flush("offline-human-first", text)
    _flush("offline-human-repeated", text)
    assert not model.called and not summary.called
    assert send.call_count == 2
    assert alert.call_count == 1
    assert alert.call_args.kwargs["mode"] == "soft"
    assert alert.call_args.kwargs["is_update"] is False
    assert _rows("SELECT notification_type,mode FROM pending_notifications") == [("escalation", "soft")]


def test_regular_soft_review_retains_enabled_summary_and_alert_dispatch(review_runtime, monkeypatch):
    model, send, _controls = review_runtime
    summary = Mock(return_value={"situation": "Accessibility needs checking"})
    alert = Mock()
    monkeypatch.setattr(state_registry, "_summary_dispatcher", summary)
    monkeypatch.setattr(state_registry, "_alert_dispatcher", alert)
    model.return_value = _understood("request_human", "The team needs to review boarding assistance.")
    _flush("regular-human", "Can you guarantee help for a wheelchair?")
    assert model.call_count == summary.call_count == alert.call_count == send.call_count == 1
    assert alert.call_args.kwargs["summary_dict"] == summary.return_value


def test_legacy_offline_intake_human_route_also_skips_summary_model(review_runtime, monkeypatch):
    summary, alert = Mock(), Mock()
    monkeypatch.setattr(state_registry, "_summary_dispatcher", summary)
    monkeypatch.setattr(state_registry, "_alert_dispatcher", alert)
    for message_id in ("legacy-human-one", "legacy-human-two"):
        result = workflow.process_intake_turn(CONVERSATION, HUMAN_REQUESTS["en"], message_id=message_id)
        assert result.action == "human_takeover"
    assert not summary.called
    assert alert.call_count == 1


@pytest.mark.parametrize("field,bad_value", [
    (field, value)
    for field in ("calendar_request", "status_request", "security_event")
    for value in ([], {}, None, "not_a_valid_selector")
] + [("guest_question_excerpt", value) for value in ([], {}, None, True)])
def test_malformed_optional_model_fields_are_not_cached_and_same_event_recovers(review_runtime, field, bad_value):
    model, send, _controls = review_runtime
    original = _locale("nl")
    model.return_value = {**_understood("question", "This malformed response must not be delivered"), field: bad_value}
    _flush("malformed-selector", "trip question")
    assert _rows("SELECT status,error_kind,response_json FROM mermaid_model_events") == [("failed", "invalid_response", "{}")]
    assert send.call_args.args[3] == recovery.FAILURE_COPY["nl"]
    assert _rows("SELECT status FROM inbound_processing_events") == [("recovering",)]
    assert state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"] == original
    _due()
    model.return_value = {
        **_understood("question", "Recovered answer"), "language": "nl",
        "calendar_request": "none", "status_request": "none", "security_event": "none", "guest_question_excerpt": "trip question",
    }
    assert webhook_server._recover_stale_ali_inbound_once(ali_workflow=False) == 1
    assert model.call_count == send.call_count == 2
    assert send.call_args.args[3] == "Recovered answer"
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]
    assert _rows("SELECT status FROM mermaid_model_events") == [("generated",)]


@pytest.mark.parametrize("malformed", [
    {"fields": {"pickup_preference": []}},
    {"fields": {"pickup_preference": "unapproved_choice"}},
    {"language": []}, {"language": "unsupported"},
    {"confidence": "not_a_valid_confidence"},
] + [
    {"fields": {field: value}}
    for field in ("adults", "children", "infants")
    for value in (True, 2.5, -1, 101)
] + [
    {"fields": {field: []}}
    for field in ("trip_date", "customer_name", "contact_phone", "pickup_location", "dietary_requirements", "accessibility_notes", "special_requests")
])
def test_malformed_nested_fields_and_language_use_schema_recovery(review_runtime, malformed):
    model, send, _controls = review_runtime
    original = _locale("en")
    model.return_value = {**_understood("details", "Malformed"), **malformed}
    _flush("nested-malformed", "synthetic")
    assert _rows("SELECT status,error_kind,response_json FROM mermaid_model_events") == [("failed", "invalid_response", "{}")]
    assert send.call_args.args[3] == recovery.FAILURE_COPY["en"]
    assert state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"] == original
    _due()
    model.return_value = _understood("question", "Recovered answer")
    assert webhook_server._recover_stale_ali_inbound_once(ali_workflow=False) == 1
    assert model.call_count == send.call_count == 2
    assert send.call_args.args[3] == "Recovered answer"
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]


def test_actual_marina_sdk_response_with_compatibility_metadata_recovers_normally(review_runtime, monkeypatch):
    import json
    _model, send, _controls = review_runtime
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-key")
    monkeypatch.setattr(marina_agent, "process_message", _real_process_message)
    structured = {
        **_understood("question", "Synthetic SDK answer"),
        "calendar_request": "none", "status_request": "none", "security_event": "none", "guest_question_excerpt": "trip question",
    }
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=structured)], usage=None,
    )
    monkeypatch.setattr(marina_agent.anthropic, "Anthropic", Mock(return_value=client))
    _flush("actual-sdk", "trip question")
    assert client.messages.create.call_count == send.call_count == 1
    assert send.call_args.args[3] == "Synthetic SDK answer"
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]
    status, raw = _rows("SELECT status,response_json FROM mermaid_model_events")[0]
    stored = json.loads(raw)
    assert status == "generated"
    assert "intents" in stored and "flags" in stored
    assert stored["mermaid_action"] == "question"


def _sdk_result(monkeypatch, **updates):
    """Keep the real adapter, recovery and buffered worker; stub only the SDK."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-key")
    monkeypatch.setattr(marina_agent, "process_message", _real_process_message)
    structured = {
        **_understood("question", ""), "guest_question_excerpt": "trip question",
        "calendar_request": "none", "status_request": "none", "security_event": "none",
        "other_question_reply": "", **updates,
    }
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=structured)], usage=None,
    )
    monkeypatch.setattr(marina_agent.anthropic, "Anthropic", Mock(return_value=client))
    return client, structured


@pytest.mark.parametrize("locale", HUMAN_REQUESTS)
@pytest.mark.parametrize("selector", ["wildlife_guarantee", "handover"])
def test_sdk_empty_critical_reply_renders_recorded_review_across_locales(review_runtime, monkeypatch, locale, selector):
    from agents.social import mermaid_response_policy as policy

    _model, send, _controls = review_runtime
    saved = dict(_locale(locale))
    state_registry.create_pending_notification("escalation", "whatsapp", CONVERSATION, "Test Guest", "Review", "Saved", mode="soft")
    client, _ = _sdk_result(monkeypatch, language=locale, status_request=selector)
    _flush("sdk-empty-critical", "trip question")
    expected = policy.wildlife_guarantee_reply(locale, {"review": "queued"}) if selector == "wildlife_guarantee" else policy.copy("review_queued", locale)
    assert client.messages.create.call_count == send.call_count == 1
    assert send.call_args.args[3] == expected
    assert _rows("SELECT status FROM mermaid_model_events") == [("generated",)]
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]
    assert not state_registry.get_ai_muted(CONVERSATION)
    assert state_registry.get_active_escalation_mode(CONVERSATION) == "soft"
    current = state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"]
    assert {k: v for k, v in current.items() if k != "phase"} == {k: v for k, v in saved.items() if k != "phase"}


@pytest.mark.parametrize("locale", HUMAN_REQUESTS)
def test_sdk_empty_confirmation_quotes_once_then_returns_recorded_status(review_runtime, monkeypatch, tmp_path, locale):
    from agents.social import mermaid_reservation_store as store, mermaid_response_policy as policy

    _model, send, _controls = review_runtime
    _locale(locale)
    monkeypatch.setenv("MERMAID_DOCUMENT_ROOT", str(tmp_path / "documents"))
    monkeypatch.setenv("MERMAID_DEMO_SIGNING_SECRET", "synthetic-test-secret")
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://demo.example")
    client, _ = _sdk_result(monkeypatch, language=locale, mermaid_action="confirm_summary", guest_question_excerpt="", has_open_question=False)
    saved = state_registry.wa_get_booking_state(CONVERSATION)
    saved["fields"]["mermaid_intake"]["phase"] = "collecting"
    state_registry.wa_save_booking_state(CONVERSATION, saved["fields"], saved["flags"])
    _flush("sdk-empty-summary", "Those are my details.")
    assert store.latest_for_conversation(CONVERSATION) is None
    current = state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"]
    assert current["phase"] == "awaiting_summary_confirmation"
    assert send.call_args.args[3] == workflow._summary(current, locale)
    _flush("sdk-empty-yes", "Yes")
    reservation = store.latest_for_conversation(CONVERSATION)
    assert reservation is not None and reservation["state"] == "demo_payment_pending"
    assert send.call_count == 2 and "/mermaid/pay/" in send.call_args.args[3]
    assert _rows("SELECT COUNT(*) FROM mermaid_delivery_jobs") == [(1,)]
    _flush("sdk-empty-repeat", "Yes")
    assert client.messages.create.call_count == send.call_count == 3
    assert send.call_args.args[3] == policy.copy("payment_unpaid", locale)
    assert store.latest_for_conversation(CONVERSATION) == reservation
    assert len(store.list_reservations()) == 1
    assert _rows("SELECT COUNT(*) FROM mermaid_delivery_jobs") == [(1,)]
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)] * 3


@pytest.mark.parametrize("reservation_state", ["booked", "cancelled"])
def test_sdk_empty_confirmation_of_existing_reservation_uses_persisted_state(review_runtime, monkeypatch, reservation_state):
    from agents.social import mermaid_reservation_store as store, mermaid_response_policy as policy

    _model, send, _controls = review_runtime
    intake = dict(_locale("en"), phase="summary_confirmed")
    reservation = store.confirm_reservation(CONVERSATION, intake, idempotency_key="existing")
    for status in ("quote_ready", "demo_payment_pending"):
        reservation = store.transition(reservation["public_id"], status, idempotency_key=status, actor="system", reason="synthetic fixture")
    if reservation_state == "booked":
        reservation, _ = store.complete_demo_payment(reservation["public_id"], payment_reference="synthetic-paid", idempotency_key="synthetic-paid")
        expected = policy.copy("payment_paid", "en")
    else:
        reservation = store.cancel(reservation["public_id"], idempotency_key="synthetic-cancelled")
        expected = workflow.COPY["en"]["cancelled"]
    client, _ = _sdk_result(monkeypatch, mermaid_action="confirm_summary", guest_question_excerpt="", has_open_question=False)
    _flush("sdk-existing-yes", "Yes")
    assert client.messages.create.call_count == send.call_count == 1
    assert send.call_args.args[3] == expected
    assert store.latest_for_conversation(CONVERSATION) == reservation
    assert len(store.list_reservations()) == 1
    assert _rows("SELECT COUNT(*) FROM mermaid_delivery_jobs") == [(0,)]


@pytest.mark.parametrize("structured,copy_key", [
    ({"status_request": "payment"}, "payment_none"),
    ({"status_request": "delivery"}, "delivery_none"),
    ({"status_request": "pickup_coverage"}, "pickup_round_trip"),
    ({"mermaid_action": "payment_status"}, "payment_none"),
    ({"mermaid_action": "request_human"}, "review_queued"),
    ({"requires_human": True}, "review_queued"),
    ({"security_event": "blocked_override"}, "security_blocked"),
    ({"mermaid_action": "cancel"}, None),
    ({"calendar_request": "operating_days"}, None),
    ({"status_request": "pickup_pricing"}, None),
])
def test_sdk_other_empty_server_routes_have_authoritative_output(review_runtime, monkeypatch, structured, copy_key):
    from agents.social import mermaid_response_policy as policy

    _model, send, _controls = review_runtime
    saved = dict(_locale("en"))
    client, _ = _sdk_result(monkeypatch, **structured)
    _flush("sdk-other-critical", "trip question")
    if copy_key:
        expected = policy.copy(copy_key, "en")
    elif structured.get("mermaid_action") == "cancel":
        expected = workflow.COPY["en"]["cancelled"]
    elif structured.get("calendar_request"):
        expected = policy.calendar_reply("operating_days", "en")
    else:
        expected = policy.pickup_pricing_reply("en", saved)
    assert client.messages.create.call_count == send.call_count == 1
    assert send.call_args.args[3] == expected
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]


@pytest.mark.parametrize("action", ["question", "details", "acknowledge", "confirm_summary"])
def test_sdk_blank_ordinary_answer_remains_retryable_and_same_event_recovers(review_runtime, monkeypatch, action):
    _model, send, _controls = review_runtime
    saved = dict(_locale("en"))
    client, structured = _sdk_result(monkeypatch, mermaid_action=action)
    _flush("sdk-empty-faq", "trip question")
    assert send.call_args.args[3] == recovery.FAILURE_COPY["en"]
    assert _rows("SELECT status,error_kind,response_json FROM mermaid_model_events") == [("failed", "invalid_response", "{}")]
    assert state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"] == saved
    assert "sdk-empty-faq" not in state_registry.wa_get_booking_state(CONVERSATION)["flags"].get("mermaid_seen_message_ids", [])
    _due()
    structured["reply"] = "Breakfast is included."
    structured["mermaid_action"] = "question"
    assert webhook_server._recover_stale_ali_inbound_once(ali_workflow=False) == 1
    assert client.messages.create.call_count == send.call_count == 2
    assert send.call_args.args[3] == "Breakfast is included."
    assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]


def test_sdk_blank_status_preserves_and_sanitizes_separate_faq(review_runtime, monkeypatch):
    from agents.social import mermaid_response_policy as policy

    _model, send, _controls = review_runtime
    state_registry.create_pending_notification("escalation", "whatsapp", CONVERSATION, "Test Guest", "Review", "Saved", mode="soft")
    client, _ = _sdk_result(monkeypatch, status_request="handover", other_question_reply="Breakfast—BBQ lunch. [HANDOFF]")
    _flush("sdk-empty-mixed", "trip question")
    assert client.messages.create.call_count == send.call_count == 1
    assert send.call_args.args[3] == "Breakfast,BBQ lunch.\n\n" + policy.copy("review_queued", "en")


@pytest.mark.parametrize("malformed", [{"fields": {"adults": True}}, {"status_request": []}, {"reply": None}, {"other_question_reply": []}])
def test_sdk_empty_critical_route_still_rejects_malformed_schema(review_runtime, monkeypatch, malformed):
    _model, send, _controls = review_runtime
    client, _ = _sdk_result(monkeypatch, **({"status_request": "wildlife_guarantee"} | malformed))
    _flush("sdk-empty-malformed", "trip question")
    assert client.messages.create.call_count == send.call_count == 1
    assert send.call_args.args[3] == recovery.FAILURE_COPY["en"]
    assert _rows("SELECT status,response_json FROM mermaid_model_events") == [("failed", "{}")]


@pytest.mark.parametrize("value,accepted", [("", True), ("passengers=5", False), ([], False), (None, False)])
def test_actual_sdk_empty_fields_normalization_is_narrow_and_preserves_intake(review_runtime, monkeypatch, value, accepted):
    import json
    _model, send, _controls = review_runtime
    original = _locale("en")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-key")
    monkeypatch.setattr(marina_agent, "process_message", _real_process_message)
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={**_understood("question", "Breakfast is included."), "fields": value})], usage=None,
    )
    monkeypatch.setattr(marina_agent.anthropic, "Anthropic", Mock(return_value=client))
    _flush("sdk-fields", "Is breakfast included?")
    assert client.messages.create.call_count == send.call_count == 1
    assert state_registry.wa_get_booking_state(CONVERSATION)["fields"]["mermaid_intake"] == original
    status, raw = _rows("SELECT status,response_json FROM mermaid_model_events")[0]
    if accepted:
        assert send.call_args.args[3] == "Breakfast is included."
        assert status == "generated" and json.loads(raw)["fields"] == {}
        assert _rows("SELECT status FROM inbound_processing_events") == [("replied",)]
    else:
        assert send.call_args.args[3] == recovery.FAILURE_COPY["en"]
        assert status == "failed" and raw == "{}"
        assert _rows("SELECT status FROM inbound_processing_events") == [("recovering",)]
    assert _rows("SELECT COUNT(*) FROM mermaid_model_circuit") == [(0,)]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(0,)]


def test_invalid_response_retries_own_event_without_blocking_other_conversations(review_runtime, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(recovery, "time", SimpleNamespace(time=lambda: clock[0]))
    message = {"from": CONVERSATION, "message_id": "invalid-isolated", "text": "trip question"}
    model = Mock(return_value={**_understood("question", "Invalid"), "fields": ["wrong type"]})
    first = recovery.generate(message, "en", model)
    assert first["generation_failure"]["retry_at"] == 1005
    recovery.notice_sent(first["generation_failure"])
    clock[0] = 1001
    blocked = recovery.generate(message, "en", model)
    assert blocked["reply"] == "" and model.call_count == 1
    other = Mock(return_value=_understood("question", "Other guest's answer"))
    assert recovery.generate({**message, "from": "other-guest"}, "en", other)["reply"] == "Other guest's answer"
    assert other.call_count == 1
    assert _rows("SELECT COUNT(*) FROM mermaid_model_circuit") == [(0,)]
    assert _rows("SELECT COUNT(*) FROM pending_notifications") == [(0,)]
    clock[0] = 1005
    model.return_value = _understood("question", "Recovered answer")
    assert recovery.generate(message, "en", model)["reply"] == "Recovered answer"
    assert recovery.generate(message, "en", model)["reply"] == "Recovered answer"
    assert model.call_count == 2


def test_invalid_response_does_not_block_fresh_message_from_same_guest(review_runtime, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(recovery, "time", SimpleNamespace(time=lambda: clock[0]))
    message = {"from": CONVERSATION, "message_id": "old-invalid", "text": "trip question"}
    recovery.generate(message, "en", lambda: {**_understood("question", "Invalid"), "fields": None})
    clock[0] = 1001
    model = Mock(return_value=_understood("question", "Fresh answer"))
    assert recovery.generate({**message, "message_id": "fresh-valid"}, "en", model)["reply"] == "Fresh answer"
    assert model.call_count == 1
    assert _rows("SELECT status FROM mermaid_model_events WHERE message_id='old-invalid'") == [("superseded",)]


def test_invalid_response_probe_clears_own_old_provider_outage(review_runtime, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(recovery, "time", SimpleNamespace(time=lambda: clock[0]))
    message = {"from": CONVERSATION, "message_id": "outage", "text": "trip question"}
    recovery.generate(message, "en", Mock(side_effect=TimeoutError()))
    clock[0] = 1005
    result = recovery.generate(message, "en", lambda: {**_understood("question", "Invalid"), "fields": None})
    assert result["generation_failure"]["kind"] == "invalid_response"
    assert result["generation_failure"]["retry_at"] == 1015
    assert _rows("SELECT COUNT(*) FROM mermaid_model_circuit") == [(0,)]
    assert _rows("SELECT status FROM pending_notifications") == [("resolved",)]
    model = Mock(return_value=_understood("question", "Healthy answer"))
    assert recovery.generate({**message, "from": "healthy-other"}, "en", model)["reply"] == "Healthy answer"
    assert model.call_count == 1


def test_invalid_response_probe_does_not_clear_concurrent_later_provider_failure(review_runtime, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(recovery, "time", SimpleNamespace(time=lambda: clock[0]))
    started, release = Event(), Event()
    message = {"from": CONVERSATION, "message_id": "slow", "text": "trip question"}
    def slow_failure():
        started.set()
        assert release.wait(3)
        return {"generation_failed": True, "model_error": {"kind": "billing", "retryable": False}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(recovery.generate, message, "en", slow_failure)
        assert started.wait(3)
        clock[0] = 1001
        recovery.generate({**message, "message_id": "outage"}, "en", Mock(side_effect=TimeoutError()))
        clock[0] = 1006
        def invalid_probe():
            clock[0] = 1007
            release.set()
            assert slow.result(timeout=3)["generation_failure"]["kind"] == "billing"
            return {**_understood("question", "Invalid"), "fields": None}
        result = recovery.generate({**message, "message_id": "probe"}, "en", invalid_probe)
    assert result["generation_failure"]["kind"] == "invalid_response"
    assert _rows("SELECT error_kind,failed_at,blocked_until FROM mermaid_model_circuit") == [("billing", 1007.0, 1907.0)]
    assert _rows("SELECT status FROM pending_notifications") == [("pending",)]
    assert "billing" in _rows("SELECT body FROM pending_notifications")[0][0]
