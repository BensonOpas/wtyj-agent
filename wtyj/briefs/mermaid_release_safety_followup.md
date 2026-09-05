# BRIEF — Mermaid release safety follow-up
**Status:** Executed | **Files:** `wtyj/scripts/prepare_mermaid_reservation_release.py`, `wtyj/scripts/deploy_mermaid_release.sh`, `wtyj/tests/scripts/test_prepare_mermaid_reservation_release.py`, `wtyj/tests/scripts/test_mermaid_deploy_isolation.py` | **Depends on:** `wtyj/briefs/mermaid_reservation_release_hardening.md` | **Blocks:** Mermaid scoped release

## Context
The scoped release verifies the live side of its compare-and-swap but does not verify staged or backup payload bytes before writing them. A local reproduction changed a staged file after manifest creation and the helper wrote those unreviewed bytes while reporting success. If candidate recreation removes the container and then fails, rollback rejects the absent container and leaves candidate files installed. The tracked response policy is loaded from the mounted configuration directory but is absent from the protected release file set.

## Why This Approach
Verify and retain the exact payload bytes under the existing configuration lock, accept container absence only after a successful Docker inventory proves it, and add the response policy to the existing four-file lifecycle. This extends the established release transaction without changing generic CI targets or adding a second deployment framework. A shell-only recovery workaround was rejected because it would leave the Python apply/rollback boundary able to write unauthenticated payloads.

## Instructions
1. In `wtyj/scripts/prepare_mermaid_reservation_release.py`, include `config/response_policy.json` in the release file set and stage it from the reviewed source.
2. Before apply or rollback writes, require every source payload to be a regular non-symlinked file whose digest matches the corresponding manifest digest. Cache verified bytes and write those bytes so validation and use cannot diverge. Verify original rollback payloads before any apply that may need partial-write recovery.
3. Treat Mermaid as safely stopped when exact inspection returns `false`, or when inspection fails and a successful exact-name Docker inventory proves the container is absent. Docker inventory errors and ambiguous/present containers remain failures.
4. Preserve the existing shared deployment lock, Mermaid-only service commands, live-side compare-and-swap, database preservation and peer checks.

## Tests
- A staged payload changed after manifest creation cannot be applied.
- A backup payload changed after manifest creation cannot be restored.
- Rollback restores all protected files when a failed recreation leaves Mermaid absent; Docker inventory failure remains fail closed.
- Response policy participates in preparation, hash checks, apply and rollback while the live database audit remains unchanged.
- Existing generic queue/rollback isolation and scoped deployment tests remain green.

## Success Condition
No release writes bytes not authenticated by its manifest, rollback handles a verified missing Mermaid container, and response policy has the same backup/CAS guarantees as every other protected configuration file.

## Rollback
Revert this focused patch; do not deploy the older scoped helper until the three release blockers are resolved another way.
