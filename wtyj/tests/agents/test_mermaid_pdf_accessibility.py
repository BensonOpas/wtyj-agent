"""Issue 342 A7: actual PDF content and parent-tree semantics, without sends."""
from pathlib import Path

import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

from agents.social import mermaid_documents as docs, mermaid_reservation_store as store
from shared import config_loader, mermaid_catalog

ROOT = Path(__file__).resolve().parents[3]
NAME = ("Alexandra María van der Meer Çosta " * 5)[:160]
LOCATION = ("Piscadera Bay Resort, bungalow 342, reception entrance beside the blue gate, " * 3)[:160]


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(ROOT / "clients/mermaid/config/client.json"))
    monkeypatch.setattr(config_loader, "_cache", {})


def sample(locale):
    intake = {"customer_name": NAME, "trip_date": "2026-09-12", "adults": 2,
              "children": 1, "infants": 1, "contact_phone": "+12025550123",
              "pickup_preference": "pickup_requested", "pickup_location": LOCATION,
              "language": locale}
    money = store._money_snapshot(intake, mermaid_catalog.get_catalog())
    reservation = {"public_id": "mermaid_audit_342_1234567890", "booking_code": "MER-DEMO-A7QA",
                   "language": locale, "customer_name": NAME, "intake": intake,
                   "monetary_snapshot": money, "catalog_version": mermaid_catalog.get_catalog()["version"]}
    payment = {"payment_reference": "PAY-DEMO-A7QA", "paid_at": "2026-09-04T07:45:00-04:00",
               "currency": money["currency"], "amount": money["total"]}
    return reservation, payment


def nodes(node):
    node = node.get_object()
    yield node
    children = node.get("/K", [])
    if isinstance(children, list):
        for child in children:
            if hasattr(child, "get_object") and isinstance(child.get_object(), dict):
                yield from nodes(child)


def assert_structure(reader):
    root = reader.trailer["/Root"]
    tree = root["/StructTreeRoot"]
    document = tree["/K"][0].get_object()
    assert document["/S"] == "/Document"
    all_nodes = list(nodes(document))
    assert len([node for node in all_nodes if node["/S"] == "/H1"]) == 1
    assert any(node["/S"] == "/H2" for node in all_nodes)
    assert any(node["/S"] == "/Table" for node in all_nodes)
    parents = tree["/ParentTree"]["/Nums"]
    for page_number, page in enumerate(reader.pages):
        assert page["/StructParents"] == page_number and page["/Tabs"] == "/S"
        assert parents[2 * page_number] == page_number
        references = parents[2 * page_number + 1]
        stream = ContentStream(page.get_contents(), reader)
        stack, seen = [], []
        for operands, operator in stream.operations:
            if operator == b"BDC":
                mcid = operands[1]["/MCID"]
                seen.append(mcid)
                stack.append("content")
                element = references[mcid].get_object()
                assert element["/K"] == mcid
                assert element["/S"] == operands[0]
                assert element["/Pg"].indirect_reference == page.indirect_reference
                assert element["/ActualText"]
            elif operator == b"BMC":
                assert operands[0] == "/Artifact"
                stack.append("artifact")
            elif operator == b"EMC":
                assert stack
                stack.pop()
            elif operator in {b"Tj", b"TJ", b"'", b'"'}:
                assert stack and stack[-1] == "content", "Untagged visible text"
        assert not stack
        assert seen == list(range(len(references)))
    for node in all_nodes:
        if node["/S"] == "/Table":
            rows = [r.get_object() for r in node["/K"]]
            assert all(row["/S"] == "/TR" for row in rows)
            for row in rows:
                assert all(c.get_object()["/S"] in {"/TH", "/TD"} for c in row["/K"])
        if node["/S"] == "/TH":
            assert node["/A"]["/Scope"] in {"/Row", "/Column"}
    return all_nodes


@pytest.mark.parametrize("locale", ["en", "nl", "de", "es", "pap", "pt"])
@pytest.mark.parametrize("kind", ["quote", "receipt"])
def test_maximum_length_localized_document_has_complete_ordered_content(locale, kind, tmp_path):
    reservation, payment = sample(locale)
    target = tmp_path / f"{kind}-{locale}.pdf"
    if kind == "quote":
        docs.render_quote_pdf(reservation, target)
    else:
        docs.render_receipt_pdf(reservation, payment, target)
    reader = PdfReader(target)
    assert len(reader.pages) == 1
    assert reader.pages[0].images
    text = " ".join(reader.pages[0].extract_text().split())
    notices = docs.DOCUMENT_NOTICES[locale]
    assert notices[f"{kind}_banner"] in text
    assert "DEMO" in text
    if locale != "en":
        assert docs.DOCUMENT_NOTICES["en"][f"{kind}_banner"] not in text
        assert docs.DOCUMENT_NOTICES["en"]["receipt_subtitle"] not in text
    assert NAME.strip() in text and text.count(LOCATION.strip()) == 1
    assert reader.metadata.title.startswith("Mermaid - ")
    assert reader.trailer["/Root"]["/Lang"] == docs.DOCUMENT_LANGUAGES[locale]
    all_nodes = assert_structure(reader)
    logical_text = " ".join(node.get("/ActualText", "") for node in all_nodes)
    assert logical_text.index(notices[f"{kind}_banner"]) < logical_text.index(NAME.strip())
    if kind == "receipt":
        assert notices["receipt_subtitle"] in text
        assert "2026-09-04 11:45 UTC" in text
        assert docs.DOCUMENT_COPY[locale]["receipt_disclaimer"] in text
    else:
        assert docs.LABELS[locale]["payment_text"] in text
    money = reservation["monetary_snapshot"]
    assert sum(item["line_total"] for item in money["items"]) == money["total"] == payment["amount"]
    for item in money["items"]:
        if item["quantity"]:
            assert docs._money(money["currency"], item["line_total"]) in text
    assert docs._money(payment["currency"], payment["amount"]) in text


def test_escaped_guest_markup_remains_data(tmp_path):
    reservation, payment = sample("en")
    reservation["customer_name"] = '<script>alert("demo")</script> & Guest'
    path = tmp_path / "escaped.pdf"
    docs.render_receipt_pdf(reservation, payment, path)
    assert reservation["customer_name"] in PdfReader(path).pages[0].extract_text()
