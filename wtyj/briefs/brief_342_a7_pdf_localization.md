# BRIEF 342 A7 - Localized, structured Mermaid demo documents
**Status:** Deployed and verified at f220c3e; A4/A8 acceptance holds remain | **Files:** mermaid_documents.py, mermaid_document_copy.py, mermaid_pdf_structure.py, PDF regression tests, render_mermaid_pdf_audit_samples.py | **Depends on:** 5922be0 | **Blocks:** Issue 342 A7/A8 document gate

## Context
The preserved 60-conversation baseline contains 76 untagged quote/receipt PDFs. Quote banners remain English; receipt banners and subtitles remain English and transport is repeated. The document renderer is `wtyj/agents/social/mermaid_documents.py`; the confirmed-input limit is 160 characters in `wtyj/agents/social/mermaid_reservation_workflow.py`.

## Why This Approach
Keep the existing ReportLab renderer, descriptive filenames and first-party image. Add document-only translated interface labels and a small flowable/canvas tagging adapter. Replacing the PDF engine or claiming PDF/UA certification from a Marked flag alone was rejected: an ordered content tree, headers and actual page-content references must be tested, and renderer/assistive-reader limitations must remain explicit. Prices and policies stay unchanged; root owns catalog remediation. Papiamentu wording is draft, pending native Curaçao review.

## Instructions
Localize both prominent demo banners and receipt subtitle. Emit catalog language metadata; tag headings/paragraphs and price table rows/cells in rendering order. Mark decorative imagery and rules as artifacts. Print receipt transport once and include its persisted monetary line items. Use compact receipt header/layout so maximum accepted guest/pickup strings fit without clipping. Preserve existing PDFs and delivery idempotency.

## Tests
Render quotes and receipts across six languages, with 160-character names and pickup locations. Verify prominent demo-only/no-real-money disclosure, localized title/subtitle, exactly one transport occurrence, image retention, line item totals and payment amount, metadata language, content MCID/parent-tree integrity and semantic table/header ordering. Re-render to PNG and visually inspect all 12 samples. Keep functional/document checks separate from native approval.

## Success Condition
All 12 document samples pass content, structure and visual checks, with unsupported accessibility certification and native Papiamentu review explicitly left pending.

## Rollback
Revert this focused commit and restore the prior Mermaid image. Existing stored PDFs are immutable and are not regenerated or resent by this change.

## Results and limitations
+- 107 focused tests passed under the pinned production dependencies (ReportLab4.4.3, pypdf4.3.1), including13 new content/structure regressions and the quote/payment/booking/pickup tests.
+- All12 maximum-length synthetic samples (160-character name and160-character pickup location) render as one page. All12 PNGs were inspected: no clipping, overlap or replacement glyphs, image and totals preserved, prominent localized demo notices, and one transport block per document.
+- Page bounds, metadata language, real MCID-to-structure/parent-tree links, exactly one H1, H2 sections, table rows/headers/scopes and tagging of every text-drawing operator pass. Poppler reports Tagged yes and Suspects no. These are structural checks, not screen-reader certification.
+- Receipts now show the immutable itemized amounts, whose sample line totals reconcile toUSD450. Payment timestamps normalize toUTC numerically, without English month abbreviations. Demo banner text uses a darker brand tone to improve contrast from2.95:1 to above4.5:1.
+- QA artifacts are in `/Users/calvin/Documents/ChatGPT/Mermaid/output/audit-342-a7-pdf-2026-09-04`; the baseline folder was only read. No database changes, model calls, provider sends or live deployments.
+- Built-in fonts remain unembedded, and no external PDF/UA validator or assistive-reader test has run. Do not claim PDF/UA or WCAG compliance. The decorative trip photograph is explicitly an artifact, not meaningful content.
+- Papiamentu wording remains a draft requiring native Curaçao approval. Shared catalog party singular/plural copy and round-trip wording belong to the root A2/A4 work and need the combined release re-render.
