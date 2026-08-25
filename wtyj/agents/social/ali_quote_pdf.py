"""One-page Ali quote PDF. Pricing is displayed, never calculated here."""

from __future__ import annotations

import hashlib
import html
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
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

NAVY = colors.HexColor("#102A43")
GOLD = colors.HexColor("#D49A12")
PALE = colors.HexColor("#F2F8FC")
MUTED = colors.HexColor("#486581")
CURACAO_TZ = ZoneInfo("America/Curacao")
MAX_TEXT = 180

LABELS = {
    "en": {
        "title": "Official car rental quote",
        "quote": "Quote",
        "customer": "Customer",
        "vehicle": "Vehicle",
        "period": "Rental period",
        "pickup": "Pickup",
        "return": "Return",
        "days": "Rental days",
        "charges": "Itemized charges",
        "rental_total": "Rental total",
        "deposit": "Refundable security deposit",
        "issued": "Issued",
        "expires": "Valid until",
        "validity": "This quote is valid for 72 hours.",
        "availability": "Subject to final vehicle availability confirmation.",
        "reply": "Reply in WhatsApp to accept this quote or ask a question.",
    },
    "nl": {
        "title": "Officiele autohuurofferte",
        "quote": "Offerte",
        "customer": "Klant",
        "vehicle": "Auto",
        "period": "Huurperiode",
        "pickup": "Ophalen",
        "return": "Terugbrengen",
        "days": "Huurdagen",
        "charges": "Kostenoverzicht",
        "rental_total": "Huurbedrag",
        "deposit": "Terugbetaalbare borg",
        "issued": "Uitgegeven",
        "expires": "Geldig tot",
        "validity": "Deze offerte is 72 uur geldig.",
        "availability": "Onder voorbehoud van definitieve beschikbaarheid.",
        "reply": "Reageer via WhatsApp om te accepteren of iets te vragen.",
    },
    "pap": {
        "title": "Oferta ofisial pa huur di outo",
        "quote": "Oferta",
        "customer": "Kliënte",
        "vehicle": "Outo",
        "period": "Periodo di huur",
        "pickup": "Busca",
        "return": "Devolvé",
        "days": "Dianan di huur",
        "charges": "Detaye di gastunan",
        "rental_total": "Total di huur",
        "deposit": "Depósito reembolsabel",
        "issued": "Emití",
        "expires": "Válido te ku",
        "validity": "E oferta aki ta válido pa 72 ora.",
        "availability": "Suhéto na konfirmashon final di disponibilidat.",
        "reply": "Kontestá via WhatsApp pa aseptá of hasi un pregunta.",
    },
    "de": {
        "title": "Offizielles Mietwagenangebot",
        "quote": "Angebot",
        "customer": "Kunde",
        "vehicle": "Fahrzeug",
        "period": "Mietzeitraum",
        "pickup": "Abholung",
        "return": "Rückgabe",
        "days": "Miettage",
        "charges": "Kostenübersicht",
        "rental_total": "Mietpreis",
        "deposit": "Rückerstattbare Kaution",
        "issued": "Ausgestellt",
        "expires": "Gültig bis",
        "validity": "Dieses Angebot ist 72 Stunden gültig.",
        "availability": "Vorbehaltlich der endgültigen Fahrzeugverfügbarkeit.",
        "reply": "Antworten Sie in WhatsApp, um anzunehmen oder etwas zu fragen.",
    },
}


def _safe(value, limit=MAX_TEXT):
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return html.escape(" ".join(text.split())[:limit])


def mask_whatsapp(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 4:
        return "****"
    return f"+{'*' * max(4, len(digits) - 4)}{digits[-4:]}"


def _money(value) -> str:
    if not isinstance(value, dict) or value.get("currency") != "USD":
        raise ValueError("PDF requires an authoritative USD money object")
    amount = str(value.get("amount") or "")
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", amount):
        raise ValueError("PDF received an invalid money amount")
    return f"USD {amount}"


def _curacao_time(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(CURACAO_TZ)
    return dt.strftime("%d %b %Y, %H:%M AST")


def render_quote_pdf(
    public_id: str,
    locale: str,
    customer: dict,
    rental: dict,
    pricing: dict,
    output_root: str = "/app/data/ali-quotes",
    logo_path: str | None = None,
) -> tuple[str, str]:
    labels = LABELS.get(locale)
    if labels is None:
        raise ValueError("Unsupported quote locale")
    if pricing.get("availabilityMode") != "request_only":
        raise ValueError("Quote availability mode must remain request_only")

    quote_reference = _safe(pricing.get("quoteReference"), 40)
    target = Path(output_root) / public_id / "quote.pdf"
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    styles = getSampleStyleSheet()
    body = ParagraphStyle("AliBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=NAVY)
    small = ParagraphStyle("AliSmall", parent=body, fontSize=8, leading=11, textColor=MUTED)
    heading = ParagraphStyle("AliHeading", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=NAVY, spaceAfter=3 * mm)
    total_style = ParagraphStyle("AliTotal", parent=body, fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY, alignment=TA_RIGHT)
    table_header = ParagraphStyle("AliTableHeader", parent=small, fontName="Helvetica-Bold", textColor=colors.white)

    document = SimpleDocTemplate(
        str(target), pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=13 * mm,
        title=f"Ali Car Rental - {quote_reference}", author="Ali Car Rental Curaçao",
    )
    story = []
    resolved_logo = logo_path or str(Path(__file__).resolve().parents[2] / "assets" / "ali-logo-full-premium.png")
    if os.path.isfile(resolved_logo):
        logo = Image(resolved_logo, width=43 * mm, height=23 * mm)
        logo.hAlign = "LEFT"
        story.append(logo)
    else:
        story.append(Paragraph("<b>ALI CAR RENTAL CURAÇAO</b>", heading))
    story.extend([Spacer(1, 2 * mm), HRFlowable(color=GOLD, thickness=1.5), Spacer(1, 5 * mm)])
    story.append(Paragraph(_safe(labels["title"]), heading))
    story.append(Paragraph(f"<b>{_safe(labels['quote'])}:</b> {quote_reference}", body))
    story.append(Spacer(1, 5 * mm))

    left = [
        [Paragraph(f"<b>{_safe(labels['customer'])}</b>", small), Paragraph(_safe(customer.get("name"), 90), body)],
        [Paragraph("WhatsApp", small), Paragraph(_safe(mask_whatsapp(customer.get("whatsapp", ""))), body)],
        [Paragraph(f"<b>{_safe(labels['vehicle'])}</b>", small), Paragraph(_safe(rental.get("vehicle_name") or rental.get("vehicle_class_name"), 100), body)],
        [Paragraph(f"<b>{_safe(labels['period'])}</b>", small), Paragraph(f"{_safe(rental.get('rental_start'), 20)} - {_safe(rental.get('rental_end'), 20)}", body)],
    ]
    right = [
        [Paragraph(f"<b>{_safe(labels['pickup'])}</b>", small), Paragraph(_safe(rental.get("pickup_location")), body)],
        [Paragraph(f"<b>{_safe(labels['return'])}</b>", small), Paragraph(_safe(rental.get("return_location")), body)],
        [Paragraph(f"<b>{_safe(labels['days'])}</b>", small), Paragraph(_safe(pricing.get("rentalDays"), 5), body)],
        [Paragraph(f"<b>{_safe(labels['expires'])}</b>", small), Paragraph(_safe(_curacao_time(pricing.get("expiresAt", ""))), body)],
    ]
    details = Table([[Table(left, colWidths=[30 * mm, 54 * mm]), Table(right, colWidths=[28 * mm, 54 * mm])]], colWidths=[88 * mm, 88 * mm])
    details.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C9D9E5")), ("BACKGROUND", (0, 0), (-1, -1), PALE), ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm), ("TOPPADDING", (0, 0), (-1, -1), 3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm)]))
    story.extend([details, Spacer(1, 6 * mm), Paragraph(_safe(labels["charges"]), ParagraphStyle("AliSection", parent=body, fontName="Helvetica-Bold", fontSize=12, spaceAfter=2 * mm))])

    item_rows = [[Paragraph("Description", table_header), Paragraph("Qty", table_header), Paragraph("Total", table_header)]]
    for item in pricing.get("items") or []:
        item_rows.append([
            Paragraph(_safe(item.get("description"), 110), body),
            Paragraph(_safe(item.get("quantity"), 5), body),
            Paragraph(_safe(_money(item.get("total"))), ParagraphStyle("AliMoney", parent=body, alignment=TA_RIGHT)),
        ])
    items = Table(item_rows, colWidths=[123 * mm, 15 * mm, 38 * mm], repeatRows=1)
    items.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D8E4EC")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm), ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm)]))
    story.extend([items, Spacer(1, 5 * mm)])

    totals = Table([
        [Paragraph(f"<b>{_safe(labels['rental_total'])}</b>", body), Paragraph(_safe(_money(pricing.get("rentalTotal"))), total_style)],
        [Paragraph(f"<b>{_safe(labels['deposit'])}</b>", body), Paragraph(_safe(_money(pricing.get("refundableSecurityDeposit"))), ParagraphStyle("AliDeposit", parent=body, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
    ], colWidths=[108 * mm, 68 * mm])
    totals.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, GOLD), ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#E6D5A8")), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF9E8")), ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm), ("TOPPADDING", (0, 0), (-1, -1), 3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm)]))
    story.append(KeepTogether([totals, Spacer(1, 5 * mm), Paragraph(f"<b>{_safe(labels['issued'])}:</b> {_safe(_curacao_time(pricing.get('createdAt', '')))}<br/>{_safe(labels['validity'])}<br/><b>{_safe(labels['availability'])}</b><br/>{_safe(labels['reply'])}", small)]))
    document.build(story)

    data = target.read_bytes()
    return str(target), hashlib.sha256(data).hexdigest()
