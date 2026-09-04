# OUTPUT 342 — Preserve FAQ answers beside recorded status

## What was done
Payment, handover and delivery routes now combine the dedicated general-trip
FAQ answer with server-owned status. The ordinary model reply remains discarded;
an empty or omitted FAQ field never causes a fallback to unverified prose.
The updated one-call schema requires a string for new output, while existing
legacy omissions remain compatible with recovery validation. Prompt guidance
permits food and published pier check-in facts and prevents pending review or
volunteered pickup prices from selecting an unrelated status route. An explicit
priority guard preserves decisions blocked by pending review.

## Tests
252 passing / 0 failures across authoritative policy, pickup, model recovery and
soft-review integration. Forty new regressions include all six languages and
the exact German BASE-045 turn 6, plus empty/omitted FAQ and action priorities.
The original German case and all 18 locale/selector cases failed first.
Six existing real-record cases verify FAQ composition with payment and delivery
status changes. Malformed-field recovery and operator controls remain covered.

## Deployment
No paid model calls, guest sends, live state changes or deployment. Parent independently approved both the brief and final output before commit. Deterministic regressions establish routing behavior, not fresh model
compliance or native-language certification.
