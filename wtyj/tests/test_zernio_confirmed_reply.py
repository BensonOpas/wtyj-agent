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
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(client.http_requests, "get", lambda *a, **k: next(gets))
    monkeypatch.setattr(
        client.http_requests,
        "post",
        lambda *a, **k: FakeResponse(
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
    ) is True


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
