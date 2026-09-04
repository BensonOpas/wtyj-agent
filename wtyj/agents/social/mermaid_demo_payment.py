"""Signed, no-money checkout for Mermaid's WhatsApp reservation demonstration."""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import time
from urllib.parse import urlencode

from fastapi.responses import HTMLResponse, Response

from agents.social import mermaid_documents, mermaid_reservation_store
from agents.social import mermaid_guest_experience as guest
from agents.social.senders import send_reply
from shared import icp_overrides, mermaid_catalog, state_registry


def _secret() -> str:
    return os.environ.get("MERMAID_DEMO_SIGNING_SECRET", "")


def sign_payment(reservation_id: str, expires: int, secret: str) -> str:
    payload = f"mermaid-payment:{reservation_id}:{int(expires)}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_payment(reservation_id: str, expires: int, signature: str, secret: str, now: int | None = None) -> bool:
    current = int(time.time() if now is None else now)
    if not secret or current > int(expires) or int(expires) > current + 3600:
        return False
    return hmac.compare_digest(sign_payment(reservation_id, expires, secret), str(signature or ""))


def build_payment_url(base_url: str, reservation_id: str, secret: str, now: int | None = None) -> str:
    if not base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")) or not secret:
        raise ValueError("Mermaid demo payment configuration is missing")
    expires = int(time.time() if now is None else now) + 3600
    signature = sign_payment(reservation_id, expires, secret)
    return f"{base_url.rstrip('/')}/api/public/mermaid-demo-payment/{reservation_id}?{urlencode({'expires': expires, 'signature': signature})}"


def _page(title: str, body: str, *, actions: str = "", status: int = 200) -> HTMLResponse:
    markup = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{margin:0;background:#eaf8f8;color:#063b46;font:16px/1.5 system-ui,sans-serif}}main{{max-width:620px;margin:40px auto;padding:30px;background:white;border-radius:18px;box-shadow:0 12px 36px #063b4622}}h1{{margin-top:18px}}.demo{{background:#f36c5b;color:white;padding:10px 14px;border-radius:8px;font-weight:800;text-align:center}}.summary{{background:#f4fbfb;padding:18px;border-radius:12px;margin:20px 0}}button{{border:0;border-radius:10px;padding:14px 18px;font-weight:750;cursor:pointer}}.pay{{background:#007f86;color:white}}.cancel{{background:#e9eef0;color:#203c44;margin-left:8px}}small{{display:block;margin-top:20px;color:#4d6870}}
</style></head><body><main><div class="demo">PAYMENT SIMULATION - NO MONEY</div><h1>{html.escape(title)}</h1>{body}{actions}<small>No card number, bank account, password, or payment credential is requested or stored.</small></main></body></html>"""
    return HTMLResponse(markup, status_code=status, headers={"Cache-Control": "private, no-store"})


def checkout_page(reservation_id: str, expires: int, signature: str) -> Response:
    if not verify_payment(reservation_id, expires, signature, _secret()):
        return Response(status_code=404)
    reservation = mermaid_reservation_store.get_reservation(reservation_id)
    if not reservation:
        return Response(status_code=404)
    money = reservation["monetary_snapshot"]
    intake = reservation["intake"]
    body = (
        f'<div class="summary"><b>{html.escape(reservation["customer_name"])}</b><br>'
        f'{html.escape(intake["trip_date"])} · {intake["adults"]} adults · '
        f'{intake["children"]} children 4-12 · {intake["infants"]} children 0-3<br>'
        f'<b>{html.escape(guest.price_text(money, intake, reservation["language"]))}</b><br>'
        f'{html.escape(guest.transport_text(intake, reservation["language"]))}</div>'
        '<p>This page demonstrates payment completion only. Clicking success moves no money.</p>'
    )
    actions = (
        f'<form method="post" action="?expires={int(expires)}&amp;signature={html.escape(signature)}">'
        '<button class="pay" name="status" value="success">Simulate successful payment</button>'
        '<button class="cancel" name="status" value="cancel">Cancel</button></form>'
    )
    return _page("Mermaid demo checkout", body, actions=actions)


def success_message(reservation: dict, payment: dict) -> str:
    intake = reservation["intake"]
    locale = reservation["language"] if reservation["language"] in mermaid_documents.LABELS else "en"
    copy = guest.guest_copy(locale)
    return "\n\n".join([
        copy["booking_complete"],
        f"{reservation['booking_code']} · {guest.guest_date(intake['trip_date'], locale)}\n{guest.party_text(intake, locale)}",
        f"{copy['paid']}: {payment['currency']} {int(payment['amount']):,.2f}",
        guest.transport_text(intake, locale),
    ])



def complete_checkout(reservation_id: str, expires: int, signature: str, status: str) -> Response:
    if not mermaid_catalog.reservation_demo_enabled() or not mermaid_catalog.demo_features()["demo_payment"] or not verify_payment(reservation_id, expires, signature, _secret()):
        return Response(status_code=404)
    reservation = mermaid_reservation_store.get_reservation(reservation_id)
    if not reservation:
        return Response(status_code=404)
    if status != "success":
        return _page("Payment simulation cancelled", "<p>No payment was recorded. Your demo reservation remains open, so you can return to WhatsApp and try again.</p>")
    reference = "PAY-DEMO-" + hashlib.sha256(reservation_id.encode()).hexdigest()[:10].upper()
    reservation, payment = mermaid_reservation_store.complete_demo_payment(
        reservation_id, payment_reference=reference,
        idempotency_key=f"demo-payment:{reservation_id}",
    )
    document, job = mermaid_documents.create_receipt(reservation, payment)
    reservation = mermaid_reservation_store.attach_receipt(reservation_id, document["public_id"])
    base_url = os.environ.get("UNBOKS_PUBLIC_BASE_URL", "http://localhost:8001")
    receipt_url = mermaid_documents.build_signed_url(base_url, document["public_id"], _secret())
    delivered = job["status"] == "delivered"
    controls = icp_overrides.fetch_overrides_fresh()
    can_send = (
        icp_overrides.whatsapp_inbox_state(controls) is True
        and icp_overrides.auto_reply_state(controls) is True
        and not state_registry.get_ai_muted(reservation["conversation_id"])
    )
    if not delivered and job["attempts"]:
        from agents.social.mermaid_delivery_reconciliation import reconcile_job
        try:
            delivered = reconcile_job(job["public_id"]) == "delivered"
        except Exception:
            delivered = False
    # A timeout can mean accepted but not delivered yet. Repeated checkout
    # callbacks must only reconcile; never resend a new signed URL blindly.
    if not delivered and can_send and not job["attempts"] and mermaid_documents.claim_initial_delivery(job["public_id"]):
        delivered = send_reply(
            "whatsapp", reservation["conversation_id"], reservation.get("zernio_account_id") or "",
            success_message(reservation, payment), attachment_url=receipt_url, attachment_type="file",
            attachment_name=document["filename"],
            confirm_delivery=True, idempotency_key=job["idempotency_key"],
        )
        mermaid_documents.mark_delivery(job["public_id"], delivered, "awaiting provider confirmation" if not delivered else "", count_attempt=False)
        if delivered:
            state_registry.dm_store_message_once(
                conversation_id=reservation["conversation_id"], channel="whatsapp", role="assistant",
                text=success_message(reservation, payment),
                source_message_key="mermaid-job:" + job["public_id"],
            )
            state_registry.dm_store_message_once(
                conversation_id=reservation["conversation_id"], channel="whatsapp", role="system",
                text="Payment receipt sent: " + document["filename"],
                source_message_key="mermaid-attachment:" + job["public_id"],
            )
    body = (
        f"<p><b>Demo payment complete.</b></p><p>Booking code: <b>{html.escape(reservation['booking_code'])}</b></p>"
        "<p>Your receipt and warm booking message were prepared for the same WhatsApp conversation. No money moved.</p>"
    )
    return _page("Mermaid demo booking complete", body)
