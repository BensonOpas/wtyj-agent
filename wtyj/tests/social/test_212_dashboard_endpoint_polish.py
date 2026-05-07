# test_212_dashboard_endpoint_polish.py
# Brief 212:
#  - GET /learning + DELETE /learning/:id are aliases for the existing
#    plural-path handlers (SR's frontend calls singular).
#  - PUT /schedule/slots accepts a raw JSON array body (SR posts
#    `[...]`, not `{slots: [...]}`).
#  - POST /ai-editor is a thin Claude proxy for the reply composer's
#    translate / style / fix buttons.
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


def _cleanup_learning(learning_id):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_learnings WHERE id = ?", (learning_id,))
    conn.commit()
    conn.close()


# --- Test 1: GET /learning returns escalation_learnings shape (Brief 215 repointed
# the singular path away from content_learnings; /learnings still serves content).
def test_learning_singular_alias_get_returns_same_as_plural():
    from shared import state_registry
    # Seed an escalation_learning row (the new domain for /learning singular)
    el_id = state_registry.save_escalation_learning(
        conversation_id="212_alias_get_phone", channel="whatsapp",
        source_question="?", human_answer="Brief 212/215 alias test")

    token = _login()
    r_singular = client.get("/dashboard/api/learning", headers=_auth(token))
    assert r_singular.status_code == 200, r_singular.text
    payload = r_singular.json()
    assert isinstance(payload, list)
    matched = next((row for row in payload if row.get("id") == el_id), None)
    assert matched is not None, f"seeded escalation_learning {el_id} not in /learning response"
    # SR-domain shape requires `status` field per row
    assert "status" in matched
    assert matched["status"] == "approved"

    state_registry.delete_escalation_learning(el_id)


# --- Test 2: DELETE /learning/:id removes an escalation_learning row.
def test_learning_singular_alias_delete_works():
    from shared import state_registry
    el_id = state_registry.save_escalation_learning(
        conversation_id="212_alias_delete_phone", channel="whatsapp",
        source_question="?", human_answer="Brief 212/215 alias delete test")

    token = _login()
    r = client.delete(f"/dashboard/api/learning/{el_id}",
                       headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # Row should no longer be in the list
    rows = state_registry.list_escalation_learnings()
    assert all(item["id"] != el_id for item in rows)


# --- Test 3: PUT /schedule/slots accepts raw array body
def test_schedule_slots_put_accepts_raw_array():
    from shared import state_registry
    token = _login()
    payload = [
        {"day_of_week": "Tuesday", "time_utc": "16:00"},
        {"day_of_week": "Friday", "time_utc": "10:00"},
    ]
    r = client.put("/dashboard/api/schedule/slots",
                    json=payload,
                    headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    # Verify slots were persisted
    saved = state_registry.get_schedule_slots()
    assert len(saved) == 2
    assert any(s["day_of_week"] == "Tuesday" and s["time_utc"] == "16:00" for s in saved)

    # Cleanup: clear schedule slots so other tests don't see stale state
    state_registry.save_schedule_slots([])


# --- Test 4: POST /ai-editor "fix" returns rewritten text
@patch("dashboard.api.anthropic")
def test_ai_editor_fix_returns_rewritten_text(mock_anthropic_module):
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="I have a draft.")]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/ai-editor",
                     json={"action": "fix", "text": "i has a draft"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "I have a draft."

    # Verify the prompt contains the operator's draft text
    call = mock_client.messages.create.call_args
    user_msg = call.kwargs["messages"][0]["content"]
    assert "i has a draft" in user_msg
    assert "fix any grammar" in user_msg.lower()


# --- Test 5: POST /ai-editor "translate" requires targetLanguage
def test_ai_editor_translate_requires_target_language():
    token = _login()
    r = client.post("/dashboard/api/ai-editor",
                     json={"action": "translate", "text": "hello"},
                     headers=_auth(token))
    assert r.status_code == 400
    assert "targetlanguage" in r.json()["detail"].lower()


# --- Test 6: Invalid action returns 400 with the offending action named
def test_ai_editor_invalid_action_returns_400():
    token = _login()
    r = client.post("/dashboard/api/ai-editor",
                     json={"action": "sing", "text": "hello"},
                     headers=_auth(token))
    assert r.status_code == 400
    assert "sing" in r.json()["detail"]
