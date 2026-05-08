# test_220_block_conversation.py
# Brief 220: per-conversation runtime block flag. Drop messages BEFORE
# any storage at all 4 ingestion paths (Zernio DM, Zernio WA flush,
# Meta-legacy WA flush, email_poller). Different from Brief 213's
# ai_muted: blocked = "drop entirely, conversation never appears in
# inbox"; ai_muted = "store then skip Marina (operator still sees it)".

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test_secret")

from unittest.mock import patch
from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _wipe_220():
    """Drop test-prefixed conversation_status rows so reruns don't accumulate."""
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id LIKE '220_%'")
    conn.commit()
    conn.close()


# --- Test 1: set_blocked / get_blocked round-trip
def test_set_blocked_get_blocked_round_trip():
    from shared import state_registry
    try:
        _wipe_220()
        # Initial state on a fresh conversation: not blocked
        assert state_registry.get_blocked("220_phone_a") is False
        # Empty/missing id: never blocked
        assert state_registry.get_blocked("") is False

        state_registry.set_blocked("220_phone_a", True, "whatsapp")
        assert state_registry.get_blocked("220_phone_a") is True

        state_registry.set_blocked("220_phone_a", False, "whatsapp")
        assert state_registry.get_blocked("220_phone_a") is False
    finally:
        _wipe_220()


# --- Test 2: list_blocked_conversations returns only blocked rows
def test_list_blocked_conversations_returns_only_blocked():
    from shared import state_registry
    try:
        _wipe_220()
        # 3 blocked
        state_registry.set_blocked("220_blk_a", True, "whatsapp")
        state_registry.set_blocked("220_blk_b", True, "instagram")
        state_registry.set_blocked("220_blk_c", True, "email")
        # 2 unblocked (rows exist but blocked=0)
        state_registry.set_blocked("220_unblk_a", False, "whatsapp")
        state_registry.set_blocked("220_unblk_b", False, "facebook")

        rows = state_registry.list_blocked_conversations()
        # Filter to our test rows only (other tests may have left state)
        ours = [r for r in rows if r["conversationId"].startswith("220_")]
        assert len(ours) == 3
        ids = {r["conversationId"] for r in ours}
        assert ids == {"220_blk_a", "220_blk_b", "220_blk_c"}
        # camelCase keys check
        for r in ours:
            assert "conversationId" in r
            assert "channel" in r
            assert "updatedAt" in r
    finally:
        _wipe_220()


# --- Test 3: POST /block sets the flag
def test_block_endpoint_sets_flag():
    from shared import state_registry
    try:
        _wipe_220()
        token = _login()
        r = client.post(
            "/dashboard/api/messages/conversations/220_endpoint_phone/block",
            headers=_auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["blocked"] is True
        assert body["conversationId"] == "220_endpoint_phone"

        assert state_registry.get_blocked("220_endpoint_phone") is True
    finally:
        _wipe_220()


# --- Test 4: POST /unblock clears the flag
def test_unblock_endpoint_clears_flag():
    from shared import state_registry
    try:
        _wipe_220()
        # Pre-seed blocked
        state_registry.set_blocked("220_unblock_phone", True, "whatsapp")
        assert state_registry.get_blocked("220_unblock_phone") is True

        token = _login()
        r = client.post(
            "/dashboard/api/messages/conversations/220_unblock_phone/unblock",
            headers=_auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["blocked"] is False

        assert state_registry.get_blocked("220_unblock_phone") is False
    finally:
        _wipe_220()


# --- Test 5: Zernio webhook drops blocked conversation BEFORE storage
def test_zernio_webhook_drops_blocked_conversation():
    from shared import state_registry
    from agents.social import webhook_server
    try:
        _wipe_220()
        blocked_conv = "220_zernio_blocked_conv"
        state_registry.set_blocked(blocked_conv, True, "instagram")

        # Mock store calls so we can assert they were NOT called
        with patch.object(state_registry, "wa_store_message") as mock_wa, \
             patch.object(state_registry, "dm_store_message") as mock_dm, \
             patch.object(state_registry, "wa_has_been_processed", return_value=False), \
             patch.object(state_registry, "wa_mark_as_processed"):
            # Mock the Zernio parser to return a blocked-conversation message
            with patch.object(webhook_server, "parse_zernio_webhook") as mock_parse:
                mock_parse.return_value = {
                    "message_id": "test_msg_220_blk",
                    "conversation_id": blocked_conv,
                    "platform": "instagram",
                    "channel": "instagram",
                    "account_id": "test_account",
                    "sender_id": "test_sender",
                    "sender_name": "Test Sender",
                    "text": "this should be dropped",
                }
                # Run the actual ingestion handler
                webhook_server._process_zernio_event({"raw": "payload"})

        # Neither store function was called — the message was dropped
        # at the block check before any storage happened.
        assert mock_wa.call_count == 0
        assert mock_dm.call_count == 0
    finally:
        _wipe_220()


# --- Test 6: GET /settings/blocked-conversations response shape
def test_get_blocked_conversations_returns_response_shape():
    from shared import state_registry
    try:
        _wipe_220()
        state_registry.set_blocked("220_resp_a", True, "whatsapp")
        state_registry.set_blocked("220_resp_b", True, "email")

        token = _login()
        r = client.get(
            "/dashboard/api/settings/blocked-conversations",
            headers=_auth(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "conversations" in body
        ours = [c for c in body["conversations"]
                if c.get("conversationId", "").startswith("220_")]
        assert len(ours) == 2
        for row in ours:
            assert isinstance(row.get("conversationId"), str)
            assert isinstance(row.get("channel"), str)
            assert isinstance(row.get("updatedAt"), str)
    finally:
        _wipe_220()
