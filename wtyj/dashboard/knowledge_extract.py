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
        runs = [t.text or "" for t in p.iter(f"{_DOCX_NAMESPACE}t")]
        line = "".join(runs).strip()
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs).strip()


def _extract_txt(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace").strip()


def extract(filename: str, mime_type: str,
            data: bytes) -> Tuple[Optional[str], str]:
    """Brief 230: extract text from a file. Returns (text, '') on success
    or (None, reason) on a known-unsupported type / parse failure."""
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
