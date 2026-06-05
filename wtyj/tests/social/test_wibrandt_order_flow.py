import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


def _wibrandt_config():
    return {
        "tenant_slug": "wibrandt",
        "business": {
            "slug": "wibrandt",
            "name": "Wibrandt",
            "email": "info.wibrandt@gmail.com",
        },
        "features": {"booking_flow": True},
    }


def _cleanup(phone):
    conn = state_registry._get_conn()
    try:
        conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (phone,))
        conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
        conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
        conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
        conn.commit()
    finally:
        conn.close()


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.config_loader.get_raw", return_value=_wibrandt_config())
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wibrandt_order_summary_waits_for_customer_confirmation(mock_process, _cfg, _sheets):
    phone = "wibrandt_order_summary"
    _cleanup(phone)
    try:
        mock_process.return_value = {
            "intents": ["order"],
            "fields": {
                "customer_name": "Sophia",
                "product_name": "Banana Carrot Pecan Crunch",
                "quantity": 5,
                "delivery_address": "Kaya Test 10",
                "order_total": 125,
                "currency": "ANG",
            },
            "confidence": "high",
            "reply": (
                "Here is your order summary: 5 x Banana Carrot Pecan Crunch, "
                "delivery to Kaya Test 10, total ANG 125."
            ),
            "requires_human": False,
            "flags": {},
            "internal_note": "",
        }

        reply = handle_incoming_whatsapp_message({
            "from": phone,
            "from_name": "Sophia",
            "text": "I want 5 Banana Carrot Pecan Crunch delivered to Kaya Test 10.",
        })

        assert "Does everything look correct?" in reply
        state = state_registry.wa_get_booking_state(phone)
        assert state["flags"]["awaiting_order_confirmation"] is True
        escalations = [
            e for e in state_registry.get_all_escalations()
            if e["customer_id"] == phone
        ]
        assert escalations == []
    finally:
        _cleanup(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.config_loader.get_raw", return_value=_wibrandt_config())
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wibrandt_confirmed_order_creates_order_escalation(mock_process, _cfg, _sheets):
    phone = "wibrandt_order_confirmed"
    _cleanup(phone)
    try:
        fields = {
            "customer_name": "Sophia",
            "phone": "+59996945527",
            "products": [
                {
                    "name": "Banana Carrot Pecan Crunch",
                    "quantity": 5,
                    "unit_price": 25,
                    "subtotal": 125,
                }
            ],
            "delivery_address": "Kaya Test 10",
            "comments": "Call before delivery",
            "order_total": 125,
            "currency": "ANG",
        }
        flags = {"awaiting_order_confirmation": True}
        state_registry.wa_save_booking_state(phone, fields, flags)

        mock_process.return_value = {
            "intents": ["order"],
            "fields": {},
            "confidence": "high",
            "reply": (
                "Perfect 💛 We've received your order.\n\n"
                "We'll give you a call shortly to confirm the details and delivery.\n\n"
                "Thank you for choosing Wibrandt."
            ),
            "requires_human": False,
            "flags": {
                "order_confirmed": True,
                "awaiting_order_confirmation": False,
            },
            "internal_note": "Customer confirmed the order summary.",
        }

        reply = handle_incoming_whatsapp_message({
            "from": phone,
            "from_name": "Sophia",
            "text": "Yes perfect",
        })

        assert "We've received your order" in reply
        escalations = [
            e for e in state_registry.get_all_escalations()
            if e["customer_id"] == phone
        ]
        assert len(escalations) == 1
        escalation = escalations[0]
        assert escalation["mode"] == "order"
        assert escalation["subject"].startswith("[ORDER]")
        assert "WAITING_FOR_HUMAN_ORDER_CONFIRMATION" in escalation["body"]
        assert "Banana Carrot Pecan Crunch" in escalation["body"]
        assert "Kaya Test 10" in escalation["body"]
        assert "ANG 125" in escalation["body"]

        state = state_registry.wa_get_booking_state(phone)
        assert state["flags"]["waiting_for_human_order_confirmation"] is True
        assert state["flags"]["fully_escalated"] is True
        assert state["flags"]["awaiting_order_confirmation"] is False
        assert state_registry.get_active_escalation_mode(phone) == "order"
    finally:
        _cleanup(phone)
