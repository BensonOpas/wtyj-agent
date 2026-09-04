# BRIEF — Preserve child ages in formal booking details
**Status:** In progress | **Files:** shared/mermaid_guest_ages.py, shared/mermaid_customers.py, agents/social/mermaid_understanding.py, agents/social/mermaid_reservation_workflow.py, agents/social/mermaid_reservation_store.py, agents/social/mermaid_guest_experience.py, dashboard/api.py, Mermaid tenant config; dashboard account and receipt views | **Depends on:** current live audit and customer-account releases | **Blocks:** none

## Context
The guest explicitly said their baby was nine months old during an information question. Only the infant count was persisted. The formal summary then used the conversational phrase little one (0–3), losing the known age.

## Why This Approach
Save structured, explicitly supplied ages in the existing one-call extraction and intake. Share professional party formatting between chat summaries, PDFs and the dashboard. Reject parsing ages from customer prose in Python or guessing from fare categories. Keep warm ordinary conversation unchanged. No extra required booking questions or changes to prices.

## Instructions
Validate ages and count consistency, preserve known ages across unrelated turns, invalidate uncertain ages when a group shrinks, include supplied ages in summary identity while preserving legacy hashes, and retain them in customer details/history. Refresh summaries after corrections. Add the verified nine-month age to the current unquoted test intake with a compare-and-swap guard. Do not rewrite historical issued PDFs, prices, or reservations, or send messages to customers.

## Tests
Verify nine-month capture in information enquiries, persistence after unrelated details, multilingual formal party copy, malformed/count-conflicting ages, corrections requiring fresh confirmation, shrinkage, unchanged pricing and legacy identity, one-page PDF rendering and API/customer persistence. Verify dashboard age display and existing controls.

## Success Condition
A guest-supplied nine-month age appears as infant (9 months) in the next formal summary, quote/receipt and saved account while chat remains natural.

## Rollback
Restore the prior Mermaid image/config and dashboard symlink. Keep additive saved ages and current messages; do not replace the live database with an older backup.
