# test_222_conversation_detail_fields.py
# Brief 222: GET /messages/conversations/:phone returns 5 new fields:
#   humanTakeoverAt + learningStatus (real storage, derived)
#   humanGuidance + humanResponder + humanRespondedAt (null placeholders)
# Tests cover the two new state_registry helpers + the JSON response shape.

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _cleanup_phone(phone):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (phone,))
    conn.execute("DELETE FROM escalation_learnings WHERE conversation_id = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 1: get_human_takeover_at returns None when unset
def test_get_human_takeover_at_helper_returns_none_when_unset():
    from shared import state_registry
    # Empty/missing customer id
    assert state_registry.get_human_takeover_at("") is None
    assert state_registry.get_human_takeover_at("222_nonexistent_conv") is None

    # Existing conversation_status row but no takeover stamped
    phone = "222_no_takeover_phone"
    try:
        state_registry.set_conversation_status(phone, "open", "whatsapp")
        assert state_registry.get_human_takeover_at(phone) is None
    finally:
        _cleanup_phone(phone)


# --- Test 2: get_human_takeover_at returns ISO string after takeover
def test_get_human_takeover_at_returns_iso_timestamp_when_set():
    from shared import state_registry
    phone = "222_takeover_phone"
    try:
        # Brief 213's set_ai_muted(..., True) UPSERTs human_takeover_at = now
        state_registry.set_ai_muted(phone, True, "whatsapp")

        ts = state_registry.get_human_takeover_at(phone)
        assert ts is not None
        assert isinstance(ts, str) and len(ts) > 10
        # ISO 8601 starts with year, has 'T' separator
        assert "T" in ts
    finally:
        _cleanup_phone(phone)


# --- Test 3: learning status precedence saved > approved > suggested > none
def test_learning_status_precedence():
    from shared import state_registry
    phone = "222_learning_phone"
    try:
        # No rows → none
        assert state_registry.get_learning_status_for_conversation(phone) == "none"

        sug_id = state_registry.save_escalation_learning(
            conversation_id=phone, channel="whatsapp",
            source_question="?", human_answer="suggested ans", status="suggested")
        assert state_registry.get_learning_status_for_conversation(phone) == "suggested"

        app_id = state_registry.save_escalation_learning(
            conversation_id=phone, channel="whatsapp",
            source_question="?", human_answer="approved ans", status="approved")
        assert state_registry.get_learning_status_for_conversation(phone) == "approved"

        sav_id = state_registry.save_escalation_learning(
            conversation_id=phone, channel="whatsapp",
            source_question="?", human_answer="saved ans", status="saved")
        assert state_registry.get_learning_status_for_conversation(phone) == "saved"

        # Mark saved row deleted → falls back to approved
        state_registry.update_escalation_learning_status(sav_id, "deleted")
        assert state_registry.get_learning_status_for_conversation(phone) == "approved"

        # Mark approved row deleted → falls back to suggested
        state_registry.update_escalation_learning_status(app_id, "deleted")
        assert state_registry.get_learning_status_for_conversation(phone) == "suggested"

        # Mark suggested row deleted → none
        state_registry.update_escalation_learning_status(sug_id, "deleted")
        assert state_registry.get_learning_status_for_conversation(phone) == "none"
    finally:
        _cleanup_phone(phone)


# --- Test 4: GET /messages/conversations returns the new contract fields
def test_get_conversation_returns_new_contract_fields():
    from shared import state_registry
    phone = "222_integration_phone"
    try:
        # Seed: a stored message + takeover + an approved learning
        state_registry.wa_store_message(phone, "user", "Hola")
        state_registry.set_ai_muted(phone, True, "whatsapp")
        state_registry.save_escalation_learning(
            conversation_id=phone, channel="whatsapp",
            source_question="Hola", human_answer="hello back",
            status="approved")

        token = _login()
        r = client.get(f"/dashboard/api/messages/conversations/{phone}",
                        headers=_auth(token))
        assert r.status_code == 200, r.text
        body = r.json()

        # Real fields
        assert body.get("humanTakeoverAt") is not None
        assert isinstance(body["humanTakeoverAt"], str)
        assert "T" in body["humanTakeoverAt"]
        assert body.get("learningStatus") == "approved"

        # Placeholders explicitly null (not undefined / missing)
        assert "humanGuidance" in body and body["humanGuidance"] is None
        assert "humanResponder" in body and body["humanResponder"] is None
        assert "humanRespondedAt" in body and body["humanRespondedAt"] is None
    finally:
        _cleanup_phone(phone)
