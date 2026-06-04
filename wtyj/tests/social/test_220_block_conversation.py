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
             patch.object(state_registry, "wa_mark_as_processed"), \
             patch.object(state_registry, "match_ignored_contact", return_value=None):
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


def test_zernio_webhook_ignored_contact_stops_before_storage_and_agent():
    from shared import state_registry
    from agents.social import webhook_server
    try:
        _wipe_220()
        ignored_conv = "220_zernio_ignored_conv"
        ignored_sender = "59996881585"
        ignored = {
            "id": 72,
            "name": "Owner",
            "phone_original": "+599 9 688 1585",
            "phone_normalized": ignored_sender,
            "email_original": "",
            "email_normalized": "",
            "channel": "whatsapp",
            "external_sender_id": "",
            "label": "Owner",
            "note": "",
        }

        with patch.object(state_registry, "wa_store_message") as mock_wa, \
             patch.object(state_registry, "dm_store_message") as mock_dm, \
             patch.object(state_registry, "wa_has_been_processed", return_value=False), \
             patch.object(state_registry, "wa_mark_as_processed") as mock_processed, \
             patch.object(state_registry, "match_ignored_contact", return_value=ignored) as mock_match, \
             patch.object(state_registry, "record_ignored_contact_event") as mock_event, \
             patch.object(webhook_server, "handle_incoming_whatsapp_message") as mock_agent, \
             patch.object(webhook_server, "send_text_message") as mock_send, \
             patch.object(webhook_server, "send_typing_indicator") as mock_typing, \
             patch.object(webhook_server, "_buffer_message") as mock_buffer, \
             patch.object(webhook_server, "parse_zernio_webhook") as mock_parse:
            mock_parse.return_value = {
                "message_id": "test_msg_220_ignored",
                "conversation_id": ignored_conv,
                "platform": "whatsapp",
                "channel": "whatsapp",
                "account_id": "test_account",
                "sender_id": ignored_sender,
                "sender_name": "Test Sender",
                "text": "this should be fully ignored",
            }
            webhook_server._process_zernio_event({"raw": "payload"})

        mock_processed.assert_called_once_with("test_msg_220_ignored")
        assert mock_match.call_count >= 1
        mock_event.assert_called_once()
        assert mock_wa.call_count == 0
        assert mock_dm.call_count == 0
        assert mock_agent.call_count == 0
        assert mock_send.call_count == 0
        assert mock_typing.call_count == 0
        assert mock_buffer.call_count == 0
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



# --- Brief 261: close 4 Brief 220 gaps (reason, blocked_by, inbox filtering, /blocked-senders alias) ---

def _wipe_261():
    """Drop 261_-prefixed conversation_status rows so reruns don't accumulate."""
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id LIKE '261_%'")
    conn.commit()
    conn.close()


def test_brief_261_set_blocked_persists_reason_and_blocked_by():
    """Brief 261 gap 2+3: set_blocked() now accepts and persists reason +
    blocked_by audit fields. list_blocked_conversations() surfaces them
    via the new camelCase keys reason + blockedBy (alongside the existing
    Brief 220 camelCase keys conversationId / channel / updatedAt)."""
    from shared import state_registry
    try:
        _wipe_261()
        state_registry.set_blocked("261_audit_test", True,
                                    channel="email",
                                    reason="spam",
                                    blocked_by="calvin")
        rows = state_registry.list_blocked_conversations()
        ours = [r for r in rows if r["conversationId"] == "261_audit_test"]
        assert len(ours) == 1, f"expected 1 row, got {len(ours)}"
        row = ours[0]
        assert row["reason"] == "spam"
        assert row["blockedBy"] == "calvin"
        # Brief 220 camelCase fields preserved unchanged
        assert row["channel"] == "email"
        assert isinstance(row["updatedAt"], str)
    finally:
        _wipe_261()


def test_brief_261_unblock_clears_reason_and_blocked_by():
    """Brief 261: unblock clears reason + blocked_by so a future re-block
    doesn't inherit stale audit context."""
    from shared import state_registry
    try:
        _wipe_261()
        state_registry.set_blocked("261_clear_test", True,
                                    channel="email",
                                    reason="abusive",
                                    blocked_by="op1")
        # Verify set
        rows = state_registry.list_blocked_conversations()
        assert any(r["conversationId"] == "261_clear_test" for r in rows)
        # Unblock
        state_registry.set_blocked("261_clear_test", False)
        # Verify gone from blocked list
        rows = state_registry.list_blocked_conversations()
        assert not any(r["conversationId"] == "261_clear_test" for r in rows)
        # Verify audit fields cleared on the row (direct SQL inspection)
        conn = state_registry._get_conn()
        sql_row = conn.execute(
            "SELECT reason, blocked_by FROM conversation_status "
            "WHERE conversation_id = ?", ("261_clear_test",)).fetchone()
        conn.close()
        assert sql_row[0] == "", f"reason should be empty, got {sql_row[0]!r}"
        assert sql_row[1] == "", f"blocked_by should be empty, got {sql_row[1]!r}"
    finally:
        _wipe_261()


def test_brief_261_wa_list_conversations_filters_blocked():
    """Brief 261 gap 1: wa_list_conversations() must exclude blocked
    conversations from the active inbox list."""
    from shared import state_registry
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    test_phone = "261_wa_block_test"
    conn = state_registry._get_conn()
    # Seed a WA thread row
    conn.execute(
        "INSERT INTO whatsapp_threads "
        "(phone, role, text, sender_name, channel, created_at) "
        "VALUES (?, 'user', ?, ?, 'whatsapp', ?)",
        (test_phone, "hi from blocked", "Test", now_iso))
    conn.commit()
    conn.close()
    try:
        _wipe_261()
        # Pre-block: appears
        listings = state_registry.wa_list_conversations()
        phones = [c["phone"] for c in listings]
        assert test_phone in phones, f"WA conv should appear before block; got {phones[:5]}"
        # Block
        state_registry.set_blocked(test_phone, True, channel="whatsapp",
                                    reason="spam", blocked_by="op")
        # Post-block: filtered out
        listings = state_registry.wa_list_conversations()
        phones = [c["phone"] for c in listings]
        assert test_phone not in phones, f"WA conv should be filtered when blocked"
        # Unblock: reappears
        state_registry.set_blocked(test_phone, False)
        listings = state_registry.wa_list_conversations()
        phones = [c["phone"] for c in listings]
        assert test_phone in phones, "WA conv should reappear after unblock"
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (test_phone,))
        conn.commit()
        conn.close()
        _wipe_261()


def test_brief_261_email_list_conversations_filters_blocked(monkeypatch, tmp_path):
    """Brief 261 gap 1: email_list_conversations() must exclude threads
    whose customer email is blocked. The check extracts the email from
    the thread_key shape `subj:<email>:<normalized_subject>` and calls
    get_blocked(email)."""
    import json
    from shared import state_registry
    from datetime import datetime, timezone
    # Seed tmp email_thread_state.json with one thread
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps({
        "threads": {
            "subj:spam_sender_261@example.com:annoying": {
                "fields": {"customer_name": "Spammer"},
                "flags": {},
                "messages": [
                    {"role": "customer", "body": "buy now!",
                     "ts": datetime.now(timezone.utc).isoformat()}
                ],
            }
        },
        "message_id_index": {},
        "sender_rates": {},
    }))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))
    try:
        _wipe_261()
        # Pre-block: appears
        listings = state_registry.email_list_conversations()
        keys = [c["phone"] for c in listings]
        assert any("spam_sender_261@example.com" in k for k in keys), (
            f"email thread should appear before block; got {keys}")
        # Block the email sender
        state_registry.set_blocked("spam_sender_261@example.com", True,
                                    channel="email", reason="spam")
        # Post-block: filtered out
        listings = state_registry.email_list_conversations()
        keys = [c["phone"] for c in listings]
        assert not any("spam_sender_261@example.com" in k for k in keys), (
            f"email thread should be filtered when blocked; got {keys}")
        # Unblock: reappears
        state_registry.set_blocked("spam_sender_261@example.com", False)
        listings = state_registry.email_list_conversations()
        keys = [c["phone"] for c in listings]
        assert any("spam_sender_261@example.com" in k for k in keys), (
            f"email thread should reappear after unblock; got {keys}")
    finally:
        _wipe_261()


def test_brief_261_block_endpoint_accepts_reason_and_blocked_by_body():
    """Brief 261 gap 2+3+4: POST /messages/conversations/{id}/block accepts
    optional JSON body with reason + blocked_by. GET /blocked-senders is
    an alias of /settings/blocked-conversations that returns the same
    wrapped envelope `{"conversations": [...]}` with camelCase row keys
    extended by reason + blockedBy."""
    try:
        _wipe_261()
        token = _login()
        # POST with body
        r = client.post(
            "/dashboard/api/messages/conversations/261_endpoint_test/block",
            headers=_auth(token),
            json={"reason": "abusive", "blocked_by": "calvin"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["conversationId"] == "261_endpoint_test"
        assert body["blocked"] is True
        assert body["reason"] == "abusive"
        assert body["blockedBy"] == "calvin"
        # GET /blocked-senders should return the row with the audit fields
        r2 = client.get("/dashboard/api/blocked-senders", headers=_auth(token))
        assert r2.status_code == 200, r2.text
        envelope = r2.json()
        assert "conversations" in envelope, f"expected wrapped envelope, got {envelope}"
        rows = envelope["conversations"]
        ours = [c for c in rows if c["conversationId"] == "261_endpoint_test"]
        assert len(ours) == 1
        assert ours[0]["reason"] == "abusive"
        assert ours[0]["blockedBy"] == "calvin"
        # GET /settings/blocked-conversations should return byte-identical shape
        r3 = client.get(
            "/dashboard/api/settings/blocked-conversations",
            headers=_auth(token))
        assert r3.status_code == 200, r3.text
        assert r3.json() == envelope, (
            "/blocked-senders and /settings/blocked-conversations should "
            "return byte-identical JSON per Brief 261 alias contract")
    finally:
        _wipe_261()
