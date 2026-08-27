"""Replay-safe automatic system steps for Ali reservation V2."""

from __future__ import annotations

from agents.social import ali_customer_dossier as dossier
from agents.social import ali_reservation_v2 as workflow
from agents.social import ali_quote_delivery
from shared import state_registry


SYSTEM_ACTOR = "reservation_v2_system"


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


def after_document_review(public_id: str) -> dict:
    """Issue and send the pre-contract once every required document is approved."""
    if not workflow.enabled():
        return {"handled": False}
    current = workflow.get_case(public_id)
    if current["state"] not in {
        "document_review_pending", "document_replacement_required",
        "documents_approved", "contract_sent",
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
        latest.get(slot, {}).get("status") in {"verified", "not_required"}
        for slot in required
    ):
        return {"handled": False, "workflowV2": current}

    try:
        if current["state"] == "document_review_pending":
            current = workflow.transition(
                public_id,
                "documents_approved",
                actor_type="system",
                actor_id=SYSTEM_ACTOR,
                idempotency_key="all-required-documents-approved",
                reason="all_required_documents_approved",
                expected_revision=current["revision"],
            )
        if current["state"] == "documents_approved":
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
        return {"handled": True, "workflowV2": current}
    except Exception as exc:
        return {
            "handled": True,
            "workflowV2": _attention(
                public_id,
                f"contract_automation_{getattr(exc, 'code', type(exc).__name__)}",
            ),
        }


def after_contract_signed(public_id: str) -> dict:
    """Create/send the payment link immediately after a valid signature."""
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
                return {"handled": True, "workflowV2": _attention(public_id, "payment_link_delivery_failed")}
            dossier.mark_payment_link_sent(public_id, actor=SYSTEM_ACTOR)
            current = workflow.transition(
                public_id,
                "payment_link_sent",
                actor_type="system",
                actor_id=SYSTEM_ACTOR,
                idempotency_key="payment-link-sent",
                reason="payment_link_provider_confirmed",
                expected_revision=current["revision"],
            )
        return {"handled": True, "workflowV2": current}
    except Exception as exc:
        return {
            "handled": True,
            "workflowV2": _attention(
                public_id,
                f"payment_automation_{getattr(exc, 'code', type(exc).__name__)}",
            ),
        }


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
