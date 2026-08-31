from agents.marina import marina_agent
from agents.social import ali_quote_workflow as workflow
from shared import state_registry


CLASS_ID = "30000000-0000-4000-8000-000000000001"
VEHICLE_ID = "40000000-0000-4000-8000-000000000001"


def _raw_config():
    return {
        "slug": "ali-car-rental",
        "workflow": {
            "type": "ali_quote",
            "required_deposit_charge_id": (
                "90000000-0000-4000-8000-000000000001"
            ),
        },
        "features": {
            "booking_flow": False,
            "ali_quote_automation": True,
            "approved_learnings_in_prompt": False,
            "info_updates_in_prompt": False,
        },
        "terminology": {},
    }


def _catalog():
    return {
        "catalogVersion": 1,
        "currency": "USD",
        "availabilityMode": "request_only",
        "vehicleClasses": [{
            "id": CLASS_ID,
            "name": "Economy",
            "description": "Small automatic category",
        }],
        "vehicles": [{
            "id": VEHICLE_ID,
            "classId": CLASS_ID,
            "name": "Toyota Agya or similar",
            "seats": 4,
            "transmission": "automatic",
            "features": ["Air conditioning"],
            "dailyRate": {"currency": "USD", "amount": "35.00"},
            "weeklyRate": {"currency": "USD", "amount": "245.00"},
        }],
        "extras": [],
        "charges": [],
    }


def _configure_ali_prompt(monkeypatch, *, icp_envelope=None):
    raw = _raw_config()
    monkeypatch.setattr(marina_agent.config_loader, "get_raw", lambda: raw)
    monkeypatch.setattr(
        marina_agent.config_loader,
        "get_business",
        lambda: {
            "name": "Ali Car Rental",
            "slug": "ali-car-rental",
            "agent_name": "Nick",
            "languages": ["English", "Dutch", "German", "Papiamentu"],
            "email": "info@example.test",
        },
    )
    monkeypatch.setattr(
        marina_agent.config_loader,
        "get_common_sense_knowledge",
        lambda: {},
    )
    monkeypatch.setattr(
        marina_agent.config_loader,
        "get_agent_signature",
        lambda: "Nick",
    )
    monkeypatch.setattr(workflow, "get_intake_catalog", lambda **_kwargs: _catalog())
    monkeypatch.setattr(
        marina_agent,
        "_icp_envelope_for_prompt",
        lambda: icp_envelope or {},
    )
    monkeypatch.setattr(marina_agent, "_build_live_product_catalog_block", lambda: "")


def test_dashboard_source_of_truth_is_injected_and_tenant_local(
    monkeypatch,
    tmp_path,
):
    _configure_ali_prompt(monkeypatch)
    first_db = tmp_path / "ali.db"
    second_db = tmp_path / "other-tenant.db"
    monkeypatch.setattr(state_registry, "DB_PATH", str(first_db))
    state_registry.source_of_truth_set([{
        "id": "rental-policy",
        "title": "Ali rental policy",
        "content": "Basic insurance and unlimited mileage are included.",
        "items": [
            "The refundable security deposit is USD 200.",
            "Airport pickup and return are included.",
        ],
        "subsections": [{
            "title": "Payment",
            "content": "The booking deposit is 15% of rental charges.",
            "items": ["Cash, credit card and debit card are accepted at pickup."],
        }],
    }])

    first_prompt = marina_agent._build_system_prompt({}, channel="whatsapp")

    assert "TENANT SOURCE OF TRUTH" in first_prompt
    assert "## Ali rental policy" in first_prompt
    assert "Basic insurance and unlimited mileage are included." in first_prompt
    assert "### Payment" in first_prompt
    assert "The booking deposit is 15% of rental charges." in first_prompt
    assert "live catalog remains authoritative for fleet, prices and extras" in first_prompt

    monkeypatch.setattr(state_registry, "DB_PATH", str(second_db))
    second_prompt = marina_agent._build_system_prompt({}, channel="whatsapp")

    assert "TENANT SOURCE OF TRUTH" not in second_prompt
    assert "Basic insurance and unlimited mileage are included." not in second_prompt


def test_malformed_or_empty_source_of_truth_fails_closed(monkeypatch, tmp_path):
    empty_db = tmp_path / "empty.db"
    monkeypatch.setattr(state_registry, "DB_PATH", str(empty_db))
    assert marina_agent._build_source_of_truth_block() == ""

    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO source_of_truth (id, blocks_json, updated_at) "
        "VALUES (1, ?, '2026-08-31T00:00:00Z')",
        ("{not-json",),
    )
    conn.commit()
    conn.close()

    assert marina_agent._build_source_of_truth_block() == ""


def test_dashboard_sot_replaces_conflicting_icp_sot_but_keeps_tone(
    monkeypatch,
    tmp_path,
):
    icp_envelope = {
        "sot_entries": [{
            "id": "stale-payment",
            "title": "Old payment policy",
            "category": "payment",
            "content": "Collect a 25% reservation payment by bank transfer.",
        }],
        "ai_agent_settings": {
            "tone": {
                "tone": "Warm premium service",
                "notes": "Be concise and attentive.",
            },
            "escalation_rules": None,
        },
    }
    _configure_ali_prompt(monkeypatch, icp_envelope=icp_envelope)
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "ali.db"))
    state_registry.source_of_truth_set([{
        "id": "current-payment",
        "title": "Current payment policy",
        "content": "Collect a 15% booking deposit with the WhatsApp payment link.",
        "items": [],
        "subsections": [],
    }])

    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")

    assert prompt.count("TENANT SOURCE OF TRUTH") == 1
    assert "15% booking deposit" in prompt
    assert "25% reservation payment" not in prompt
    assert "bank transfer" not in prompt
    assert "Tone override: Warm premium service" in prompt
    assert prompt.index("TENANT SOURCE OF TRUTH") > prompt.index(
        "FINAL TENANT-SPECIFIC OPERATOR OVERRIDES"
    )
    assert prompt.index("TENANT SOURCE OF TRUTH") < prompt.index(
        "ALI CAR RENTAL WHATSAPP QUOTE INTAKE"
    )


def test_icp_sot_remains_fallback_when_dashboard_sot_is_empty(
    monkeypatch,
    tmp_path,
):
    icp_envelope = {
        "sot_entries": [{
            "id": "fallback-policy",
            "title": "Fallback policy",
            "category": "general",
            "content": "Use the tenant fallback instructions.",
        }],
        "ai_agent_settings": {},
    }
    _configure_ali_prompt(monkeypatch, icp_envelope=icp_envelope)
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "empty.db"))

    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")

    assert "TENANT SOURCE OF TRUTH" not in prompt
    assert "Use the tenant fallback instructions." in prompt

def test_ali_high_engagement_contract_covers_both_owner_examples(monkeypatch):
    _configure_ali_prompt(monkeypatch)
    prompt = " ".join(marina_agent._build_ali_quote_block().split())

    required_contract = (
        "PREMIUM SERVICE STANDARD is mandatory on every Ali turn",
        "shorter messages still receive the same warmth, precision, and ownership",
        "HIGH-ENGAGEMENT, MULTI-QUESTION CARE is mandatory",
        "two or more distinct direct questions",
        "Recognize that internally as strong engagement",
        "Answer every question and requested confirmation directly, in the same order",
        "mirror its numbering",
        "silently skip an item",
        "Do not re-ask a fact from their message",
        "limits NEW questions Nick asks the customer",
        "never limits how many customer questions Nick must answer",
        "normal WhatsApp word target",
        "never grade, praise, count, characterize, or announce the length",
        "HIGH-ENGAGEMENT OPENING CONTRACT",
        "Do not appraise the questions or describe the message",
        "do not multiply a catalog daily rate",
        "more than one driver age",
        "preserve every additional driver's age in `comments`",
    )
    for rule in required_contract:
        assert rule in prompt

    detailed_follow_up = (
        "Thank you for the quote. Before reserving, could you please confirm: "
        "1. Is USD 300 the final total, including all taxes and airport pickup "
        "and return? 2. Are unlimited kilometres included? 3. What insurance is "
        "included, and what is the deductible in case of accident, theft or damage? "
        "4. Are there any fees for drivers aged 21 and 22 or for adding a second "
        "driver? 5. Can we reserve the car now and pay the full amount in cash at "
        "the office when we pick it up, without any advance payment? 6. If we pay "
        "the USD 200 security deposit in cash, will it be refunded in cash "
        "immediately when the car is returned? 7. Will the reservation and vehicle "
        "availability be guaranteed in writing? 8. Can we review the complete "
        "rental agreement before confirming? Thank you."
    )
    detailed_request = (
        "Hello, I’m interested in renting a Toyota Agya from December 31, 2026 "
        "to January 10, 2027, for three people. The drivers would be 21 and 22 "
        "years old. We would like to pick up and return the car at Curaçao Airport. "
        "Could you please confirm availability, the total rental price, the security "
        "deposit, whether insurance and unlimited mileage are included, any fees for "
        "drivers aged 21 and 22, and the available payment methods?"
    )

    for body in (detailed_follow_up, detailed_request):
        user_prompt = marina_agent._build_user_prompt(
            "synthetic-customer",
            "",
            body,
            {},
            {},
            channel="whatsapp",
            messages=[],
        )
        assert body in user_prompt
        assert "INBOUND MESSAGE" in user_prompt


def test_numbered_complete_answer_survives_one_new_question_guard():
    reply = (
        "Thanks for laying that out so clearly. I’ll go through each point.\n\n"
        "1. The official quote shows the complete base-rental total.\n"
        "2. Unlimited mileage is included.\n"
        "3. Basic insurance is included under the tenant policy.\n"
        "4. I’ve recorded both driver ages.\n"
        "5. The booking-deposit terms are listed in the agreement.\n"
        "6. The refundable security-deposit procedure is explained there as well.\n"
        "7. Written confirmation follows the required reservation steps.\n"
        "8. I’ll send the agreement for review before payment.\n\n"
        "I have your car, dates, airport locations and driver ages. What full name "
        "should I put on the official quote?"
    )

    sanitized = workflow.sanitize_intake_reply(
        reply,
        "en",
        {"conversation_language": "en"},
    )

    assert sanitized == reply
    for number in range(1, 9):
        assert f"{number}." in sanitized
    assert sanitized.count("?") == 1
