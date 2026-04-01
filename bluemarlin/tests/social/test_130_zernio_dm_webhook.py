# test_130_zernio_dm_webhook.py
import sys, os, hashlib, hmac, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test-secret-key-abc123")

from agents.social.zernio_dm_client import verify_webhook_signature, parse_zernio_webhook
from shared import state_registry


def _make_ig_payload(text="Hello there", conv_id="conv_ig_001", msg_id="msg_001"):
    return {
        "event": "message.received",
        "timestamp": "2026-04-01T15:30:00Z",
        "data": {
            "id": msg_id,
            "text": text,
            "conversationId": conv_id,
            "platform": "instagram",
            "sender": {"id": "user_789", "name": "John Smith"},
            "accountId": "69b8689d6cb7b8cf4c7846ff",
        }
    }


def _make_fb_payload(text="Hi from Facebook", conv_id="conv_fb_001", msg_id="msg_fb_001"):
    return {
        "event": "message.received",
        "timestamp": "2026-04-01T15:30:00Z",
        "data": {
            "id": msg_id,
            "text": text,
            "conversationId": conv_id,
            "platform": "facebook",
            "sender": {"id": "user_456", "name": "Jane Doe"},
            "accountId": "69bb24a66cb7b8cf4c8074aa",
        }
    }


# --- Test 1: HMAC verification with correct signature ---
def test_verify_signature_valid():
    secret = "test-secret-key-abc123"
    os.environ["ZERNIO_WEBHOOK_SECRET"] = secret
    payload = b'{"event": "message.received"}'
    expected_sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(payload, expected_sig) is True


# --- Test 2: HMAC verification with wrong signature ---
def test_verify_signature_invalid():
    os.environ["ZERNIO_WEBHOOK_SECRET"] = "test-secret-key-abc123"
    payload = b'{"event": "message.received"}'
    assert verify_webhook_signature(payload, "deadbeef0000") is False


# --- Test 3: HMAC verification with missing secret ---
def test_verify_signature_missing_secret():
    old = os.environ.pop("ZERNIO_WEBHOOK_SECRET", None)
    try:
        payload = b'{"event": "message.received"}'
        assert verify_webhook_signature(payload, "anything") is False
    finally:
        if old:
            os.environ["ZERNIO_WEBHOOK_SECRET"] = old


# --- Test 4: Parse Instagram DM webhook ---
def test_parse_webhook_message_received():
    payload = _make_ig_payload()
    result = parse_zernio_webhook(payload)
    assert result is not None
    assert result["conversation_id"] == "conv_ig_001"
    assert result["platform"] == "instagram"
    assert result["channel"] == "instagram_dm"
    assert result["sender_name"] == "John Smith"
    assert result["text"] == "Hello there"
    assert result["message_id"] == "msg_001"
    assert result["account_id"] == "69b8689d6cb7b8cf4c7846ff"


# --- Test 5: Parse Facebook DM webhook ---
def test_parse_webhook_facebook_message():
    payload = _make_fb_payload()
    result = parse_zernio_webhook(payload)
    assert result is not None
    assert result["conversation_id"] == "conv_fb_001"
    assert result["platform"] == "facebook"
    assert result["channel"] == "facebook_dm"
    assert result["sender_name"] == "Jane Doe"
    assert result["text"] == "Hi from Facebook"


# --- Test 6: Non-message event returns None ---
def test_parse_webhook_non_message_event():
    payload = {"event": "post.published", "data": {"id": "post_1"}}
    assert parse_zernio_webhook(payload) is None

    payload2 = {"event": "comment.received", "data": {"id": "c1"}}
    assert parse_zernio_webhook(payload2) is None


# --- Test 7: Missing conversation ID returns None ---
def test_parse_webhook_missing_ids():
    payload = {
        "event": "message.received",
        "data": {
            "id": "msg_1",
            "text": "hello",
            # no conversationId
            "platform": "instagram",
        }
    }
    assert parse_zernio_webhook(payload) is None

    # Missing message ID
    payload2 = {
        "event": "message.received",
        "data": {
            "conversationId": "conv_1",
            "text": "hello",
            # no id
            "platform": "instagram",
        }
    }
    assert parse_zernio_webhook(payload2) is None


# --- Test 8: Empty text returns dict (parser doesn't reject, event handler does) ---
def test_parse_webhook_no_text():
    payload = {
        "event": "message.received",
        "data": {
            "id": "msg_notext",
            "text": "",
            "conversationId": "conv_notext",
            "platform": "instagram",
            "sender": {"id": "u1", "name": "NoText User"},
            "accountId": "acc1",
        }
    }
    result = parse_zernio_webhook(payload)
    assert result is not None
    assert result["text"] == ""
    assert result["conversation_id"] == "conv_notext"


# --- Test 9: dm_store_message + dm_get_history ---
def test_dm_store_and_get_history():
    conv = "test_conv_130_store"
    # Clean up
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv,))
    conn.commit()
    conn.close()

    state_registry.dm_store_message(conv, "instagram_dm", "user", "Hi from IG", "Alice")
    state_registry.dm_store_message(conv, "instagram_dm", "assistant", "Hello Alice!")

    history = state_registry.dm_get_history(conv, "instagram_dm")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["text"] == "Hi from IG"
    assert history[1]["role"] == "assistant"
    assert history[1]["text"] == "Hello Alice!"

    # Clean up
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv,))
    conn.commit()
    conn.close()


# --- Test 10: DM history doesn't leak WhatsApp messages ---
def test_dm_history_does_not_leak_whatsapp():
    phone = "test_130_leak_check"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

    # Store a WhatsApp message (default channel)
    state_registry.wa_store_message(phone, "user", "WhatsApp msg")
    # Store a DM message with same phone/conv ID
    state_registry.dm_store_message(phone, "instagram_dm", "user", "IG DM msg", "Bob")

    # dm_get_history should only return the DM
    dm_history = state_registry.dm_get_history(phone, "instagram_dm")
    assert len(dm_history) == 1
    assert dm_history[0]["text"] == "IG DM msg"

    # wa_get_history should return both (it doesn't filter by channel)
    wa_history = state_registry.wa_get_history(phone)
    assert len(wa_history) == 2

    # Clean up
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 11: Existing WA functions still work after migration ---
def test_existing_wa_functions_still_work():
    phone = "test_130_wa_compat"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

    state_registry.wa_store_message(phone, "user", "Test WA message")
    state_registry.wa_store_message(phone, "assistant", "Reply")

    history = state_registry.wa_get_history(phone)
    assert len(history) == 2
    assert history[0]["text"] == "Test WA message"
    assert history[1]["text"] == "Reply"

    full = state_registry.wa_get_full_history(phone)
    assert len(full) == 2

    # Clean up
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 12b: Real Zernio payload structure (account at top level, not in message) ---
def test_parse_real_zernio_payload():
    """Test with actual Zernio webhook payload structure discovered in production."""
    payload = {
        "id": "1d28c779-c1f4-40bf-932e-a0906521a272",
        "event": "message.received",
        "message": {
            "id": "69cd4ef83e56aceadd9ffcd6",
            "conversationId": "69cd4ef86ff501fad9ed38a6",
            "platform": "instagram",
            "text": "hello",
            "sender": {
                "id": "883716081391205",
                "name": "calvin",
                "username": "calvinsousy",
            },
            "sentAt": "2026-04-01T16:59:34.071Z",
        },
        "account": {
            "id": "69b8689d6cb7b8cf4c7846ff",
            "platform": "instagram",
            "username": "bluemarlincharters",
        },
        "timestamp": "2026-04-01T16:59:36.461Z",
    }
    result = parse_zernio_webhook(payload)
    assert result is not None
    assert result["conversation_id"] == "69cd4ef86ff501fad9ed38a6"
    assert result["text"] == "hello"
    assert result["sender_name"] == "calvin"
    assert result["account_id"] == "69b8689d6cb7b8cf4c7846ff"
    assert result["channel"] == "instagram_dm"
    assert result["platform"] == "instagram"


# --- Test 12: Dedup with Zernio message ID ---
def test_dedup_zernio_message():
    msg_id = "zernio_dedup_test_130"
    # Clean up
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", (msg_id,))
    conn.commit()
    conn.close()

    assert state_registry.wa_has_been_processed(msg_id) is False
    state_registry.wa_mark_as_processed(msg_id)
    assert state_registry.wa_has_been_processed(msg_id) is True

    # Clean up
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", (msg_id,))
    conn.commit()
    conn.close()
