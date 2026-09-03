# Mermaid demo catalog and feature controls

## Scope

Create one tenant-scoped, versioned Mermaid demo catalog consumed by TRACY,
reservation pricing, quote rendering and the dashboard.

Published demo facts:

- Adult: USD 150, EUR 130, XCG 270.
- Child age 4-12: USD 75, EUR 65, XCG 135.
- Child age 0-3: free.
- Operating days: Monday, Tuesday, Wednesday, Friday, Saturday and Sunday.
- Arrival: Fishermen's Pier at 06:45.
- Island departure: approximately 15:20.
- Includes breakfast; soft drinks and juices; BBQ lunch; Mermaid beach house;
  restrooms and fresh-water shower; snorkeling equipment; beach chairs.
- Beer and wine are available for an additional charge.
- Pickup/return is optional and its price remains unspecified in the demo.
- Bring towel, sunscreen, swimwear and personal medication.

Demo policy text must be visibly marked as demo content. Use a conservative
48-hour cancellation placeholder and neutral safety wording; do not claim
verified insurance coverage.

Add independent Mermaid-only flags for intake, quote delivery, demo payment
and dashboard projection. Reminders default off and cannot be enabled by the
demo feature.

## Acceptance

- Schema/config validation rejects missing prices, unsupported currencies,
  malformed schedules and unmarked demo policy text.
- All consumers receive the same immutable catalog version.
- Ali and every non-Mermaid tenant remain byte-equivalent.
- Config contains no secret, provider credential or real-payment endpoint.
- Tests prove reminders remain disabled.

## Rollback

Disable the Mermaid reservation demo feature flags and restore the previous
Mermaid config; historical snapshots remain readable.
