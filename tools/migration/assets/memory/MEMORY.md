# WTYJ (wetakeyourjob.com) Agent Platform — Memory Index

**This file is a pointer index, not a source of truth.** Details live in the files linked below.

> **READ THESE FIRST (in order):**
> 1. **[project_company_naming.md](project_company_naming.md)** — WTYJ is the real company. BlueMarlin and Adamus are demo clients. BlueFinn is a real charter company we have NO connection to (BlueMarlin's data USED to mirror BlueFinn's but Brief 150 scrubbed it).
> 2. **[project_session_state_2026_05_09.md](project_session_state_2026_05_09.md)** — Latest end-of-session snapshot. Briefs 236+237 shipped. **1015 tests passing / 0 failures.** All 4 containers healthy. unboks production data wiped clean (preserved tasks/settings/learnings). 12 Jr tasks closed, 2 reply tasks sent to SR. BlueMarlin email re-enabled (was missing EMAIL_ADDRESS env var); BlueMarlin demo prep aborted before WhatsApp went live (Meta app unpublished, Late at 2/2 phone limit).
> 3. **[project_session_state_2026_05_08_late.md](project_session_state_2026_05_08_late.md)** — Prior snapshot. Briefs 224-235.
> 4. **[project_open_work.md](project_open_work.md)** — Single list of unfinished work and next steps.

## Quick Reference (post Brief 196)
- Working dir (Mac): `~/Projects/bluemarlin-agent/` (source at `wtyj/`, clients at `clients/bluemarlin/`, `clients/adamus/`, `clients/consultadespertares/`)
- Mac Python: 3.14. VPS: Python 3.12, Ubuntu.
- VPS source: `/root/wtyj/`. VPS clients: `/root/clients/{bluemarlin,adamus,consultadespertares,unboks}/`
- Containers: `wtyj-bluemarlin` (8001), `wtyj-adamus` (8002), `wtyj-consultadespertares` (8003), `wtyj-unboks` (8004), `wtyj-staging` (9001). Image: `wtyj-agent:latest` (production), `wtyj-agent:staging` (staging container), `wtyj-agent:previous` (rollback target), `wtyj-agent:<short-sha>` (per-build archive).
- **Deploy queue at `/root/wtyj_deploy_queue.json`** — managed by `wtyj/shared/deploy_queue.py` with `fcntl.flock`. Visualized in control panel `Deploys` tab.
- Repo: `BensonOpas/wtyj-agent` (renamed from `bluemarlin-agent`)
- SR's frontend repo: `unboks-org/unboks-dashboard-api` (perma-clone at `~/Projects/unboks-dashboard-api/`)
- **All infrastructure details → `wtyj/briefs/infra.md`** (VPS, credentials, services, deploy pipeline, URLs, channels)
- **Endpoint inventory → `wtyj/docs/endpoint_inventory.md`** (canonical caller↔handler map; regenerate with the grep at the bottom)
- **Tasks CLI → `tools/unboks-cli/tasks.py`** (`python3 tools/unboks-cli/tasks.py list --status open`)
- **Product vision → `wtyj/briefs/master_plan.md`**
- **What to build next → `wtyj/briefs/roadmap.md`**
- **Brief history → `wtyj/briefs/system_state.md`**
- **Lessons learned → `wtyj/briefs/marina_lessons.md`**
- **Live preps decisions → `wtyj/docs/project_live_preparations.md`** (deploy model, off-hours, rollback, snapshot decisions captured per protocol)

## Deployment status (2026-05-09 end-of-session, post Briefs 236+237)
- **Last deployed:** Brief 237 (post-exec `80d45bf`). All 4 containers healthy (8001, 8002, 8003, 8004).
- **1015 tests passing / 0 failures** (1100 → 1007 via Brief 236 tautology cleanup, 1007 → 1015 via Brief 237's 9 new + 1 stale removed).
- **Pipeline live:** push to main → test → canary deploys to BlueMarlin always + 10-check E2E → off-hours-decide queues for off-hours OR proceeds with `[HOTFIX]` in subject → production deploys to Adamus + Consulta Despertares + unboks with pre-deploy DB snapshot + auto-rollback on failure.
- **Three unboks feature flags flipped ON live:** `features.approved_learnings_in_prompt: true` + `features.info_updates_in_prompt: true` + `features.knowledge_files_in_prompt: true` (Brief 230). Default-OFF for other tenants.

## References
- [reference_saas_checklist.md](reference_saas_checklist.md) — 6-point SaaS production checklist
- [reference_late_dms.md](reference_late_dms.md) — Zernio (Late) full platform reference
- [late_api.md](late_api.md) — Late API setup notes
- [stripe_test.md](stripe_test.md) — Stripe test key
- [reference_google_cloud.md](reference_google_cloud.md) — Google Cloud project, OAuth, account ownership
- [reference_calico_ai.md](reference_calico_ai.md) — AI video platform (future)
- [reference_email_accounts.md](reference_email_accounts.md) — All platform email accounts and what each one is for

## Feedback memories
- [feedback_read_before_acting.md](feedback_read_before_acting.md) — ALWAYS read files before acting, never trust summaries or memory
- [feedback_detailed_lessons.md](feedback_detailed_lessons.md) — Lessons entries must be detailed (full story, not 2 sentences)
- [feedback_env_file_format.md](feedback_env_file_format.md) — VPS env file must NOT have `export` prefix
- [feedback_always_run_reviewers.md](feedback_always_run_reviewers.md) — Always run reviewers
- [feedback_design_principles.md](feedback_design_principles.md) — Scale, dynamism, client-agnostic
- [feedback_partner_not_servant.md](feedback_partner_not_servant.md) — Challenge the user, research first
- [feedback_communication.md](feedback_communication.md) — Plain language, TLDR after changes
- [feedback_post_exec_subagents.md](feedback_post_exec_subagents.md) — Post-exec subagents run background/silent, never add wall-time or TLDR noise
- [feedback_default_effort_and_tight_briefs.md](feedback_default_effort_and_tight_briefs.md) — Use default effort + tight briefs; max effort + 600-line briefs ate 6.5 hours on Brief 205

## User memories
- [user_role.md](user_role.md) — Who Benson is and how to work with him

## Project memories
- **[project_company_naming.md](project_company_naming.md) — READ FIRST** — WTYJ vs BlueMarlin vs BlueFinn vs Adamus
- **[project_session_state_2026_05_08_late.md](project_session_state_2026_05_08_late.md) — READ SECOND** — current state (post Brief 235), 1100 tests, Briefs 224-235 shipped, 3 unboks flags ON, TASK-60 cloud connectors queued for next stretch
- [project_session_state_2026_05_08.md](project_session_state_2026_05_08.md) — older snapshot (briefs 216-223 era, 1028 tests)
- [project_session_state_2026_05_07.md](project_session_state_2026_05_07.md) — older snapshot (briefs 209-218 era, 998 tests, Tier 2 mostly done)
- [project_session_state_2026_05_06.md](project_session_state_2026_05_06.md) — older snapshot (briefs 200-208 era, Tier 1 done)
- [project_session_state_2026_04_14.md](project_session_state_2026_04_14.md) — older snapshot (briefs 195-196 era, pre-unboks-tenant launch)
- [project_session_state_2026_04_06.md](project_session_state_2026_04_06.md) — even older snapshot (briefs 146-154 era)
- **[project_open_work.md](project_open_work.md) — READ THIRD** — what's next, IMMEDIATE Adamus email bootstrap item
- [project_dashboard.md](project_dashboard.md) — Dashboard architecture and SR's role
- [project_image_pipeline_future.md](project_image_pipeline_future.md) — Current graphics are placeholder
- [project_ig_fb_dms.md](project_ig_fb_dms.md) — IG/FB DMs via Zernio (deployed)
- [project_generalization_priority.md](project_generalization_priority.md) — Phase 2 priorities (now COMPLETE per Brief 152)
- [project_adamus_deployment.md](project_adamus_deployment.md) — Restaurant Adamus deployment notes (now mostly complete except email OAuth)
- [project_phase1_notes.md](project_phase1_notes.md) — Benson's Phase 1 polish notes (12 items: UX, tone, booking flow, logs, brand)
- [project_llm_training_data.md](project_llm_training_data.md) — Preserve all docs for future LLM fine-tuning
- [project_windows_migration.md](project_windows_migration.md) — Full plan to migrate dev from Mac to Windows 11 + WSL2 (not now, ready when he is)
- [project_sr_parallel_backend.md](project_sr_parallel_backend.md) — RESOLVED — SR's frontend at `unboks-org/unboks-dashboard-api` is now the canonical dashboard; Python backend is the single source of truth for everything dashboard reads/writes (no Node parallel backend in use)

## Dashboard frontend repo
- Production frontend (SR's): `unboks-org/unboks-dashboard-api` (perma-clone at `~/Projects/unboks-dashboard-api/`)
- Direct push by Benson is the workflow (SR + Benson share `main`; Replit auto-deploys on push)
- Hosted: served from Replit; URL behind `dashboard.unboks.org`
- Vite dev/preview proxy forwards `/api/*` to `https://api.unboks.org` so Replit dev preview works without env vars (commit `65993d8`, 2026-05-08)
- Stack: React 19 + Vite + Tailwind + shadcn/ui + TanStack Query
- Legacy: `BensonOpas/wetakeyourjob-dashboard` (pre-unboks rebrand, archived but kept as a fallback reference)
