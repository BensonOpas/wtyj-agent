"""Tests for customer-facing Zernio attachment sends."""

from datetime import datetime, timedelta, timezone

from agents.social import zernio_dm_client


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.text = '{"ok": true}'

    def json(self):
        return self.payload


def _incoming(hours_ago=1):
    return {
        "direction": "incoming",
        "createdAt": (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).isoformat(),
    }


def test_send_dm_reply_with_attachment_posts_zernio_payload(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        })
        return _Resp()

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)

    ok = zernio_dm_client.send_dm_reply(
        "conv_123",
        "account_123",
        "Here is the cupcake photo.",
        attachment_url="https://api.unboks.org/media/photo.jpg",
        attachment_type="image",
    )

    assert ok is True
    assert calls == [{
        "url": "https://zernio.com/api/v1/inbox/conversations/conv_123/messages",
        "headers": {
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
        "json": {
            "accountId": "account_123",
            "message": "Here is the cupcake photo.",
            "attachmentUrl": "https://api.unboks.org/media/photo.jpg",
            "attachmentType": "image",
        },
        "timeout": 15,
    }]


def test_send_dm_reply_with_attachment_rejects_invalid_attachment_type(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")

    ok = zernio_dm_client.send_dm_reply(
        "conv_123",
        "account_123",
        "bad",
        attachment_url="https://api.unboks.org/media/photo.jpg",
        attachment_type="exe",
    )

    assert ok is False


def test_whatsapp_file_attachment_includes_recipient_visible_name(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        return _Resp()

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)

    ok = zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Your quote is ready.",
        "https://api.unboks.org/api/public/ali-quote/id?signature=safe",
        attachment_type="file",
        attachment_name="Ali-Car-Rental-Quote-Calvin-2026-08-25-4C7CC225.pdf",
    )

    assert ok is True
    assert calls[0]["attachmentName"] == (
        "Ali-Car-Rental-Quote-Calvin-2026-08-25-4C7CC225.pdf"
    )


def test_attachment_name_is_omitted_for_non_file_and_legacy_calls(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        return _Resp()

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)

    assert zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Photo", "https://example.test/photo.jpg",
        attachment_type="image", attachment_name="ignored.pdf",
    )
    assert zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Legacy file", "https://example.test/file.pdf",
        attachment_type="file",
    )

    assert "attachmentName" not in calls[0]
    assert "attachmentName" not in calls[1]


def test_idempotent_attachment_requires_terminal_provider_confirmation(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(zernio_dm_client.time, "sleep", lambda _seconds: None)
    gets = iter([
        _Resp(200, {"messages": [_incoming()]}),
        _Resp(200, {"messages": [{
            "id": "quote-pdf-message-1",
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
        posts.append({"headers": headers, "json": json})
        return _Resp(201, {"data": {"id": "quote-pdf-message-1"}})

    monkeypatch.setattr(zernio_dm_client.http_requests, "post", fake_post)

    assert zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Your official quote is ready.",
        "https://api.unboks.org/api/public/ali-quote/quote-1?signature=safe",
        attachment_type="file",
        attachment_name="Ali-Car-Rental-Quote-Calvin.pdf",
        idempotency_key="ali-quote-pdf-quote-1",
    ) is True
    assert len(posts) == 1
    assert posts[0]["headers"]["Idempotency-Key"] == "ali-quote-pdf-quote-1"


def test_idempotent_attachment_reconciles_confirmed_replay_without_post(
    monkeypatch,
):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    attachment_url = (
        "https://api.unboks.org/api/public/ali-quote/quote-1?signature=safe"
    )
    history = [{
        "id": "quote-pdf-existing",
        "direction": "outgoing",
        "deliveryStatus": "read",
        "message": "Your official quote is ready.",
        "attachments": [{"url": attachment_url}],
    }, _incoming()]
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: _Resp(200, {"messages": history}),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmed replay posted a duplicate")
        ),
    )

    assert zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Your official quote is ready.",
        attachment_url,
        attachment_type="file",
        idempotency_key="ali-quote-pdf-quote-1",
    ) is True


def test_idempotent_attachment_does_not_treat_http_2xx_as_delivery(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    gets = iter([
        _Resp(200, {"messages": [_incoming()]}),
        _Resp(200, {"messages": [_incoming()]}),
    ])
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: next(gets),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: _Resp(201, {}),
    )

    assert zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Your official quote is ready.",
        "https://api.unboks.org/api/public/ali-quote/quote-1?signature=safe",
        attachment_type="file",
        idempotency_key="ali-quote-pdf-quote-1",
    ) is False


def test_idempotent_attachment_reconciles_http_2xx_without_message_id(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    attachment_url = (
        "https://api.unboks.org/api/public/ali-quote/quote-1?signature=safe"
    )
    gets = iter([
        _Resp(200, {"messages": [_incoming()]}),
        _Resp(200, {"messages": [{
            "id": "quote-pdf-reconciled",
            "direction": "outgoing",
            "status": "sent",
            "message": "Your official quote is ready.",
            "attachmentUrl": attachment_url,
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
        lambda *_args, **_kwargs: _Resp(201, {}),
    )

    assert zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Your official quote is ready.",
        attachment_url,
        attachment_type="file",
        idempotency_key="ali-quote-pdf-quote-1",
    ) is True


def test_idempotent_attachment_reports_terminal_provider_failure(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(zernio_dm_client.time, "sleep", lambda _seconds: None)
    gets = iter([
        _Resp(200, {"messages": [_incoming()]}),
        _Resp(200, {"messages": [{
            "id": "quote-pdf-failed",
            "direction": "outgoing",
            "status": "failed",
        }]}),
    ])
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: next(gets),
    )
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: _Resp(
            201, {"data": {"id": "quote-pdf-failed"}},
        ),
    )

    assert zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Your official quote is ready.",
        "https://api.unboks.org/api/public/ali-quote/quote-1?signature=safe",
        attachment_type="file",
        idempotency_key="ali-quote-pdf-quote-1",
    ) is False


def test_idempotent_attachment_fails_closed_outside_whatsapp_window(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "get",
        lambda *_args, **_kwargs: _Resp(
            200, {"messages": [_incoming(hours_ago=25)]},
        ),
    )
    posts = []
    monkeypatch.setattr(
        zernio_dm_client.http_requests,
        "post",
        lambda *_args, **_kwargs: posts.append(True),
    )

    assert zernio_dm_client.send_dm_reply_with_attachment(
        "conv_123", "account_123", "Your official quote is ready.",
        "https://api.unboks.org/api/public/ali-quote/quote-1?signature=safe",
        attachment_type="file",
        idempotency_key="ali-quote-pdf-quote-1",
    ) is False
    assert posts == []
