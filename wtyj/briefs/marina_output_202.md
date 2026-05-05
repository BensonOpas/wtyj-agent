# OUTPUT 202 — Surface sender_name in conversation list for dm_agent-path tenants

## What was done
Single-function change at `wtyj/shared/state_registry.py:wa_list_conversations()` adds a 4th-tier customer-name fallback: when `whatsapp_booking_state.fields.customer_name` is empty (the dm_agent path for booking_flow:false tenants like unboks doesn't populate it), now queries `whatsapp_threads.sender_name` for the most recent user-role message and uses that. Marina's path remains untouched — booking_state.customer_name still wins by priority order. Closes discrepancy #12 from the SR communication audit (dashboard inbox showed Zernio hex IDs instead of human names for unboks/calvin-csa conversations). Zero changes to the dashboard API layer; the dict response key stays `customer_name`, so SR's frontend mapper resolves it on first try without any frontend coordination. Two new tests cover both branches: dm-only path falls back to sender_name; Marina path with booking_state preserves priority. Brief-reviewer PASS first try, no flagged issues.

## Tests
913 passing / 0 failures (baseline 911 + 2 new — sender_name fallback for dm-only conversation, regression guard for Marina-path priority).

## Deployment
Source commit will be `<source-sha>`. Standard deploy via the canary pipeline rebuilds the shared image and restarts all 4 production containers + staging. Post-deploy verification: open `https://dashboard.unboks.org`, log in, the inbox now shows "Calvin" (or whatever sender_name Zernio passed) for both unboks conversations instead of the 24-char hex.
