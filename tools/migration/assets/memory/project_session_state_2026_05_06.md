---
name: Session state 2026-05-06
description: End-of-session snapshot. Briefs 200-208 + hotfixes shipped. 4 unboks-org repos now exist. calvin-csa fully voiced for unboks. Login persists across deploys. Phone block live. Tasks API live. Tests at 937.
type: project
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
End-of-session snapshot taken 2026-05-06 evening.

## Current state at end of session

- **All 4 production containers healthy.** Ports 8001 (bluemarlin), 8002 (adamus), 8003 (consultadespertares), 8004 (unboks). Plus staging on 9001.
- **937 tests passing / 0 failures.**
- **Latest commit on main:** `58027e8` ([FIX] Brief 207 tasks /uploads contract). Below that: `e208c9e` Brief 208, `56b550c` CI quick fix, `ae096dd` Brief 207, `232ae41` Brief 206.
- **CI pipeline green.** E2E check 4 (Claude brain) was removed — Anthropic 529s were gating deploys on upstream issues we can't fix.
- **Brief 205 was rolled back.** Audit found wrong diagnosis on the camelCase aliases (frontend already had snake_case fallback) + Unicode-digit bypass on the phone filter. Done correctly in Brief 208.

## Briefs shipped this session (in order)

- **Brief 199** (pre-session) — unboks tenant SOT-based config + WhatsApp credential migration.
- **Brief 200** — `api.unboks.org` cutover. New nginx server block, TLS, DNS flip. Replit AI had generated a parallel Node backend; we re-pointed DNS at our Python.
- **Brief 201** — em-dash strip in dm_agent + dashboard message field aliases (`content`/`timestamp` for the detail endpoint).
- **Brief 202** — sender_name fallback in `wa_list_conversations` so dashboard inbox shows real names instead of Zernio hex IDs.
- **Brief 203** — wired `agent_persona.freeform_notes` injection in dm_agent (was a silent bug — never read since Brief 199) + installed SR's master prompt as unboks's calvin-csa voice (~17,400 chars).
- **Brief 204** — Gmail app-password auth in email_adapter.py (IMAP + SMTP). Plus hotfix for Brief 146's graceful-exit guard (didn't recognize app-password mode).
- **Brief 205** — ATTEMPTED dashboard UX cleanup (4 changes). **Rolled back** after audit caught wrong diagnosis + Unicode-digit bypass. Took ~6h on max-effort thinking mode for what should have been 30 min.
- **Brief 206** — real escalation handler for dm_agent (was lying about "I've flagged" — no backend code), added `[ESCALATE]` sentinel in master prompt, suppressed BOOKING REDIRECT block for booking_flow:false tenants.
- **Brief 207** — Tasks backend endpoints for SR's dashboard Tasks page (GET/POST/PATCH/POST uploads + serve). New SQLite tables `tasks` + `task_attachments`.
- **Brief 207 hotfix** — fixed `/tasks/uploads` contract: frontend sends FormData with field name `files` (plural, multi-file), expects `{attachments: [...]}` response. I'd implemented `file` (singular) with bare attachment dict; corrected.
- **Brief 208** — `ignored_phones` webhook filter (blocks SR's contact "Excluir" `+59995133333`) + disk-persisted session token at `/app/data/session_token` so login survives container restarts.

## What's actively live for unboks

- `api.unboks.org` serves the Python backend (nginx prefix-strip routes `/api/unboks/...` → backend `/...`)
- `dashboard.unboks.org` renders against `api.unboks.org`. Login persists across deploys.
- calvin-csa runs SR's full master prompt (~17,400 char freeform_notes + concrete escalation script with `[ESCALATE]` sentinel)
- WhatsApp poll → reply flow works. Email poll → reply flow works (Gmail app password, hello@unboks.org).
- Tasks page at `dashboard.unboks.org/tasks` works (CRUD + screenshot uploads).
- `+599 9 513 3333` auto-blocked at webhook ingestion. Other numbers reply normally.
- Real escalations create `pending_notifications` rows visible in the dashboard's Escalations tab.

## GitHub access (added 2026-05-06)

SR moved his Replit-side repos from `calvin835/*` to a new GitHub org `unboks-org`. Two repos exist:
- `unboks-org/unboks-dashboard-api` — frontend + the orphan Node backend (private, WRITE access for BensonOpas as outside collaborator)
- `unboks-org/unboks-public-website` — public marketing site (private, WRITE)

Replit projects still have OLD `calvin835/...` URLs in their git remotes — that's why Replit shows "remote not accessible." Fix is per-Replit: update remote URL.

## Two security/hygiene findings (not blocking)

1. **`.gitignore` doesn't explicitly cover `clients/*/data/*`.** `state_registry.db` is caught by safety net but Brief 207's `task_uploads/` and Brief 208's `session_token` are not. Currently nothing is tracked there but a local dev could accidentally commit. Recommended fix: add `clients/*/data/*` (with `!.gitkeep` allowance). 3-line edit.

2. **Brief 146 markdown contains stale Adamus password** `adamus-demo-2026` (now rotated to `456`). Informational only — if reused as a passphrase elsewhere, rotate.

## Behavioral feedback from this session

- **Max-effort thinking mode is the dominant slowdown.** Set via `/model`, multiplies every operation 5-10x. Combined with oversized briefs and subagent ceremony, made Brief 205 take 6h 30m for 50 lines of code.
- **Oversized briefs are wrong for small fixes.** 5-line changes don't need 600-line briefs with rejected-alternatives essays + JSON-escaping notes + threat models. Aim for ~200 lines max for tight briefs.
- **Quick-fix path applies to more than I was using it for.** Behavioral changes need a brief, but the brief CEREMONY (subagent reviewers, lessons file entry, code-explainer, system_state writeup) is overkill for changes under ~50 lines.
- **No internal "I've been at this 2 hours, abort" heartbeat.** Just keeps going. That's a real gap.
- **Trust the audit.** Brief 205's rollback came from honest second-look review (subagents-in-parallel). Saved shipping wrong code. Worth doing for any non-trivial brief.

## What's queued for next session (`project_open_work.md` head)

1. `.gitignore` hardening (3-line quick fix)
2. Stale password in Brief 146 (informational; only act if reused)
3. SMTP "From" header still hardcodes "Marina" — should read agent_name from client.json
4. Frontend Brief 200 follow-ups (JWT expiry handling, defensive read in MessageBubble — SR's territory)
5. Hallucinated URL fix in dm_agent (calvin-csa invented unboks.com/contact)
6. Adamus email bootstrap (Microsoft OAuth one-time interactive flow for sophia@wetakeyourjob.com — still pending)
7. `requires_human:true` from Zernio webhook → escalation flag (SR's audit asked for this; still not honored backend-side)

## Resume path on next session

1. Read this file + `project_open_work.md` + `wtyj/briefs/system_state.md` (for the latest brief outcomes).
2. If user asks "what's the state?" → 4 containers healthy, 937 tests, calvin-csa live with full master prompt + escalation, Tasks page works.
3. **Switch to default effort first** unless explicitly told otherwise. Max effort + oversized briefs is the failure mode this session exposed.
