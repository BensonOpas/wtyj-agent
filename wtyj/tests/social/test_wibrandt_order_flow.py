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
        conn.execute("DELETE FROM appointments WHERE conversation_id = ?", (phone,))
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

        order_state = state_registry.get_order_state_for_conversation(phone)
        assert order_state is not None
        assert order_state["is_order"] is True
        assert order_state["order_status"] == "awaiting_customer_confirmation"
        assert order_state["badge_type"] == "order"
        assert order_state["queue_type"] == "orders"
        assert order_state["human_action_required"] is False

        queue = [
            item for item in state_registry.list_order_queue()
            if item["conversation_id"] == phone
        ]
        assert len(queue) == 1
        assert queue[0]["order_status"] == "awaiting_customer_confirmation"
        assert queue[0]["order_payload"]["delivery_address"] == "Kaya Test 10"
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
        assert "waiting_for_human_order_confirmation" not in state["flags"]
        assert "fully_escalated" not in state["flags"]
        assert "order_escalation_id" not in state["flags"]
        assert state["flags"]["last_order_escalation_id"] == escalation["id"]
        assert "awaiting_order_confirmation" not in state["flags"]
        assert state_registry.get_active_escalation_mode(phone) == "order"

        order_state = state_registry.get_order_state_for_conversation(phone)
        assert order_state is not None
        assert order_state["order_status"] == "awaiting_human_confirmation"
        assert order_state["escalation_mode"] == "order"
        assert order_state["human_action_required"] is True
        assert order_state["escalation_id"] == escalation["id"]

        queue = [
            item for item in state_registry.list_order_queue()
            if item["conversation_id"] == phone
        ]
        assert len(queue) == 1
        assert queue[0]["order_status"] == "awaiting_human_confirmation"
    finally:
        _cleanup(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.config_loader.get_raw", return_value=_wibrandt_config())
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wibrandt_second_order_creates_separate_escalation(mock_process, _cfg, _sheets):
    phone = "wibrandt_second_order"
    _cleanup(phone)
    try:
        first_fields = {
            "customer_name": "Calvin",
            "products": [
                {"name": "The Tosca Twist", "quantity": 2, "unit_price": 5, "subtotal": 10}
            ],
            "delivery_address": "Calle One",
            "order_total": 10,
            "currency": "XCG",
        }
        state_registry.wa_save_booking_state(
            phone,
            first_fields,
            {"awaiting_order_confirmation": True},
        )

        second_fields = {
            "customer_name": "Calvin",
            "products": [
                {"name": "White Chocolate Pecan Cookie", "quantity": 3, "unit_price": 6, "subtotal": 18}
            ],
            "delivery_address": "Calle Two",
            "order_total": 18,
            "currency": "XCG",
        }
        mock_process.side_effect = [
            {
                "intents": ["order"],
                "fields": {},
                "confidence": "high",
                "reply": "Perfect 💛 We've received your order.",
                "requires_human": False,
                "flags": {
                    "order_confirmed": True,
                    "awaiting_order_confirmation": False,
                },
                "internal_note": "First order confirmed.",
            },
            {
                "intents": ["order"],
                "fields": second_fields,
                "confidence": "high",
                "reply": "Perfect 💛 We've received your order.",
                "requires_human": False,
                "flags": {
                    "order_confirmed": True,
                    "awaiting_order_confirmation": False,
                },
                "internal_note": "Second order confirmed.",
            },
        ]

        handle_incoming_whatsapp_message({
            "from": phone,
            "from_name": "Calvin",
            "text": "Yes, first order is good",
        })
        handle_incoming_whatsapp_message({
            "from": phone,
            "from_name": "Calvin",
            "text": "Second order: 3 white chocolate cookies to Calle Two. Yes, confirmed.",
        })

        escalations = [
            e for e in state_registry.get_all_escalations()
            if e["customer_id"] == phone and e["mode"] == "order"
        ]
        assert len(escalations) == 2
        bodies = "\n\n".join(e["body"] for e in escalations)
        assert "Calle One" in bodies
        assert "Calle Two" in bodies
        assert "The Tosca Twist" in bodies
        assert "White Chocolate Pecan Cookie" in bodies

        state = state_registry.wa_get_booking_state(phone)
        assert "waiting_for_human_order_confirmation" not in state["flags"]
        assert "fully_escalated" not in state["flags"]
        assert "order_escalation_id" not in state["flags"]
        assert state["flags"]["last_order_escalation_id"] in {e["id"] for e in escalations}
    finally:
        _cleanup(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.config_loader.get_raw", return_value=_wibrandt_config())
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wibrandt_order_followup_does_not_create_appointment_signal(mock_process, _cfg, _sheets):
    phone = "wibrandt_order_no_appointment"
    _cleanup(phone)
    try:
        mock_process.return_value = {
            "intents": ["order"],
            "fields": {
                "customer_name": "Lisa",
                "product_name": "Cinnamon Cardamom Twist",
                "quantity": 29,
                "delivery_address": "Purinchi",
                "order_total": 145,
                "currency": "XCG",
            },
            "confidence": "high",
            "reply": (
                "Here is your order summary: Cinnamon Cardamom Twist x 29, "
                "delivery to Purinchi, total XCG 145. Does everything look correct?"
            ),
            "requires_human": False,
            "flags": {},
            "internal_note": "",
        }

        handle_incoming_whatsapp_message({
            "from": phone,
            "from_name": "Lisa",
            "text": "I want Cinnamon Cardamom Twist x 29 delivered to Purinchi.",
        })

        appointments = [
            a for a in state_registry.appointments_list()
            if a["conversationId"] == phone
        ]
        assert appointments == []
    finally:
        _cleanup(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.config_loader.get_raw", return_value=_wibrandt_config())
@patch("agents.social.social_agent.marina_agent.process_message")
def test_wibrandt_fully_escalated_order_followup_creates_order_mode(mock_process, _cfg, _sheets):
    phone = "wibrandt_order_followup_mode"
    _cleanup(phone)
    try:
        state_registry.wa_store_message(
            phone,
            "assistant",
            "Here is your order summary: 5 x Cinnamon Cardamom Twist, total XCG 25.",
        )
        state_registry.wa_save_booking_state(
            phone,
            {"customer_name": "Lisa"},
            {"fully_escalated": True},
        )
        mock_process.return_value = {
            "reply": "I am passing this to our team.",
            "requires_human": True,
            "semi_escalation": False,
            "internal_note": (
                "Customer wants to reduce her confirmed order of Cinnamon "
                "Cardamom Twist from 29 to 20."
            ),
        }

        handle_incoming_whatsapp_message({
            "from": phone,
            "from_name": "Lisa",
            "text": "I need to change my order to 20 cinnamon twists.",
        })

        escalations = [
            e for e in state_registry.get_all_escalations()
            if e["customer_id"] == phone
        ]
        assert len(escalations) == 1
        assert escalations[0]["mode"] == "order"
        assert escalations[0]["subject"].startswith("[ORDER]")

        appointments = [
            a for a in state_registry.appointments_list()
            if a["conversationId"] == phone
        ]
        assert appointments == []
    finally:
        _cleanup(phone)
