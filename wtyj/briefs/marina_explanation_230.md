# EXPLANATION 230 — AI knowledge files Phase 1 (PDF/DOCX/TXT upload, extraction, Marina injection)

## In one sentence
Operators can now upload PDF, Word, and plain-text reference documents through the dashboard, and once a tenant flips the new opt-in switch, Marina starts using the contents of those documents as factual context when answering customer questions.

## What's changing and why

Up to this point, the "Your AI knowledge" area on the dashboard was a frontend-only feature — files an operator dropped in lived in the browser's local storage, never touched the server, and never reached Marina. This change wires that area to the backend for the first time. An operator uploading a menu, a policy doc, or a short reference sheet now gets that file saved on the server, its text pulled out, and (when their tenant has opted in) folded into Marina's system prompt so she can quote from it in replies.

The scope is deliberately narrow. Three formats are supported in this phase: PDF, Word (.docx), and plain text (.txt). Spreadsheets, images, and cloud-folder syncing (Google Drive, OneDrive, Dropbox, SharePoint, Box) are intentionally not in this phase — each of those is its own multi-day project. If an operator uploads one of the unsupported types anyway, the upload still succeeds but the file lands marked as "failed" with a clear reason, so the dashboard can show that status without a confusing error. The feature is off by default for every tenant; turning it on is one configuration switch per tenant.

## Step by step — what the code does now

UPLOAD A KNOWLEDGE FILE

When the operator drops a file into the AI knowledge area, the dashboard sends it to the server. The server first checks the size — anything over 25 MB is rejected with a "file too large" error. The bytes are then handed to a small extractor that decides what to do based on the filename extension and the type the browser claims:

- For a PDF, it walks every page and pulls out whatever text the PDF library can read.
- For a Word document, it opens the file as a zip (which is what a .docx really is), reads the inner document XML, and stitches together every paragraph.
- For a plain-text file, it tries UTF-8, then UTF-16, then Latin-1 until one decodes cleanly.
- For anything else (PNG, CSV, XLSX, etc.), it returns no text and a reason that says Phase 1 doesn't index this format yet.

If text came back, the file is marked "ready"; if not, it's marked "failed" and the reason is stored. Either way, the file's bytes are saved to disk under a knowledge folder, a database row is created with the file's name, type, size, status, extracted text, and timestamp, and then the file on disk is renamed to include the row's id so the disk file and the database row stay tied together. A log line records the upload. The response sent back to the dashboard matches the shape SR's frontend already expects: filename, mime type, size, status, and timestamps, all in camelCase.

LIST KNOWLEDGE FILES

When the dashboard asks for the list, the server returns every knowledge file row, newest first, in the same camelCase shape. The extracted text and the failure reason are deliberately left out of this response — the operator UI doesn't need them, and keeping them server-side avoids leaking large blobs over the wire on every page load.

DELETE A KNOWLEDGE FILE

When the operator deletes a file, the server looks up the row, removes it from the database, and then removes the matching file from disk. If the file id doesn't exist, it returns a "not found" error. If the database row is gone but the disk file is already missing, the delete still succeeds quietly.

MARINA READS KNOWLEDGE FILES

Before every reply, Marina's system prompt is rebuilt. A new step in that build process checks whether the tenant has the knowledge-files switch turned on. If it's off, nothing changes. If it's on, the system pulls up to five ready files (newest first), and inserts a section into the prompt titled "KNOWLEDGE FILES (uploaded reference documents — use these as factual context when answering customer questions)" followed by each filename and its extracted text. Each file's text is capped at 3000 characters before it goes into the prompt, so even an oversized document can't run away with the prompt budget. The section sits alongside the existing approved-answers block and info-updates block; if there are no ready files, the section collapses out of the prompt entirely.

## Edge cases

- If an operator uploads a PNG, JPG, CSV, or spreadsheet, the upload succeeds but the file is marked failed with a reason saying Phase 1 doesn't index it. The file is still stored on disk. This is intentional so the frontend's existing "failed" status display works without surprises.
- If a PDF is a scanned image (no actual text layer), the extractor returns empty text and the file ends up marked failed. OCR for scanned PDFs is a Phase 2 problem.
- If a Word document is malformed or password-protected, the extractor catches the error and stores the file as failed with the underlying error message (truncated to 200 characters).
- If the same tenant uploads more than five ready files, only the five newest reach Marina's prompt. Older ones still exist in the list but won't be quoted.
- A single very long document can produce a huge extracted text. Each file is capped at 3000 characters before it enters Marina's prompt, but the full extracted text remains in the database. A document with 50,000 tokens of body still won't blow the prompt because of this per-file cap.
- The upload, the disk write, the database insert, and the disk rename are not a single all-or-nothing step. If the server crashes mid-upload, the database row could exist while the disk file is in a half-renamed state, or vice versa. In practice this would surface as a row whose stored filename doesn't match a file on disk; delete still works for the row, and the orphaned disk file is harmless.
- Deleting a file removes both the row and the disk file but does not retroactively remove that file's text from any in-flight Claude calls. The next reply Marina builds will see the updated list.
- Reverting this change leaves the database table and the on-disk knowledge folder in place. The endpoints disappear and the dashboard falls back to its old local-storage behavior. The pypdf dependency stays in the requirements file even after a revert.

## What did NOT change

Marina's persona, writing style, booking flow, escalation rules, and everything else in her prompt are untouched. The new knowledge-files section is opt-in per tenant — every existing tenant continues to see the exact same prompt they saw before until someone explicitly flips the switch. Customer messages, conversation handling, and reply generation are not affected for any tenant that hasn't turned the feature on. Cloud connectors (Drive, OneDrive, Dropbox, SharePoint, Box), image OCR, and spreadsheet support are not part of this change — they remain to be built.
