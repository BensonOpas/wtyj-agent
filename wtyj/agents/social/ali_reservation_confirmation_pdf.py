"""Informational Ali reservation confirmation PDF.

This document records a confirmed reservation. It deliberately does not claim
to be a rental agreement, an invoice, or proof of payment.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from agents.social.ali_quote_presentation import (
    format_curacao_datetime,
    format_rental_period,
    format_usd_money,
    total_quote_amount,
)


NAVY = colors.HexColor("#102A43")
GOLD = colors.HexColor("#D49A12")
PALE = colors.HexColor("#F2F8FC")
MUTED = colors.HexColor("#486581")

LABELS = {
    "en": {
        "title": "Reservation confirmation",
        "status": "Confirmed",
        "reservation": "Reservation",
        "quote": "Quote",
        "customer": "Customer",
        "vehicle": "Vehicle",
        "period": "Rental period",
        "pickup": "Pickup",
        "return": "Return",
        "total": "Confirmed quote total",
        "issued": "Issued",
        "next": "Pickup information",
        "notice": (
            "This document confirms the reservation recorded by Ali Car Rental. "
            "It is not a rental agreement, an invoice, or proof of payment."
        ),
    },
    "nl": {
        "title": "Reserveringsbevestiging",
        "status": "Bevestigd",
        "reservation": "Reservering",
        "quote": "Offerte",
        "customer": "Klant",
        "vehicle": "Auto",
        "period": "Huurperiode",
        "pickup": "Ophalen",
        "return": "Terugbrengen",
        "total": "Bevestigd offertebedrag",
        "issued": "Uitgegeven",
        "next": "Ophaalinformatie",
        "notice": (
            "Dit document bevestigt de reservering die Ali Car Rental heeft "
            "vastgelegd. Het is geen huurovereenkomst, factuur of betaalbewijs."
        ),
    },
    "pap": {
        "title": "Konfirmashon di reservashon",
        "status": "Konfirma",
        "reservation": "Reservashon",
        "quote": "Oferta",
        "customer": "Kliente",
        "vehicle": "Outo",
        "period": "Periodo di huur",
        "pickup": "Busca",
        "return": "Devolve",
        "total": "Montante di oferta konfirma",
        "issued": "Emiti",
        "next": "Informashon pa busca e outo",
        "notice": (
            "E dokumento aki ta konfirmando e reservashon registra pa Ali Car "
            "Rental. E no ta un kontrato di huur, faktura ni prueba di pago."
        ),
    },
    "de": {
        "title": "Reservierungsbestatigung",
        "status": "Bestatigt",
        "reservation": "Reservierung",
        "quote": "Angebot",
        "customer": "Kunde",
        "vehicle": "Fahrzeug",
        "period": "Mietzeitraum",
        "pickup": "Abholung",
        "return": "Ruckgabe",
        "total": "Bestatigter Angebotsbetrag",
        "issued": "Ausgestellt",
        "next": "Abholinformationen",
        "notice": (
            "Dieses Dokument bestatigt die von Ali Car Rental erfasste "
            "Reservierung. Es ist kein Mietvertrag, keine Rechnung und kein "
            "Zahlungsnachweis."
        ),
    },
}


def _safe(value: object, limit: int = 180) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return html.escape(" ".join(text.split())[:limit])


def _object(value: object, label: str) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {label} data") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid {label} data")
    return parsed


def render_reservation_confirmation_pdf(
    reservation: dict,
    quote: dict,
    *,
    output_root: str = "/app/data/ali-reservations",
    logo_path: str | None = None,
) -> tuple[str, str]:
    """Render one immutable, informational reservation confirmation."""
    if not isinstance(reservation, dict) or not isinstance(quote, dict):
        raise ValueError("Reservation and quote are required")
    reference = str(reservation.get("confirmation_reference") or "").strip()
    public_id = str(reservation.get("public_id") or "").strip()
    if not reference or not public_id:
        raise ValueError("Confirmation reference and reservation id are required")
    if str(reservation.get("availability_status") or "") != "approved":
        raise ValueError("Availability must be approved")

    locale = str(quote.get("locale") or "en").lower()
    labels = LABELS.get(locale, LABELS["en"])
    customer = _object(quote.get("customer_json"), "customer")
    rental = _object(quote.get("rental_json"), "rental")
    pricing = _object(quote.get("pricing_json"), "pricing")
    quote_reference = str(quote.get("quote_reference") or pricing.get("quoteReference") or "")
    issued_at = str(reservation.get("confirmed_at") or reservation.get("updated_at") or "")
    vehicle = rental.get("vehicle_name") or rental.get("vehicle_class_name")
    if not quote_reference or not vehicle or not issued_at:
        raise ValueError("Confirmation source data is incomplete")

    target = Path(output_root) / public_id / "reservation-confirmation.pdf"
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "AliReservationBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=10, leading=14, textColor=NAVY,
    )
    small = ParagraphStyle(
        "AliReservationSmall", parent=body, fontSize=8.5, leading=12,
        textColor=MUTED,
    )
    heading = ParagraphStyle(
        "AliReservationHeading", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY,
    )
    status_style = ParagraphStyle(
        "AliReservationStatus", parent=body, fontName="Helvetica-Bold",
        fontSize=13, leading=17, textColor=colors.HexColor("#13795B"),
    )
    money_style = ParagraphStyle(
        "AliReservationMoney", parent=body, fontName="Helvetica-Bold",
        fontSize=15, leading=18, alignment=TA_RIGHT,
    )

    document = SimpleDocTemplate(
        str(target), pagesize=A4, rightMargin=17 * mm, leftMargin=17 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Ali Car Rental - {reference}",
        author="Ali Car Rental Curacao",
    )
    story = []
    resolved_logo = logo_path or str(
        Path(__file__).resolve().parents[2] / "assets" / "ali-logo-full-premium.png"
    )
    if os.path.isfile(resolved_logo):
        logo = Image(resolved_logo, width=43 * mm, height=23 * mm)
        logo.hAlign = "LEFT"
        story.append(logo)
    else:
        story.append(Paragraph("<b>ALI CAR RENTAL CURACAO</b>", heading))
    story.extend([
        Spacer(1, 2 * mm),
        HRFlowable(color=GOLD, thickness=1.5),
        Spacer(1, 5 * mm),
        Paragraph(_safe(labels["title"]), heading),
        Spacer(1, 2 * mm),
        Paragraph(_safe(labels["status"]).upper(), status_style),
        Spacer(1, 5 * mm),
    ])

    reference_rows = [
        [Paragraph(f"<b>{_safe(labels['reservation'])}</b>", small), Paragraph(_safe(reference, 60), body)],
        [Paragraph(f"<b>{_safe(labels['quote'])}</b>", small), Paragraph(_safe(quote_reference, 60), body)],
        [Paragraph(f"<b>{_safe(labels['issued'])}</b>", small), Paragraph(_safe(format_curacao_datetime(issued_at, locale)), body)],
    ]
    reference_table = Table(reference_rows, colWidths=[42 * mm, 126 * mm])
    reference_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#C9D9E5")),
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    story.extend([reference_table, Spacer(1, 6 * mm)])

    detail_rows = [
        [labels["customer"], customer.get("name")],
        [labels["vehicle"], vehicle],
        [labels["period"], format_rental_period(
            rental.get("rental_start", ""), rental.get("rental_end", ""), locale,
        )],
        [labels["pickup"], rental.get("pickup_location")],
        [labels["return"], rental.get("return_location")],
    ]
    details = Table(
        [[Paragraph(f"<b>{_safe(label)}</b>", small), Paragraph(_safe(value), body)] for label, value in detail_rows],
        colWidths=[42 * mm, 126 * mm],
    )
    details.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#D8E4EC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    story.extend([details, Spacer(1, 6 * mm)])

    if pricing:
        total = Table([[
            Paragraph(f"<b>{_safe(labels['total'])}</b>", body),
            Paragraph(_safe(format_usd_money(total_quote_amount(pricing))), money_style),
        ]], colWidths=[100 * mm, 68 * mm])
        total.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, GOLD),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF9E8")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.extend([total, Spacer(1, 6 * mm)])

    pickup_copy = f"{labels['next']}: {rental.get('pickup_location') or ''}"
    notice = KeepTogether([
        Paragraph(f"<b>{_safe(pickup_copy)}</b>", body),
        Spacer(1, 4 * mm),
        HRFlowable(color=colors.HexColor("#C9D9E5"), thickness=0.7),
        Spacer(1, 4 * mm),
        Paragraph(_safe(labels["notice"], 350), small),
    ])
    story.append(notice)
    document.build(story)

    data = target.read_bytes()
    return str(target), hashlib.sha256(data).hexdigest()
