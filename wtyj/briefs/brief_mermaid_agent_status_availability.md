# BRIEF — Distinguish unavailable agent controls from an operator pause
**Status:** Implemented | **Files:** dashboard/api.py; shared/icp_overrides.py; tests/dashboard/test_agent_control_availability.py; tests/shared/test_icp_overrides.py | **Depends on:** live Mermaid pickup source 8053f5d | **Blocks:** truthful dashboard agent status

## Context
The user reported that TRACY appears to pause without an operator action. The
live backend's GET status route maps every false `auto_reply_enabled` result to
`paused`, including a timed-out control-panel read. Runtime controls already
distinguish unavailable (`None`) from an explicit pause (`False`), but the status
endpoint discards that distinction. These reads never persist a pause.

Both agent status routes and the dashboard's companion ICP override/onboarding
reads were asynchronous handlers invoking the synchronous bridge. A slow GET
blocks unrelated HTTP handling for its three-second timeout; an explicit update
can wait on both its write and verification read.

Read-only production audit found Mermaid's durable `ai_auto_reply` still true,
last updated by `nr2-dashboard` at 2026-09-03T22:38:34Z. The last actual
`tenant_agent_paused` event predates that activation (21:55:15Z); the last control
unavailability event (23:40:35Z) predates the control-panel lock repair
(23:40:47Z). There is no evidence of a new durable automatic pause. Public and
local status checks both returned verified active during this audit.

## Why This Approach
Expose the existing tri-state control result to the dashboard: unknown controls
return `active: null`, `status: unavailable`, and `available: false`. Verified
active/paused responses retain their existing shape. Run these synchronous
handlers in FastAPI's normal worker pool to preserve unrelated HTTP progress.

Coalesce ordinary override reads per tenant and check the cache inside the
shared read lock. Otherwise, concurrent dashboard startup requests can each
fetch healthy controls but supersede each other through the existing freshness
fence, falsely reporting unavailability. Pre-send and pause-verification fresh
reads bypass this lock and retain all request-sequence/generation safeguards.
The lock registry survives cache invalidation so overlapping callers cannot
create different locks for the same tenant.

Rejected automatically enabling replies on bridge failure: that would bypass
operator control and tenant isolation safeguards. Also rejected presenting the
last known enabled state as current because a pause may have occurred meanwhile.
The runtime's strict sending checks and all control writes remain unchanged.
Rejected reusing an older cached enabled result while a newer read is pending:
the newer read could be an authoritative pause. Coalescing only ordinary reads
avoids that ambiguity without relaxing the fresh-read fences.

## Instructions
1. Update the status read at `dashboard/api.py:1007` to preserve unknown state.
2. Use synchronous route functions for agent GET/PUT, ICP overrides
   (`dashboard/api.py:259`), and onboarding status (`dashboard/api.py:209`) so
   dashboard startup bridge I/O leaves the event loop available; retain existing
   authentication and strict boolean validation.
3. Have dashboard consumers show unavailability and disable state-changing
   controls until a boolean authoritative status returns.
4. Coalesce ordinary reads at `shared/icp_overrides.py:345`, leaving forced reads
   and the existing cache generation/request-sequence fences unchanged.

## Tests
All ten new regression cases fail without their respective fixes: six because
unavailable state appears paused, and four because agent GET/PUT and companion
startup reads block a simultaneous HTTP request until timeout. The regressions cover missing
controls, null values, unavailable responses with stale false values, recovery
to either explicit state, and concurrent HTTP progress while the bridge waits.
The existing client-profile and ICP override suites cover authentication,
explicit pause persistence, strict inputs, and stale-fetch pause fencing.
Review additionally reproduced healthy parallel HTTP reads incorrectly returning
unavailable before ordinary-read coalescing. The new HTTP test exercises either
dashboard endpoint reading first; both return available with one bridge fetch.
Two more cases verify an expired ordinary read cannot revive enabled state while
a newer forced pause is pending or after it completes. The existing explicit
pause generation-invalidation test remains unchanged and passes.
After the fix, these three suites pass: **46 tests** on local Python 3.14.
Production verification should repeat the same suites in the exact deployment
image's Python 3.12 runtime without production mounts or network access.

The broader exact-image run exposed an unrelated timing-sensitive fixture in
`tests/test_mermaid_runtime_hardening.py:2425`: same-inode, same-size recovery
writes sometimes retained the prior `mtime_ns` in Docker (66 of 100 isolated
repetitions reported by the deployment task). The fixture now publishes its
final valid configuration through a sibling-file atomic replacement, matching
production writes and giving it a distinct inode. Its malformed in-place write
and last-good assertions remain unchanged. This is a test-fixture correction;
production `config_loader.py` is unchanged.

## Success Condition
A control-panel outage is displayed as unavailable without writing a pause, and
waiting for the bridge leaves the tenant HTTP event loop responsive.

## Rollback
Revert this commit and redeploy the previous verified image. This change does
not write control state, customer data, or configuration, so no data rollback is
required. Revert the matching frontend contract change with the backend rollback.
