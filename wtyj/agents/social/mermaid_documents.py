"""Localized Mermaid demo PDFs, signed downloads, and delivery evidence."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi.responses import FileResponse, Response
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from agents.social import mermaid_reservation_store
from shared import mermaid_catalog, state_registry


TEAL = colors.HexColor("#007F86")
DEEP = colors.HexColor("#063B46")
CORAL = colors.HexColor("#F36C5B")
PALE = colors.HexColor("#EAF8F8")
MUTED = colors.HexColor("#4D6870")

LABELS = {
    "en": {"title": "Your Klein Curaçao demo quote", "quote": "Quote", "customer": "Guest", "date": "Trip date", "guests": "Guests", "transport": "Transport", "charges": "Itemized price", "description": "Description", "qty": "Qty", "unit": "Unit", "amount": "Amount", "total": "Total", "included": "Everything included", "schedule": "Your day", "bring": "Bring with you", "rules": "Rules and important notes", "payment": "Next step", "payment_text": "Use the secure demo payment link sent in WhatsApp. It asks for no card or bank details and moves no money.", "arrival": "Arrive at Fishermen's Pier at 06:45. The published island departure is approximately 15:20.", "pickup": "Hotel pickup requested; location and price require confirmation.", "pier": "Meet at Fishermen's Pier", "valid": "This demo quote is valid for 60 minutes.", "available": "For this demo experience, seats are assumed available. No live inventory was checked."},
    "nl": {"title": "Je demo-offerte voor Klein Curaçao", "quote": "Offerte", "customer": "Gast", "date": "Tripdatum", "guests": "Gasten", "transport": "Vervoer", "charges": "Prijsopbouw", "description": "Omschrijving", "qty": "Aantal", "unit": "Per stuk", "amount": "Bedrag", "total": "Totaal", "included": "Alles inbegrepen", "schedule": "Jullie dag", "bring": "Zelf meenemen", "rules": "Regels en belangrijke informatie", "payment": "Volgende stap", "payment_text": "Gebruik de veilige demo-betaallink in WhatsApp. Er worden geen kaart- of bankgegevens gevraagd en er wordt geen geld verplaatst.", "arrival": "Wees om 06:45 bij Fishermen's Pier. Het gepubliceerde vertrek van het eiland is ongeveer 15:20.", "pickup": "Hoteltransfer aangevraagd; locatie en prijs moeten worden bevestigd.", "pier": "Ontmoeting bij Fishermen's Pier", "valid": "Deze demo-offerte is 60 minuten geldig.", "available": "Voor deze demo wordt beschikbaarheid aangenomen. Er is geen live voorraad gecontroleerd."},
    "de": {"title": "Ihr Demo-Angebot für Klein Curaçao", "quote": "Angebot", "customer": "Gast", "date": "Ausflugsdatum", "guests": "Gäste", "transport": "Transport", "charges": "Preisübersicht", "description": "Beschreibung", "qty": "Anzahl", "unit": "Einzelpreis", "amount": "Betrag", "total": "Gesamt", "included": "Alles inklusive", "schedule": "Ihr Tag", "bring": "Bitte mitbringen", "rules": "Regeln und wichtige Hinweise", "payment": "Nächster Schritt", "payment_text": "Nutzen Sie den sicheren Demo-Zahlungslink in WhatsApp. Er fragt keine Karten- oder Bankdaten ab und bewegt kein Geld.", "arrival": "Seien Sie um 06:45 am Fishermen's Pier. Die veröffentlichte Abfahrt von der Insel ist ungefähr um 15:20.", "pickup": "Hotelabholung angefragt; Ort und Preis müssen bestätigt werden.", "pier": "Treffpunkt Fishermen's Pier", "valid": "Dieses Demo-Angebot ist 60 Minuten gültig.", "available": "Für diese Demo wird die Verfügbarkeit angenommen. Es wurde kein Live-Bestand geprüft."},
    "es": {"title": "Tu cotización demo para Klein Curaçao", "quote": "Cotización", "customer": "Pasajero", "date": "Fecha", "guests": "Pasajeros", "transport": "Transporte", "charges": "Precio detallado", "description": "Descripción", "qty": "Cant.", "unit": "Unidad", "amount": "Importe", "total": "Total", "included": "Todo incluido", "schedule": "Tu día", "bring": "Qué llevar", "rules": "Reglas e información importante", "payment": "Siguiente paso", "payment_text": "Usa el enlace seguro de pago demo enviado por WhatsApp. No solicita datos de tarjeta o banco y no mueve dinero.", "arrival": "Llega a Fishermen's Pier a las 06:45. La salida publicada de la isla es aproximadamente a las 15:20.", "pickup": "Recogida en hotel solicitada; ubicación y precio requieren confirmación.", "pier": "Encuentro en Fishermen's Pier", "valid": "Esta cotización demo es válida por 60 minutos.", "available": "Para esta demo se asume disponibilidad. No se consultó un inventario en vivo."},
    "pap": {"title": "Bo oferta demo pa Klein Curaçao", "quote": "Oferta", "customer": "Huésped", "date": "Fecha di trip", "guests": "Huéspednan", "transport": "Transporte", "charges": "Detaye di preis", "description": "Deskripshon", "qty": "Kant.", "unit": "Unidat", "amount": "Montante", "total": "Total", "included": "Tur kos inkluí", "schedule": "Bo dia", "bring": "Hiba ku bo", "rules": "Reglanan i informashon importante", "payment": "Siguiente paso", "payment_text": "Usa e link sigur di pago demo mandá den WhatsApp. E no ta pidi dato di karta òf banko i no ta move plaka.", "arrival": "Yega Fishermen's Pier pa 06:45. E salida publiká for di e isla ta mas o ménos 15:20.", "pickup": "Pickup na hotel ta pidi; lugá i preis mester wordu konfirmá.", "pier": "Topa na Fishermen's Pier", "valid": "E oferta demo aki ta válido pa 60 minüt.", "available": "Pa e demo aki nos ta asumí ku tin lugá. Nos no a kontrolá inventario live."},
    "pt": {"title": "Sua cotação demo para Klein Curaçao", "quote": "Cotação", "customer": "Passageiro", "date": "Data", "guests": "Passageiros", "transport": "Transporte", "charges": "Preço detalhado", "description": "Descrição", "qty": "Qtd.", "unit": "Unidade", "amount": "Valor", "total": "Total", "included": "Tudo incluído", "schedule": "Seu dia", "bring": "O que levar", "rules": "Regras e informações importantes", "payment": "Próximo passo", "payment_text": "Use o link seguro de pagamento demo enviado no WhatsApp. Ele não solicita cartão ou dados bancários e não movimenta dinheiro.", "arrival": "Chegue ao Fishermen's Pier às 06:45. A saída publicada da ilha é aproximadamente às 15:20.", "pickup": "Traslado do hotel solicitado; local e preço exigem confirmação.", "pier": "Encontro no Fishermen's Pier", "valid": "Esta cotação demo é válida por 60 minutos.", "available": "Para esta demo, a disponibilidade é presumida. Nenhum inventário ao vivo foi consultado."},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: object, limit: int = 500) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return html.escape(" ".join(text.split())[:limit])


def _root() -> Path:
    return Path(os.environ.get("MERMAID_DOCUMENT_ROOT", "/app/data/mermaid-documents")).resolve()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(state_registry.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mermaid_documents (
            public_id TEXT PRIMARY KEY,
            tenant_slug TEXT NOT NULL CHECK (tenant_slug='mermaid'),
            reservation_public_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('quote','receipt')),
            locale TEXT NOT NULL,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            content_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (tenant_slug, reservation_public_id, kind)
        );
        CREATE TABLE IF NOT EXISTS mermaid_delivery_jobs (
            public_id TEXT PRIMARY KEY,
            tenant_slug TEXT NOT NULL CHECK (tenant_slug='mermaid'),
            reservation_public_id TEXT NOT NULL,
            document_public_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def _money(currency: str, amount: int) -> str:
    return f"{currency} {amount:,.2f}"


def render_quote_pdf(reservation: dict, target: Path) -> str:
    """Render only snapshotted monetary values; no price calculation occurs here."""
    locale = reservation["language"] if reservation["language"] in LABELS else "en"
    labels = LABELS[locale]
    intake = reservation["intake"]
    money = reservation["monetary_snapshot"]
    catalog = mermaid_catalog.get_catalog()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    styles = getSampleStyleSheet()
    body = ParagraphStyle("MermaidBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.4, leading=13, textColor=DEEP)
    small = ParagraphStyle("MermaidSmall", parent=body, fontSize=7.8, leading=10.5, textColor=MUTED)
    heading = ParagraphStyle("MermaidHeading", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=21, leading=25, textColor=DEEP)
    section = ParagraphStyle("MermaidSection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=TEAL, spaceBefore=3 * mm, spaceAfter=2 * mm)
    marker = ParagraphStyle("MermaidMarker", parent=body, fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.white, alignment=TA_CENTER)
    total = ParagraphStyle("MermaidTotal", parent=body, fontName="Helvetica-Bold", fontSize=17, leading=20, alignment=TA_RIGHT)

    doc = SimpleDocTemplate(
        str(target), pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=13 * mm, bottomMargin=13 * mm,
        title=f"Mermaid demo quote {reservation['public_id']}", author="Mermaid Boat Trips Curaçao",
    )
    story = [
        Paragraph("MERMAID BOAT TRIPS CURAÇAO", heading),
        Paragraph("Klein Curaçao, good vibes included", body),
        Spacer(1, 3 * mm),
        Table([[Paragraph("DEMO QUOTE - NOT A VALID TICKET", marker)]], colWidths=[180 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CORAL), ("BOX", (0, 0), (-1, -1), 0.5, CORAL),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])),
        Spacer(1, 4 * mm), Paragraph(_safe(labels["title"]), heading),
    ]
    transport = labels["pickup"] if intake["pickup_preference"] == "pickup_requested" else labels["pier"]
    reference = reservation["public_id"][-10:].upper()
    detail_rows = [
        [Paragraph(_safe(labels["quote"]), body), Paragraph(_safe(reference), body), Paragraph(_safe(labels["customer"]), body), Paragraph(_safe(reservation["customer_name"], 100), body)],
        [Paragraph(_safe(labels["date"]), body), Paragraph(_safe(intake["trip_date"]), body), Paragraph(_safe(labels["transport"]), body), Paragraph(_safe(transport, 160), body)],
        [Paragraph(_safe(labels["guests"]), body), Paragraph(_safe(f"{intake['adults']} adults, {intake['children']} children 4-12, {intake['infants']} children 0-3"), body), Paragraph("Catalog", body), Paragraph(_safe(reservation["catalog_version"]), body)],
    ]
    detail = Table(detail_rows, colWidths=[26 * mm, 61 * mm, 25 * mm, 68 * mm])
    detail.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B7DCDD")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), DEEP), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([detail, Paragraph(labels["charges"], section)])
    rows = [[labels["description"], labels["qty"], labels["unit"], labels["amount"]]]
    for item in money["items"]:
        rows.append([
            _safe(item["label"]), str(item["quantity"]),
            _money(money["currency"], item["unit_amount"]),
            _money(money["currency"], item["line_total"]),
        ])
    price_table = Table(rows, colWidths=[78 * mm, 22 * mm, 38 * mm, 42 * mm])
    price_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (-1, 1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B7DCDD")),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([
        price_table, Spacer(1, 2 * mm),
        Table([[Paragraph(f"{_safe(labels['total'])}: {_money(money['currency'], money['total'])}", total)]], colWidths=[180 * mm]),
        Paragraph(_safe(labels["available"]), small),
        Paragraph(labels["included"], section),
        Paragraph(" • ".join(_safe(x, 120) for x in catalog["included"]), body),
        Paragraph(labels["schedule"], section), Paragraph(_safe(labels["arrival"]), body),
        Paragraph(labels["bring"], section), Paragraph(" • ".join(_safe(x, 100) for x in catalog["bring"]), body),
        PageBreak(),
        HRFlowable(color=TEAL, thickness=1.5),
        Paragraph(labels["rules"], section),
        Paragraph(_safe(catalog["policies"]["cancellation"]), body), Spacer(1, 3 * mm),
        Paragraph(_safe(catalog["policies"]["safety"]), body), Spacer(1, 3 * mm),
        Paragraph(_safe(catalog["policies"]["insurance"]), body),
        Paragraph("Trip protocol", section),
        Paragraph("Arrive on time, follow all captain and crew instructions, supervise children, use supplied safety equipment as directed, and tell the crew about relevant mobility or dietary requests. Wildlife and exact sea conditions are never guaranteed.", body),
        Paragraph(labels["payment"], section), Paragraph(_safe(labels["payment_text"]), body),
        Spacer(1, 3 * mm), Paragraph(_safe(labels["valid"]), body),
        Spacer(1, 8 * mm), HRFlowable(color=CORAL, thickness=1), Spacer(1, 3 * mm),
        Paragraph("Bring towels and sunscreen. Mermaid takes care of the rest of your included tropical day.", body),
    ])
    doc.build(story)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _doc_id(reservation_id: str, kind: str) -> str:
    return "mdoc_" + hashlib.sha256(f"{reservation_id}:{kind}".encode()).hexdigest()[:24]


def _document(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def create_quote(reservation: dict) -> tuple[dict, dict]:
    """Create one stable quote and one pending idempotent delivery job."""
    public_id = _doc_id(reservation["public_id"], "quote")
    filename = f"Mermaid-Demo-Quote-{reservation['public_id'][-10:].upper()}.pdf"
    target = _root() / reservation["public_id"] / filename
    conn = _conn()
    try:
        existing = conn.execute(
            "SELECT * FROM mermaid_documents WHERE tenant_slug='mermaid' AND reservation_public_id=? AND kind='quote'",
            (reservation["public_id"],),
        ).fetchone()
        if existing is None:
            digest = render_quote_pdf(reservation, target)
            now = _now()
            conn.execute(
                "INSERT INTO mermaid_documents (public_id, tenant_slug, reservation_public_id, kind, locale, "
                "filename, path, sha256, content_type, created_at) VALUES (?, 'mermaid', ?, 'quote', ?, ?, ?, ?, 'application/pdf', ?)",
                (public_id, reservation["public_id"], reservation["language"], filename, str(target), digest, now),
            )
            conn.commit()
            existing = conn.execute("SELECT * FROM mermaid_documents WHERE public_id=?", (public_id,)).fetchone()
        now = _now()
        job_id = "mjob_" + hashlib.sha256(f"quote:{reservation['public_id']}".encode()).hexdigest()[:24]
        conn.execute(
            "INSERT OR IGNORE INTO mermaid_delivery_jobs (public_id, tenant_slug, reservation_public_id, "
            "document_public_id, conversation_id, kind, status, idempotency_key, created_at, updated_at) "
            "VALUES (?, 'mermaid', ?, ?, ?, 'quote', 'pending', ?, ?, ?)",
            (job_id, reservation["public_id"], public_id, reservation["conversation_id"],
             f"mermaid-quote:{reservation['public_id']}", now, now),
        )
        conn.commit()
        job = conn.execute("SELECT * FROM mermaid_delivery_jobs WHERE public_id=?", (job_id,)).fetchone()
        return _document(existing), dict(job)
    finally:
        conn.close()


def mark_delivery(job_id: str, delivered: bool, error: str = "") -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE mermaid_delivery_jobs SET status=?, attempts=attempts+1, last_error=?, updated_at=? "
            "WHERE tenant_slug='mermaid' AND public_id=? AND status!='delivered'",
            ("delivered" if delivered else "failed", str(error or "")[:240], _now(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def delivery_job(job_id: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM mermaid_delivery_jobs WHERE tenant_slug='mermaid' AND public_id=?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def sign_download(public_id: str, expires: int, secret: str) -> str:
    return hmac.new(secret.encode(), f"mermaid:{public_id}:{int(expires)}".encode(), hashlib.sha256).hexdigest()


def build_signed_url(base_url: str, public_id: str, secret: str, now: int | None = None) -> str:
    if not base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")) or not secret:
        raise ValueError("Mermaid signed-download configuration is missing")
    expires = int(time.time() if now is None else now) + 3600
    signature = sign_download(public_id, expires, secret)
    return f"{base_url.rstrip('/')}/api/public/mermaid-document/{public_id}?{urlencode({'expires': expires, 'signature': signature})}"


def verify_download(public_id: str, expires: int, signature: str, secret: str, now: int | None = None) -> bool:
    current = int(time.time() if now is None else now)
    return bool(secret and current <= int(expires) <= current + 3600 and hmac.compare_digest(sign_download(public_id, expires, secret), str(signature or "")))


def document_response(public_id: str, expires: int, signature: str):
    secret = os.environ.get("MERMAID_DEMO_SIGNING_SECRET", "")
    if not verify_download(public_id, expires, signature, secret):
        return Response(status_code=404)
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM mermaid_documents WHERE tenant_slug='mermaid' AND public_id=?", (public_id,)).fetchone()
    finally:
        conn.close()
    doc = _document(row)
    if not doc:
        return Response(status_code=404)
    path = Path(doc["path"]).resolve()
    try:
        path.relative_to(_root())
    except ValueError:
        return Response(status_code=404)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
        return Response(status_code=404)
    return FileResponse(
        str(path), media_type="application/pdf", filename=doc["filename"],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def quote_message(reservation: dict) -> str:
    copy = {
        "en": "Your complete demo quote is ready and attached. It includes the schedule, inclusions, what to bring, and the demo rules. Bring towels and sunscreen; Mermaid takes care of the rest.",
        "nl": "Je volledige demo-offerte is klaar en bijgevoegd, met planning, inbegrepen onderdelen, meeneemlijst en demo-regels. Neem handdoeken en zonnebrand mee; Mermaid zorgt voor de rest.",
        "de": "Ihr vollständiges Demo-Angebot ist fertig und angehängt, mit Ablauf, Leistungen, Packliste und Demo-Regeln. Bringen Sie Handtücher und Sonnencreme mit; Mermaid kümmert sich um den Rest.",
        "es": "Tu cotización demo completa está lista y adjunta, con horario, inclusiones, qué llevar y reglas demo. Trae toallas y protector solar; Mermaid se encarga del resto.",
        "pap": "Bo oferta demo kompleto ta kla i ta adjuntá, ku orario, tur loke ta inkluí, kiko pa hiba i reglanan demo. Hiba handuk i krema solar; Mermaid ta sòru pa e rèst.",
        "pt": "Sua cotação demo completa está pronta e anexada, com horários, inclusões, o que levar e regras demo. Leve toalhas e protetor solar; a Mermaid cuida do resto.",
    }
    return copy.get(reservation["language"], copy["en"])
