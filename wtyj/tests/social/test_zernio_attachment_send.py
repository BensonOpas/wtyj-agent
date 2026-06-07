"""Tests for customer-facing Zernio attachment sends."""

from agents.social import zernio_dm_client


class _Resp:
    status_code = 200
    text = '{"ok": true}'


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
