# OUTPUT 230 — AI knowledge files Phase 1 (PDF/DOCX/TXT upload, extraction, Marina injection)

## What was done
Added `pypdf==4.3.1` to `requirements.txt`. New `knowledge_files` SQLite table with `id, filename, stored_filename, mime_type, size_bytes, status, extracted_text, failure_reason, uploaded_at, last_used_at`. New module `wtyj/dashboard/knowledge_extract.py` exposes `extract(filename, mime_type, data) -> (text, reason)` — uses `pypdf` for PDF, stdlib `zipfile + xml.etree.ElementTree` for DOCX (zero new dep — DOCX is just a ZIP of XML), direct decode for TXT, returns `(None, reason)` for everything else. Four state-registry helpers: `knowledge_file_create`, `knowledge_files_list`, `knowledge_file_delete`, `get_knowledge_files_for_prompt`. Three new endpoints — `POST /knowledge/files` (multipart, synchronous extraction, returns SR's KnowledgeFile shape), `GET /knowledge/files`, `DELETE /knowledge/files/{file_id}`. Marina injection: `_build_knowledge_files_block` mirrors Brief 219's leading-`\n\n` pattern, gated on `features.knowledge_files_in_prompt` (default OFF), wired into `_build_system_prompt`'s f-string between Brief 216's `_info_updates_block` and the writing-style block. Files persist to `wtyj/data/knowledge/`. 25MB cap matches SR's frontend.

## Tests
1073 passing / 0 failures (baseline 1066 + 7 new).

## Deployment
Source committed and pushed; deploy still to fire.
