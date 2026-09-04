# Mermaid pickup vehicle pricing
**Status:** Deployed and verified | **Files:** tenant catalog/version, catalog pricing helper, monetary snapshot, guest presentation, understanding/workflow, PDF labels, tests, runtime overlay | **Depends on:** one-page quote release 2eb3709 | **Blocks:** None

## Context
The user clarified pickup capacity and price: one car carries at most five customers for USD 75; six through nine customers need a van at USD 125 per van. The old unconditional USD 75 fee is wrong above five guests. Count adults, children and infants as passengers. Island-wide coverage and 05:45 pickup remain unchanged.

## Why This Approach
Select and price vehicles in Python using tenant configuration, then persist the selected vehicle, capacity, quantity and charge with the immutable reservation. Reject a prompt-only change because checkout could still charge USD 75. Existing quotes/payments keep their original amounts and do not gain an invented vehicle assignment. The user was asked asynchronously whether groups above nine should use multiple vans or require team confirmation; until clarified, require review instead of inventing a larger-group charge.

## Instructions
- Replace current flat pickup configuration with car/van capacities and per-vehicle prices. Keep old snapshots readable.
- Compute a pickup plan from the complete party count. Unknown party size cannot produce a final pickup charge. Preserve the selected vehicle and line-item quantity/unit price/total in new snapshots.
- Feed current pricing options and known-party offers to the one-call model contract. Explain the appropriate vehicle naturally; never promise one car above its capacity. Do not treat an enquiry as pickup consent.
- Render the same selected vehicle and amount in summaries, checkout, one-page quotes and receipts. Preserve historical money and old transport presentation when no vehicle was snapshotted.
- Gate any configured over-capacity review in both workflow and reservation creation so a model response cannot bypass it. Review must not mute safe conversation.
- Deploy only Mermaid on the current image with minimal configuration merge and rollback backup; no customer sends or retroactive repricing.

## Tests
Passenger-count boundaries (including children/infants), corrected party sizes, pier exclusion, missing counts, overflow policy, historical snapshots, all six locales and one-page quotes, and isolated real-model replies with no provider sends.

## Success Condition
Five guests receive a USD 75 car quote; six to nine receive a USD 125 van quote; every customer surface matches the persisted pickup plan.

## Rollback
Restore the prior Mermaid image and catalog/client version from the deployment backup, retaining current customer data and any immutable vehicle snapshots.

## Verification
- 292 Mermaid/status tests passed, covering passenger boundaries, six-language quote/receipt/checkout consistency, configuration errors, optional multiple-van math, capacity review gates and immutable historic pricing. Quotes and receipts remain one page; English and German van examples were visually checked.
- Real-model testing exposed an enquiry being recorded as pickup consent and a corrected party being asked for its known name again. The structured field descriptions now distinguish an enquiry from an explicit pickup choice, and the model receives the server's missing-fields list. The final eight-turn replay covers both fixes, car/van boundaries, a baby counting toward capacity, a six-adult USD 1,025 quote and over-capacity team review, with no provider sends.
- Larger groups remain on team review pending the user's optional clarification; capacities/prices for one car and one van are fully implemented. Explicit `multiple_vans` configuration is supported and tested but is not enabled by default.
- The exact release image passed 105 focused tests. Mermaid is running `wtyj-agent:tracy-vehicles-776b0df`, image digest `sha256:98cb55599905a9d2342c3f870c426a97ddca5b9ef08ead69d6859cb0ba2927c3`, with catalog `mermaid-demo-v4-2026-09-03`. Deployment backup: `/root/backups/tracy-vehicles-776b0df`; source: `/root/releases/tracy-vehicles-776b0df`.
- Live dry-run pricing confirms the 1/5/6/9 passenger boundaries and totals including mixed age bands. The existing booked reservation and its USD 600 monetary snapshot are unchanged. Public health and the watchdog are healthy; all six peer containers are unchanged. No customer messages were sent.
