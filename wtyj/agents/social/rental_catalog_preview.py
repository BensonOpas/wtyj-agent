"""No-send rental catalog preview using the production PDF and caption paths."""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents.social.ali_quote_delivery import build_customer_quote_text
from agents.social.ali_quote_pdf import render_quote_pdf
from shared import rental_catalog


_PREVIEW_ID = re.compile(r"^[a-f0-9]{32}$")


def _money(cents: int, currency: str) -> dict:
    whole, fraction = divmod(cents, 100)
    return {"currency": currency, "amount": f"{whole}.{fraction:02d}"}


def _preview_root() -> Path:
    return Path(os.environ.get(
        "RENTAL_CATALOG_PREVIEW_ROOT",
        "/app/data/rental-catalog-previews",
    )).resolve()


def _tenant_root(tenant_slug: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", tenant_slug):
        raise rental_catalog.RentalCatalogError("invalid_tenant", status_code=404)
    return _preview_root() / tenant_slug


def resolve_preview_pdf(tenant_slug: str, preview_id: str) -> Path:
    if not _PREVIEW_ID.fullmatch(str(preview_id or "")):
        raise rental_catalog.RentalCatalogError("preview_not_found", status_code=404)
    tenant_root = _tenant_root(tenant_slug).resolve()
    candidate = (tenant_root / preview_id / "quote.pdf").resolve()
    try:
        candidate.relative_to(tenant_root)
    except ValueError as exc:
        raise rental_catalog.RentalCatalogError("preview_not_found", status_code=404) from exc
    if not candidate.is_file():
        raise rental_catalog.RentalCatalogError("preview_not_found", status_code=404)
    return candidate


def render_preview(
    tenant_slug: str,
    document: dict,
    scenario: dict,
    *,
    now: datetime | None = None,
) -> dict:
    calculation = rental_catalog.calculate_preview(document, scenario)
    normalized = rental_catalog.RentalCatalogDocument.model_validate(document).model_dump(mode="json")
    parsed_scenario = rental_catalog.PreviewScenario.model_validate(scenario)
    currency = calculation["currency"]
    if currency != "USD":
        raise rental_catalog.RentalCatalogError("preview_pdf_currency_unsupported")
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    validity_hours = int(normalized["settings"]["quoteValidityHours"])
    preview_id = secrets.token_hex(16)
    quote_reference = f"PREVIEW-{preview_id[:8].upper()}"
    pricing_items = []
    for item in calculation["items"]:
        if item["kind"] == "rental":
            pricing_items.append({
                "code": "vehicle.daily",
                "category": "vehicle",
                "description": item["name"],
                "quantity": item["quantity"],
                "refundable": False,
                "unitPrice": _money(item["unitPriceCents"], currency),
                "total": _money(item["subtotalCents"], currency),
            })
        else:
            pricing_items.append({
                "code": f"extra.{item['billingBasis']}",
                "category": "extra",
                "description": item["name"],
                "quantity": item["quantity"],
                "refundable": False,
                "billingBasis": item["billingBasis"],
                **({"rentalDays": calculation["rentalDays"]} if item["billingBasis"] == "per_day" else {}),
                "unitPrice": _money(item["unitPriceCents"], currency),
                "total": _money(item["subtotalCents"], currency),
            })
    deposit = calculation["refundableSecurityDepositCents"]
    pricing_items.append({
        "code": "charge.deposit",
        "category": "security_deposit",
        "description": "Refundable security deposit",
        "quantity": 1,
        "refundable": True,
        "unitPrice": _money(deposit, currency),
        "total": _money(deposit, currency),
    })
    rental_total = calculation["rentalTotalCents"]
    reservation_deposit = (
        rental_total * int(normalized["settings"]["reservationDepositPercent"]) + 50
    ) // 100
    pricing = {
        "quoteSnapshotId": f"preview-{preview_id}",
        "quoteReference": quote_reference,
        "catalogVersion": "draft",
        "availabilityMode": "request_only",
        "availabilityCopy": normalized["settings"]["availabilityCopy"],
        "quoteFooter": normalized["settings"]["quoteFooter"],
        "quoteValidityHours": validity_hours,
        "currency": currency,
        "rentalDays": calculation["rentalDays"],
        "items": pricing_items,
        "subtotal": _money(calculation["grandTotalCents"], currency),
        "total": _money(calculation["grandTotalCents"], currency),
        "rentalTotal": _money(rental_total, currency),
        "refundableSecurityDeposit": _money(deposit, currency),
        "reservationDeposit": _money(reservation_deposit, currency),
        "createdAt": issued.isoformat().replace("+00:00", "Z"),
        "expiresAt": (
            issued + timedelta(hours=validity_hours)
        ).isoformat().replace("+00:00", "Z"),
    }
    supplements = [
        {
            "id": item["id"],
            "name": item["name"],
            "quantity": item["quantity"],
            "billing_basis": item["billingBasis"],
            "unit_price_usd": _money(item["unitPriceCents"], currency)["amount"],
        }
        for item in calculation["items"] if item["kind"] == "supplement"
    ]
    rental = {
        "vehicle_name": calculation["selection"]["name"],
        "rental_start": parsed_scenario.rentalStart,
        "rental_end": parsed_scenario.rentalEnd,
        "pickup_location": "Synthetic preview pickup",
        "return_location": "Synthetic preview return",
        "supplements": supplements,
    }
    customer = {"name": "Synthetic preview customer", "whatsapp": "+00000000000"}
    output_root = str(_tenant_root(tenant_slug))
    pdf_path, digest = render_quote_pdf(
        preview_id,
        parsed_scenario.locale,
        customer,
        rental,
        pricing,
        output_root=output_root,
        availability_copy=normalized["settings"]["availabilityCopy"],
        quote_footer=normalized["settings"]["quoteFooter"],
        validity_hours=validity_hours,
    )
    quote_record = {
        "quote_reference": quote_reference,
        "locale": parsed_scenario.locale,
        "pricing_json": json.dumps(pricing, separators=(",", ":")),
        "rental_json": json.dumps(rental, separators=(",", ":")),
    }
    return {
        "quote": calculation,
        "customerWhatsAppText": build_customer_quote_text(quote_record),
        "pdfPreviewId": preview_id,
        "pdfSha256": digest,
        "pdfBytes": os.path.getsize(pdf_path),
        "deliveryAttempted": False,
    }
