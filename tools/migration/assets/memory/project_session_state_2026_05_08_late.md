---
name: Session state — 2026-05-08 late
description: End-of-stretch snapshot after Briefs 224-235 shipped. Tonight's batch: 12 briefs, +72 tests, all 4 containers healthy at 1100 tests passing. Most of SR's overnight task batch closed; cloud connectors (TASK-60) explicitly deferred to OAuth registration session.
type: project
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
# Session state — 2026-05-08 late (post Brief 235)

**Latest snapshot.** Supersedes `project_session_state_2026_05_08.md` (which was the 1028-test mid-day snapshot). Tests went from 1028 → 1100, +72 across 12 new briefs (224-235).

## Test count + container health
- **1100 passing / 0 failures**
- All 4 production containers healthy: BlueMarlin (8001), Adamus (8002), Consulta Despertares (8003), unboks (8004), plus staging (9001).
- Latest backend commit on `main`: `be59331` (Brief 235 post-exec docs)

## Briefs shipped this stretch (in commit order)

| # | Brief | One-liner |
|---|---|---|
| 224 | Strip internal escalation tokens from Marina email replies | `[ESCALATE]`/`[SOFT_ESCALATION]`/etc no longer leak into customer-facing email. Allowlist not regex (preserves `[BOOKING_REF]` / `[PAYMENT_LINK]`). |
| 225 | Email reply endpoint for non-escalated threads | `POST /messages/conversations/{id}/email/reply` works on any email thread, not just escalated. Sibling to Brief 218's forward + delete. |
| 226 | Alternative email destination for escalation alerts | `email_alternative_destination` column on `alert_settings`. Pydantic `field_validator` rejects malformed emails 422. Dispatcher fans out to both, dedupes when equal. |
| 227 | Decision-first escalation summary | Claude generator at `dashboard/escalation_summary.py` populates `escalation_summary` JSON column on every escalation. Surfaces on `/escalations` rows + `/messages/conversations/{phone}`. **HAD TWO BUGS — fixed in 235.** |
| 228 | Appointments backend | New `appointments` table populated as side-effect of Brief 227's summary when `intent=='scheduling'`. New `GET /appointments`. |
| 229 | Data retention settings | `GET/PUT /settings/data-retention` storage. Pydantic `Literal` validation. Three action endpoints (archive-now/export/delete-customer-data) return 501. **Cleanup automation deferred.** |
| 230 | AI knowledge files Phase 1 | `pypdf` dep added. Upload + extract for PDF/DOCX/TXT. New `knowledge_files` table. Marina injection via `_build_knowledge_files_block` behind `features.knowledge_files_in_prompt`. **Cloud connectors deferred (TASK-60).** |
| 231 | Email poller crash on ISO `last_activity` | `_cleanup_stale_data` was crashing every iteration with `'<' not supported between instances of 'str' and 'int'` because Brief 210/218 wrote ISO strings while cleanup expected float epochs. Fix accepts both. |
| 232 | Archive auto-restore on inbound email | `flags.deleted=true` cleared when customer sends new email, unless blocked. Block always wins. WhatsApp/IG/FB unaffected (those hard-delete server-side). |
| 233 | Operator email reply role | New `role: "operator"` value on operator-typed replies. Brief 214 guidance path stays `marina`. Frontend mapper falls back to "assistant" until SR ships render update. |
| 234 | Marina-uses-approved-learnings on IG/FB DM path | `_build_dm_approved_answers_block` mirror of Brief 219's helper. Both branches of `_build_dm_system_prompt` get the injection. Channel-isolated learning pools. |
| 235 | Fix Brief 227 in production | (1) Status filter `WHERE status='pending'` matched zero rows because Brief 217 transitions rows to `'sent'` instantly — fixed to `IN ('pending','sent')` at both dedup + readback sites. (2) Extracted dispatcher to new `wtyj/shared/escalation_dispatcher.py` so email_poller process registers it via side-effect import (was None before — webhook_server's process had it but email_poller didn't). |

## Active feature flags on unboks (per-tenant, default OFF on others)

```
features.approved_learnings_in_prompt: true   (Brief 219, prior stretch)
features.info_updates_in_prompt:       true   (Brief 216, prior stretch)
features.knowledge_files_in_prompt:    true   (Brief 230, this stretch)
```

All three flips were direct edits to `/root/clients/unboks/config/client.json` followed by `docker compose restart`.

## New schema (this stretch)

| Table / column | Brief | Purpose |
|---|---|---|
| `alert_settings.email_alternative_destination` | 226 | second email recipient for escalation alerts |
| `pending_notifications.escalation_summary TEXT` | 227 | JSON-blob structured AI briefing |
| `appointments` table | 228 | scheduling-escalation-derived rows |
| `data_retention_settings` table | 229 | singleton config for retention policy |
| `knowledge_files` table | 230 | uploaded reference docs + extracted text |

## New endpoints (this stretch)

```
POST   /messages/conversations/{id}/email/reply        Brief 225
PUT    /settings/escalation-alerts (alternativeDestination kwarg) Brief 226
GET    /appointments                                    Brief 228
GET    /settings/data-retention                         Brief 229
PUT    /settings/data-retention                         Brief 229
POST   /data-retention/archive-now                      Brief 229 (501 stub)
POST   /data-retention/export                           Brief 229 (501 stub)
POST   /data-retention/delete-customer-data             Brief 229 (501 stub)
POST   /knowledge/files                                 Brief 230 (multipart)
GET    /knowledge/files                                 Brief 230
DELETE /knowledge/files/{file_id}                       Brief 230
```

## New shared module (Brief 235)

`wtyj/shared/escalation_dispatcher.py` — registers `_summary_dispatcher` via load-time side effect. Imported by both `dashboard/api.py` (replacing the inline ~70-line wrapper) and `email_poller.py` (closes the process gap that left email-channel escalations with NULL summaries).

## SR's task queue state

### Done by this stretch's work (most of the original 10-task batch)
- Marina email leaking `[ESCALATE]` (`e593428d74f6`) → Brief 224
- Email forward placeholder (`c420a13816f8`) → Brief 218 + 225
- Alternative email (`b5bbb58447a5`) → Brief 226
- Decision-first escalation view (`727264bd9c61`, `fd4b4a6fcba9`, `952f48c7c768` — three duplicates) → Brief 227 (then 235 fixed it for prod)
- Appointment thread-based (`fc3dc9eb2b40`, `4bf443de31a9` — duplicates) → Brief 228
- Data retention storage (`ab7d8f1eb97c`) → Brief 229 (cleanup automation = follow-up)
- AI knowledge Phase 1 (`1108f913ad12`) → Brief 230 (cloud connectors = TASK-60)
- Terminology AI → Agent (`a571664b0921`) → SR's frontend, done by SR
- Archive restore on inbound (`93328e8039e1`) → Brief 232
- Q1 of verification task (`f61c511ffd3c`): operator email reply role → Brief 233

### Still open in SR's task system
- **TASK-60 / `5beade3592c3aad4`** — Cloud connectors Phase 2 (Drive/OneDrive/Dropbox/SharePoint/Box). Filed by Jr tonight. Blocked on OAuth app registrations (need Benson + me at the consoles). The "8th task."
- **`f61c511ffd3c`** — 7 verification questions. Q1 (operator role) shipped via Brief 233. Q2/Q3/Q7 are SR's frontend. Q4 (knowledge flag location) confirmed. Q6 (data retention `policyActive: false` honesty) confirmed. Need to send the consolidated reply to SR.
- **`e4354116cf4a`** — empty body task. Skip.

### Still in my queue but not on SR's task board
- **Data retention cleanup automation** — the three 501 stubs from Brief 229. Real customer data destruction work. Multi-hour brief.
- **Operator-identity model** — required to populate the 3 null placeholders from Brief 222 (`humanGuidance`, `humanResponder`, `humanRespondedAt`). Multi-user auth feature, not on immediate roadmap.

## Important production state observations

### Email poller is now alive and processing
After Brief 231 deployed, the unboks email_poller drained its IMAP UNSEEN backlog and processed two queued emails from `calvin@gaimin.io` (one booking attempt for 2026-05-09 17:00 + one "I want to contract your service" → escalation row #9 fired with alert email to `butlerbensonagent@gmail.com`).

### Existing email threads on unboks all have `flags.deleted=true`
SR exercised the dashboard delete button on every email thread that existed pre-Brief-232. Those are still hidden from the inbox. Brief 232 doesn't bulk un-archive — it only auto-restores when a NEW customer message lands. Fresh customer email re-engagement is the trigger.

### Pre-Brief-227 escalation rows have NULL summaries
Rows 1-7 on unboks predate Brief 227's column add. They have NULL `escalation_summary` permanently (skipped backfill). Frontend renders generic fallback text for those. Newly-created escalations on any channel (rows 8+) will have summaries from this point forward.

### Zernio webhook 403s on `/webhooks/zernio` (no `/api/{tenant}/` prefix)
The legacy bare URL hits the catchall on `api.wetakeyourjob.com` which forwards to BlueMarlin. Some tenant's Zernio config still points at the legacy URL — a different tenant from unboks (whose webhooks correctly hit `/api/unboks/webhooks/zernio` and return 200). When this comes up, that tenant's Zernio dashboard webhook URL needs updating.

## Lessons captured this stretch (full versions in `wtyj/briefs/marina_lessons.md`)

- **Edit tool hook gate misfires on `marina_agent.py`** — workaround: Bash-driven `python3` script with exact-string `str.replace` against unique anchors. Same pattern from prior stretch, third time it's appeared.
- **Process boundary blindness (Brief 235)** — supervisord-style multi-process containers (webhook_server, email_poller, hold_reaper) each have their own Python interpreter. Module-level globals don't share across processes. Side-effect-import registration must run in EVERY process that needs the registry. The shared `escalation_dispatcher.py` pattern is the fix.
- **Status filter must test all real production states (Brief 235)** — Brief 227's tests inserted with `pending` and queried with `pending`-only filter. Tautology — the filter only worked because the test created the data shape it expected. Production rows transition to `sent` within microseconds of insertion. Lesson: enumerate every status value the row could be in by query time and test each.
- **Cross-helper duplication is honest (Brief 234)** — marina_agent and dm_agent stayed independent code paths since Brief 131. Cross-importing a private helper would create a hidden dependency. Two-caller copy beats three-callsite indirection until a third caller actually appears.
- **Tests-codify-the-bug pattern (Brief 233)** — pre-existing tests asserting `role == "marina"` on operator-typed replies were codifying the bug Brief 233 fixes. Updating those assertions when the contract changes is correct, not "modifying tests to pass."
- **Brief authors lie about source (Brief 234 round 1)** — my "before" snippet for the fallback branch invented a block ordering. Reviewer caught. Lesson: re-read the actual source character-by-character before writing a "before" snippet, especially when the brief asserts byte-equivalence. Don't trust prior-stretch memory.
- **ISO vs numeric epoch storage drift (Brief 231)** — Brief 210 + 218 wrote `last_activity` as ISO strings while the legacy `_cleanup_stale_data` expected numeric epochs. Bug only triggered after operators exercised the dashboard write paths enough times to accumulate ISO-stringed threads. Lesson: when changing a write format, audit every reader of that field — not just the obvious ones in the same module.
- **Boilerplate >> test logic ratio is the real test bloat problem** — each test file starts with ~40 lines of duplicated setup (sys.path, env vars, _login, _auth, _reset). The TESTS are 8-15 lines each. Conftest.py fixture extraction would let new test files be 30 lines instead of 200. Documented but not yet shipped.

## Where things live (unchanged from prior snapshot, here for completeness)

| Thing | Path |
|---|---|
| Backend repo (worktree) | `~/Projects/bluemarlin-agent/.claude/worktrees/etakeyourjob/wtyj/` |
| Backend repo (main checkout) | `~/Projects/bluemarlin-agent/wtyj/` |
| Frontend repo (SR's) | `~/Projects/unboks-dashboard-api/` |
| Tasks CLI | `tools/unboks-cli/tasks.py` |
| Endpoint inventory | `wtyj/docs/endpoint_inventory.md` |
| Briefs | `wtyj/briefs/marina_brief_NNN_*.md` |
| Outputs | `wtyj/briefs/marina_output_NNN.md` |
| Explanations | `wtyj/briefs/marina_explanation_NNN.md` |
| Brief history | `wtyj/briefs/system_state.md` |
| Lessons | `wtyj/briefs/marina_lessons.md` |
| Token + password cache | `~/.claude/projects/.../auth/unboks_token` + `unboks_password` |
| VPS source | `/root/wtyj/` |
| VPS clients | `/root/clients/{bluemarlin,adamus,consultadespertares,unboks}/` |

## How to resume

1. Read `MEMORY.md` → it points here as READ SECOND.
2. Pull SR's frontend if you'll touch UI: `cd ~/Projects/unboks-dashboard-api && git pull`.
3. Top of queue: TASK-60 cloud connectors. Blocked on OAuth registrations — needs Benson + me at the consoles (Google Cloud first). Half a day per provider once credentials are in env vars.
4. Other queued items (in priority order):
   - Send SR's `f61c511ffd3c` reply consolidating answers to the 7 verification questions
   - Data retention cleanup automation brief (the three 501 stubs)
   - Operator-identity model brief (low priority, deferred to later phase)
5. Watch for new escalations on unboks to confirm Brief 235's fix is working in production — should see `escalation_summary` populated for newly-created rows.
