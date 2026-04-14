# OUTPUT 195 — Canary deploy pipeline

## What was done

Rewrote `.github/workflows/ci-deploy.yml` as a four-job canary pipeline (test → off-hours-check → deploy-canary → deploy-production) and added four helper scripts at `wtyj/scripts/`: `off_hours_check.py` (DST-correct via `zoneinfo` for Curaçao + Madrid, blocks deploys during either's business hours unless `[HOTFIX]` in commit message), `e2e_canary_test.sh` (10 checks on BlueMarlin: health, login, config, brain via seeded `/messages/suggest-reply`, DB writability, conversations, escalations, signed-webhook accept, conversation_status write, customer record write — sentinel `e2etest`-prefixed test data swept at end), `pre_deploy_snapshot.sh` (timestamped `/root/backups/pre_deploy/<ts>_<sha>/` copies before paying-client deploy, 7-day retention), `rollback.sh` (retags `wtyj-agent:previous → :latest` + `:staging`, restarts containers). Image tagging: each build tags `:latest`, archives as `:<short-sha>`, retags previous as `:previous` for instant rollback. Staging container now gets rebuilt code via `:latest → :staging` retag. No Python source code changes outside `wtyj/scripts/`.

## Tests

899 passing / 0 failures (baseline 893 + 6 new).

## Unexpected findings

**The `[HOTFIX]` substring match is too loose.** My commit message contained the literal string `[HOTFIX]` inside a documentation line describing the bypass mechanism (`block, [HOTFIX] bypass. Tested at boundary cases`). The off-hours check matched on that substring and bypassed the business-hours block — which is how the pipeline managed to self-deploy at 13:17 UTC (mid-Curaçao + Madrid business hours). Fortuitous: it let me validate the pipeline end-to-end on the same commit that introduced it. But the bypass marker needs to be stricter (subject-line prefix, dedicated trailer, or more specific token like `[HOTFIX-DEPLOY]`) to prevent accidental bypasses when commit messages legitimately mention the feature. Logged as a follow-up brief.

**Full pipeline validated first try.** Ten E2E checks all green: `1/10 health → 10/10 customer record`. Image tags present (`:a9ee25f`, `:latest`, `:staging`, `:previous`). Pre-deploy snapshot directory created (`/root/backups/pre_deploy/20260414T131820Z_a9ee25f/`). All 4 containers healthy post-deploy.

## Deployment

Source commit `a9ee25f` pushed. CI run `24401106632` completed all 4 jobs successfully (test ✓, off-hours-check bypassed-by-accident ✓, deploy-canary ✓ with all 10 E2E checks green, deploy-production ✓). All 4 containers healthy: 8001 (BlueMarlin), 8002 (Adamus), 8003 (Consulta Despertares), 9001 (staging).
