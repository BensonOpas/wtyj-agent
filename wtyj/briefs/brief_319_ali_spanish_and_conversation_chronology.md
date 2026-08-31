# BRIEF 319 — Ali Spanish continuity and conversation chronology
**Status:** Implemented | **Files:** `agents/marina/marina_agent.py`, `agents/social/ali_media_first.py`, `agents/social/ali_quote_workflow.py`, `agents/social/ali_quote_presentation.py`, `agents/social/ali_quote_brand_card.py`, `agents/social/ali_quote_delivery.py`, `agents/social/ali_quote_pdf.py`, `agents/social/ali_vehicle_recommendations.py`, `agents/social/ali_vehicle_selection.py`, `agents/social/ali_reservation_workflow.py`, `agents/social/ali_reservation_v2_inbound.py`, `agents/social/ali_reservation_confirmation_pdf.py`, `agents/social/ali_lead_follow_up.py`, `agents/social/social_agent.py`, Ali runtime `client.json`, dashboard `artifacts/unboks/src/pages/Inbox.tsx`, dashboard message-order helper and tests, focused Ali tests | **Depends on:** Brief 317 and Brief 318 | **Blocks:** none

## Context
Production evidence from Federico's WhatsApp conversation shows a Spanish customer message followed by an English Nick reply. The same thread later interpreted an Airport return answer as completed hotel-delivery details. The dashboard renders the newer assistant message above the older customer message because its detail pane deliberately reverses the backend's chronological history. Production Ali configuration also omits `business.languages`, while Ali's structured language enum and deterministic customer copy accept only EN/NL/PAP/DE. Pre-reservation reminder eligibility has a related defect: a customer-visible assistant reply followed by an internal system audit row is excluded because the query examines the latest row of any role.

## Why This Approach
Spanish must be a first-class Ali locale across the whole journey, not a one-message translation patch; otherwise the next carousel, quote, document prompt, payment instruction, or confirmation can fall back to English. The dashboard should render an ordinary oldest-to-newest chat while independently selecting the latest customer message for escalation previews. Airport and hotel delivery need distinct completion paths so a fixed location can never produce hotel copy. The rejected alternative is prompt-only wording: it cannot override the structured enum or deterministic Python-owned messages and would leave the failure intact.

## Instructions
1. Add `es` to Ali's structured conversation-language contract and to every Ali-owned localized presentation map used from discovery through confirmation.
2. Add Spanish-aware vehicle discovery, pickup/return option, hotel-delivery, quote, reservation, document-validation, and reminder presentation behavior while keeping server-owned catalog facts authoritative.
3. Separate fixed-location completion from hotel-delivery completion in `social_agent.py`; resolve an exact location answer against the currently missing pickup or return field and never emit hotel-delivery copy for Airport or Ali office.
4. Update the production Ali runtime configuration to publish the intended supported languages and Spanish pre-reservation reminder copy.
5. Make reminder eligibility ignore internal `system` audit rows when determining whether Nick's visible reply is the latest customer-facing message.
6. Render dashboard conversation detail oldest-to-newest, auto-scroll to the latest message, and keep latest-customer previews order-independent.
7. Add regression tests for the exact Spanish/English contract, Spanish deterministic surfaces, Airport pickup-and-return sequencing, reminder eligibility after a system audit row, and dashboard message chronology.

## Tests
1. The Marina tool schema accepts `conversation_language="es"`, and Ali's generated welcome, vehicle picker, quote summary/date, and reservation controls remain Spanish.
2. A replay with pickup Airport followed by return Airport stores both fixed locations and never emits hotel-delivery wording or hotel-stage flags.
3. A lead with an assistant reply followed by an internal system audit row remains eligible for its due reminder.
4. Dashboard message-order tests prove an older customer message renders before its newer Nick reply and latest-customer selection works from either source order.
5. Focused Ali suites, dashboard Vitest/typecheck, and the full backend regression suite pass.

## Success Condition
Fresh Spanish Ali conversations stay Spanish from first reply through after-sales, Airport answers cannot trigger hotel copy, reminder audits do not suppress follow-up, and dashboard chats read in chronological order with the newest message in view.

## Rollback
Revert the backend and dashboard commits, restore the backed-up Ali runtime configuration, and redeploy the previous revisions; no database migration or customer-data rewrite is involved.
