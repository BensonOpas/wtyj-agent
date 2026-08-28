"""Issue 298: one professional 24-hour quote and payment window."""

from unittest.mock import patch

import pytest

from agents.social import ali_quote_delivery as delivery


@pytest.mark.parametrize(
    ("locale", "percent_text", "window_text", "not_secured_text"),
    [
        ("en", "15%", "within 24 hours", "not reserved"),
        ("nl", "15%", "binnen 24 uur", "pas voor jou gereserveerd"),
        ("pap", "15%", "denter di 24 ora", "solamente despues"),
        ("de", "15%", "innerhalb von 24 Stunden", "erst für Sie reserviert"),
    ],
)
def test_payment_copy_states_percent_deadline_and_verification_gate(
    locale, percent_text, window_text, not_secured_text,
):
    with patch(
        "agents.social.ali_customer_dossier.customer_delivery_context",
        return_value={
            "conversation_id": "synthetic-conversation",
            "account_id": "synthetic-account",
            "locale": locale,
        },
    ), patch(
        "agents.social.ali_customer_dossier.record_requirement_delivery",
    ), patch.object(delivery, "send_dm_reply", return_value=True) as send:
        assert delivery.send_customer_requirement_link(
            "synthetic-reservation",
            "payment",
            {
                "url": "https://pay.example.test/secure",
                "amount": "690.00",
                "percent": 15,
                "validityHours": 24,
            },
        ) is True

    message = send.call_args.args[2]
    assert percent_text in message
    assert window_text in message
    assert not_secured_text in message
    assert "690.00" in message
    assert "https://pay.example.test/secure" in message


def test_payment_delivery_rejects_missing_snapshot_percent():
    with patch(
        "agents.social.ali_customer_dossier.customer_delivery_context",
        return_value={
            "conversation_id": "synthetic-conversation",
            "account_id": "synthetic-account",
            "locale": "en",
        },
    ):
        with pytest.raises(delivery.AliReservationError) as missing:
            delivery.send_customer_requirement_link(
                "synthetic-reservation",
                "payment",
                {
                    "url": "https://pay.example.test/secure",
                    "amount": "690.00",
                },
            )
    assert missing.value.code == "customer_payment_percent_missing"
