"""Render synthetic quote/receipt samples without touching tenant state or sending."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.social import mermaid_documents
from pypdf import PdfReader


def main():
    destination = Path(sys.argv[1])
    for locale in mermaid_documents.LABELS:
        reservation = {
            "public_id": "mermaid_pdf_preview_1234567890",
            "booking_code": "MER-DEMO-PREVIEW",
            "language": locale, "customer_name": "Demo Guest",
            "catalog_version": "mermaid-demo-v1",
            "intake": {"trip_date": "2026-09-05", "adults": 2, "children": 1,
                       "infants": 1, "pickup_preference": "pier"},
            "monetary_snapshot": {"currency": "USD", "total": 375, "items": [
                {"key": "adult", "quantity": 2, "unit_amount": 150, "line_total": 300},
                {"key": "child_4_12", "quantity": 1, "unit_amount": 75, "line_total": 75},
                {"key": "infant_0_3", "quantity": 1, "unit_amount": 0, "line_total": 0},
            ]},
        }
        payment = {"payment_reference": "PAY-DEMO-PREVIEW", "paid_at": "2026-09-03T19:45:00+00:00",
                   "currency": "USD", "amount": 375}
        for kind, renderer, args, pages in (
            ("quote", mermaid_documents.render_quote_pdf, (reservation,), 2),
            ("receipt", mermaid_documents.render_receipt_pdf, (reservation, payment), 1),
        ):
            path = destination / f"{kind}-{locale}.pdf"
            renderer(*args, path)
            pdf = PdfReader(path)
            assert len(pdf.pages) == pages, (locale, kind, len(pdf.pages))
            assert pdf.pages[0].images
            assert pdf.metadata.title.startswith("Mermaid - ")
            print(locale, kind, len(pdf.pages), path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
