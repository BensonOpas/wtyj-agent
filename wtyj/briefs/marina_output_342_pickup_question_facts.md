# OUTPUT 342 — Authoritative pickup-question facts

## What was done
Added a structured pickup-pricing enquiry route to the existing one-call
understanding contract. The server now renders party composition, total
passengers, configured vehicle capacity/price, scheduled collection time and
return coverage from the catalog or immutable reservation snapshot. A separate
optional string preserves distinct non-transport FAQ answers without appending
the model's pickup arithmetic. Pure price enquiries stay unselected; explicit
mixed pickup requests remain valid. Existing review decisions, cancellation,
human requests and security refusals retain priority.

## Tests
211 passing / 0 failures across pickup questions, vehicle pricing, authoritative
policy, model recovery and soft-review integration; includes 46 new focused
cases. The original Papiamentu BASE-023 contradiction was reproduced first.
An independent reviewer approved the diff and independently passed all 46 new
checks. Papiamentu native-language certification remains pending.

## Deployment
No deployment, live state changes, guest sends or paid model calls were made.
The root release owner integrates this isolated commit with the companion
review-status repair and runs final combined acceptance.
