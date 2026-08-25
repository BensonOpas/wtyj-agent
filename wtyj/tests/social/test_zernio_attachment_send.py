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
