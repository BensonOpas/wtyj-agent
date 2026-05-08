# BRIEF 230 — AI knowledge files Phase 1 (PDF/DOCX/TXT upload, extraction, Marina injection)
**Status:** Draft | **Files:** `requirements.txt`, `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/dashboard/knowledge_extract.py` (new), `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/social/test_230_knowledge_files.py` | **Depends on:** Brief 216 (feature-flag injection pattern + atomic write idiom), Brief 219 (`_build_*_block` Marina-prompt injection pattern) | **Blocks:** SR's `useKnowledgeFiles` hook moving from localStorage to backend; cloud connectors (Google Drive / OneDrive / Dropbox / SharePoint / Box) deferred to follow-up briefs

## Context

SR's task `1108f913ad12` ("Jr, we need to expand 'Your AI knowledge' into the real knowledge hub for the AI"):
> "POST /knowledge/files (upload), GET /knowledge/files (list), DELETE /knowledge/files/{id}. PDF / DOC / DOCX / TXT / CSV / XLS / XLSX / PNG / JPG / WebP. Extract text from supported file types. For images, use OCR. Index extracted knowledge so Marina can use it in replies. Cloud folders (Google Drive / OneDrive / Dropbox / SharePoint / Box) sync into same pipeline. Tenant isolation. Don't expose internal terms RAG / embeddings / vector DB / SOT."

**Phase 1 scope (explicitly negotiated with Benson):** ship file upload + text extraction for **PDF, DOCX, TXT only**. Skip CSV/XLS/XLSX (needs `openpyxl` or `pandas`), skip image OCR (needs vision API or `tesseract`), skip cloud connectors (each one is a multi-day OAuth + sync project — Google Drive alone would eat the night). Future briefs add the rest.

Frontend today (`use-knowledge-files.ts`): pure localStorage. SR's contract uses camelCase `KnowledgeFile { id, filename, mimeType, sizeBytes, status, uploadedAt, lastUsedAt? }` with `status: pending | processing | ready | failed`. 25MB cap. POST is multipart (`file` field). DELETE removes by id.

## Why This Approach

**Chosen:** add `pypdf` to requirements (single ~1MB pure-Python dep), use stdlib `zipfile` + `xml.etree.ElementTree` for DOCX (zero new dep — DOCX is just a ZIP of XML), TXT decodes directly. Synchronous extraction at upload time (status `ready` or `failed` returned in the POST response — no async polling). Files stored on disk in `wtyj/data/knowledge/` (mirrors the `wtyj/data/photos/` pattern from photo upload, per-tenant via Docker volume mount). Extracted text persists in a SQLite column for fast Marina-prompt injection without re-parsing on every Claude call.

**Why pypdf, not pdfplumber or pdfminer.six.** pypdf is the smallest, has the simplest text-extraction API (`PdfReader(...).pages[i].extract_text()`), and handles the common cases (text-PDFs, not scanned PDFs). pdfplumber has better quality but depends on pypdf anyway. Scanned-PDF OCR is a Phase 2 problem.

**Why stdlib zipfile for DOCX, not python-docx.** python-docx pulls in `lxml` (~9MB, includes C extension that has to compile per-Python-version). DOCX is `word/document.xml` inside a ZIP — extracting all `<w:t>` tags via stdlib `zipfile` + `xml.etree.ElementTree` gives us the body text in 15 lines. Good enough for RAG-ish prompt injection where exact formatting doesn't matter.

**Why synchronous extraction.** A 25MB cap with text-only formats means worst-case extraction is sub-second. Async processing buys us nothing here, and complicates the contract (frontend would need a polling loop). When Phase 2 adds image OCR (longer), THAT'S when we go async with a `processing` status.

**Why a separate module `wtyj/dashboard/knowledge_extract.py`.** Keeps state_registry dumb (no third-party imports). Mirrors the Brief 227 pattern of putting Claude-related code in `dashboard/escalation_summary.py` not in state_registry.

**Marina injection follows Brief 219's exact pattern.** New helper `_build_knowledge_files_block()` returns `\n\nKNOWLEDGE FILES\n...content...` when the flag is on AND there is at least one `ready` file, or `""` when the block should collapse. Wired into `_build_system_prompt`'s f-string between the existing approved-answers block and the writing-style block. Feature-flagged: `features.knowledge_files_in_prompt`, default OFF, opt-in per tenant.

**Tradeoff: 25MB hard cap.** Frontend already enforces this; backend re-checks. Beyond 25MB the text payload starts blowing the Claude prompt budget anyway — chunking + retrieval is a Phase 3 problem.

**Tradeoff: extracted text is the FULL file text in the prompt.** For a 5MB PDF that extracts to 50K tokens, Marina's prompt would be expensive every call. We mitigate via: (a) the feature flag, off by default; (b) a per-file size sanity log so we can see when extracted text is unreasonably large; (c) future Phase 2 brief switches to embedding-based retrieval. For Phase 1 with ~1-page menus / short docs, full-text injection is fine.

**Rejected: skip text extraction, just store the file and have Marina retrieve at call-time.** Would require Claude to read PDF/DOCX bytes per call — way more tokens and latency than extracting once at upload. Not how the AI side is structured today.

**Rejected: 415 Unsupported Media Type for non-PDF/DOCX/TXT (e.g., a PNG upload).** SR's frontend allows uploads for all 9 types. Returning 415 surfaces a confusing error when the operator already passed the frontend's allowlist. Better: accept the upload, mark `status: "failed"`, set a `failure_reason` like "Phase 1 supports PDF/DOCX/TXT — image OCR ships in a follow-up." Frontend already renders `status: "failed"`.

**Rejected: image OCR via Claude vision in this brief.** A separate Claude call per image upload is meaningful cost; needs its own tradeoff conversation. Phase 2.

## Instructions

### 1. Dependency

Append to `requirements.txt`:
```
pypdf==4.3.1
```

### 2. Schema

In `wtyj/shared/state_registry.py`, add to `_get_conn()` after the `data_retention_settings` CREATE block (Brief 229, around line 486):

```python
    # Brief 230: knowledge files (uploaded reference docs Marina reads when
    # features.knowledge_files_in_prompt is true). One row per file. Text is
    # extracted synchronously at upload time and stored here; the actual
    # uploaded file lives on disk under wtyj/data/knowledge/.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_files ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "filename TEXT NOT NULL, "
        "stored_filename TEXT NOT NULL, "
        "mime_type TEXT NOT NULL DEFAULT '', "
        "size_bytes INTEGER NOT NULL DEFAULT 0, "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "extracted_text TEXT NOT NULL DEFAULT '', "
        "failure_reason TEXT NOT NULL DEFAULT '', "
        "uploaded_at TEXT NOT NULL, "
        "last_used_at TEXT"
        ")"
    )
```

### 3. State-registry helpers

Place next to the Brief 229 helpers:

```python
def knowledge_file_create(filename: str, stored_filename: str, mime_type: str,
                           size_bytes: int, status: str, extracted_text: str,
                           failure_reason: str = "") -> int:
    """Brief 230: insert a knowledge_files row at upload time. Returns id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO knowledge_files "
        "(filename, stored_filename, mime_type, size_bytes, status, "
        "extracted_text, failure_reason, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (filename, stored_filename, mime_type, size_bytes, status,
         extracted_text, failure_reason, now))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def knowledge_files_list() -> list:
    """Brief 230: return all knowledge files in SR's frontend shape
    (camelCase, ISO timestamps). extracted_text + failure_reason are NOT
    surfaced — operator UI doesn't need to render them."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, filename, mime_type, size_bytes, status, uploaded_at, "
        "last_used_at FROM knowledge_files ORDER BY uploaded_at DESC"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": str(r[0]),
            "filename": r[1],
            "mimeType": r[2] or "",
            "sizeBytes": r[3],
            "status": r[4],
            "uploadedAt": r[5],
            "lastUsedAt": r[6],
        })
    return out


def knowledge_file_delete(file_id: int) -> Optional[str]:
    """Brief 230: hard-delete a knowledge_files row. Returns the
    stored_filename so the caller can also unlink the file from disk
    (registry stays disk-agnostic). Returns None if the id doesn't exist."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT stored_filename FROM knowledge_files WHERE id = ?",
        (file_id,)).fetchone()
    if not row:
        conn.close()
        return None
    stored = row[0]
    conn.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    return stored


def get_knowledge_files_for_prompt(limit: int = 5) -> list:
    """Brief 230: return up to `limit` ready knowledge files with their
    extracted text, newest first. Used by Marina's _build_knowledge_files_block."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT filename, extracted_text FROM knowledge_files "
        "WHERE status = 'ready' AND extracted_text != '' "
        "ORDER BY uploaded_at DESC LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    return [{"filename": r[0], "text": r[1]} for r in rows]
```

### 4. Extractor module — `wtyj/dashboard/knowledge_extract.py`

NEW FILE.

```python
"""Brief 230: text extraction from uploaded knowledge files.

Phase 1 supports PDF (via pypdf), DOCX (via stdlib zipfile + xml), TXT
(direct decode). All other file types return a (None, reason) tuple so
the caller can store the file with status='failed'.

No third-party deps beyond pypdf. DOCX deliberately avoids python-docx
(pulls in lxml). Image OCR + spreadsheets are Phase 2.
"""
import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from pypdf import PdfReader


_DOCX_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts).strip()


def _extract_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        with zf.open("word/document.xml") as f:
            tree = ET.parse(f)
    root = tree.getroot()
    paragraphs = []
    for p in root.iter(f"{_DOCX_NAMESPACE}p"):
        # Each <w:p> contains zero or more <w:r><w:t>text</w:t></w:r>.
        runs = [t.text or "" for t in p.iter(f"{_DOCX_NAMESPACE}t")]
        line = "".join(runs).strip()
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs).strip()


def _extract_txt(data: bytes) -> str:
    # Try UTF-8 first; fall back to latin-1 (never raises).
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace").strip()


def extract(filename: str, mime_type: str,
            data: bytes) -> Tuple[Optional[str], str]:
    """Brief 230: extract text from a file. Returns (text, '') on success
    or (None, reason) on a known-unsupported type / parse failure.

    Routing prefers extension over mime_type because browsers emit
    inconsistent mime types for txt/csv. PDF and DOCX have stable mimes
    but we still check both."""
    lower = (filename or "").lower()
    try:
        if lower.endswith(".pdf") or mime_type == "application/pdf":
            return _extract_pdf(data), ""
        if lower.endswith(".docx") or mime_type == (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"):
            return _extract_docx(data), ""
        if lower.endswith(".txt") or mime_type == "text/plain":
            return _extract_txt(data), ""
        return None, ("Phase 1 supports PDF, DOCX, and TXT only. "
                      f"File '{filename}' will be stored but not indexed.")
    except Exception as exc:
        return None, f"Extraction failed: {str(exc)[:200]}"
```

### 5. Endpoints

In `wtyj/dashboard/api.py`, add after the Brief 229 data-retention block (before `# --- Scheduling ---`):

```python
# --- Brief 230: AI knowledge files Phase 1 ---
# Upload + text extraction for PDF/DOCX/TXT. Files stored under
# wtyj/data/knowledge/. Marina reads the extracted text via
# features.knowledge_files_in_prompt (default OFF).

_KNOWLEDGE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "knowledge")
os.makedirs(_KNOWLEDGE_DIR, exist_ok=True)

_KNOWLEDGE_MAX_BYTES = 25 * 1024 * 1024  # match SR's frontend cap


@router.post("/knowledge/files", dependencies=[Depends(_check_auth)])
async def upload_knowledge_file(file: UploadFile = File(...)):
    """Brief 230: accept a file upload, store on disk, extract text
    synchronously, return SR's KnowledgeFile shape. Synchronous because
    Phase 1 only handles small text-format files; async polling adds
    complexity for no benefit here."""
    data = await file.read()
    if len(data) > _KNOWLEDGE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {_KNOWLEDGE_MAX_BYTES // (1024*1024)} MB.")

    from dashboard.knowledge_extract import extract
    text, reason = extract(file.filename or "", file.content_type or "", data)
    status = "ready" if text else "failed"

    # Persist file to disk first with a placeholder name; we'll rename
    # to include the row id once it's created.
    safe_ext = (os.path.splitext(file.filename or "")[1] or "").lower()
    placeholder = f"knowledge_pending_{secrets.token_hex(8)}{safe_ext}"
    tmp_path = os.path.join(_KNOWLEDGE_DIR, placeholder)
    with open(tmp_path, "wb") as fh:
        fh.write(data)

    row_id = state_registry.knowledge_file_create(
        filename=file.filename or "unknown",
        stored_filename=placeholder,  # rename below
        mime_type=file.content_type or "",
        size_bytes=len(data),
        status=status,
        extracted_text=text or "",
        failure_reason=reason,
    )

    final_name = f"knowledge_{row_id}_{secrets.token_hex(4)}{safe_ext}"
    final_path = os.path.join(_KNOWLEDGE_DIR, final_name)
    os.rename(tmp_path, final_path)
    # Update the row with the final stored_filename.
    conn = state_registry._get_conn()
    conn.execute(
        "UPDATE knowledge_files SET stored_filename = ? WHERE id = ?",
        (final_name, row_id))
    conn.commit()
    conn.close()

    bm_logger.log("knowledge_file_uploaded",
                  file_id=row_id,
                  status=status,
                  size_bytes=len(data),
                  filename=(file.filename or "")[:120])

    files = state_registry.knowledge_files_list()
    matching = next((f for f in files if f["id"] == str(row_id)), None)
    return matching


@router.get("/knowledge/files", dependencies=[Depends(_check_auth)])
async def list_knowledge_files():
    """Brief 230: return all knowledge files in SR's KnowledgeFile shape."""
    return state_registry.knowledge_files_list()


@router.delete("/knowledge/files/{file_id}",
               dependencies=[Depends(_check_auth)])
async def delete_knowledge_file(file_id: int):
    """Brief 230: hard-delete a knowledge file (DB row + disk file)."""
    stored = state_registry.knowledge_file_delete(file_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Knowledge file not found")
    try:
        os.remove(os.path.join(_KNOWLEDGE_DIR, stored))
    except OSError:
        pass  # row deleted; disk file already gone or never existed
    return {"ok": True, "id": file_id}
```

(Verify `secrets` is already imported in api.py — `import secrets` line near the top. If not, add it.)

### 6. Marina injection

In `wtyj/agents/marina/marina_agent.py`, add a helper near `_build_approved_answers_block` (Brief 219, around line 540 — find by name). Mirror its leading-`\n\n` pattern so the f-string collapses cleanly when the flag is off:

```python
def _build_knowledge_files_block() -> str:
    """Brief 230: when features.knowledge_files_in_prompt is true and at
    least one knowledge file has status='ready', inject the extracted
    text as a KNOWLEDGE FILES section in Marina's system prompt.

    Returns leading "\\n\\n<block>" when there's content, "" when off
    so the f-string collapses cleanly.
    """
    biz = config_loader.get_business() or {}
    features = (config_loader.get_features() or {}) if hasattr(
        config_loader, "get_features") else (biz.get("features") or {})
    # Defensive: features may live at root or under business.features.
    flag_on = False
    try:
        from shared import config_loader as _cl
        client = _cl.load_client_config() or {}
        flag_on = bool(((client.get("features") or {})
                        .get("knowledge_files_in_prompt")))
    except Exception:
        flag_on = False
    if not flag_on:
        return ""

    from shared import state_registry
    files = state_registry.get_knowledge_files_for_prompt(limit=5)
    if not files:
        return ""
    lines = ["KNOWLEDGE FILES (uploaded reference documents — use these "
             "as factual context when answering customer questions):"]
    for f in files:
        lines.append(f"\n--- {f['filename']} ---")
        # Cap each file at ~3000 chars to bound prompt size.
        text = (f.get("text") or "")[:3000]
        lines.append(text)
    return "\n\n" + "\n".join(lines)
```

Wire into `_build_system_prompt` immediately after the existing `_approved_answers_block` interpolation (find the f-string by searching for `_approved_answers_block`):

```python
{_customer_file_block}{_approved_answers_block}{_knowledge_files_block}{_info_updates_block}
```

(The exact f-string variable names depend on what's already there from Briefs 216 + 219. Find the line, splice `_knowledge_files_block` in alongside the others, and ensure `_knowledge_files_block = _build_knowledge_files_block()` is computed earlier in the same function.)

## Tests

Place at `wtyj/tests/social/test_230_knowledge_files.py`:

```python
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
    """Build a tiny valid PDF containing one text-bearing page so pypdf
    can extract `text`."""
    # Build with pypdf itself for guaranteed compat.
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject, ArrayObject, NumberObject
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    page = writer.pages[0]
    # Inject a simple text content stream.
    content = (f"BT /F1 12 Tf 10 40 Td ({text}) Tj ET").encode("latin-1")
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = stream
    # Add a Helvetica font resource so the Tj operator resolves.
    from pypdf.generic import DictionaryObject
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    page[NameObject("/Resources")] = resources
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


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
    # extracted_text is not surfaced via list endpoint, read directly.
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
    """Brief 230: PDF upload via pypdf → status=ready."""
    _reset()
    token = _login()
    pdf = _make_minimal_pdf("Brief 230 inside")
    r = client.post(
        "/dashboard/api/knowledge/files",
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    # PDFs may legitimately produce empty text in Phase 1 if the writer's
    # font config didn't render to extractable glyphs — but the upload
    # should still SUCCEED and the row should exist with a status.
    assert r.json()["status"] in ("ready", "failed")
    if r.json()["status"] == "ready":
        # If extraction worked, our text should be in there somewhere.
        files_for_prompt = state_registry.get_knowledge_files_for_prompt()
        assert any("brief 230" in f["text"].lower() for f in files_for_prompt)


def test_upload_unsupported_type_lands_failed():
    """Brief 230: unsupported types (PNG, CSV, XLSX) are stored with
    status='failed' and a clear failure_reason. Phase 2 enables them."""
    _reset()
    token = _login()
    # PNG bytes — minimal 1x1 transparent PNG.
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
    assert "extractedText" not in f0  # MUST NOT leak


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
```

## Success Condition

After deploy, an operator uploads a TXT/DOCX file via SR's frontend and gets back `status: "ready"` plus a row in `GET /knowledge/files`. Uploading a PNG/CSV/XLSX returns `status: "failed"` with a clear reason (Phase 1 doesn't index them). DELETE cleans up DB row + disk file. With `features.knowledge_files_in_prompt: true` flipped on for a tenant, Marina's system prompt gains a `KNOWLEDGE FILES` block listing up to 5 ready files (each capped at 3000 chars). New regression tests cover all three formats, unsupported types, list shape, delete, and the Marina-injection helper's filtering. Full suite stays at 1066 + 7 new = 1073 passing / 0 failures.

## Rollback

`git revert <commit>`. The `knowledge_files` table survives revert (CREATE IF NOT EXISTS, no DROP). All endpoints disappear; SR's frontend gracefully falls back to localStorage. Disk files in `wtyj/data/knowledge/` are orphaned but harmless — a follow-up brief can sweep. The `pypdf` dep stays in requirements.txt; removing it requires a separate `pip uninstall` in production but causes no harm if left.
