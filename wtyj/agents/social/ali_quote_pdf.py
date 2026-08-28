"""One-page Ali quote PDF. Pricing is displayed, never calculated here."""

from __future__ import annotations

import hashlib
import html
import os
import re
from pathlib import Path

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

from agents.social.ali_quote_presentation import (
    format_curacao_datetime,
    format_rental_period,
    format_usd_money,
    total_quote_amount,
    usd_cents,
)

NAVY = colors.HexColor("#102A43")
GOLD = colors.HexColor("#D49A12")
PALE = colors.HexColor("#F2F8FC")
MUTED = colors.HexColor("#486581")
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
        "description": "Description",
        "quantity": "Qty",
        "total": "Total",
        "per_day": "per rental day",
        "per_rental": "per rental",
        "days_suffix": "days",
        "grand_total": "Total quote amount",
        "deposit_included": "Includes a refundable security deposit of {amount}.",
        "rental_total": "Rental charges",
        "deposit": "Refundable security deposit",
        "issued": "Issued",
        "expires": "Valid until",
        "validity": "This quote is valid for {hours} hours.",
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
        "description": "Omschrijving",
        "quantity": "Aantal",
        "total": "Totaal",
        "per_day": "per huurdag",
        "per_rental": "per huur",
        "days_suffix": "dagen",
        "grand_total": "Totaalbedrag offerte",
        "deposit_included": "Inclusief een terugbetaalbare borg van {amount}.",
        "rental_total": "Huurkosten",
        "deposit": "Terugbetaalbare borg",
        "issued": "Uitgegeven",
        "expires": "Geldig tot",
        "validity": "Deze offerte is {hours} uur geldig.",
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
        "description": "Deskripshon",
        "quantity": "Kantidat",
        "total": "Total",
        "per_day": "pa dia di huur",
        "per_rental": "pa huur",
        "days_suffix": "dia",
        "grand_total": "Montante total di oferta",
        "deposit_included": "Ta inkluí un depósito reembolsabel di {amount}.",
        "rental_total": "Gastunan di huur",
        "deposit": "Depósito reembolsabel",
        "issued": "Emití",
        "expires": "Válido te ku",
        "validity": "E oferta aki ta válido pa {hours} ora.",
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
        "description": "Beschreibung",
        "quantity": "Menge",
        "total": "Gesamt",
        "per_day": "pro Miettag",
        "per_rental": "pro Miete",
        "days_suffix": "Tage",
        "grand_total": "Gesamtbetrag des Angebots",
        "deposit_included": "Enthält eine rückerstattbare Kaution von {amount}.",
        "rental_total": "Mietkosten",
        "deposit": "Rückerstattbare Kaution",
        "issued": "Ausgestellt",
        "expires": "Gültig bis",
        "validity": "Dieses Angebot ist {hours} Stunden gültig.",
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
    return format_usd_money(value)


def _item_description(item: dict, labels: dict, supplement_name: str = "") -> str:
    description = _safe(supplement_name or item.get("description"), 110)
    if item.get("category") != "extra":
        return description
    basis = item.get("billingBasis")
    if basis not in {"per_day", "per_rental"}:
        raise ValueError("PDF supplement requires a billing basis")
    detail = f"{_money(item.get('unitPrice'))} {labels[basis]}"
    if basis == "per_day":
        days = item.get("rentalDays")
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            raise ValueError("PDF daily supplement requires rental days")
        detail += f" × {days} {labels['days_suffix']}"
    return f"{description}<br/><font color='#486581' size='8'>{_safe(detail, 90)}</font>"


def render_quote_pdf(
    public_id: str,
    locale: str,
    customer: dict,
    rental: dict,
    pricing: dict,
    output_root: str = "/app/data/ali-quotes",
    logo_path: str | None = None,
    availability_copy: str | None = None,
    quote_footer: str | None = None,
    validity_hours: int | None = None,
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
    total_style = ParagraphStyle("AliTotal", parent=body, fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY, alignment=TA_RIGHT)
    total_label_style = ParagraphStyle("AliTotalLabel", parent=body, fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=NAVY)
    deposit_note_style = ParagraphStyle("AliDepositNote", parent=small, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=MUTED)
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
        [
            Paragraph(f"<b>{_safe(labels['period'])}</b>", small),
            Paragraph(
                _safe(format_rental_period(
                    rental.get("rental_start", ""),
                    rental.get("rental_end", ""),
                    locale,
                ), 80),
                body,
            ),
        ],
    ]
    right = [
        [Paragraph(f"<b>{_safe(labels['pickup'])}</b>", small), Paragraph(_safe(rental.get("pickup_location")), body)],
        [Paragraph(f"<b>{_safe(labels['return'])}</b>", small), Paragraph(_safe(rental.get("return_location")), body)],
        [Paragraph(f"<b>{_safe(labels['days'])}</b>", small), Paragraph(_safe(pricing.get("rentalDays"), 5), body)],
        [
            Paragraph(f"<b>{_safe(labels['expires'])}</b>", small),
            Paragraph(_safe(format_curacao_datetime(pricing.get("expiresAt", ""), locale)), body),
        ],
    ]
    details = Table([[Table(left, colWidths=[30 * mm, 54 * mm]), Table(right, colWidths=[28 * mm, 54 * mm])]], colWidths=[88 * mm, 88 * mm])
    details.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C9D9E5")), ("BACKGROUND", (0, 0), (-1, -1), PALE), ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm), ("TOPPADDING", (0, 0), (-1, -1), 3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm)]))
    story.extend([details, Spacer(1, 6 * mm), Paragraph(_safe(labels["charges"]), ParagraphStyle("AliSection", parent=body, fontName="Helvetica-Bold", fontSize=12, spaceAfter=2 * mm))])

    item_rows = [[
        Paragraph(_safe(labels["description"]), table_header),
        Paragraph(_safe(labels["quantity"]), table_header),
        Paragraph(_safe(labels["total"]), table_header),
    ]]
    supplement_names = [
        str(item.get("name") or "")
        for item in rental.get("supplements") or []
        if isinstance(item, dict)
    ]
    supplement_index = 0
    for item in pricing.get("items") or []:
        supplement_name = ""
        if item.get("category") == "extra":
            if supplement_index < len(supplement_names):
                supplement_name = supplement_names[supplement_index]
            supplement_index += 1
        item_rows.append([
            Paragraph(_item_description(item, labels, supplement_name), body),
            Paragraph(_safe(item.get("quantity"), 5), body),
            Paragraph(_safe(_money(item.get("total"))), ParagraphStyle("AliMoney", parent=body, alignment=TA_RIGHT)),
        ])
    items = Table(item_rows, colWidths=[118 * mm, 20 * mm, 38 * mm], repeatRows=1)
    items.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D8E4EC")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm), ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm)]))
    story.extend([items, Spacer(1, 5 * mm)])

    deposit = pricing.get("refundableSecurityDeposit")
    grand_total = total_quote_amount(pricing)
    total_rows = [[
        Paragraph(_safe(labels["grand_total"]), total_label_style),
        Paragraph(_safe(_money(grand_total)), total_style),
    ]]
    if usd_cents(deposit):
        total_rows.append([
            Paragraph(
                _safe(labels["deposit_included"].format(amount=_money(deposit))),
                deposit_note_style,
            ),
            "",
        ])
    total_rows.append([
        Paragraph(_safe(labels["rental_total"]), body),
        Paragraph(
            _safe(_money(pricing.get("rentalTotal"))),
            ParagraphStyle("AliRentalSubtotal", parent=body, fontName="Helvetica-Bold", alignment=TA_RIGHT),
        ),
    ])
    totals = Table(total_rows, colWidths=[108 * mm, 68 * mm])
    total_styles = [
        ("BOX", (0, 0), (-1, -1), 1, GOLD),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#E6D5A8")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF9E8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if usd_cents(deposit):
        total_styles.append(("SPAN", (0, 1), (1, 1)))
    totals.setStyle(TableStyle(total_styles))
    resolved_validity_hours = validity_hours or int(pricing.get("quoteValidityHours") or 24)
    resolved_availability = availability_copy or pricing.get("availabilityCopy") or labels["availability"]
    resolved_footer = quote_footer if quote_footer is not None else pricing.get("quoteFooter")
    closing = (
        f"<b>{_safe(labels['issued'])}:</b> "
        f"{_safe(format_curacao_datetime(pricing.get('createdAt', ''), locale))}<br/>"
        f"{_safe(labels['validity'].format(hours=resolved_validity_hours))}<br/>"
        f"<b>{_safe(resolved_availability)}</b><br/>{_safe(labels['reply'])}"
    )
    if resolved_footer:
        closing += f"<br/><br/>{_safe(resolved_footer, 500)}"
    story.append(KeepTogether([totals, Spacer(1, 5 * mm), Paragraph(closing, small)]))
    document.build(story)

    data = target.read_bytes()
    return str(target), hashlib.sha256(data).hexdigest()
