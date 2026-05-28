import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test_secret")

from fastapi.testclient import TestClient

from agents.social.social_agent import handle_incoming_whatsapp_message
from agents.social.webhook_server import app
from shared import auto_block, state_registry


client = TestClient(app)


def _auth():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _wipe(prefix="autoblock_"):
    auto_block.get_settings()
    conn = state_registry._get_conn()
    try:
        conn.execute("DELETE FROM conversation_status WHERE conversation_id LIKE ?", (f"{prefix}%",))
        conn.execute("DELETE FROM whatsapp_threads WHERE phone LIKE ?", (f"{prefix}%",))
        conn.execute("DELETE FROM whatsapp_booking_state WHERE phone LIKE ?", (f"{prefix}%",))
        conn.execute("DELETE FROM pending_notifications WHERE customer_id LIKE ?", (f"{prefix}%",))
        conn.execute("DELETE FROM auto_block_events WHERE user_identifier LIKE ?", (f"{prefix}%",))
        conn.execute("DELETE FROM auto_block_settings")
        conn.commit()
    finally:
        conn.close()


def test_zero_tolerance_threat_blocks_and_creates_escalation():
    phone = "autoblock_threat"
    try:
        _wipe()
        reply = handle_incoming_whatsapp_message({
            "from": phone,
            "from_name": "Angry Customer",
            "text": "I will kill you tomorrow",
        })
        assert reply == ""
        assert state_registry.get_blocked(phone) is True
        escalations = [
            e for e in state_registry.get_all_escalations()
            if e["customer_id"] == phone
        ]
        assert escalations
        assert "AUTO-BLOCK REVIEW" in escalations[0]["subject"]
        assert "threat / intimidation" in escalations[0]["body"]
    finally:
        _wipe()


def test_one_profanity_message_does_not_block_but_repeated_threshold_does():
    phone = "autoblock_profanity"
    try:
        _wipe()
        auto_block.save_settings({
            "enabled": True,
            "repeated_profanity": {
                "enabled": True,
                "threshold": 3,
                "warn_before_block": False,
            },
        })
        first = auto_block.evaluate_inbound(
            channel="whatsapp",
            user_identifier=phone,
            text="this is shit",
        )
        second = auto_block.evaluate_inbound(
            channel="whatsapp",
            user_identifier=phone,
            text="still shit",
        )
        third = auto_block.evaluate_inbound(
            channel="whatsapp",
            user_identifier=phone,
            text="again shit",
        )
        assert first["action"] == "none"
        assert second["action"] == "none"
        assert third["action"] == "blocked"
        assert state_registry.get_blocked(phone) is True
    finally:
        _wipe()


def test_auto_block_settings_endpoint_round_trip():
    try:
        _wipe()
        headers = _auth()
        r = client.put(
            "/dashboard/api/settings/auto-block",
            headers=headers,
            json={
                "enabled": True,
                "zero_tolerance": {"threat": False},
                "repeated_profanity": {
                    "enabled": True,
                    "threshold": 5,
                    "warn_before_block": True,
                },
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["zero_tolerance"]["threat"] is False
        assert body["repeated_profanity"]["threshold"] == 5

        fetched = client.get("/dashboard/api/settings/auto-block", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["repeated_profanity"]["threshold"] == 5
    finally:
        _wipe()
