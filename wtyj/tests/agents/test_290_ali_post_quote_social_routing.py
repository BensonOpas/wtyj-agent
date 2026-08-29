"""Brief 290: signed post-quote commands bypass Nick's model turn."""

from agents.social import social_agent


def _configure_early_route(monkeypatch):
    saved = []
    alerts = []
    monkeypatch.setattr(
        social_agent.state_registry,
        "match_ignored_contact",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        social_agent.auto_block,
        "evaluate_inbound",
        lambda **_kwargs: {"action": "allow"},
    )
    monkeypatch.setattr(
        social_agent.state_registry,
        "wa_get_booking_state",
        lambda _phone: {
            "fields": {"customer_name": "Synthetic Customer"},
            "flags": {},
            "completed_bookings": [],
            "last_activity": None,
        },
    )
    monkeypatch.setattr(
        social_agent.state_registry,
        "wa_save_booking_state",
        lambda *args: saved.append(args),
    )
    monkeypatch.setattr(
        social_agent.state_registry,
        "create_pending_notification",
        lambda *args, **kwargs: alerts.append((args, kwargs)) or 290,
    )
    monkeypatch.setattr(social_agent, "ali_quote_tenant_enabled", lambda: True)
    monkeypatch.setattr(
        social_agent.marina_agent,
        "process_message",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("signed post-quote action must bypass Claude")
        ),
    )
    return saved, alerts


def test_signed_reserve_creates_staff_alert_without_model_call(monkeypatch):
    saved, alerts = _configure_early_route(monkeypatch)
    monkeypatch.setattr(
        social_agent,
        "resolve_ali_post_quote_interaction",
        lambda *_args, **_kwargs: {
            "verified": True,
            "status": "current",
            "action": "reserve",
        },
    )
    monkeypatch.setattr(
        social_agent,
        "handle_ali_post_quote_action",
        lambda *_args, **_kwargs: {
            "text": "I am asking our team to check availability now.",
            "status": "created",
            "action": "reserve",
            "reservation": {
                "public_id": "reservation-290",
                "availability_status": "pending",
            },
        },
    )

    result = social_agent.handle_incoming_whatsapp_message(
        {
            "from": "conversation-290",
            "text": "Reserve This Car",
            "from_name": "Synthetic Customer",
            "message_id": "message-290",
            "_zernio_account_id": "account-290",
            "_zernio_interactive_type": "buttonReply",
            "_zernio_interactive_id": "ali_post_quote:v1:signed",
        },
        include_media=True,
    )

    assert result["text"] == "I am asking our team to check availability now."
    assert result["ali_turn_commit"] is None
    assert len(saved) == 1
    assert len(alerts) == 1
    assert alerts[0][0][4] == "[ALI AVAILABILITY CHECK]"
    assert "reservation-290" in alerts[0][0][5]


def test_exact_reserve_fallback_uses_same_route_without_model_call(monkeypatch):
    saved, alerts = _configure_early_route(monkeypatch)
    monkeypatch.setattr(
        social_agent,
        "resolve_ali_post_quote_interaction",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        social_agent,
        "handle_ali_exact_reserve",
        lambda *_args, **_kwargs: {
            "text": "I am checking availability now.",
            "status": "created",
            "action": "reserve",
            "reservation": {
                "public_id": "reservation-fallback-290",
                "availability_status": "pending",
            },
        },
    )

    result = social_agent.handle_incoming_whatsapp_message(
        {
            "from": "conversation-290",
            "text": "RESERVE",
            "message_id": "message-fallback-290",
            "_zernio_account_id": "account-290",
        },
    )

    assert result == "I am checking availability now."
    assert len(saved) == 1
    assert len(alerts) == 1


def test_v2_auto_approved_reserve_creates_no_availability_alert(monkeypatch):
    saved, alerts = _configure_early_route(monkeypatch)
    monkeypatch.setattr(
        social_agent,
        "resolve_ali_post_quote_interaction",
        lambda *_args, **_kwargs: {
            "verified": True,
            "status": "current",
            "action": "reserve",
        },
    )
    monkeypatch.setattr(
        social_agent,
        "handle_ali_post_quote_action",
        lambda *_args, **_kwargs: {
            "text": "",
            "status": "created",
            "action": "reserve",
            "customer_delivery_deferred": True,
            "reservation": {
                "public_id": "reservation-auto-290",
                "availability_status": "approved",
                "workflow_v2": {"state": "documents_collecting"},
            },
        },
    )

    result = social_agent.handle_incoming_whatsapp_message(
        {
            "from": "conversation-290",
            "text": "Reserve This Car",
            "from_name": "Synthetic Customer",
            "message_id": "message-auto-290",
            "_zernio_account_id": "account-290",
            "_zernio_interactive_type": "buttonReply",
            "_zernio_interactive_id": "ali_post_quote:v1:signed",
        },
        include_media=True,
    )

    assert result["text"] == ""
    assert result["ali_customer_delivery_deferred"] is True
    assert len(saved) == 1
    assert alerts == []


def test_question_tap_prompts_for_question_without_creating_case(monkeypatch):
    saved, alerts = _configure_early_route(monkeypatch)
    monkeypatch.setattr(
        social_agent,
        "resolve_ali_post_quote_interaction",
        lambda *_args, **_kwargs: {
            "verified": True,
            "status": "current",
            "action": "question",
        },
    )
    monkeypatch.setattr(
        social_agent,
        "handle_ali_post_quote_action",
        lambda *_args, **_kwargs: {
            "text": "",
            "status": "question",
            "action": "question",
            "reservation": None,
        },
    )

    result = social_agent.handle_incoming_whatsapp_message(
        {
            "from": "conversation-290",
            "text": "Ask A Question",
            "message_id": "message-question-290",
            "_zernio_account_id": "account-290",
            "_zernio_interactive_type": "buttonReply",
            "_zernio_interactive_id": "ali_post_quote:v1:signed",
        },
    )

    assert result == "What would you like to know about your quote?"
    assert len(saved) == 1
    assert alerts == []


def test_change_tap_durably_opens_post_quote_correction_context(monkeypatch):
    saved, alerts = _configure_early_route(monkeypatch)
    monkeypatch.setattr(
        social_agent,
        "resolve_ali_post_quote_interaction",
        lambda *_args, **_kwargs: {
            "verified": True,
            "status": "current",
            "action": "change",
            "quote_public_id": "quote-public-290",
        },
    )
    monkeypatch.setattr(
        social_agent,
        "handle_ali_post_quote_action",
        lambda *_args, **_kwargs: {
            "text": "Of course. What would you like me to change in your quote?",
            "status": "change_requested",
            "action": "change",
            "reservation": None,
        },
    )

    result = social_agent.handle_incoming_whatsapp_message(
        {
            "from": "conversation-290",
            "text": "Change Something",
            "message_id": "message-change-290",
            "_zernio_account_id": "account-290",
            "_zernio_interactive_type": "buttonReply",
            "_zernio_interactive_id": "ali_post_quote:v1:signed",
        },
    )

    assert result == "Of course. What would you like me to change in your quote?"
    assert len(saved) == 1
    assert saved[0][2]["ali_post_quote_change_requested"]["quote_public_id"] == (
        "quote-public-290"
    )
    assert saved[0][2]["ali_post_quote_change_requested"]["requested_at"]
    assert alerts == []
