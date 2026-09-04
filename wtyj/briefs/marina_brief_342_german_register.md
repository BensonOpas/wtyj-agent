# BRIEF342 — Use consistent formal German address
**Status:** Prepared, independently reviewed; not deployed | **Files:** `clients/mermaid/config/client.json`, `clients/mermaid/config/reservation_catalog.json`, `wtyj/agents/social/mermaid_understanding.py`, `wtyj/tests/agents/test_mermaid_german_register.py` | **Depends on:** 7788f54 | **Blocks:** final A4 language acceptance

## Context
The preserved English/German compatibility review records German generated replies using informal du/ihr while the canonical summary, payment, pickup and review copy uses formal Sie/Ihr. BASE045 T1 says “Für welches Datum planst du den Ausflug?”; its T6 dedicated FAQ says “seid ihr”. PARA003 T4 refers to “deine Bestätigung”. These are actual saved model outputs, not new model tests. The tenant's `agent_persona.language_register` currently tells the agent to match guest formality, and the Mermaid-specific prompt does not inject that existing field. Two deterministic German contact copies also use dich/du and need the same narrow correction.

## Why This Approach
Use the existing tenant register setting as the authority and pass it through the existing public configuration projection to Mermaid's system prompt. Apply it to both generated reply fields so ordinary answers and the dedicated FAQ body match formal canonical text. Reject Python pronoun replacement, language classification, a second model call or changing all canonical text to informal: those would be brittle, increase cost or broaden an otherwise small wording fix. Prompt delivery can be tested offline; actual language adherence cannot be certified without a separately authorized new evaluation.

## Instructions
1. Replace `agent_persona.language_register` at `client.json:60` with the proposed wording below. Preserve every other persona/config field.
2. Add one register paragraph to the final presentation section of `mermaid_understanding.system_prompt` near `mermaid_understanding.py:125`. Read only the already-public `persona` projection. It applies to generated `reply` and `other_question_reply`, not exact guest-question excerpts or extracted customer facts. No routing, recovery, schema, pause or booking logic changes.
3. Change only German `guest_copy.de.contact_phone_prompt` and `contact_phone_retry` at `reservation_catalog.json:175-176` to the proposed formal text below. Preserve catalog version, amounts, timing, placeholders and all other locales.

Proposed register setting:

> Use clear, guest-friendly language. In German, address guests consistently with formal Sie, Ihnen and the appropriate capitalized Ihr forms, with matching formal verb forms. Apply this to every generated customer-facing field, including reply and other_question_reply, from the first greeting through FAQs, review follow-ups and language switches back to German. Keep the tone warm and conversational, without bureaucratic wording. Do not switch to du, dich, dein or informal plural ihr/euch when addressing guests, even if the guest or earlier history uses them. In other supported languages, continue matching the guest's language and level of formality. Preserve exact guest-question excerpts and supplied customer facts; this guidance changes the assistant's wording only.

Proposed German contact wording:

> Unter welcher Telefonnummer mit Ländervorwahl können wir Sie erreichen? Sie ist für wichtige Informationen zur Fahrt, etwa bei einer wetterbedingten Absage.

> Können Sie die vollständige Telefonnummer mit Ländervorwahl senden, beginnend mit +? So kann ich eine Kontaktnummer für Informationen zur Fahrt speichern.

## Tests
Exercise the actual Marina SDK request boundary with a stubbed provider: the current tenant register reaches the Mermaid system prompt, the dedicated FAQ field is explicitly in scope, one call is made, and guest evidence remains unchanged. Include a credential copied into the register to prove the existing public projection still redacts it. Test missing/invalid German contact flows through the workflow against the formal configured copy, keeping the contact requirement and booking block intact. Run the existing relevant prompt/projection/contact regressions. Do not use keyword classifiers or mocked German output as evidence of model language quality.

The four new regressions failed before the change. After implementation, 83 tests passed across the new register tests, contact-number workflow, public configuration projection and Marina tool-use suites. The actual SDK request is captured with a stubbed provider; its supplied output is not a model-quality result. A structural JSON comparison confirms only one persona leaf and the two German contact leaves changed. Before/after logs are preserved outside this checkout at `output/remediation-342-2026-09-04/german-register-{before,after}.txt`. Independent brief review passed before the runtime/config edits.

## Success Condition
The reviewed formal register reaches Mermaid's generated reply contract and both deterministic contact prompts use matching formal address; native review and fresh model adherence remain explicitly unverified.

## Rollback
Revert the source/config/test commit before release. No deployment, live mutation, migration or paid evaluation is included; the recorded USD 19.126587 of the USD 20 ceiling is unchanged.

Independent output review passed with no actionable findings. The reviewer verified the exact three configuration leaves and one prompt paragraph, reran all four new regressions successfully, and confirmed the documented distinction between prompt delivery and fresh/native language validation.
