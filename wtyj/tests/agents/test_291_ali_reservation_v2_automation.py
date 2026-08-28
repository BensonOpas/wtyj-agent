from unittest.mock import Mock, call, patch

from agents.social import ali_reservation_v2_automation as automation
from agents.social import ali_quote_delivery


@patch.object(automation.ali_quote_delivery, "send_customer_requirement_link")
@patch.object(automation.dossier, "mark_contract_link_sent")
@patch.object(automation.dossier, "issue_contract_link")
@patch.object(automation.dossier, "list_documents")
@patch.object(automation.workflow, "required_document_slots")
@patch.object(automation.workflow, "transition")
@patch.object(automation.workflow, "get_case")
@patch.object(automation.workflow, "enabled")
def test_document_collection_runs_contract_work_before_client_wait(
    enabled, get_case, transition, required, documents,
    issue_contract, mark_sent, deliver,
):
    enabled.return_value = True
    get_case.return_value = {
        "state": "document_review_pending",
        "revision": 4,
        "identityType": "passport",
    }
    required.return_value = ("license_front", "license_back", "passport")
    documents.return_value = [
        {"public_id": f"doc-{index}", "slot": slot, "version": 1, "status": "verified"}
        for index, slot in enumerate(required.return_value)
    ]
    transition.side_effect = [
        {"state": "documents_collected", "revision": 5},
        {"state": "contract_sent", "revision": 6},
    ]
    issue_contract.return_value = {
        "contract": {"public_id": "contract-1"},
        "url": "https://example.test/sign",
    }
    deliver.return_value = True

    result = automation.after_document_review("reservation-1")

    assert result["workflowV2"]["state"] == "contract_sent"
    assert transition.call_args_list[0].args[1] == "documents_collected"
    issue_contract.assert_called_once_with("reservation-1", actor=automation.SYSTEM_ACTOR)
    deliver.assert_called_once_with(
        "reservation-1", "contract", issue_contract.return_value,
    )
    mark_sent.assert_called_once_with(
        "reservation-1", "contract-1", actor=automation.SYSTEM_ACTOR,
    )
    assert transition.call_args_list[1].args[1] == "contract_sent"


@patch.object(automation.state_registry, "create_pending_notification")
@patch.object(automation.state_registry, "get_pending_notifications")
@patch.object(automation.dossier, "customer_delivery_context")
@patch.object(automation.ali_quote_delivery, "send_customer_requirement_link")
@patch.object(automation.workflow, "transition")
@patch.object(automation.workflow, "get_case")
@patch.object(automation.workflow, "enabled")
def test_signature_opens_one_staff_gate_and_does_not_send_payment(
    enabled, get_case, transition, deliver, delivery_context,
    pending_notifications, notify,
):
    enabled.return_value = True
    get_case.return_value = {"state": "contract_sent", "revision": 6}
    transition.side_effect = [
        {"state": "contract_signed", "revision": 7},
        {"state": "prepayment_approval_pending", "revision": 8},
    ]
    delivery_context.return_value = {"conversation_id": "conversation-1"}
    pending_notifications.side_effect = [[], []]
    notify.return_value = 41

    result = automation.after_contract_signed("reservation-1")

    assert result["workflowV2"]["state"] == "prepayment_approval_pending"
    assert result["notificationId"] == 41
    assert result["paymentDelivered"] is False
    assert [item.args[1] for item in transition.call_args_list] == [
        "contract_signed", "prepayment_approval_pending",
    ]
    deliver.assert_not_called()
    assert notify.call_count == 1


@patch.object(automation.state_registry, "create_pending_notification")
@patch.object(automation.state_registry, "get_pending_notifications")
@patch.object(automation.dossier, "customer_delivery_context")
@patch.object(automation.workflow, "get_case")
@patch.object(automation.workflow, "enabled")
def test_signature_replay_reuses_the_existing_staff_review(
    enabled, get_case, delivery_context, pending_notifications, notify,
):
    enabled.return_value = True
    get_case.return_value = {
        "state": "prepayment_approval_pending",
        "revision": 8,
    }
    delivery_context.return_value = {"conversation_id": "conversation-1"}
    pending_notifications.side_effect = [
        [{
            "id": 41,
            "customer_id": "conversation-1",
            "subject": "[ALI PRE-PAYMENT REVIEW] reservation-1",
        }],
    ]

    result = automation.after_contract_signed("reservation-1")

    assert result["notificationId"] == 41
    notify.assert_not_called()


@patch.object(automation.ali_quote_delivery, "send_customer_requirement_link")
@patch.object(automation.dossier, "mark_payment_link_sent")
@patch.object(automation.dossier, "payment_delivery_payload")
@patch.object(automation.dossier, "set_payment_link")
@patch.object(automation.dossier, "tenant_settings")
@patch.object(automation.dossier, "record_prepayment_file_approval")
@patch.object(automation.dossier, "prepayment_review_summary")
@patch.object(automation.dossier, "customer_delivery_context")
@patch.object(automation.state_registry, "get_pending_notifications")
@patch.object(automation.workflow, "transition")
@patch.object(automation.workflow, "get_case")
@patch.object(automation.workflow, "enabled")
def test_complete_file_approval_is_the_only_path_that_sends_payment(
    enabled, get_case, transition, pending_notifications, delivery_context,
    review_summary, record_approval, settings, set_link, payment_payload,
    mark_sent, deliver,
):
    enabled.return_value = True
    get_case.side_effect = [
        {"state": "prepayment_approval_pending", "revision": 8},
        {"state": "prepayment_approved", "revision": 9},
    ]
    transition.side_effect = [
        {"state": "prepayment_approved", "revision": 9},
        {"state": "payment_link_sent", "revision": 10},
    ]
    pending_notifications.return_value = []
    delivery_context.return_value = {"conversation_id": "conversation-1"}
    review_summary.return_value = {
        "readyForApproval": True,
        "paymentReady": True,
    }
    settings.return_value = {"payment": {"mode": "fixed_link"}}
    payment_payload.return_value = {
        "url": "https://pay.example.test/rental",
        "amount": "42.00",
        "percent": 15,
        "validityHours": 24,
    }
    deliver.return_value = True

    result = automation.approve_prepayment_file(
        "reservation-1",
        actor_id="dashboard",
        expected_revision=8,
    )

    assert result["delivered"] is True
    assert [item.args[1] for item in transition.call_args_list] == [
        "prepayment_approved", "payment_link_sent",
    ]
    record_approval.assert_called_once_with("reservation-1", "dashboard")
    set_link.assert_called_once_with(
        "reservation-1", "", reference="reservation-1",
        actor=automation.SYSTEM_ACTOR,
    )
    deliver.assert_called_once_with(
        "reservation-1", "payment", payment_payload.return_value,
    )
    mark_sent.assert_called_once_with(
        "reservation-1", actor=automation.SYSTEM_ACTOR,
    )


@patch.object(automation.ali_quote_delivery, "send_customer_requirement_link")
@patch.object(automation.workflow, "get_case")
@patch.object(automation.workflow, "enabled")
def test_payment_send_fails_closed_before_complete_file_approval(
    enabled, get_case, deliver,
):
    enabled.return_value = True
    get_case.return_value = {
        "state": "prepayment_approval_pending",
        "revision": 8,
    }

    try:
        automation.send_approved_payment_link("reservation-1")
    except Exception as exc:
        assert getattr(exc, "code", "") == "prepayment_approval_required"
    else:
        raise AssertionError("payment delivery bypassed prepayment approval")
    deliver.assert_not_called()


@patch.object(automation, "_payment_delivery_attention")
@patch.object(automation.ali_quote_delivery, "send_customer_requirement_link")
@patch.object(automation.dossier, "payment_delivery_payload")
@patch.object(automation.dossier, "tenant_settings")
@patch.object(automation.workflow, "transition")
@patch.object(automation.workflow, "get_case")
@patch.object(automation.workflow, "enabled")
def test_failed_payment_delivery_preserves_approval_for_retry(
    enabled, get_case, transition, settings, payment_payload, deliver, attention,
):
    enabled.return_value = True
    get_case.return_value = {"state": "prepayment_approved", "revision": 9}
    settings.return_value = {"payment": {"mode": "per_reservation"}}
    payment_payload.return_value = {
        "url": "https://pay.example.test/rental",
        "amount": "42.00",
        "percent": 15,
        "validityHours": 24,
    }
    deliver.return_value = False

    result = automation.send_approved_payment_link("reservation-1")

    assert result["delivered"] is False
    assert result["workflowV2"]["state"] == "prepayment_approved"
    attention.assert_called_once_with(
        "reservation-1", "payment_link_delivery_failed",
    )
    transition.assert_not_called()


@patch.object(automation.dossier, "generate_dossier")
@patch.object(automation.workflow, "transition")
@patch.object(automation.workflow, "get_case")
@patch.object(automation.workflow, "enabled")
def test_verified_payment_generates_dossier_before_staff_final_approval(
    enabled, get_case, transition, generate,
):
    enabled.return_value = True
    get_case.return_value = {"state": "customer_reports_paid", "revision": 9}
    transition.side_effect = [
        {"state": "payment_verified", "revision": 10},
        {"state": "dossier_ready", "revision": 11},
        {"state": "final_approval_pending", "revision": 12},
    ]
    generate.return_value = {"version": 3}

    result = automation.after_payment_review("reservation-1", "verified")

    assert result["workflowV2"]["state"] == "final_approval_pending"
    assert [item.args[1] for item in transition.call_args_list] == [
        "payment_verified", "dossier_ready", "final_approval_pending",
    ]
    generate.assert_called_once_with("reservation-1", actor=automation.SYSTEM_ACTOR)


def test_reminder_copy_is_localized_and_contains_only_next_step():
    assert "passport" in ali_quote_delivery.reservation_reminder_text(
        "en", "choose_identity_type",
    )
    assert "paspoort" in ali_quote_delivery.reservation_reminder_text(
        "nl", "choose_identity_type",
    )
    assert "pasport" in ali_quote_delivery.reservation_reminder_text(
        "pap", "choose_identity_type",
    )
    assert "Reisepass" in ali_quote_delivery.reservation_reminder_text(
        "de", "choose_identity_type",
    )


def test_scheduler_hard_gate_blocks_customer_reminder_delivery(monkeypatch):
    from agents.social import webhook_server

    monkeypatch.setattr(webhook_server, "send_reply", Mock())
    monkeypatch.setattr(webhook_server, "_run_ali_document_retention_cleanup", Mock())
    with patch(
        "agents.social.ali_reservation_v2.enabled", return_value=True,
    ), patch(
        "agents.social.ali_reservation_v2.reminder_plan",
        return_value=[{
            "kind": "reminder",
            "reservationPublicId": "reservation-1",
            "nextAction": "send_expected_document",
            "idempotencyKey": "reminder-1",
        }],
    ), patch(
        "agents.social.ali_reservation_v2.reminder_sends_enabled",
        return_value=False,
    ), patch(
        "agents.social.ali_reservation_v2.record_reminder_result",
    ) as record:
        assert webhook_server._run_ali_reservation_v2_scheduled_once() == 0
        webhook_server.send_reply.assert_not_called()
        record.assert_not_called()


def test_scheduler_retries_only_the_missing_direct_document_prompt():
    from agents.social import webhook_server

    plan = {
        "kind": "documents_prompt",
        "reservationPublicId": "reservation-1",
        "idempotencyKey": "ali-v2-documents-prompt:reservation-1",
    }
    payload = {
        "reservationPublicId": "reservation-1",
        "mode": "direct_whatsapp",
        "identityTypes": ["passport", "id_card"],
        "links": [],
    }
    with patch(
        "agents.social.ali_reservation_v2.enabled", return_value=True,
    ), patch(
        "agents.social.ali_reservation_v2.reminder_plan", return_value=[plan],
    ), patch(
        "agents.social.ali_customer_dossier.issue_document_links",
        return_value=payload,
    ) as issue, patch(
        "agents.social.ali_quote_delivery.send_customer_requirement_link",
        return_value=True,
    ) as deliver:
        assert webhook_server._run_ali_reservation_v2_scheduled_once() == 1
        issue.assert_called_once_with(
            "reservation-1", actor="reservation_v2_scheduler",
        )
        deliver.assert_called_once_with(
            "reservation-1", "documents", payload,
        )


def test_scheduler_expires_hold_even_when_reminders_are_disabled():
    from agents.social import webhook_server

    plan = {
        "kind": "expire",
        "reservationPublicId": "reservation-1",
        "idempotencyKey": "expire-1",
    }
    with patch(
        "agents.social.ali_reservation_v2.enabled", return_value=True,
    ), patch(
        "agents.social.ali_reservation_v2.reminder_plan", return_value=[plan],
    ), patch(
        "agents.social.ali_reservation_v2.expire_due_case",
    ) as expire, patch(
        "agents.social.ali_customer_dossier.customer_delivery_context",
        return_value={
            "conversation_id": "conversation-1",
            "account_id": "account-1",
            "locale": "en",
        },
    ), patch(
        "agents.social.webhook_server.send_reply", return_value=True,
    ) as send, patch(
        "agents.social.ali_reservation_v2.record_expiry_closure_result",
    ) as record:
        assert webhook_server._run_ali_reservation_v2_scheduled_once() == 1
        expire.assert_called_once_with(plan)
        send.assert_called_once()
        record.assert_called_once()
        assert record.call_args.kwargs["sent"] is True
