# Brief 326 — Despertares pricing knowledge regression

**Status:** Verified, tenant-only deployment pending
**Files:** agents/marina/marina_agent.py; shared/state_registry.py;
tests/agents/test_326_despertares_pricing_knowledge.py;
scripts/verify_despertares_pricing.py
**Depends on:** Brief 320 single-SOT authority

## Context

On 2026-09-03 an adult-session price enquiry was unnecessarily relayed. On
2026-09-04 the model quoted unsupported individual and family tariffs. The
correct prices existed in ICP pricing knowledge, but Brief 320 excluded every
ICP entry whenever any dashboard SOT existed. This clinic's dashboard SOT
contained personality and reference links, not replacement tariffs. Links
are not automatically crawled. A later operator price note mitigated the
missing values without fixing the lost-source regression.

## Why this approach

Restore only the clinic's structured pricing/services reference categories,
with current operator updates explicitly higher priority. Preserve
valid base facts and require service-specific grounded prices. No hardcoded
tariffs, additional model calls, UI changes or stored-note edits.

Rejected a global revert: it would restore superseded rental policy for Ali.
Rejected restoring all clinic ICP policy: legacy greetings, first-session
exceptions, intake, and appointment rules must not silently regain priority.
Rejected a currency-only whitelist as a complete safety mechanism: the right
amount for the wrong service would pass, while legitimate corrected amounts
or bundles could fail. Grounding is a prompt contract, verified with actual
model replays; it is not claimed as a deterministic hallucination guarantee.

## Instructions

- Render pricing/services references only for consulta-despertares, when the
  normal ICP block would otherwise be suppressed by dashboard SOT.
- Leave existing instructions in place; state their precedence over old
  reference facts in the final pricing contract. Do not change the precedence
  of unrelated greeting, scheduling or escalation instructions.
- Give clinic updates explicit newest-edit priority numbers. An existing
  note edited today must outrank an older competing note even if its original
  creation date is earlier. Other tenants retain their existing ordering.
- Add a final price grounding contract: exact service/amount pairs, no pricing
  from AI history or bare links, correct stale replies, answer known prices
  without unnecessary escalation, and follow operator fallback for unknowns.
- Leave human dashboard replies, other tenants, routing and persisted data alone.

## Tests

Exercise the actual prompt builder with isolated tenant databases: partial
dashboard knowledge, generic pricing instruction without amounts, updated
prices, obsolete online exception, missing bridge, malformed entries, legacy
booking-policy exclusion, and unchanged Ali single-source behaviour. Replay
synthetic versions of the reported enquiries against the configured live model
without delivering messages or writing conversation records.

## Replay finding

The first candidate passed 8/9 real-model cases but failed a synthetic partial
price update: a long older tariff note overruled a short newer correction.
The final contract therefore uses explicit priority numbers and newest-edit
ordering. All operator texts and validity windows remain unchanged.

Final verification: 2,114 automated tests pass. All nine isolated real-model
replays pass, including the missing-baseline scenario, separate family tariff,
online first session, unsupported tariff fallback, stale AI price correction,
and a synthetic partial update of the individual rate. No WhatsApp messages
were delivered and no prospect records were created by these checks.

## Deployment boundary

Use a tenant-only hotfix, not the automatic all-tenant deployment. Existing
Despertares Compose configuration contains unrelated pending environment
changes; preserve both that configuration and the running environment. Verify
the two old runtime source hashes match main before replacing only those two
modules, then restart the existing tenant container. Keep rollback copies and
the merged source. Never recreate or restart unrelated tenant containers.

## Success condition

Correct clinic tariffs reach the model despite partial dashboard SOT; both
reported enquiries receive grounded prices without tariff-only escalation,
newer instructions win, and unrelated tenants' tests pass.

## Rollback

Revert this code commit and redeploy only consulta-despertares, or restore its
pre-deploy image. No data migration or operator-note rollback is needed.
