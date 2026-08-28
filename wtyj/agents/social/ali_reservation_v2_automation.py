"""Replay-safe automatic system steps for Ali reservation V2."""

from __future__ import annotations

from agents.social import ali_customer_dossier as dossier
from agents.social import ali_reservation_v2 as workflow
from agents.social import ali_quote_delivery
from shared import state_registry


SYSTEM_ACTOR = "reservation_v2_system"


def _prepayment_subject(public_id: str) -> str:
    return f"[ALI PRE-PAYMENT REVIEW] {public_id}"


def _notification_conversation(public_id: str) -> str:
    try:
        delivery = dossier.customer_delivery_context(public_id)
        return str(delivery["conversation_id"])
    except Exception:
        return str(public_id)


def _notify_prepayment_review(public_id: str) -> int:
    """Create one deduplicated staff item after the customer file is complete."""
    conversation_id = _notification_conversation(public_id)
    subject = _prepayment_subject(public_id)
    for status in ("pending", "sent"):
        for item in state_registry.get_pending_notifications(status):
            if (
                str(item.get("customer_id") or "") == conversation_id
                and str(item.get("subject") or "") == subject
            ):
                return int(item["id"])
    return state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        conversation_id,
        "Ali reservation customer",
        subject,
        (
            "All required identity and driver-license documents are stored, "
            "and the pre-contract is signed. Review the complete file once in "
            "Quote leads. Approval will send the payment link."
        ),
        mode="soft",
    )


def _resolve_prepayment_notification(public_id: str) -> None:
    subject = _prepayment_subject(public_id)
    conversation_id = _notification_conversation(public_id)
    for status in ("pending", "sent"):
        for item in state_registry.get_pending_notifications(status):
            if (
                str(item.get("customer_id") or "") == conversation_id
                and str(item.get("subject") or "") == subject
            ):
                state_registry.update_notification_status(int(item["id"]), "resolved")


def _payment_delivery_attention(public_id: str, code: str) -> None:
    """Alert staff but preserve durable approval so delivery can be retried."""
    state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        _notification_conversation(public_id),
        "Ali reservation customer",
        f"[ALI PAYMENT DELIVERY ATTENTION] {public_id}",
        (
            "The complete customer file was approved, but the payment-link "
            f"message was not delivered. Code: {code}. Retry from Quote leads."
        ),
        mode="hard",
    )


def _attention(public_id: str, code: str) -> dict:
    current = workflow.get_case(public_id)
    if current["state"] != "technical_attention_required":
        try:
            current = workflow.transition(
                public_id,
                "technical_attention_required",
                actor_type="system",
                actor_id=SYSTEM_ACTOR,
                idempotency_key=f"technical-attention:{code}:{current['revision']}",
                reason=code,
                expected_revision=current["revision"],
            )
        except Exception:
            current = workflow.get_case(public_id)
    try:
        delivery = dossier.customer_delivery_context(public_id)
        conversation_id = str(delivery["conversation_id"])
    except Exception:
        conversation_id = str(public_id)
    state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        conversation_id,
        "Ali reservation customer",
        "[ALI RESERVATION V2 ATTENTION]",
        f"An automatic reservation step stopped safely. Code: {code}.",
        mode="hard",
    )
    return current


def after_documents_collected(public_id: str) -> dict:
    """Issue the pre-contract after secure receipt, without per-file approval."""
    if not workflow.enabled():
        return {"handled": False}
    current = workflow.get_case(public_id)
    if current["state"] not in {
        "document_review_pending", "documents_collected", "documents_approved",
        "contract_sent", "prepayment_approval_pending",
    }:
        return {"handled": False, "workflowV2": current}
    documents = dossier.list_documents(public_id)
    latest = {}
    for item in documents:
        latest.setdefault(str(item.get("slot") or ""), item)
    required = workflow.required_document_slots(str(current.get("identityType") or ""))
    replacement = next(
        (
            item for slot in required
            if (item := latest.get(slot))
            and item.get("status") in {"rejected", "replacement_requested"}
        ),
        None,
    )
    if replacement:
        updated = workflow.request_document_replacement(
            public_id,
            str(replacement["slot"]),
            actor_id=SYSTEM_ACTOR,
            idempotency_key=(
                f"replacement:{replacement['public_id']}:{replacement['version']}"
            ),
        )
        return {"handled": True, "workflowV2": updated, "replacement": True}
    if not required or not all(
        latest.get(slot, {}).get("status") in {
            "received", "verified", "not_required",
        }
        for slot in required
    ):
        return {"handled": False, "workflowV2": current}

    try:
        if current["state"] == "document_review_pending":
            current = workflow.transition(
                public_id,
                "documents_collected",
                actor_type="system",
                actor_id=SYSTEM_ACTOR,
                idempotency_key="all-required-documents-collected",
                reason="all_required_documents_received",
                expected_revision=current["revision"],
            )
        if current["state"] in {"documents_collected", "documents_approved"}:
            contract = dossier.issue_contract_link(public_id, actor=SYSTEM_ACTOR)
            delivered = ali_quote_delivery.send_customer_requirement_link(
                public_id, "contract", contract,
            )
            if not delivered:
                return {"handled": True, "workflowV2": _attention(public_id, "contract_delivery_failed")}
            dossier.mark_contract_link_sent(
                public_id, contract["contract"]["public_id"], actor=SYSTEM_ACTOR,
            )
            current = workflow.transition(
                public_id,
                "contract_sent",
                actor_type="system",
                actor_id=SYSTEM_ACTOR,
                idempotency_key=(
                    f"contract-sent:{contract['contract']['public_id']}"
                ),
                reason="contract_provider_confirmed",
                expected_revision=current["revision"],
            )
        if current["state"] == "prepayment_approval_pending":
            _notify_prepayment_review(public_id)
        return {"handled": True, "workflowV2": current}
    except Exception as exc:
        return {
            "handled": True,
            "workflowV2": _attention(
                public_id,
                f"contract_automation_{getattr(exc, 'code', type(exc).__name__)}",
            ),
        }


def after_document_review(public_id: str) -> dict:
    """Backward-compatible entry point for older queued V2 cases."""
    return after_documents_collected(public_id)


def after_contract_signed(public_id: str) -> dict:
    """Open the single staff gate; never send payment from the signature path."""
    if not workflow.enabled():
        return {"handled": False}
    current = workflow.get_case(public_id)
    try:
        if current["state"] == "contract_sent":
            current = workflow.transition(
                public_id,
                "contract_signed",
                actor_type="customer",
                actor_id="signed_contract_link",
                idempotency_key="contract-signed",
                reason="customer_signed_contract",
                expected_revision=current["revision"],
            )
        if current["state"] == "contract_signed":
            current = workflow.transition(
                public_id,
                "prepayment_approval_pending",
                actor_type="system",
                actor_id=SYSTEM_ACTOR,
                idempotency_key="prepayment-review-ready",
                reason="documents_and_signed_contract_ready",
                expected_revision=current["revision"],
            )
        notification_id = None
        if current["state"] == "prepayment_approval_pending":
            notification_id = _notify_prepayment_review(public_id)
        return {
            "handled": True,
            "workflowV2": current,
            "notificationId": notification_id,
            "paymentDelivered": False,
        }
    except Exception as exc:
        return {
            "handled": True,
            "workflowV2": _attention(
                public_id,
                f"payment_automation_{getattr(exc, 'code', type(exc).__name__)}",
            ),
        }


def send_approved_payment_link(public_id: str) -> dict:
    """Send payment only from the durable approved state, with safe retries."""
    if not workflow.enabled():
        return {"handled": False}
    current = workflow.get_case(public_id)
    if current["state"] == "payment_link_sent":
        return {
            "handled": True,
            "delivered": True,
            "workflowV2": current,
            "repeated": True,
        }
    if current["state"] != "prepayment_approved":
        from agents.social.ali_reservation_workflow import AliReservationError
        raise AliReservationError("prepayment_approval_required", 409)
    try:
        settings = dossier.tenant_settings()
        if (settings.get("payment") or {}).get("mode") == "fixed_link":
            dossier.set_payment_link(
                public_id,
                "",
                reference=str(public_id),
                actor=SYSTEM_ACTOR,
            )
        payment = dossier.payment_delivery_payload(public_id)
        delivered = ali_quote_delivery.send_customer_requirement_link(
            public_id, "payment", payment,
        )
        if not delivered:
            _payment_delivery_attention(public_id, "payment_link_delivery_failed")
            return {
                "handled": True,
                "delivered": False,
                "workflowV2": workflow.get_case(public_id),
            }
        dossier.mark_payment_link_sent(public_id, actor=SYSTEM_ACTOR)
        current = workflow.transition(
            public_id,
            "payment_link_sent",
            actor_type="system",
            actor_id=SYSTEM_ACTOR,
            idempotency_key="payment-link-sent-after-prepayment-approval",
            reason="payment_link_provider_confirmed",
            expected_revision=current["revision"],
        )
        return {
            "handled": True,
            "delivered": True,
            "workflowV2": current,
            "repeated": False,
        }
    except Exception as exc:
        _payment_delivery_attention(
            public_id,
            f"payment_delivery_{getattr(exc, 'code', type(exc).__name__)}",
        )
        raise


def approve_prepayment_file(
    public_id: str,
    *,
    actor_id: str,
    expected_revision: int,
) -> dict:
    """Approve the complete file once, then attempt the payment delivery."""
    if not workflow.enabled():
        return {"handled": False}
    current = workflow.get_case(public_id)
    if current["state"] == "payment_link_sent":
        return send_approved_payment_link(public_id)
    if current["state"] == "prepayment_approval_pending":
        summary = dossier.prepayment_review_summary(public_id)
        if not summary["readyForApproval"]:
            from agents.social.ali_reservation_workflow import AliReservationError
            raise AliReservationError("prepayment_file_incomplete", 409)
        if not summary["paymentReady"]:
            from agents.social.ali_reservation_workflow import AliReservationError
            raise AliReservationError("payment_link_not_configured", 409)
        current = workflow.transition(
            public_id,
            "prepayment_approved",
            actor_type="staff",
            actor_id=actor_id,
            idempotency_key="prepayment-file-approved",
            reason="complete_prepayment_file_approved",
            expected_revision=expected_revision,
        )
        _resolve_prepayment_notification(public_id)
    elif current["state"] != "prepayment_approved":
        from agents.social.ali_reservation_workflow import AliReservationError
        raise AliReservationError("prepayment_review_not_ready", 409)
    dossier.record_prepayment_file_approval(public_id, actor_id)
    return send_approved_payment_link(public_id)


def after_payment_review(public_id: str, decision: str) -> dict:
    """Generate and persist the dossier after staff verifies payment."""
    if not workflow.enabled() or decision not in {"verified", "not_required"}:
        return {"handled": False}
    current = workflow.get_case(public_id)
    try:
        if current["state"] == "customer_reports_paid":
            current = workflow.transition(
                public_id,
                "payment_verified",
                actor_type="staff",
                actor_id="dashboard",
                idempotency_key=f"payment-reviewed:{decision}",
                reason=f"payment_{decision}",
                expected_revision=current["revision"],
            )
        if current["state"] == "payment_verified":
            generated = dossier.generate_dossier(public_id, actor=SYSTEM_ACTOR)
            current = workflow.transition(
                public_id,
                "dossier_ready",
                actor_type="system",
                actor_id=SYSTEM_ACTOR,
                idempotency_key=f"dossier-ready:{generated['version']}",
                reason="dossier_generated",
                expected_revision=current["revision"],
            )
        if current["state"] == "dossier_ready":
            current = workflow.transition(
                public_id,
                "final_approval_pending",
                actor_type="system",
                actor_id=SYSTEM_ACTOR,
                idempotency_key="final-approval-pending",
                reason="dossier_ready_for_staff",
                expected_revision=current["revision"],
            )
        return {"handled": True, "workflowV2": current}
    except Exception as exc:
        return {
            "handled": True,
            "workflowV2": _attention(
                public_id,
                f"dossier_automation_{getattr(exc, 'code', type(exc).__name__)}",
            ),
        }
