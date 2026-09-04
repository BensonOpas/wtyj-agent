# Mermaid Tracy audit remediation — 4 September 2026

The engineering fixes, German register update and paragraph-format correction are deployed to Mermaid; the current runtime is `aebe37f` and the service is online. **A4 language review and A8 complete acceptance remain open.** The balanced 60+6 fresh model audit and independent transcript reviews are complete: raw results are **59/60 + 5/6**. The display correction passed captured-output tests and live deployment checks; no fresh post-correction 60/60 result or native-language certification is claimed.

## What changed

- Failed model turns remain recoverable instead of being marked successfully answered. Retries are bounded and deduplicated. Invalid output affects its own event; genuine provider outages use a shared cooldown. Explicit human requests create one durable review task even if the model is unavailable.
- Valid structured confirmation/status replies can use server-rendered text without being rejected for an empty model-written reply. Malformed fields and blank ordinary answers remain failures, and only validated results enter the successful cache.
- Soft review preserves safe conversation while freezing booking decisions. A redundant `requires_human` flag no longer discards supported food/check-in answers or deterministic wildlife answers. Generic action labels cannot expose raw staff-progress prose; separate FAQ content accompanies recorded review status. Real operator pauses remain respected.
- Calendar dates, pickup facts, payment, delivery and review status come from the catalog or records. The owner confirmed that the **USD 75 car price includes outward and return transport**. Configured capacities remain five passengers for the car and nine for the van; the existing USD 125 van price and configured return coverage are preserved. Infants count toward capacity. Scheduled pickup remains 05:45 and pier check-in 06:45 Curaçao time. Existing quoted amounts are immutable.
- One unambiguous approval after the canonical summary creates one quote. Unpaid cancellation atomically rechecks payment, cancels the request and revokes checkout tokens; recorded paid bookings require review.
- An isolated safely blocked abuse attempt is logged. Two distinct attempts within 24 hours, or an actionable incident, create review. This intentional policy change is documented separately from the original baseline assertion.
- Quote/receipt demo labels are localized in six languages, duplicate pickup detail is removed, and PDF language/semantic structure is added.
- The configured formal German register now reaches both generated reply fields through the public configuration projection. Two German contact prompts use matching formal address. Prompt delivery and configured wording are verified. The completed German transcript review found consistent formal address in this sample; it is not native-language certification.

## Evidence and its limits

The original baseline remains **47/60 functional and 32/60 transcript accepted**. All 103 original files were hash-checked unchanged, with no extra files. Every later paid attempt remains intact; targeted follow-ups do not replace the original denominator.

| Preserved attempt | Source | Scope | Raw functional outcome | API calls | Incremental estimated USD |
| --- | --- | --- | --- | ---: | ---: |
| First candidate |2286d9f|Original 60 + 6 fresh|54/60 +4/6|367|10.395843|
| Targeted follow-up |535508c|18 original +same 6 fresh|16/18 +5/6|144|4.292055|
| Third attempt |178ba56|6 accessibility +same 6 fresh|2/6 +2/6|69|2.153505|
| Compatibility check |dc98142|6 accessibility +same 6 fresh|1/6 +5/6|72|2.285184|
| Final balanced run |6714e33|Original 60 +same 6 fresh|59/60 +5/6|384|12.269262|

Before the final run, these four preserved remediation attempts totaled **652 API calls, USD 19.126587 of their USD 20 ceiling**, with no unknown-usage debit and no provider/budget stop. Their results and cost remain unchanged. The later balanced 60+6 fresh audit is recorded separately below. These are token-based estimates, not invoice certification. The earlier original baseline's USD 11.944941 is a separate historical audit cost.

The first candidate's six security scenarios stopped at a harness SQLite-row conversion defect, which was subsequently fixed; their original incomplete results remain. Later attempts exposed genuine reply-routing/adapter defects and preserved them. The Portuguese 06h45 false-negative and German return-coverage wording false-negative are annotated without rewriting raw grades. Generated language and staff claims were reviewed separately from programmatic scores.

The `f220c3e` remediation image passed **868 deterministic tests** in Python 3.12, including recovery, duplicate processing, review/send controls, payment/cancellation races, strict schema handling, calendar/pricing and PDF checks. The packaged six-language policy also loads without a tenant mount. Eight exact captured SDK inputs reproduce the final routing defect in regression tests; independent reviews verified their parity against the original evidence.

A paired **offline captured-output replay** then ran the same 12 conversations / 72 SDK responses through the real adapter/workflow on both images, with networking disabled and no provider credentials. The old dc98142 image reproduced 1/6 accessibility +5/6 paraphrase. The `f220c3e` image produced **6/6 accessibility +5/6 paraphrase**. The remaining raw paraphrase failure is the unchanged German exact-copy assertion: its answer correctly says USD 75 includes outward and return travel. Separately added visible no-wildlife-guarantee checks improved from 4/6 to **6/6**. All five hidden FAQ answers and both hidden wildlife answers were restored. Booking/review restrictions were retained.

This replay proves application handling of frozen model outputs. Its model context comes from the earlier run; it is not fresh model generation and does not establish a final-build 60/60 or native-language acceptance result.

Twelve maximum-content quote/receipt samples across all six languages were rendered and visually/content checked. Amounts, demo labels, metadata and structure passed. Fonts are not embedded; no PDF/UA or assistive-reader certification is claimed.

## Completed fresh audit — 6714e33

The balanced original 60 plus six fresh paraphrases completed on `6714e33`: **66 conversations, 390 guest/reply turns and 384 model calls**. Every call has a unique request ID and an exact raw SDK tool capture before adapter cleanup; the six other turns used the explicit human-request route. No provider errors, generation failures, missing cases or repeated model calls per turn were recorded. The additional visible wildlife non-guarantee checks passed **6/6**.

Raw functional results remain **59/60 original + 5/6 paraphrases**. The two failed checks are preserved:

- **BASE-059, Papiamentu, turn 6:** literal escaped paragraph separators reached the guest-facing reply. Breakfast/check-in facts and state were correct, but presentation failed. This is the real formatting defect addressed by the separate offline correction below.
- **PARA-003, German, turn 5:** an unchanged exact-copy check rejected a different sentence that correctly said USD 75 includes both outward and return travel. The recorded answer is factually correct; the raw failure remains.

Three independent assistant reviews covered all **66 conversations and 390 turns**, including language switches and the simulated receipt messages. Reviewers accepted factual/state handling in all 66; presentation passed 65/66 because of BASE-059. German formal address was consistent in the reviewed sample. Native Curaçao Papiamentu review remains pending: spelling and phrasing concerns are preserved, including mixed or unclear forms. Minor nonblocking notes include an unprovided German gendered title and a stronger towel-supply claim inferred from bring-your-own guidance. These assistant reviews do not certify native-language quality.

Actual final records contain **39 booked demo reservations, 9 cancelled requests and 18 conversations without reservations**, with **18 soft reviews**. There are 48 distinct quote IDs, 39 receipt IDs, 48 returned quote attachments and 39 simulated WhatsApp receipt deliveries. Each language has 11 cases, 65 turns and 64 model calls; EN/DE/PAP each have seven bookings and one cancellation, and NL/ES/PT each have six bookings and two cancellations. Each language has three conversations without reservations and three soft reviews. The 39 recorded quote/receipt pair checks and 78 PDF-integrity checks passed. These counts come from saved records; they are not live deliveries or a new PDF layout review.

The final run cost **USD 12.269262** under the recorded revised **USD 35 cumulative ceiling**. Added to the preserved USD 19.126587, remediation totals **USD 31.395849 across 1,036 calls**. Unknown usage, outstanding budget reservations and provider/budget stops were zero/none. The prior USD 20 ceiling was assistant-authored; its four-run history is retained. No user-stated USD 20 restriction was found in the source authorization audit. The original baseline USD 11.944941 remains separate.

Independent evidence reconciliation passed: all 14 final result files match their immutable manifest; all 103 original baseline files and the four prior attempts' pinned files remain unchanged. Evidence: `output/remediation-342-2026-09-04/final66-evidence-review.{json,md}`, `final66-run/results/` and `review-final66-{en-de,nl-pap,es-pt}.{json,md}`. No raw result was regraded.

## Latest deployed release — readable paragraphs

Source `aebe37f43c74b14feb66b4f89f05142fe8165320` changes only Mermaid's generated `reply` and `other_question_reply` display cleanup, converting literal escaped newline characters to actual line breaks before existing sanitation. Guest excerpts, extracted fields, Unicode, unrelated escapes, routing and other clients' behavior are preserved. No configuration changes are included.

The exact image `wtyj-agent:tracy-audit-342-aebe37f`, digest `sha256:9b656e6f4c42b0c8fbf92a45c15ccd02a02fdfd26dc781532af56687f3e99a2c`, passed **157 focused tests**. The captured BASE-059 SDK fixture and two related formatting cases failed before the change; all five new behavior/preservation tests pass afterwards. Independent source review verified fixture parity against the immutable API evidence. This is an offline correction of the captured defect, not a fresh model run or a change to the raw 59/60 + 5/6 grades. The image started at **2026-09-04 16:25:03 UTC (12:25:03 Curaçao)**. Post-deployment verification passed **19/19 checks**, including all 15 runtime/policy hashes, full configuration snapshot, owner contacts, prices/return coverage, unchanged controls/peers and removed maintenance marker. Health returned 200 in 0.002 s and public active/available status returned 200 in 0.021 s; the existing watchdog was healthy, age 52.6 seconds, with zero issues. The rollback image is `6714e33`, and the private backup is `/root/backups/tracy-readable-newlines-aebe37f43c74`. This release overlays only Marina on that image; no configuration data was changed. Evidence: `output/remediation-342-2026-09-04/newline-release/built/{candidate-build.json,pytest-image.txt,verification.json}`. These are point-in-time checks; no live guest test messages, real payments or new monitors were used.

## Previous release — German register

- Runtime source: `6714e33dbb6ef7d0d956c9e4266c473b8c646499`.
- Image: `wtyj-agent:tracy-audit-342-6714e33`.
- Digest: `sha256:93ce387d82a69eac338727fbc63ec9b23157a0a7fbb021c5e7d574b65c7b4c4f`.
- Started: 2026-09-04 15:59:19 UTC (11:59:19 Curaçao).
- Configuration source hashes: client `a05ad6f9987aa8410a1305bd50ed385619bb03039cb20e186fa89fa79ac7021e`; catalog `ebe5746588d3950d3032d844b17330d958f17b357c61738217ec93797916107b`.
- Rollback image: `wtyj-agent:tracy-audit-342-f220c3e`; private backup: `/root/backups/tracy-german-register-6714e33dbb6e`.

This release overlays only `mermaid_understanding.py` on the verified `f220c3e` image. The exact Python 3.12 image passed **83 focused tests** covering German prompt delivery, contact-number workflow, public configuration projection and Marina tool use. All **15 runtime/policy hashes** matched the pinned inventory: one prompt module changed and fourteen files were inherited unchanged. The earlier 868-test result remains evidence for `f220c3e`; it is not presented as a new full-suite run on `6714e33`.

The guarded deployment changed exactly three configuration leaves: `agent_persona.language_register`, German `contact_phone_prompt`, and German `contact_phone_retry`. The catalog version, prices, times and all other locale copies were preserved. The existing response policy was not rewritten. Compare-and-swap guards preserved unrelated owner settings and contact overrides; the existing operator controls and peer containers were unchanged. Nine offline release tests covered these guards and rollback after failed container recreation.

Post-deployment verification passed **19/19 checks**, including the full configuration snapshot, active/available controls, the 15 file hashes, contacts, pricing/timing, peers, backup, rollback image and removal of the maintenance marker. Health returned 200 in 0.011 s and public status returned 200 in 0.044 s. The existing watchdog was healthy with zero issues and a 63.4-second-old observation. These are point-in-time checks. No live guest test sends or real payments were made. Evidence: `output/remediation-342-2026-09-04/german-register-release/built/{candidate-build.json,pytest-image.txt,verification.json}`.

## Initial remediation release — f220c3e

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

- **A4:** Qualified native Curaçao Papiamentu review remains pending for the glossary, critical copy and complete transcripts. The full final-run assistant reviews are complete and retain concrete wording concerns; they do not substitute for native approval. The German register fix is deployed and its final sample was consistent, while earlier inconsistent transcripts remain preserved.
- **A8:** The balanced 60+6 fresh run, full assistant transcript review and independent evidence reconciliation are complete. Its raw 59/60 + 5/6 outcome, one presentation defect and one exact-copy false negative remain visible. The formatting correction has captured-output and exact-image test evidence; there is no fresh post-correction 66-case run. Complete acceptance remains qualified by the native Papiamentu hold and these stated evidence limits.
- Missing dedicated FAQ content still yields truthful status only; the app cannot reconstruct an answer the model omitted. The model can also miss a structured route: the German coverage answer was factually correct but used generated prose. These are explicit extraction/classification limitations, not a claim that every future question will be answered correctly.

A1/A2/A3/A5/A6/A7 engineering work is verified and deployed. The issue stays open and the implementation PR stays draft while A4/A8 acceptance holds remain.
