# BRIEF342 — Render escaped model paragraph breaks
**Status:** Implemented and locally verified; not deployed | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/agents/test_mermaid_readable_newlines.py`, `wtyj/tests/fixtures/mermaid_base059_escaped_newlines.json` | **Depends on:** 6714e33 | **Blocks:** correction of final-audit BASE-059 T6 display defect

## Context
The final balanced audit's preserved BASE-059 Papiamentu turn 6 has a correct breakfast/arrival answer and unchanged saved trip date, but `readable_newlines` is false. Its actual raw SDK tool input contains literal backslash+n characters between paragraphs, and the same characters reach the displayed reply. The canonical evidence is BASE-059/n=6 in `output/remediation-342-2026-09-04/final66-run/results/final-balanced-60-results.jsonl`, with its raw tool input pinned from the matching request in `final66-run/results/api-events.jsonl`; its raw response text is “Desayuno ta inklui, si! Bo mester yega na Fishermen's Pier pa 06:45.\\n\\nKuantu hende lo bai: adultonan, yu'nan (4–12 aña) i bebinan (0–3 aña)?” (the separators denote literal escaped characters). Existing customer-text cleanup at `wtyj/agents/marina/marina_agent.py:2227` removes internal tokens and em dashes, but does not normalize those paragraph separators.

## Why This Approach
Normalize only the literal two-character backslash+n sequence in the two Mermaid generated display fields immediately before their existing cleanup. This changes presentation without interpreting language, selecting actions or modifying facts. Reject whole-string Unicode decoding because it can corrupt Papiamentu/other Unicode text and unrelated escape sequences. Reject prompt-only correction because the preserved provider output already violates the intended display form and another paid call is unnecessary. The tradeoff is that a deliberately written literal backslash+n in Mermaid customer-facing prose is displayed as a line break; guest evidence and extracted fields retain their exact values.

## Instructions
1. Preserve the raw audit and its raw grade. Add a compact fixture containing the captured turn's input, saved fields, exact raw SDK tool input and original displayed text, with its source/turn identified.
2. At `wtyj/agents/marina/marina_agent.py:2227`, for `response_contract == mermaid_reservation_demo` only, replace literal escaped newline characters in string `reply` and `other_question_reply` before existing token/whitespace/em-dash cleanup. Do not coerce malformed values. Do not change other fields, tool schemas, model prompts, routing, language detection, storage or other response contracts.
3. Add focused actual mocked-SDK tests at the adapter/workflow boundary using isolated SQLite and disabled alert/summary dispatchers. No live provider/customer calls.

## Tests
Five behaviors: (1) exact captured BASE-059 SDK response through the real workflow produces two real newline separators, identical other wording and identical stored intake/reservation/review outcome; (2) escaped breaks in dedicated `other_question_reply` normalize and compose with existing internal-token/em-dash cleanup; (3) already-correct newlines, Unicode and unrelated escapes are preserved; (4) guest input/excerpts/extracted fields and raw SDK input remain unchanged; (5) the generic non-Mermaid contract preserves its prior handling of literal backslash+n. Record the captured case failing before and passing after. Run the existing tool-use/German prompt/recovery suites only to cover the shared adapter boundary.

The corrected five-case fixture gate reproduced three formatting failures and two preservation passes before the runtime change. Afterwards, all 157 tests passed across the five new cases, German register, Marina tool-use and Mermaid model-recovery suites. Evidence is preserved at `output/remediation-342-2026-09-04/readable-newlines-{before,after}.txt`; preliminary fixture setup errors remain in separately named logs. The fixture's raw SDK tool input matches the canonical API event exactly, verified by source-file and event hashes. The paid raw 59/60 + 5/6 result remains unchanged; this is an offline display correction, not a new model-language acceptance result.

## Success Condition
The saved BASE-059 T6 output becomes readable paragraphs through the actual adapter/workflow without changing its wording, booking/security state or other contracts; the original paid audit remains unchanged.

## Rollback
Revert this source/test/fixture commit. No live configuration, data, provider call or deployment is part of this change.
