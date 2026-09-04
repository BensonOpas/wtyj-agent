# BRIEF — Preserve child ages in formal booking details
**Status:** Complete | **Files:** shared/mermaid_guest_ages.py, shared/mermaid_customers.py, agents/social/mermaid_understanding.py, agents/social/mermaid_reservation_workflow.py, agents/social/mermaid_reservation_store.py, agents/social/mermaid_guest_experience.py, dashboard/api.py, Mermaid tenant config; dashboard account and receipt views | **Depends on:** current live audit and customer-account releases | **Blocks:** none

## Context
The guest explicitly said their baby was nine months old during an information question. Only the infant count was persisted. The formal summary then used the conversational phrase little one (0–3), losing the known age.

## Why This Approach
Save structured, explicitly supplied ages in the existing one-call extraction and intake. Share professional party formatting between chat summaries, PDFs and the dashboard. Reject parsing ages from customer prose in Python or guessing from fare categories. Keep warm ordinary conversation unchanged. No extra required booking questions or changes to prices.

## Instructions
Validate ages and count consistency, preserve known ages across unrelated turns, invalidate uncertain ages when a group shrinks, include supplied ages in summary identity while preserving legacy hashes, and retain them in customer details/history. Refresh summaries after corrections. Add the verified nine-month age to the current unquoted test intake with a compare-and-swap guard. Do not rewrite historical issued PDFs, prices, or reservations, or send messages to customers.

## Tests
Verify nine-month capture in information enquiries, persistence after unrelated details, multilingual formal party copy, malformed/count-conflicting ages, corrections requiring fresh confirmation, shrinkage, unchanged pricing and legacy identity, one-page PDF rendering and API/customer persistence. Verify dashboard age display and existing controls.

## Rollout Evidence
- Backend `wtyj-agent:tracy-age-1b5d54f` (`sha256:d76b9e4da40beeff1df04c26fb299feeb47d225e90ee02680edcbc7c0f8e9160`) is healthy with catalog `mermaid-demo-v7-2026-09-04`; its exact image passed 74 tests and the complete local Mermaid suite passed 801 tests.
- The dedicated child-age suite, including one-page PDF extraction, passed 12 tests.
- Dashboard release `4f5e7da51b7eab9dd1f74c9e7d800b889b9d4e26` displays the saved nine-month age; its UI tests, typecheck, production build and authenticated live browser check passed.
- The guarded repair saved `9 months` on conversation `6a997cbb837438e2a7862522`, reset its intake to collecting for a fresh summary, and left all 26 messages, pricing and reservations unchanged. No customer message was sent.

## Success Condition
A guest-supplied nine-month age appears as infant (9 months) in the next formal summary, quote/receipt and saved account while chat remains natural.

## Rollback
Restore the prior Mermaid image/config and dashboard symlink. Keep additive saved ages and current messages; do not replace the live database with an older backup.
