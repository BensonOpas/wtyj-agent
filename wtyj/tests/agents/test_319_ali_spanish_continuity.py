"""Brief 319: Spanish remains first-class throughout the Ali journey."""

from agents.marina import marina_agent
from agents.social import ali_quote_workflow as quote_workflow
from agents.social import ali_reservation_workflow as reservation_workflow
from agents.social.ali_media_first import add_first_turn_welcome
from agents.social.ali_quote_presentation import (
    format_curacao_datetime,
    format_rental_period,
)
from agents.social.ali_vehicle_recommendations import build_vehicle_recommendation


VEHICLE_ID = "40000000-0000-4000-8000-000000000001"
CLASS_ID = "30000000-0000-4000-8000-000000000001"


def _catalog():
    return {
        "catalogVersion": 1,
        "vehicleClasses": [{"id": CLASS_ID, "name": "Economy"}],
        "vehicles": [{
            "id": VEHICLE_ID,
            "slug": "toyota-agya",
            "classId": CLASS_ID,
            "name": "Toyota Agya",
            "seats": 5,
            "luggageCapacity": 2,
            "transmission": "automatic",
            "dailyRate": {"currency": "USD", "amount": "30.00"},
            "images": [{"url": "/agya.png", "alt": "Toyota Agya"}],
        }],
    }


def test_spanish_is_an_allowed_structured_conversation_language():
    language = marina_agent.MARINA_TOOL["input_schema"]["properties"][
        "fields"
    ]["properties"]["conversation_language"]

    assert "es" in language["enum"]
    assert "es" in quote_workflow.LOCALES


def test_spanish_welcome_and_vehicle_card_never_fall_back_to_english():
    welcome = add_first_turn_welcome(
        "¿Qué tipo de auto buscas?",
        {"conversation_language": "es"},
    )
    recommendation = build_vehicle_recommendation(
        {
            "mode": "specific",
            "vehicle_names": ["Toyota Agya"],
            "availability_note": (
                "La disponibilidad final del vehículo aún debe confirmarse."
            ),
            "cta_label": "Detalles Del Auto",
        },
        _catalog(),
        {"conversation_language": "es"},
        {},
        "Aquí tienes una opción adecuada.",
        public_base_url="https://alicarrental.com",
    )

    assert welcome.startswith("¡Bienvenido a Ali Car Rental! Soy Nick")
    assert recommendation["buttons"][0]["title"] == "Elegir Este Auto"
    assert recommendation["options"][0]["seats"] == 5
    assert recommendation["options"][0]["detail_url"].startswith(
        "https://alicarrental.com/en/fleet/"
    )


def test_spanish_quote_dates_summary_and_post_quote_controls(monkeypatch):
    assert format_rental_period(
        "2027-02-02", "2027-02-17", "es",
    ) == "2 de febrero de 2027 – 17 de febrero de 2027"
    assert format_curacao_datetime(
        "2027-02-01T16:00:00Z", "es",
    ) == "1 de febrero de 2027 a las 12:00 (hora de Curaçao)"

    summary = quote_workflow._summary_text({
        "customer": {"name": "Federico Barcio", "whatsapp": "+59990000000"},
        "rental": {
            "rental_start": "2027-02-02",
            "rental_end": "2027-02-17",
            "pickup_location": "Airport",
            "return_location": "Airport",
            "vehicle_name": "Toyota Agya",
            "driver_age": 48,
            "conversation_language": "es",
            "supplements": [],
        },
    })
    assert summary.startswith("Tengo estos datos:")
    assert "Período de alquiler" in summary
    assert "¿Está todo correcto?" in summary

    monkeypatch.setattr(
        reservation_workflow.config_loader,
        "get_raw",
        lambda: {"slug": "ali-car-rental", "workflow": {"type": "ali_quote"}},
    )
    control = reservation_workflow.build_post_quote_control({
        "conversation_id": "conversation-es",
        "zernio_account_id": "account-es",
        "public_id": "quote-es",
        "quote_snapshot_id": "snapshot-es",
        "whatsapp_status": "accepted",
        "customer_delivery_superseded_at": None,
        "locale": "es",
    }, secret="synthetic-secret")
    assert control["text"] == "¿Cómo quieres continuar?"
    assert [button["title"] for button in control["buttons"]] == [
        "Reservar Este Auto",
        "Cambiar Algo",
        "Hacer Una Pregunta",
    ]


def test_spanish_confirmation_phrases_are_accepted_without_losing_questions():
    assert quote_workflow.confirmation_decision("Sí, todo está bien") == (
        True,
        "affirmative_allowlist",
    )
    assert quote_workflow.confirmation_decision("Sí, ¿cómo puedo pagar?")[0] is True
