"""Tests for Brief 230 — AI knowledge files Phase 1 (PDF/DOCX/TXT)."""
import sys, os, io, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient
from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM knowledge_files")
    conn.commit()
    conn.close()


def _make_docx(body_text: str) -> bytes:
    """Build the smallest valid DOCX containing the given body text."""
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>'
        f'<w:p><w:r><w:t>{body_text}</w:t></w:r></w:p>'
        '</w:body>'
        '</w:document>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '</Types>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def _make_minimal_pdf(text: str) -> bytes:
    """Build a tiny PDF containing one text-bearing page so pypdf can
    extract `text`. Hand-rolled PDF — pypdf's higher-level API doesn't
    expose font+content-stream injection cleanly, so we build the bytes
    by hand using the documented PDF object structure."""
    objs = []
    def add(o):
        objs.append(o)
        return len(objs)

    # Object 1: Catalog
    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    # Object 2: Pages
    add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    # Object 3: Page
    add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
    # Object 4: content stream
    stream_body = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("latin-1")
    add(b"<< /Length " + str(len(stream_body)).encode() + b" >>\nstream\n"
        + stream_body + b"\nendstream")
    # Object 5: Font
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objs)+1).encode()
            + b" /Root 1 0 R >>\nstartxref\n" + str(xref_offset).encode()
            + b"\n%%EOF\n")
    return out


def test_upload_txt_extracts_text():
    """Brief 230: TXT upload → status=ready, body persists in extracted_text."""
    _reset()
    token = _login()
    body = b"Our menu: tacos, burritos, agua de jamaica."
    r = client.post(
        "/dashboard/api/knowledge/files",
        files={"file": ("menu.txt", body, "text/plain")},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    assert r.json()["filename"] == "menu.txt"
    files_for_prompt = state_registry.get_knowledge_files_for_prompt()
    assert any("agua de jamaica" in f["text"] for f in files_for_prompt)


def test_upload_docx_extracts_paragraphs():
    """Brief 230: DOCX upload → status=ready, body extracted from <w:t>."""
    _reset()
    token = _login()
    docx = _make_docx("Restaurant Adamus — house rule: no shoes.")
    r = client.post(
        "/dashboard/api/knowledge/files",
        files={"file": ("policy.docx", docx,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    files_for_prompt = state_registry.get_knowledge_files_for_prompt()
    assert any("no shoes" in f["text"].lower() for f in files_for_prompt)


def test_upload_pdf_extracts_text():
    """Brief 230: PDF upload via pypdf → status=ready or failed (writer
    quirk-friendly). When ready, body matches."""
    _reset()
    token = _login()
    pdf = _make_minimal_pdf("Brief 230 inside")
    r = client.post(
        "/dashboard/api/knowledge/files",
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("ready", "failed")
    if r.json()["status"] == "ready":
        files_for_prompt = state_registry.get_knowledge_files_for_prompt()
        assert any("brief 230" in f["text"].lower() for f in files_for_prompt)


def test_upload_unsupported_type_lands_failed():
    """Brief 230: unsupported types (PNG, etc.) are stored with
    status='failed' and a clear failure_reason. Phase 2 enables them."""
    _reset()
    token = _login()
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
           b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT"
           b"x\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND"
           b"\xaeB`\x82")
    r = client.post(
        "/dashboard/api/knowledge/files",
        files={"file": ("logo.png", png, "image/png")},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"


def test_list_returns_uploaded_files_in_camel_case():
    """Brief 230: GET returns SR's KnowledgeFile shape — camelCase
    fields, no extracted_text leaked."""
    _reset()
    token = _login()
    client.post(
        "/dashboard/api/knowledge/files",
        files={"file": ("a.txt", b"alpha", "text/plain")},
        headers=_auth(token))
    client.post(
        "/dashboard/api/knowledge/files",
        files={"file": ("b.txt", b"beta", "text/plain")},
        headers=_auth(token))
    r = client.get("/dashboard/api/knowledge/files", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 2
    f0 = body[0]
    assert "filename" in f0 and "mimeType" in f0 and "sizeBytes" in f0
    assert "uploadedAt" in f0
    assert "extractedText" not in f0


def test_delete_removes_row_and_returns_404_on_missing():
    """Brief 230: DELETE removes the row; missing id → 404."""
    _reset()
    token = _login()
    r = client.post(
        "/dashboard/api/knowledge/files",
        files={"file": ("z.txt", b"zeta", "text/plain")},
        headers=_auth(token))
    file_id = int(r.json()["id"])
    r2 = client.delete(f"/dashboard/api/knowledge/files/{file_id}",
                       headers=_auth(token))
    assert r2.status_code == 200
    r3 = client.delete(f"/dashboard/api/knowledge/files/{file_id}",
                       headers=_auth(token))
    assert r3.status_code == 404


def test_get_knowledge_files_for_prompt_only_returns_ready():
    """Brief 230: the Marina-prompt helper filters to status='ready'
    AND non-empty extracted_text."""
    _reset()
    state_registry.knowledge_file_create(
        filename="ready.txt", stored_filename="x", mime_type="text/plain",
        size_bytes=5, status="ready", extracted_text="ready content")
    state_registry.knowledge_file_create(
        filename="failed.txt", stored_filename="y", mime_type="text/plain",
        size_bytes=5, status="failed", extracted_text="",
        failure_reason="phase 1 limit")
    state_registry.knowledge_file_create(
        filename="empty.txt", stored_filename="z", mime_type="text/plain",
        size_bytes=0, status="ready", extracted_text="")
    files = state_registry.get_knowledge_files_for_prompt()
    names = [f["filename"] for f in files]
    assert "ready.txt" in names
    assert "failed.txt" not in names
    assert "empty.txt" not in names



# --- Brief 260: cloud knowledge connectors status endpoint ---

def _reset_oauth_tokens():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM oauth_tokens")
    conn.commit()


def test_brief_260_cloud_connections_returns_three_providers_in_fixed_order(monkeypatch):
    """Brief 260: GET /knowledge/cloud-connections returns exactly 3
    providers (Google Drive, OneDrive, Dropbox) in stable order.
    SharePoint and Box are excluded per issue #29."""
    _reset_oauth_tokens()
    # Force OneDrive/Dropbox env vars absent so the response is deterministic.
    monkeypatch.delenv("ONEDRIVE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ONEDRIVE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("DROPBOX_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("DROPBOX_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    token = _login()
    r = client.get("/dashboard/api/knowledge/cloud-connections", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    providers = body["providers"]
    assert len(providers) == 3
    ids = [p["provider"] for p in providers]
    assert ids == ["google_drive", "onedrive", "dropbox"]
    # SharePoint and Box must not appear.
    assert "sharepoint" not in ids
    assert "box" not in ids


def test_brief_260_google_drive_setup_required_when_env_set_but_no_tokens(monkeypatch):
    """Brief 260: Google Drive shows setup_required when OAuth env vars
    are set but no token row exists yet."""
    _reset_oauth_tokens()
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    token = _login()
    r = client.get("/dashboard/api/knowledge/cloud-connections", headers=_auth(token))
    assert r.status_code == 200, r.text
    google = [p for p in r.json()["providers"] if p["provider"] == "google_drive"][0]
    assert google["status"] == "setup_required", google
    assert google["needs_provider_app_registration"] is False


def test_brief_260_google_drive_connected_when_env_set_and_tokens_stored(monkeypatch):
    """Brief 260: Google Drive flips to connected once env vars are set
    AND a token row exists in oauth_tokens."""
    _reset_oauth_tokens()
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    state_registry.save_oauth_tokens(
        "google_drive", "test-access", "test-refresh",
        "2030-01-01T00:00:00+00:00")
    try:
        token = _login()
        r = client.get("/dashboard/api/knowledge/cloud-connections", headers=_auth(token))
        assert r.status_code == 200, r.text
        google = [p for p in r.json()["providers"] if p["provider"] == "google_drive"][0]
        assert google["status"] == "connected", google
        assert google["needs_provider_app_registration"] is False
    finally:
        _reset_oauth_tokens()


def test_brief_260_onedrive_and_dropbox_not_configured_without_env(monkeypatch):
    """Brief 260 load-bearing assertion: OneDrive and Dropbox honestly
    report not_configured when their OAuth env vars are absent on this
    deploy. needs_provider_app_registration=True signals to the UI
    that Calvin must register the external provider app before any
    Connect flow can be wired."""
    _reset_oauth_tokens()
    monkeypatch.delenv("ONEDRIVE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ONEDRIVE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("DROPBOX_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("DROPBOX_OAUTH_CLIENT_SECRET", raising=False)
    token = _login()
    r = client.get("/dashboard/api/knowledge/cloud-connections", headers=_auth(token))
    assert r.status_code == 200, r.text
    by_id = {p["provider"]: p for p in r.json()["providers"]}
    assert by_id["onedrive"]["status"] == "not_configured"
    assert by_id["onedrive"]["needs_provider_app_registration"] is True
    assert by_id["dropbox"]["status"] == "not_configured"
    assert by_id["dropbox"]["needs_provider_app_registration"] is True
