"""Issue 330: localized Mermaid quote PDF and signed delivery."""

import hashlib
from pathlib import Path

import pytest
from pypdf import PdfReader

from agents.social import mermaid_documents, mermaid_reservation_store
from shared import config_loader, state_registry


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "clients" / "mermaid" / "config" / "client.json"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(CONFIG))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("MERMAID_DOCUMENT_ROOT", str(tmp_path / "documents"))


def reservation(locale="en"):
    return mermaid_reservation_store.confirm_reservation(
        f"guest-{locale}",
        {"trip_date": "2026-09-05", "adults": 2, "children": 1, "infants": 1,
         "customer_name": "Ana Çosta", "pickup_preference": "pier", "language": locale,
         "phase": "summary_confirmed"},
        idempotency_key=f"confirm-{locale}",
    )


@pytest.mark.parametrize("locale", ["en", "nl", "de", "es", "pap", "pt"])
def test_six_localized_quote_pdfs_render_required_content(locale):
    item, job = mermaid_documents.create_quote(reservation(locale))
    path = Path(item["path"])
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) == 2
    assert "DEMO QUOTE - NOT A VALID TICKET" in text
    assert "Ana Çosta" in text
    assert "2026-09-05" in text
    assert "USD 375.00" in text
    assert "Fishermen's Pier" in text
    assert "06:45" in text and "15:20" in text
    assert "Insurance coverage is not verified" in text
    assert path.name == item["filename"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    assert item["content_type"] == "application/pdf"
    assert job["status"] == "pending"


def test_renderer_displays_snapshot_without_recalculating(monkeypatch):
    value = reservation()
    value["monetary_snapshot"]["total"] = 999
    value["monetary_snapshot"]["items"][0]["line_total"] = 777
    target = Path(__import__("tempfile").mkdtemp()) / "quote.pdf"
    mermaid_documents.render_quote_pdf(value, target)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(target)).pages)
    assert "USD 999.00" in text
    assert "USD 777.00" in text


def test_quote_and_delivery_job_are_idempotent():
    value = reservation()
    first_doc, first_job = mermaid_documents.create_quote(value)
    second_doc, second_job = mermaid_documents.create_quote(value)
    assert first_doc == second_doc
    assert first_job["public_id"] == second_job["public_id"]
    mermaid_documents.mark_delivery(first_job["public_id"], True)
    mermaid_documents.mark_delivery(first_job["public_id"], False, "late retry")
    assert mermaid_documents.delivery_job(first_job["public_id"])["status"] == "delivered"


def test_signed_download_is_expiry_and_signature_bound():
    item, _ = mermaid_documents.create_quote(reservation())
    url = mermaid_documents.build_signed_url("https://demo.example", item["public_id"], "secret", now=1000)
    assert item["public_id"] in url
    signature = mermaid_documents.sign_download(item["public_id"], 4600, "secret")
    assert mermaid_documents.verify_download(item["public_id"], 4600, signature, "secret", now=1000)
    assert not mermaid_documents.verify_download(item["public_id"], 4600, signature, "wrong", now=1000)
    assert not mermaid_documents.verify_download(item["public_id"], 4600, signature, "secret", now=4601)
