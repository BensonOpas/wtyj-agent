"""Brief 290: provider-confirmed Ali post-quote WhatsApp actions."""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agents.social import zernio_dm_client


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _incoming(hours_ago=1):
    return {
        "direction": "incoming",
        "createdAt": (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).isoformat(),
    }


def _actions():
    return {
        "state_hash": "a" * 64,
        "idempotency_key": "ali-post-quote-" + "a" * 64,
        "text": "Your official quote is ready. What would you like to do?",
        "buttons": [
            {
                "type": "postback",
                "title": "Reserve This Car",
                "payload": "ali_post_quote:v1:reserve:signed-token",
            },
            {
                "type": "postback",
                "title": "Change Something",
                "payload": "ali_post_quote:v1:change:signed-token",
            },
            {
                "type": "postback",
                "title": "Ask A Question",
                "payload": "ali_post_quote:v1:question:signed-token",
            },
        ],
    }


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(zernio_dm_client.time, "sleep", lambda _seconds: None)


def test_post_quote_actions_send_three_buttons_and_require_provider_success(
    monkeypatch,
):
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{
            "id": "provider-action-1",
            "direction": "outgoing",
            "status": "delivered",
        }]}),
    ])
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: next(gets),
    )

    def fake_post(url, headers, json, timeout):
        posts.append({
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        })
        return _Response(201, {"data": {"id": "provider-action-1"}})

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)
    actions = _actions()

    result = zernio_dm_client.send_dm_post_quote_actions(
        "conversation/1", "account-1", actions,
    )

    assert result == {
        "success": True,
        "delivery": "interactive",
        "provider_message_ids": ["provider-action-1"],
    }
    assert len(posts) == 1
    assert posts[0]["url"].endswith("/conversations/conversation/1/messages")
    assert posts[0]["headers"]["Idempotency-Key"] == (
        f"{actions['idempotency_key']}-interactive"
    )
    assert posts[0]["json"] == {
        "accountId": "account-1",
        "message": actions["text"],
        "buttons": actions["buttons"],
    }


def test_post_quote_actions_reconcile_delivered_replay_without_duplicate(
    monkeypatch,
):
    actions = _actions()
    existing = {
        "id": "provider-existing",
        "direction": "outgoing",
        "deliveryStatus": "read",
        "message": actions["text"],
    }
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: _Response(
            200, {"messages": [existing, _incoming()]},
        ),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: posts.append(True),
    )

    result = zernio_dm_client.send_dm_post_quote_actions(
        "conversation-1", "account-1", actions,
    )

    assert result == {
        "success": True,
        "delivery": "interactive",
        "provider_message_ids": ["provider-existing"],
    }
    assert posts == []


@pytest.mark.parametrize(
    "history_response",
    [
        _Response(503, {}),
        _Response(200, {"messages": []}),
        _Response(200, {"messages": [_incoming(hours_ago=25)]}),
    ],
)
def test_post_quote_actions_fail_closed_when_session_is_not_proven_open(
    monkeypatch,
    history_response,
):
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: history_response,
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: posts.append(True),
    )

    result = zernio_dm_client.send_dm_post_quote_actions(
        "conversation-1", "account-1", _actions(),
    )

    assert result == {"success": False, "delivery": "window_closed"}
    assert posts == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda actions: actions.update(state_hash="not-a-hash"),
        lambda actions: actions["buttons"][0].update(title="Book now"),
        lambda actions: actions["buttons"][1].update(payload="unsigned"),
        lambda actions: actions["buttons"].pop(),
    ],
)
def test_post_quote_actions_reject_invalid_controls_without_network(
    monkeypatch,
    mutate,
):
    actions = _actions()
    mutate(actions)
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("invalid control made a GET"),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: pytest.fail("invalid control made a POST"),
    )

    assert zernio_dm_client.send_dm_post_quote_actions(
        "conversation-1", "account-1", actions,
    ) == {"success": False, "delivery": "invalid"}


def test_post_quote_actions_do_not_treat_http_success_as_delivery(monkeypatch):
    actions = _actions()
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [_incoming()]}),
    ])
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: next(gets),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: _Response(201, {}),
    )

    result = zernio_dm_client.send_dm_post_quote_actions(
        "conversation-1", "account-1", actions,
    )

    assert result == {"success": False, "delivery": "ambiguous"}


def test_post_quote_actions_report_terminal_provider_failure(monkeypatch):
    gets = iter([
        _Response(200, {"messages": [_incoming()]}),
        _Response(200, {"messages": [{
            "id": "provider-action-failed",
            "direction": "outgoing",
            "status": "failed",
        }]}),
        _Response(200, {"messages": [{
            "id": "provider-action-failed",
            "direction": "outgoing",
            "status": "failed",
            "message": _actions()["text"],
        }, _incoming()]}),
    ])
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: next(gets),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: _Response(
            201, {"data": {"id": "provider-action-failed"}},
        ),
    )

    result = zernio_dm_client.send_dm_post_quote_actions(
        "conversation-1", "account-1", _actions(),
    )

    assert result == {"success": False, "delivery": "failed"}
