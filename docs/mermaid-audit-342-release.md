# Mermaid Tracy audit remediation — 4 September 2026

The engineering fixes are deployed to Mermaid and the service is online. **A4 language review and A8 complete acceptance remain open.** This report does not claim a fresh final-build 60/60 result.

## What changed

- Failed model turns remain recoverable instead of being marked successfully answered. Retries are bounded and deduplicated. Invalid output affects its own event; genuine provider outages use a shared cooldown. Explicit human requests create one durable review task even if the model is unavailable.
- Valid structured confirmation/status replies can use server-rendered text without being rejected for an empty model-written reply. Malformed fields and blank ordinary answers remain failures, and only validated results enter the successful cache.
- Soft review preserves safe conversation while freezing booking decisions. A redundant `requires_human` flag no longer discards supported food/check-in answers or deterministic wildlife answers. Generic action labels cannot expose raw staff-progress prose; separate FAQ content accompanies recorded review status. Real operator pauses remain respected.
- Calendar dates, pickup facts, payment, delivery and review status come from the catalog or records. Pickup includes **both outward and return transport**: the configured car is **USD 75 per vehicle, up to five passengers**, and the van remains USD 125/up to nine. Infants count toward capacity. Scheduled pickup remains 05:45 and pier check-in 06:45 Curaçao time. Existing quoted amounts are immutable.
- One unambiguous approval after the canonical summary creates one quote. Unpaid cancellation atomically rechecks payment, cancels the request and revokes checkout tokens; recorded paid bookings require review.
- An isolated safely blocked abuse attempt is logged. Two distinct attempts within 24 hours, or an actionable incident, create review. This intentional policy change is documented separately from the original baseline assertion.
- Quote/receipt demo labels are localized in six languages, duplicate pickup detail is removed, and PDF language/semantic structure is added.

## Evidence and its limits

The original baseline remains **47/60 functional and 32/60 transcript accepted**. All 103 original files were hash-checked unchanged, with no extra files. Every later paid attempt remains intact; targeted follow-ups do not replace the original denominator.

| Preserved attempt | Source | Scope | Raw functional outcome | API calls | Incremental estimated USD |
| --- | --- | --- | --- | ---: | ---: |
| First candidate |2286d9f|Original 60 + 6 fresh|54/60 +4/6|367|10.395843|
| Targeted follow-up |535508c|18 original +same 6 fresh|16/18 +5/6|144|4.292055|
| Third attempt |178ba56|6 accessibility +same 6 fresh|2/6 +2/6|69|2.153505|
| Compatibility check |dc98142|6 accessibility +same 6 fresh|1/6 +5/6|72|2.285184|

Current remediation total: **652 API calls, USD 19.126587 of the same USD 20 ceiling**, no unknown-usage debit and no provider/budget stop. No further paid run was performed. These are token-based estimates, not invoice certification. The earlier original baseline's USD 11.944941 is a separate historical audit cost.

The first candidate's six security scenarios stopped at a harness SQLite-row conversion defect, which was subsequently fixed; their original incomplete results remain. Later attempts exposed genuine reply-routing/adapter defects and preserved them. The Portuguese 06h45 false-negative and German return-coverage wording false-negative are annotated without rewriting raw grades. Generated language and staff claims were reviewed separately from programmatic scores.

The final image passed **868 deterministic tests** in Python 3.12, including recovery, duplicate processing, review/send controls, payment/cancellation races, strict schema handling, calendar/pricing and PDF checks. The packaged six-language policy also loads without a tenant mount. Eight exact captured SDK inputs reproduce the final routing defect in regression tests; independent reviews verified their parity against the original evidence.

A paired **offline captured-output replay** then ran the same 12 conversations / 72 SDK responses through the real adapter/workflow on both images, with networking disabled and no provider credentials. The old dc98142 image reproduced 1/6 accessibility +5/6 paraphrase. The final image produced **6/6 accessibility +5/6 paraphrase**. The remaining raw paraphrase failure is the unchanged German exact-copy assertion: its answer correctly says USD 75 includes outward and return travel. Separately added visible no-wildlife-guarantee checks improved from 4/6 to **6/6**. All five hidden FAQ answers and both hidden wildlife answers were restored. Booking/review restrictions were retained.

This replay proves application handling of frozen model outputs. Its model context comes from the earlier run; it is not fresh model generation and does not establish a final-build 60/60 or native-language acceptance result.

Twelve maximum-content quote/receipt samples across all six languages were rendered and visually/content checked. Amounts, demo labels, metadata and structure passed. Fonts are not embedded; no PDF/UA or assistive-reader certification is claimed.

## Deployed release

- Runtime source: `f220c3eab85aa9fe2306f73697000131b9252c4a`.
- Image: `wtyj-agent:tracy-audit-342-f220c3e`.
- Digest: `sha256:12f8dfeb740f3861fab294c4580d529ea7478492746c7aa24943025f151acf52`.
- Started: 2026-09-04 15:30:45 UTC (11:30:45 Curaçao).
- Catalog: `mermaid-demo-v6-2026-09-04`; policy: `mermaid-response-policy-342-v2`.
- Configuration source hashes: client `02172191b3a544a49c64a5aed4c559f14d9c4665e2a52cf160cf4ea23e0d3588`; catalog `738bf05e1eb9e40e7c70c3075791e768a14b32315248de7da0a8b8b46a311d3f`; policy `aaf0cafbbfdb1862831e2c9e2d42455de09c9d3f5d22e90d2e03d94db62bbd4a`.

The guarded Mermaid-only deployment changed the reviewed seven client paths, 29 catalog paths and added the policy file, preserving owner contact overrides and other live settings. It retained a private consistent database/configuration backup and the previous image; no live rollback was needed. Rollback guards were exercised offline.

Post-deployment verification passed **19/19 checks**: exact image and all 15 runtime/policy file hashes, complete configuration snapshot, active/available controls, owner contacts, prices and timings, peer containers, removed maintenance marker, backup/rollback image, public status and health. Health returned 200 in 0.003 s and public status 200 in 0.034 s at verification. The existing VPS watchdog was healthy, fresh 9 seconds and had zero issues. These are point-in-time observations, not an uptime guarantee.

There were no live guest test sends, real payments/refunds, inventory operations, new monitors or unrelated tenant restarts. The paused Codex monitor was not resumed. Synthetic delivery/payment boundaries in the audits do not prove Zernio/WhatsApp provider delivery.

## Open acceptance work

- **A4:** Qualified native Curaçao Papiamentu review remains pending for the glossary, critical copy and complete transcripts. The review packet preserves attested historical wording concerns and distinguishes borrowing from meaning errors. German generated replies still vary between informal language and formal canonical copy; this consistency hold remains visible.
- **A8:** The original 60-case rerun and all follow-ups are preserved, but the final image has targeted captured-output verification, not a fresh balanced 60-case accepted run. No scope reduction, failed-attempt removal or native-certification claim clears that gate.
- Missing dedicated FAQ content still yields truthful status only; the app cannot reconstruct an answer the model omitted. The model can also miss a structured route: the German coverage answer was factually correct but used generated prose. These are explicit extraction/classification limitations, not a claim that every future question will be answered correctly.

A1/A2/A3/A5/A6/A7 engineering work is verified and deployed. The issue stays open and the implementation PR stays draft while A4/A8 acceptance holds remain.
