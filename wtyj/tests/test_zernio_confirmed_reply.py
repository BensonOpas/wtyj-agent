"""Provider-confirmed Zernio replies for the operator Inbox."""

from datetime import datetime, timedelta, timezone

import pytest

from agents.social import zernio_dm_client as client


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _incoming(hours_ago=1):
    return {
        "id": "incoming-1",
        "direction": "incoming",
        "createdAt": (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).isoformat(),
        "status": "delivered",
        "message": "hola",
    }


def test_automation_scope_rechecks_after_provider_reads_and_does_not_leak(monkeypatch):
    from shared import tenant_guard

    monkeypatch.setattr(tenant_guard, "is_account_allowed", lambda *_a, **_kw: True)
    permitted = {"value": True}
    responses = [
        FakeResponse(200, {"data": {"platform": "whatsapp"}}),
        FakeResponse(200, {"messages": [_incoming()]}),
    ]
    posts = []

    def read_then_take_over(*_args, **_kwargs):
        response = responses.pop(0)
        if not responses:
            permitted["value"] = False
        return response

    monkeypatch.setattr(client.http_requests, "get", read_then_take_over)
    monkeypatch.setattr(client.http_requests, "post", lambda *_a, **_kw: posts.append(True))
    with client.provider_mutation_scope(lambda: permitted["value"]):
        assert client._confirmed_text_reply("conv-1", "account-1", "No stale AI reply", "test-key") is False
    assert posts == []
    # The same worker can service an operator request after the AI scope exits.
    assert client._provider_mutation_account_allowed("account-1", "operator-reply") is True


def test_automation_scope_checks_every_structured_retry(monkeypatch):
    from shared import tenant_guard

    monkeypatch.setattr(tenant_guard, "is_account_allowed", lambda *_a, **_kw: True)
    permitted = {"value": True}
    posts = []

    def first_attempt_loses_claim(*_args, **_kwargs):
        posts.append(True)
        permitted["value"] = False
        return FakeResponse(503, {})

    monkeypatch.setattr(client.http_requests, "post", first_attempt_loses_claim)
    with client.provider_mutation_scope(lambda: permitted["value"]):
        outcome = client._post_recommendation_message(
            "https://zernio.com/conversation/messages", {},
            {"accountId": "account-1", "message": "An image caption"},
        )
    assert outcome == ("rejected", 503, "")
    assert posts == [True]


def test_automation_scope_exception_also_restores_operator_context(monkeypatch):
    from shared import tenant_guard

    monkeypatch.setattr(tenant_guard, "is_account_allowed", lambda *_a, **_kw: True)

    def controls_unavailable():
        raise RuntimeError("unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        with client.provider_mutation_scope(controls_unavailable):
            client._provider_mutation_account_allowed("account-1", "automatic-reply")
    assert client._provider_mutation_account_allowed("account-1", "operator-reply") is True


def test_confirmed_reply_blocks_closed_whatsapp_window(monkeypatch):
    gets = iter([
        FakeResponse(200, {"data": {"platform": "whatsapp"}}),
        FakeResponse(200, {"messages": [_incoming(hours_ago=25)]}),
    ])
    posts = []
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(client.http_requests, "get", lambda *a, **k: next(gets))
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *a, **k: posts.append((a, k)) or FakeResponse(201, {}),
    )

    with pytest.raises(client.WhatsAppWindowClosedError):
        client.send_dm_reply(
            "0123456789abcdef01234567",
            "account-1",
            "test",
            confirm_delivery=True,
        )

    assert posts == []


@pytest.mark.parametrize(
    "detail_payload",
    [
        {"data": {}},
        {"data": {"platform": "instagram"}},
    ],
)
def test_confirmed_reply_requires_verified_whatsapp_platform(
    monkeypatch,
    detail_payload,
):
    gets = []
    posts = []
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *args, **kwargs: (
            gets.append((args, kwargs)) or FakeResponse(200, detail_payload)
        ),
    )
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *args, **kwargs: posts.append((args, kwargs)),
    )

    assert client.send_dm_reply(
        "0123456789abcdef01234567",
        "account-1",
        "must stay inside the WhatsApp window",
        confirm_delivery=True,
    ) is False
    assert len(gets) == 1
    assert posts == []


@pytest.mark.parametrize("provider_payload", [{}, {"data": {}}, {"id": "   "}])
def test_confirmed_reply_no_id_cannot_reconcile_old_identical_text(
    monkeypatch, provider_payload,
):
    old_message = {
        "id": "old-outgoing", "direction": "outgoing", "status": "delivered",
        "message": "Yes", "createdAt": _incoming(hours_ago=2)["createdAt"],
    }
    responses = [
        FakeResponse(200, {"data": {"platform": "whatsapp"}}),
        FakeResponse(200, {"messages": [_incoming(), old_message]}),
    ]
    gets = []
    posts = []

    def fake_get(*_args, **_kwargs):
        gets.append(True)
        return responses[min(len(gets) - 1, 1)]

    monkeypatch.setattr(client.http_requests, "get", fake_get)
    monkeypatch.setattr(
        client.http_requests, "post",
        lambda *_a, **_k: posts.append(True) or FakeResponse(201, provider_payload),
    )
    with pytest.raises(client.ZernioReplyError, match="referencia verificable"):
        client._confirmed_text_reply("conv-1", "account-1", "Yes", "test-key")
    assert len(gets) == 2
    assert posts == [True]


@pytest.mark.parametrize("status", ["", "queued", "pending", "unknown"])
def test_confirmed_reply_id_without_terminal_status_is_not_sent(monkeypatch, status):
    responses = [
        FakeResponse(200, {"data": {"platform": "whatsapp"}}),
        FakeResponse(200, {"messages": [_incoming()]}),
    ]
    polls = FakeResponse(200, {"messages": [{
        "id": "new-outgoing", "direction": "outgoing", "status": status,
    }]})
    monkeypatch.setattr(client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        client.http_requests, "get",
        lambda *_a, **_k: responses.pop(0) if responses else polls,
    )
    monkeypatch.setattr(
        client.http_requests, "post",
        lambda *_a, **_k: FakeResponse(201, {"id": "new-outgoing"}),
    )
    with pytest.raises(client.ZernioReplyError, match="no confirmó"):
        client._confirmed_text_reply("conv-1", "account-1", "Yes", "test-key")


def test_confirmed_reply_requires_provider_success_status(monkeypatch):
    gets = iter([
        FakeResponse(200, {"data": {"platform": "whatsapp"}}),
        FakeResponse(200, {"messages": [_incoming(hours_ago=1)]}),
        FakeResponse(200, {
            "messages": [{
                "id": "message-1",
                "direction": "outgoing",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "status": "delivered",
                "message": "test",
            }]
        }),
    ])
    posts = []
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(client.http_requests, "get", lambda *a, **k: next(gets))
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *a, **k: posts.append((a, k)) or FakeResponse(
            201,
            {"data": {"messageId": "message-1"}},
        ),
    )
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)

    assert client.send_dm_reply(
        "0123456789abcdef01234567",
        "account-1",
        "test",
        confirm_delivery=True,
        idempotency_key="ali-turn-abc123",
    ) is True
    assert posts[0][1]["headers"]["Idempotency-Key"] == "ali-turn-abc123"


def test_confirmed_reply_rechecks_account_after_window_reads_before_post(monkeypatch):
    from shared import tenant_guard

    gets = []
    responses = iter([
        FakeResponse(200, {"data": {"platform": "whatsapp"}}),
        FakeResponse(200, {"messages": [_incoming(hours_ago=1)]}),
    ])
    posts = []
    decisions = iter([True, True, True, True, True, True, False])
    monkeypatch.setenv("LATE_API_KEY", "test-key")

    def fake_get(*args, **kwargs):
        gets.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr(client.http_requests, "get", fake_get)
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *a, **k: posts.append((a, k)) or FakeResponse(201, {}),
    )
    monkeypatch.setattr(
        tenant_guard,
        "is_account_allowed",
        lambda account_id, direction: next(decisions),
    )

    assert client.send_dm_reply(
        "0123456789abcdef01234567",
        "reassigned-account",
        "must not cross tenants",
        confirm_delivery=True,
    ) is False
    assert len(gets) == 2
    assert posts == []


def test_confirmed_reply_rejects_provider_failed_status(monkeypatch):
    gets = iter([
        FakeResponse(200, {"data": {"platform": "whatsapp"}}),
        FakeResponse(200, {"messages": [_incoming(hours_ago=1)]}),
        FakeResponse(200, {
            "messages": [{
                "id": "message-2",
                "direction": "outgoing",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "status": "failed",
                "message": "test",
            }]
        }),
    ])
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(client.http_requests, "get", lambda *a, **k: next(gets))
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *a, **k: FakeResponse(
            201,
            {"data": {"messageId": "message-2"}},
        ),
    )
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)

    with pytest.raises(client.ZernioReplyError):
        client.send_dm_reply(
            "0123456789abcdef01234567",
            "account-1",
            "test",
            confirm_delivery=True,
        )

def test_template_send_requires_meta_approval(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *a, **k: FakeResponse(200, {
            "templates": [{
                "name": "consulta_despertares_seguimiento",
                "language": "es",
                "status": "PENDING",
            }]
        }),
    )
    posts = []
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *a, **k: posts.append((a, k)) or FakeResponse(201, {}),
    )

    with pytest.raises(client.ZernioReplyError, match="pendiente"):
        client.send_dm_template(
            "0123456789abcdef01234567",
            "account-1",
            "consulta_despertares_seguimiento",
        )

    assert posts == []


def test_template_send_confirms_provider_delivery(monkeypatch):
    gets = iter([
        FakeResponse(200, {
            "templates": [{
                "name": "consulta_despertares_seguimiento",
                "language": "es",
                "status": "APPROVED",
            }]
        }),
        FakeResponse(200, {
            "messages": [{
                "id": "template-message-1",
                "direction": "outgoing",
                "status": "delivered",
            }]
        }),
    ])
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(client.http_requests, "get", lambda *a, **k: next(gets))
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *a, **k: FakeResponse(
            201,
            {"data": {"messageId": "template-message-1"}},
        ),
    )
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)

    assert client.send_dm_template(
        "0123456789abcdef01234567",
        "account-1",
        "consulta_despertares_seguimiento",
    ) is True


def test_template_rechecks_account_after_approval_before_post(monkeypatch):
    from shared import tenant_guard

    gets = []
    posts = []
    decisions = iter([True, True, True, True, False])
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *a, **k: (
            gets.append((a, k))
            or FakeResponse(200, {
                "templates": [{
                    "name": "consulta_despertares_seguimiento",
                    "language": "es",
                    "status": "APPROVED",
                }]
            })
        ),
    )
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *a, **k: posts.append((a, k)) or FakeResponse(201, {}),
    )
    monkeypatch.setattr(
        tenant_guard,
        "is_account_allowed",
        lambda account_id, direction: next(decisions),
    )

    assert client.send_dm_template(
        "0123456789abcdef01234567",
        "reassigned-account",
        "consulta_despertares_seguimiento",
    ) is False
    assert len(gets) == 1
    assert posts == []


def test_sdk_text_send_rechecks_after_sender_adapter_guard(monkeypatch):
    from types import SimpleNamespace

    from agents.social.senders.zernio import ZernioSender
    from shared import tenant_guard

    mutations = []
    decisions = iter([True, False])
    fake_client = SimpleNamespace(
        inbox=SimpleNamespace(
            send_inbox_message=lambda **kwargs: mutations.append(kwargs)
        )
    )
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(client, "_get_client", lambda: fake_client)
    monkeypatch.setattr(
        tenant_guard,
        "is_account_allowed",
        lambda account_id, direction: next(decisions),
    )

    assert ZernioSender.send(
        "0123456789abcdef01234567",
        "account-reassigned-after-caller-check",
        "must not cross tenants",
    ) is False
    assert mutations == []


def test_typing_indicator_rechecks_account_before_sdk_mutation(monkeypatch):
    from types import SimpleNamespace

    from shared import tenant_guard

    mutations = []
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(
            send_typing_indicator=lambda **kwargs: mutations.append(kwargs)
        )
    )
    monkeypatch.setattr(client, "_get_client", lambda: fake_client)
    monkeypatch.setattr(
        tenant_guard,
        "is_account_allowed",
        lambda account_id, direction: False,
    )

    assert client.send_typing_indicator(
        "0123456789abcdef01234567",
        "reassigned-account",
    ) is None
    assert mutations == []


def test_account_scoped_history_get_is_blocked_after_reassignment(monkeypatch):
    from shared import tenant_guard

    requests = []
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(
        tenant_guard,
        "is_account_allowed",
        lambda account_id, direction: False,
    )
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *args, **kwargs: requests.append((args, kwargs)),
    )

    result = client.whatsapp_customer_service_window(
        "0123456789abcdef01234567",
        "reassigned-account",
    )

    assert result == {"open": False, "reason": "provider_unavailable"}
    assert requests == []


def test_history_response_is_discarded_if_account_changes_during_get(monkeypatch):
    from shared import tenant_guard

    decisions = iter([True, False])
    requests = []
    monkeypatch.setattr(
        tenant_guard,
        "is_account_allowed",
        lambda account_id, direction: next(decisions),
    )
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *args, **kwargs: (
            requests.append((args, kwargs))
            or FakeResponse(200, {"messages": [_incoming()]})
        ),
    )

    opened, messages = client._recommendation_session_open(
        "https://zernio.com/api/v1/inbox/conversations/conversation-1",
        {"Authorization": "Bearer test-key"},
        "reassigned-during-read",
    )

    assert opened is False
    assert messages == []
    assert len(requests) == 1


def test_visible_foreign_history_cannot_reconcile_or_make_requests(monkeypatch):
    from shared import tenant_guard

    monkeypatch.setattr(
        tenant_guard,
        "is_account_allowed",
        lambda account_id, direction: False,
    )
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("foreign history triggered a GET"),
    )
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *_args, **_kwargs: pytest.fail("foreign history triggered a POST"),
    )

    result = client._send_recommendation_part(
        "https://zernio.com/api/v1/inbox/conversations/conversation-1/messages",
        {"Authorization": "Bearer test-key"},
        "reassigned-account",
        [{
            "id": "foreign-message",
            "direction": "outgoing",
            "status": "delivered",
            "message": "Already sent",
        }],
        body={"accountId": "reassigned-account", "message": "Already sent"},
        idempotency_key="tenant-scoped-part",
        visible_text="Already sent",
    )

    assert result == ("ambiguous", None, False, "")


@pytest.mark.parametrize(
    ("provider_status", "provider_id"),
    [
        ("queued", "queued-message"),
        ("pending", "pending-message"),
        ("", "empty-status-message"),
        ("unexpected", "unknown-status-message"),
        ("delivered", ""),
    ],
)
@pytest.mark.parametrize("require_delivered", [False, True])
def test_existing_visible_history_requires_id_and_terminal_success(
    monkeypatch,
    provider_status,
    provider_id,
    require_delivered,
):
    visible = {
        "direction": "outgoing",
        "status": provider_status,
        "message": "Already sent",
    }
    if provider_id:
        visible["id"] = provider_id
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("nonterminal replay polled history"),
    )
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *_args, **_kwargs: pytest.fail("nonterminal replay was resent"),
    )

    result = client._send_recommendation_part(
        "https://zernio.com/api/v1/inbox/conversations/conversation-1/messages",
        {"Authorization": "Bearer test-key"},
        "account-1",
        [visible],
        body={"accountId": "account-1", "message": "Already sent"},
        idempotency_key="tenant-scoped-part",
        visible_text="Already sent",
        require_delivered=require_delivered,
    )

    assert result[0] == "ambiguous"
    assert result[2] is True


@pytest.mark.parametrize(
    ("provider_status", "provider_id"),
    [
        ("queued", "queued-message"),
        ("pending", "pending-message"),
        ("", "empty-status-message"),
        ("unexpected", "unknown-status-message"),
        ("delivered", ""),
    ],
)
@pytest.mark.parametrize("require_delivered", [False, True])
def test_post_ambiguous_visible_history_requires_id_and_terminal_success(
    monkeypatch,
    provider_status,
    provider_id,
    require_delivered,
):
    visible = {
        "direction": "outgoing",
        "status": provider_status,
        "message": "Possibly sent",
    }
    if provider_id:
        visible["id"] = provider_id
    gets = []
    monkeypatch.setattr(
        client,
        "_post_recommendation_message",
        lambda *_args, **_kwargs: ("ambiguous", 503, ""),
    )
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *args, **kwargs: (
            gets.append((args, kwargs))
            or FakeResponse(200, {"messages": [visible]})
        ),
    )

    result = client._send_recommendation_part(
        "https://zernio.com/api/v1/inbox/conversations/conversation-1/messages",
        {"Authorization": "Bearer test-key"},
        "account-1",
        [],
        body={"accountId": "account-1", "message": "Possibly sent"},
        idempotency_key="tenant-scoped-part",
        visible_text="Possibly sent",
        require_delivered=require_delivered,
    )

    assert result[0] == "ambiguous"
    assert result[1] == 503
    assert result[2] is True
    assert len(gets) == 1


def test_http_success_without_provider_id_requires_history_proof(monkeypatch):
    gets = []
    posts = []
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *args, **kwargs: (
            posts.append((args, kwargs)) or FakeResponse(201, {})
        ),
    )
    monkeypatch.setattr(
        client.http_requests,
        "get",
        lambda *args, **kwargs: (
            gets.append((args, kwargs)) or FakeResponse(200, {"messages": []})
        ),
    )

    result = client._send_recommendation_part(
        "https://zernio.com/api/v1/inbox/conversations/conversation-1/messages",
        {"Authorization": "Bearer test-key"},
        "account-1",
        [],
        body={"accountId": "account-1", "message": "Possibly sent"},
        idempotency_key="tenant-scoped-part",
        visible_text="Possibly sent",
    )

    assert result == ("ambiguous", 201, False, "")
    assert len(posts) == 1
    assert len(gets) == 1
