from agents.social.social_agent import _callback_name_fields, _valid_callback_phone


def test_callback_phone_rejects_zernio_id_and_short_number():
    assert _valid_callback_phone("6a63ad24d9fbaff38cc09ed3") == ("", "")
    assert _valid_callback_phone("63537883") == ("", "")


def test_callback_phone_accepts_formatted_callable_number():
    assert _valid_callback_phone("640 62 30 87") == (
        "640 62 30 87",
        "640623087",
    )


def test_callback_name_falls_back_to_full_customer_name():
    assert _callback_name_fields({"customer_name": "Celia Guzmán Manosalvas"}) == (
        "Celia",
        "Guzmán Manosalvas",
    )
