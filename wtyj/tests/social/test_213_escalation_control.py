# test_213_escalation_control.py
# Brief 213: escalation mode + takeover/handback + ai_muted enforcement.
# This brief touches the customer-message ingestion path on multiple
# channels (DM, Zernio-WhatsApp, Meta-WhatsApp). Test 9 + 10 cover the
# webhook ingestion paths; Test 11 covers the email_poller helper.

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_escalation(channel, customer_id, mode=None):
    from shared import state_registry
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel=channel,
        customer_id=customer_id, customer_name="Test",
        subject="[ESCALATION] test213", body="test body")
    if mode:
        state_registry.set_escalation_mode(esc_id, mode)
    return esc_id


def _cleanup(esc_id, customer_id):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (esc_id,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (customer_id,))
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (customer_id,))
    conn.commit()
    conn.close()


# --- Test 1: POST /mode sets field + returns updated row
def test_post_mode_sets_field_and_returns_updated_row():
    customer_id = "213_mode_phone"
    esc_id = _seed_escalation("whatsapp", customer_id)
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/mode",
                     json={"mode": "hard"}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "hard"
    # Verify DB row reflects update
    from shared import state_registry
    rows = state_registry.get_all_escalations()
    matched = next(e for e in rows if e["id"] == esc_id)
    assert matched["mode"] == "hard"
    _cleanup(esc_id, customer_id)


# --- Test 2: POST /mode rejects invalid value
def test_post_mode_rejects_invalid_value():
    customer_id = "213_invalid_mode_phone"
    esc_id = _seed_escalation("whatsapp", customer_id)
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/mode",
                     json={"mode": "medium"}, headers=_auth(token))
    assert r.status_code == 400
    assert "medium" in r.json()["detail"]
    _cleanup(esc_id, customer_id)


# --- Test 3: POST /takeover sets hard + mutes + preserves status
def test_post_takeover_sets_hard_and_mutes_and_preserves_status():
    from shared import state_registry
    customer_id = "213_takeover_phone"
    esc_id = _seed_escalation("whatsapp", customer_id)
    # Confirm starting state: status="open" (set by create_pending_notification)
    assert state_registry.get_conversation_status(customer_id) == "open"

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/takeover",
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "hard", f"mode in response: {body}"

    # Storage assertions
    assert state_registry.get_ai_muted(customer_id) is True
    # Status invariant: takeover MUST NOT clobber the "open" status
    assert state_registry.get_conversation_status(customer_id) == "open", \
        "set_ai_muted must preserve existing status"
    # human_takeover_at must be populated
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT human_takeover_at FROM conversation_status WHERE conversation_id = ?",
        (customer_id,)).fetchone()
    conn.close()
    assert row and row[0], f"human_takeover_at not set, got: {row}"

    _cleanup(esc_id, customer_id)


# --- Test 4: POST /handback clears mute + sets soft
def test_post_handback_clears_mute_and_sets_soft():
    from shared import state_registry
    customer_id = "213_handback_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="hard")
    state_registry.set_ai_muted(customer_id, True, "whatsapp")
    assert state_registry.get_ai_muted(customer_id) is True

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/handback",
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "soft"
    assert state_registry.get_ai_muted(customer_id) is False
    _cleanup(esc_id, customer_id)


# --- Test 4b: POST /resolve clears mute so agent can resume
def test_post_resolve_clears_ai_mute_and_human_takeover():
    from shared import state_registry
    customer_id = "213_resolve_clears_mute_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="hard")
    state_registry.set_ai_muted(customer_id, True, "whatsapp")
    assert state_registry.get_ai_muted(customer_id) is True

    token = _login()
    r = client.post(
        f"/dashboard/api/escalations/{esc_id}/resolve",
        json={"resolutionNote": "Handled by operator.", "saveAsLearning": False},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert state_registry.get_ai_muted(customer_id) is False
    assert state_registry.get_conversation_status(customer_id) == "resolved"
    assert state_registry.get_human_takeover_at(customer_id) is None
    _cleanup(esc_id, customer_id)


# --- Test 5: GET /escalations filters by mode
def test_get_escalations_filters_by_mode():
    customer_a = "213_filter_phone_a"
    customer_b = "213_filter_phone_b"
    esc_a = _seed_escalation("whatsapp", customer_a, mode="hard")
    esc_b = _seed_escalation("whatsapp", customer_b, mode="soft")

    token = _login()
    r = client.get("/dashboard/api/escalations?mode=hard", headers=_auth(token))
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()]
    assert str(esc_a) in ids
    assert str(esc_b) not in ids
    _cleanup(esc_a, customer_a)
    _cleanup(esc_b, customer_b)


# --- Test 6: GET /escalations response includes mode field
def test_get_escalations_response_includes_mode_field():
    customer_id = "213_field_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="soft")
    token = _login()
    r = client.get("/dashboard/api/escalations", headers=_auth(token))
    matched = next((row for row in r.json() if row["id"] == str(esc_id)), None)
    assert matched is not None
    assert "mode" in matched
    assert matched["mode"] == "soft"
    _cleanup(esc_id, customer_id)


def test_post_unresolve_reopens_resolved_soft_escalation():
    from shared import state_registry
    customer_id = "213_unresolve_soft_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="soft")
    state_registry.update_notification_status(esc_id, "resolved")
    state_registry.resolve_conversation_from_escalation(esc_id)
    assert state_registry.get_conversation_status(customer_id) == "resolved"

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/unresolve",
                    headers=_auth(token))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(esc_id)
    assert body["status"] == "sent"
    assert body["mode"] == "soft"
    assert state_registry.get_conversation_status(customer_id) == "open"
    reopened = next(e for e in state_registry.get_all_escalations()
                    if e["id"] == esc_id)
    assert reopened["status"] == "sent"
    assert reopened["mode"] == "soft"
    _cleanup(esc_id, customer_id)


def test_post_unresolve_reopens_resolved_hard_escalation_in_hard_mode():
    from shared import state_registry
    customer_id = "213_unresolve_hard_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="hard")
    state_registry.update_notification_status(esc_id, "resolved")
    state_registry.resolve_conversation_from_escalation(esc_id)

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/unresolve",
                    headers=_auth(token))

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent"
    assert r.json()["mode"] == "hard"
    assert state_registry.get_conversation_status(customer_id) == "open"
    _cleanup(esc_id, customer_id)


# --- Test 7: Conversation detail returns real escalationMode
def test_conversation_detail_returns_real_escalation_mode():
    customer_id = "213_detail_mode_phone"
    esc_id = _seed_escalation("whatsapp", customer_id, mode="hard")
    token = _login()
    r = client.get(f"/dashboard/api/messages/conversations/{customer_id}",
                    headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["escalationMode"] == "hard"
    _cleanup(esc_id, customer_id)


# --- Test 8: Conversation detail returns real aiMuted
def test_conversation_detail_returns_real_ai_muted():
    from shared import state_registry
    customer_id = "213_detail_muted_phone"
    state_registry.set_ai_muted(customer_id, True, "whatsapp")
    token = _login()
    r = client.get(f"/dashboard/api/messages/conversations/{customer_id}",
                    headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["aiMuted"] is True
    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (customer_id,))
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (customer_id,))
    conn.commit()
    conn.close()


# --- Test 9: DM ingestion (_process_zernio_event IG/FB branch) skips when muted
@patch("agents.social.webhook_server.handle_incoming_dm")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
@patch("agents.social.webhook_server.send_typing_indicator")
@patch("agents.social.webhook_server.parse_zernio_webhook")
def test_dm_ingestion_skips_when_muted(mock_parse, mock_typing, mock_wa_handler, mock_dm_handler):
    from shared import state_registry
    from agents.social.webhook_server import _process_zernio_event

    conv_id = "213_dm_ingest_conv"
    # Pre-clean dedup state from any prior failed run (whatsapp_processed
    # is the dedup table; if test failed before, the row leaks and
    # dedup short-circuits the next run before our mute check fires).
    _conn = state_registry._get_conn()
    _conn.execute("DELETE FROM whatsapp_processed WHERE message_id = 'msg_213_dm_test'")
    _conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv_id,))
    _conn.commit()
    _conn.close()

    state_registry.set_ai_muted(conv_id, True, "instagram")

    mock_parse.return_value = {
        "message_id": "msg_213_dm_test",
        "conversation_id": conv_id,
        "platform": "instagram",
        "channel": "instagram",
        "account_id": "acct_test",
        "sender_id": "sender_test",
        "sender_name": "Test Sender",
        "text": "hello from muted convo",
    }

    _process_zernio_event({"fake": "payload"})

    # Marina handlers must NOT have been called
    mock_dm_handler.assert_not_called()
    mock_wa_handler.assert_not_called()

    # POSITIVE assertion (Brief 213 Step 7 invariant): inbound message
    # MUST be stored so operator sees it in the dashboard.
    history = state_registry.dm_get_history(conv_id, "instagram", limit=10)
    assert any(m.get("text") == "hello from muted convo" and m.get("role") == "user"
               for m in history), \
        f"muted-but-stored invariant broken; history={history}"

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (conv_id,))
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv_id,))
    conn.execute("DELETE FROM whatsapp_processed WHERE message_id = ?", ("msg_213_dm_test",))
    conn.commit()
    conn.close()


# --- Test 10: WhatsApp _flush_buffer skips marina when muted (Zernio path)
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
@patch("agents.social.webhook_server.handle_incoming_dm")
def test_whatsapp_flush_skips_when_muted(mock_dm_handler, mock_wa_handler):
    from shared import state_registry
    from agents.social import webhook_server

    conv_id = "213_wa_flush_conv"
    phone = "+213111000111"
    state_registry.set_ai_muted(conv_id, True, "whatsapp")

    # Pre-populate the message buffer with a single Zernio-WhatsApp message
    final_msg = {
        "text": "hi from muted convo",
        "_zernio_conversation_id": conv_id,
        "_zernio_account_id": "acct_test",
        "_zernio_channel": "whatsapp",
        "_zernio_sender_name": "MutedCustomer",
        "message_id": "msg_213_wa_test",
    }
    with webhook_server._buffer_lock:
        webhook_server._message_buffers[phone] = {
            "messages": [final_msg],
            "timer": None,
        }

    webhook_server._flush_buffer(phone)

    # Marina handlers must NOT have been called
    mock_wa_handler.assert_not_called()
    mock_dm_handler.assert_not_called()

    # POSITIVE assertion (Brief 213 Step 7 invariant): inbound message
    # MUST be stored so operator sees it in the dashboard.
    history = state_registry.dm_get_history(conv_id, "whatsapp", limit=10)
    assert any(m.get("text") == "hi from muted convo" and m.get("role") == "user"
               for m in history), \
        f"muted-but-stored invariant broken; history={history}"

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (conv_id,))
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (conv_id,))
    conn.commit()
    conn.close()


# --- Test 11: email_poller mute helper unit test
def test_email_poller_mute_helper_returns_correct_value():
    from shared import state_registry
    from agents.marina.email_poller import _should_skip_marina_for_mute

    target = "test213-helper@example.com"
    # (a) returns True when set_ai_muted writes True
    state_registry.set_ai_muted(target, True, "whatsapp")
    assert _should_skip_marina_for_mute(target) is True

    # (b) returns False after set_ai_muted writes False
    state_registry.set_ai_muted(target, False, "whatsapp")
    assert _should_skip_marina_for_mute(target) is False

    # (c) returns False for unknown id
    assert _should_skip_marina_for_mute("never-seen@example.com") is False
    assert _should_skip_marina_for_mute("") is False

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (target,))
    conn.commit()
    conn.close()


# ── Brief 246: hard-takeover WhatsApp /reply sends verbatim ─

def test_hard_mode_whatsapp_reply_sends_verbatim_not_through_marina(monkeypatch):
    """Brief 246: when escalation.mode='hard' (set by /takeover), a WhatsApp
    /reply MUST send operator text verbatim via send_whatsapp_message — NOT
    route through marina_agent.process_message which would reformulate or
    refuse abusive text. Mirrors email branch Brief 210 verbatim behavior."""
    from shared import state_registry
    from dashboard import api as dapi

    customer_id = "246_hard_wa_verbatim_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation",
        channel="whatsapp",
        customer_id=customer_id,
        customer_name="Test Customer",
        subject="Marina escalated",
        body="needs help",
        mode="hard",
    )

    sent = {}
    monkeypatch.setattr(dapi, "send_whatsapp_message",
                         lambda phone, text: sent.update(phone=phone, text=text) or True)
    marina_called = {"called": False}
    def fail_if_called(*a, **k):
        marina_called["called"] = True
        return {"reply": "MARINA SHOULD NOT BE CALLED"}
    monkeypatch.setattr(dapi.marina_agent, "process_message", fail_if_called)

    operator_text = "Hi, this is Calvin from Unboks. Quick test reply."
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": operator_text}, headers=_auth(token))

    assert r.status_code == 200, f"reply failed: {r.text}"
    body = r.json()
    assert body["ok"] is True
    assert body["reply"] == operator_text
    assert body.get("role") == "operator"
    assert body.get("channel") == "whatsapp"
    assert sent.get("text") == operator_text, (
        f"send_whatsapp_message was called with {sent.get('text')!r}, "
        f"expected verbatim {operator_text!r}")
    assert marina_called["called"] is False, (
        "marina_agent.process_message MUST NOT be called in hard-mode WhatsApp /reply")


def test_hard_mode_whatsapp_reply_stores_role_operator_not_assistant(monkeypatch):
    """Brief 246: stored conversation trail row uses role='operator' so the
    dashboard does NOT render it as Marina/assistant. Mirrors email branch
    Brief 210 storage behavior."""
    from shared import state_registry
    from dashboard import api as dapi

    customer_id = "246_hard_wa_role_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation",
        channel="whatsapp",
        customer_id=customer_id,
        customer_name="Test Customer",
        subject="Marina escalated",
        body="needs help",
        mode="hard",
    )
    monkeypatch.setattr(dapi, "send_whatsapp_message", lambda p, t: True)

    operator_text = "Operator reply for role storage test."
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": operator_text}, headers=_auth(token))
    assert r.status_code == 200

    history = state_registry.wa_get_history(customer_id, limit=5)
    assert any(m["role"] == "operator" and m["text"] == operator_text
               for m in history), (
        f"expected role='operator' row with verbatim text; history={history}")
    assert not any(m["role"] == "assistant" and m["text"] == operator_text
                   for m in history), (
        f"hard-mode operator text MUST NOT be stored as role='assistant'; "
                   f"history={history}")


def test_hard_mode_whatsapp_reply_can_send_selected_media(monkeypatch):
    """Operator-selected tenant media is resolved to a public provider URL and
    only stored after the provider send confirms success."""
    from shared import state_registry
    from dashboard import api as dapi

    customer_id = "246_hard_wa_media_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation",
        channel="whatsapp",
        customer_id=customer_id,
        customer_name="Test Customer",
        subject="Marina escalated",
        body="needs help",
        mode="hard",
    )
    filename = "photo_246_media_test.jpg"
    media_path = os.path.join(dapi._PHOTOS_DIR, filename)
    with open(media_path, "wb") as fh:
        fh.write(b"\xff\xd8\xff\xd9")
    photo_id = state_registry.save_photo(
        filename=filename,
        original_filename="menu.jpg",
        tags=["Menu photo"],
        service_key="knowledge:products:menu",
        source="knowledge_media",
        source_id="menu",
        file_size=4,
    )

    sent = {}
    def fake_send(phone, text, **kwargs):
        sent.update(phone=phone, text=text, **kwargs)
        return True
    monkeypatch.setattr(dapi, "send_whatsapp_message", fake_send)

    token = _login()
    r = client.post(
        f"/dashboard/api/escalations/{esc_id}/reply",
        json={"message": "Here is the menu.", "mediaId": str(photo_id)},
        headers=_auth(token),
    )

    assert r.status_code == 200, r.text
    assert sent["phone"] == customer_id
    assert sent["text"] == "Here is the menu."
    assert sent["attachment_type"] == "image"
    assert sent["attachment_url"].endswith(f"/dashboard/api/public/media/{filename}")

    state_registry.delete_photo(photo_id)
    try:
        os.remove(media_path)
    except FileNotFoundError:
        pass
    _cleanup(esc_id, customer_id)


def test_hard_mode_whatsapp_media_send_failure_does_not_store_reply(monkeypatch):
    from shared import state_registry
    from dashboard import api as dapi

    customer_id = "246_hard_wa_media_fail_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation",
        channel="whatsapp",
        customer_id=customer_id,
        customer_name="Test Customer",
        subject="Marina escalated",
        body="needs help",
        mode="hard",
    )
    filename = "photo_246_media_fail.jpg"
    media_path = os.path.join(dapi._PHOTOS_DIR, filename)
    with open(media_path, "wb") as fh:
        fh.write(b"\xff\xd8\xff\xd9")
    photo_id = state_registry.save_photo(
        filename=filename,
        original_filename="menu.jpg",
        tags=[],
        service_key="knowledge:products:menu",
        source="knowledge_media",
        source_id="menu",
        file_size=4,
    )
    monkeypatch.setattr(dapi, "send_whatsapp_message", lambda *a, **k: False)

    token = _login()
    r = client.post(
        f"/dashboard/api/escalations/{esc_id}/reply",
        json={"message": "Here is the menu.", "mediaId": str(photo_id)},
        headers=_auth(token),
    )

    assert r.status_code == 500
    history = state_registry.wa_get_history(customer_id, limit=5)
    assert not any(m["role"] == "operator" for m in history)

    state_registry.delete_photo(photo_id)
    try:
        os.remove(media_path)
    except FileNotFoundError:
        pass
    _cleanup(esc_id, customer_id)


def test_soft_mode_whatsapp_reply_unchanged_still_routes_through_marina(monkeypatch):
    """Brief 246: regression — when escalation.mode is NOT 'hard' (soft or
    None for legacy rows), WhatsApp /reply preserves the existing Brief 159
    relay behavior: routes through marina_agent.process_message and stores
    Marina's reformulation as role='assistant'."""
    from shared import state_registry
    from dashboard import api as dapi

    customer_id = "246_soft_wa_relay_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation",
        channel="whatsapp",
        customer_id=customer_id,
        customer_name="Test Customer",
        subject="Marina escalated",
        body="needs help",
        mode="soft",
    )

    monkeypatch.setattr(dapi, "send_whatsapp_message", lambda p, t: True)
    monkeypatch.setattr(
        dapi.marina_agent, "process_message",
        lambda *a, **k: {"reply": "Marina-reformulated reply", "flags": {}})

    operator_text = "Operator coaching text, Marina should reformulate."
    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"message": operator_text}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Marina-reformulated reply"

    history = state_registry.wa_get_history(customer_id, limit=5)
    assert any(m["role"] == "assistant" and m["text"] == "Marina-reformulated reply"
               for m in history), (
        f"soft-mode reply MUST still store as role='assistant'; history={history}")
