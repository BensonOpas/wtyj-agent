"""Render 12 maximum-length synthetic A7 samples; no DB, network or sends.

Usage: PYTHONPATH=wtyj python this_file.py OUTPUT_DIR
Reads the tracked Mermaid catalog from this checkout.
The supplied output must differ from the preserved audit baseline directory.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader
from agents.social import mermaid_documents as docs, mermaid_reservation_store as store
from shared import config_loader, mermaid_catalog


def main(destination):
    target_root = Path(destination).resolve()
    if "baseline-60-2026-09-04" in target_root.parts:
        raise ValueError("The baseline artifacts must remain unchanged")
    config_loader._CONFIG_PATH = str(Path(__file__).resolve().parents[2] / "clients/mermaid/config/client.json")
    config_loader._cache = {}
    catalog = mermaid_catalog.get_catalog()
    name = ("Alexandra María van der Meer Çosta " * 5)[:160]
    location = ("Piscadera Bay Resort, bungalow 342, reception entrance beside the blue gate, " * 3)[:160]
    report = []
    for locale in docs.LABELS:
        intake = {"trip_date": "2026-09-12", "adults": 2, "children": 1, "infants": 1,
                  "customer_name": name, "contact_phone": "+12025550123",
                  "pickup_preference": "pickup_requested", "pickup_location": location,
                  "language": locale}
        money = store._money_snapshot(intake, catalog)
        reservation = {"public_id": "mermaid_audit_342_1234567890", "booking_code": "MER-DEMO-A7QA",
                       "language": locale, "customer_name": name, "intake": intake,
                       "monetary_snapshot": money, "catalog_version": catalog["version"]}
        payment = {"payment_reference": "PAY-DEMO-A7QA", "paid_at": "2026-09-04T11:45:00+00:00",
                   "currency": money["currency"], "amount": money["total"]}
        for kind in ("quote", "receipt"):
            filename = ("Mermaid - Demo Trip Quote - 1234567890.pdf" if kind == "quote"
                        else "Mermaid - Demo Payment Receipt - MER-DEMO-A7QA.pdf")
            path = target_root / locale / filename
            digest = (docs.render_quote_pdf(reservation, path) if kind == "quote"
                      else docs.render_receipt_pdf(reservation, payment, path))
            pdf = PdfReader(path)
            text = " ".join(page.extract_text() for page in pdf.pages)
            normalized = " ".join(text.split())
            assert len(pdf.pages) == 1 and pdf.pages[0].images
            assert name.strip() in normalized and normalized.count(location.strip()) == 1
            assert docs.DOCUMENT_NOTICES[locale][f"{kind}_banner"] in normalized
            assert sum(item["line_total"] for item in money["items"]) == money["total"] == payment["amount"]
            assert docs._money(payment["currency"], payment["amount"]) in normalized
            assert pdf.trailer["/Root"]["/Lang"] == docs.DOCUMENT_LANGUAGES[locale]
            report.append({"locale": locale, "kind": kind, "file": str(path), "sha256": digest,
                           "title": pdf.metadata.title, "pages": len(pdf.pages),
                           "images": len(pdf.pages[0].images), "tagged": True,
                           "language": str(pdf.trailer["/Root"]["/Lang"]),
                           "name_characters": len(name), "pickup_characters": len(location),
                           "pickup_occurrences": normalized.count(location.strip()),
                           "currency": money["currency"], "total": money["total"],
                           "line_items": money["items"], "demo_banner": docs.DOCUMENT_NOTICES[locale][f"{kind}_banner"]})
    (target_root / "inspection.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"samples": len(report), "all_one_page": True, "output": str(target_root)}))


if __name__ == "__main__":
    main(sys.argv[1])
