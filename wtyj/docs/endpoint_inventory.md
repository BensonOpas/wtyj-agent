# Endpoint Inventory — wtyj-agent ↔ unboks-dashboard-api

Single canonical map of every dashboard API endpoint, the backend handler that serves it, and the frontend caller that consumes it. Generated 2026-05-07 by grepping both repos.

**External URL pattern (per nginx routing, Brief 200):**
- `https://api.unboks.org/api/{tenant}/dashboard/api/{path}` → backend sees `/dashboard/api/{path}` (FastAPI `dashboard.api.router` mounted with `prefix="/dashboard/api"`)
- `https://api.unboks.org/api/{tenant}/tasks{path}` → backend sees `/tasks{path}` (FastAPI `dashboard.tasks_api.router` mounted with `prefix="/tasks"`)

Where `{tenant}` ∈ `{bluemarlin, adamus, consultadespertares, unboks}`.

---

## Auth

| Method | Path | Backend handler | Frontend caller |
|---|---|---|---|
| POST | `/dashboard/api/login` | `api.py:135 login` | `lib/api.ts:apiFetch` (Bearer token) |

Session token persisted at `/app/data/session_token` (Brief 208). 0600 perms, survives container restart.

---

## Status / config

| Method | Path | Backend handler | Frontend caller |
|---|---|---|---|
| GET | `/dashboard/api/status` | `api.py:147` | `lib/api.ts` |
| GET | `/dashboard/api/availability` | `api.py:451` | `lib/api.ts` |
| GET | `/dashboard/api/config` | `api.py:456` | `lib/api.ts` |

---

## Drafts (content pipeline)

| Method | Path | Backend handler | Notes |
|---|---|---|---|
| GET | `/dashboard/api/drafts` | `api.py:165` | List drafts |
| GET | `/dashboard/api/drafts/{draft_id}` | `api.py:170` | |
| PUT | `/dashboard/api/drafts/{draft_id}` | `api.py:179` | |
| POST | `/dashboard/api/drafts/generate` | `api.py:192` | |
| POST | `/dashboard/api/drafts/{draft_id}/approve` | `api.py:198` | |
| POST | `/dashboard/api/drafts/{draft_id}/reject` | `api.py:215` | |
| POST | `/dashboard/api/drafts/{draft_id}/publish` | `api.py:223` | |
| POST | `/dashboard/api/drafts/{draft_id}/graphics` | `api.py:238` | |
| POST | `/dashboard/api/drafts/{draft_id}/compose` | `api.py:246` | |
| DELETE | `/dashboard/api/drafts/{draft_id}` | `api.py:365` | |
| GET | `/dashboard/api/drafts/{draft_id}/image` | `api.py:381` | |
| POST | `/dashboard/api/drafts/manual` | `api.py:1538` | Manual draft creation |
| POST | `/dashboard/api/drafts/{draft_id}/schedule` | `api.py:871` | |
| POST | `/dashboard/api/drafts/{draft_id}/unschedule` | `api.py:884` | |
| PUT | `/dashboard/api/drafts/{draft_id}/platforms` | `api.py:926` | |

---

## Learnings (legacy + Brief 215 escalation_learnings)

| Method | Path | Backend handler | Brief | Notes |
|---|---|---|---|---|
| GET | `/dashboard/api/learnings` | `api.py:395` | original | content_learnings (plural) |
| POST | `/dashboard/api/learnings/distill` | `api.py:400` | original | |
| DELETE | `/dashboard/api/learnings/{learning_id}` | `api.py:406` | original | |
| GET | `/dashboard/api/learning` | `api.py:420` | 212 alias → repointed by 215 | escalation_learnings (singular) |
| DELETE | `/dashboard/api/learning/{learning_id}` | `api.py:425` | 215 | |
| POST | `/dashboard/api/learning/{learning_id}/approve` | `api.py:433` | 215 | |
| POST | `/dashboard/api/learning/{learning_id}/save` | `api.py:441` | 215 | |

Frontend caller: `lib/api.ts:fetchLearningEntries`. SR's frontend uses singular `/learning`.

---

## Photos / brand training

| Method | Path | Backend handler |
|---|---|---|
| POST | `/dashboard/api/photos/upload` | `api.py:464` |
| GET | `/dashboard/api/photos` | `api.py:491` |
| GET | `/dashboard/api/photos/stats` | `api.py:496` |
| GET | `/dashboard/api/photos/{photo_id}/image` | `api.py:501` |
| PUT | `/dashboard/api/photos/{photo_id}` | `api.py:512` |
| DELETE | `/dashboard/api/photos/{photo_id}` | `api.py:520` |
| POST | `/dashboard/api/training/examples` | `api.py:938` |
| GET | `/dashboard/api/training/examples` | `api.py:964` |
| DELETE | `/dashboard/api/training/examples/{example_id}` | `api.py:969` |
| GET | `/dashboard/api/training/examples/{example_id}/image` | `api.py:980` |
| POST | `/dashboard/api/training/analyze` | `api.py:989` |
| POST | `/dashboard/api/training/analyze-visual` | `api.py:1004` |
| GET | `/dashboard/api/training/profile` | `api.py:1016` |
| POST | `/dashboard/api/training/profile` | `api.py:1025` |
| PUT | `/dashboard/api/training/profile/{rule_id}` | `api.py:1033` |
| DELETE | `/dashboard/api/training/profile/{rule_id}` | `api.py:1041` |

---

## Google integration (Drive sync, OAuth)

| Method | Path | Backend handler |
|---|---|---|
| GET | `/dashboard/api/google/auth` | `api.py:534` (OAuth start, no auth) |
| GET | `/dashboard/api/google/callback` | `api.py:553` (OAuth callback, no auth) |
| GET | `/dashboard/api/google/status` | `api.py:621` |
| POST | `/dashboard/api/google/disconnect` | `api.py:634` |
| GET | `/dashboard/api/google/folders` | `api.py:641` |
| POST | `/dashboard/api/google/folder` | `api.py:665` |
| POST | `/dashboard/api/google/sync` | `api.py:674` |

---

## Settings

| Method | Path | Backend handler | Brief |
|---|---|---|---|
| GET | `/dashboard/api/settings/dry-run` | `api.py:734` | original |
| POST | `/dashboard/api/settings/dry-run` | `api.py:739` | original |
| GET | `/dashboard/api/settings/escalation-alerts` | `api.py:762` | 217 |
| PUT | `/dashboard/api/settings/escalation-alerts` | `api.py:768` | 217 |
| GET | `/dashboard/api/settings/your-info` | `api.py:789` | 216 |
| PUT | `/dashboard/api/settings/your-info` | `api.py:798` | 216 |
| GET | `/dashboard/api/settings/info-updates` | `api.py:831` | 216 |
| POST | `/dashboard/api/settings/info-updates` | `api.py:838` | 216 |
| DELETE | `/dashboard/api/settings/info-updates/{update_id}` | `api.py:851` | 216 |
| GET | `/dashboard/api/settings/blocked-conversations` | `api.py:1520` | 220 |

---

## Schedule

| Method | Path | Backend handler | Brief |
|---|---|---|---|
| GET | `/dashboard/api/schedule/slots` | `api.py:892` | original |
| PUT | `/dashboard/api/schedule/slots` | `api.py:897` | 212 (raw array body) |
| GET | `/dashboard/api/schedule/upcoming` | `api.py:908` | original |
| GET | `/dashboard/api/platforms/available` | `api.py:920` | original |

---

## Messages / conversations

| Method | Path | Backend handler | Brief | Frontend caller |
|---|---|---|---|---|
| GET | `/dashboard/api/messages/conversations` | `api.py:1051` | original (Brief 202 sender_name fallback) | `lib/api.ts:fetchConversations` |
| GET | `/dashboard/api/messages/conversations/{phone:path}` | `api.py:1092` | 211 + 222 (extra contract fields) | `lib/api.ts:fetchConversationDetail` |
| DELETE | `/dashboard/api/messages/conversations/{phone}` | `api.py:1125` | original | |
| POST | `/dashboard/api/messages/conversations/{conversation_id:path}/email/forward` | `api.py:1148` | 218 | `lib/api.ts:forwardEmail` |
| POST | `/dashboard/api/messages/conversations/{conversation_id:path}/email/delete` | `api.py:1217` | 218 | `lib/api.ts:deleteEmail` |
| POST | `/dashboard/api/messages/conversations/{conversation_id:path}/block` | `api.py:1496` | 220 | (frontend pending) |
| POST | `/dashboard/api/messages/conversations/{conversation_id:path}/unblock` | `api.py:1509` | 220 | (frontend pending) |
| POST | `/dashboard/api/messages/suggest-reply` | `api.py:1575` | original (operator AI helper) | |

---

## Customers

| Method | Path | Backend handler |
|---|---|---|
| GET | `/dashboard/api/customers/by-identifier/{type}/{value}` | `api.py:1257` |

---

## Escalations

| Method | Path | Backend handler | Brief | Frontend caller |
|---|---|---|---|---|
| GET | `/dashboard/api/escalations` | `api.py:1358` | 213 (`?mode=` filter) | `lib/api.ts:fetchEscalations` |
| GET | `/dashboard/api/escalations/{escalation_id}` | `api.py:1371` | original | |
| POST | `/dashboard/api/escalations/{escalation_id}/resolve` | `api.py:1389` | 215 (body params: saveAsLearning, autoUseNextTime) | `lib/api.ts:resolveEscalation` |
| DELETE | `/dashboard/api/escalations/{escalation_id}` | `api.py:1420` | original | |
| POST | `/dashboard/api/escalations/{escalation_id}/mode` | `api.py:1451` | 213 | `lib/api.ts:setEscalationMode` |
| POST | `/dashboard/api/escalations/{escalation_id}/takeover` | `api.py:1462` | 213 | `lib/api.ts:takeoverEscalation` |
| POST | `/dashboard/api/escalations/{escalation_id}/handback` | `api.py:1479` | 213 | `lib/api.ts:handbackEscalation` |
| POST | `/dashboard/api/escalations/{escalation_id}/reply` | `api.py:1706` | 210 (hard-mode operator-to-customer) | `lib/api.ts:replyToEscalation` |
| POST | `/dashboard/api/escalations/{escalation_id}/guidance` | `api.py:1826` | 214 (soft-mode operator-to-Marina). Hotfix `2e36547` accepts `{guidance}` field name. | `lib/api.ts:sendGuidance` |

---

## AI Editor (operator tools)

| Method | Path | Backend handler | Brief | Notes |
|---|---|---|---|---|
| POST | `/dashboard/api/ai-editor` | `api.py:2032` | 212 + 221 | `action: translate \| style \| fix`. Brief 221: translate routes to Haiku, style/fix stay on Sonnet. |

Frontend caller: `lib/api.ts:aiEditorEdit` for the reply composer's translate/style/fix tabs.
**Also reused** by `lib/api.ts:translateMessage` (operator clicks Translate on an inbound customer message) — same endpoint with `action: "translate"`. See `lib/api.ts:583` comment.

---

## Tasks (separate router, mounted at `/tasks`)

External URL: `/api/{tenant}/tasks{path}`. Internal: `/tasks{path}` (router has `prefix="/tasks"` from Brief 207).

| Method | Path | Backend handler | Brief | Frontend caller |
|---|---|---|---|---|
| GET | `/tasks` | `tasks_api.py:75` | 207 + 223 (`taskNumber` field) | `lib/tasks-api.ts:listTasks` |
| POST | `/tasks` | `tasks_api.py:80` | 207 + 223 (allocates `taskNumber`) | `lib/tasks-api.ts:createTask` |
| PATCH | `/tasks/{task_id}` | `tasks_api.py:107` | 207 (status flip) | `lib/tasks-api.ts:updateTaskStatus` |
| POST | `/tasks/uploads` | `tasks_api.py:121` | 207 + 207-hotfix (`files: list`, returns `{attachments: [...]}`) | `lib/tasks-api.ts:uploadAttachments` |
| GET | `/tasks/uploads/{filename}` | `tasks_api.py:158` | 207 (no auth, serves images) | `<img src={url}>` |

---

## Webhooks (no auth, third-party callbacks)

| Method | Path | Backend handler | Notes |
|---|---|---|---|
| POST | `/webhook/whatsapp` | `webhook_server.py` | Meta WhatsApp Cloud API |
| GET | `/webhook/whatsapp` | `webhook_server.py` | Meta verification handshake |
| POST | `/zernio/webhook` | `webhook_server.py` | Zernio multi-platform DMs |
| GET | `/health` | `webhook_server.py` | Container health probe |

---

## Notes

- **Singular vs plural learning paths** — Brief 215 repointed `/learning` (singular) from content_learnings to escalation_learnings. The plural `/learnings` still serves content_learnings for the original content-pipeline flows. Different domains — both kept.
- **Email-thread conversation IDs** use the `email::<thread_key>` prefix and require the `:path` URL converter to allow slashes. Brief 211 added `_find_email_thread_key_for(email)` so `/escalations` rows expose a routable `phone` field for email channel.
- **Brief 220's block** is per-conversation runtime state in `conversation_status.blocked`. **Brief 208's `ignored_phones`** is tenant-level static config in `client.json::features.ignored_phones`. Both are checked at the 4 ingestion paths (Zernio DM, Zernio WA, Meta-legacy WA, email_poller); ignored_phones runs first.
- **Frontend graceful degradation** — SR's frontend treats `0/404/501/503` as "not connected" and shows calm fallback copy. Don't return 200 with fake success — let unimplemented features surface as 404 so the frontend's degradation kicks in.

## Maintenance

To regenerate this doc, grep both repos:
```bash
# Backend routes
grep -n "@router\." wtyj/dashboard/api.py wtyj/dashboard/tasks_api.py

# Frontend callers (assumes ~/Projects/unboks-dashboard-api/ checkout)
grep -rn "apiFetch\|fetch.*\\\`/" ~/Projects/unboks-dashboard-api/artifacts/unboks/src/lib/
```
