# OUTPUT 213 — Escalation control surface

## What was done

Added schema columns + 4 helpers + 3 endpoints + AI-mute enforcement on 4 ingestion paths. Schema: `pending_notifications.mode TEXT`, `conversation_status.ai_muted INTEGER NOT NULL DEFAULT 0`, `conversation_status.human_takeover_at TEXT` — all idempotent ALTER TABLE wrapped in `try/except sqlite3.OperationalError: pass` matching the existing pattern at lines 20-51. Helpers in `wtyj/shared/state_registry.py`: `set_escalation_mode(esc_id, mode)`, `get_ai_muted(cid)`, `set_ai_muted(cid, muted, channel)` (UPSERT preserves existing `status` value), `get_active_escalation_mode(cid)`. Endpoints in `wtyj/dashboard/api.py`: POST `/escalations/:id/mode`, POST `/escalations/:id/takeover` (mode=hard + ai_muted=true + human_takeover_at), POST `/escalations/:id/handback` (mode=soft + ai_muted=false). `_refresh_and_stringify_escalation()` helper uses int-int compare with `get_all_escalations()` returns and stringifies for response (matches the GET /escalations contract from Brief 210). `list_escalations` now supports `?mode=soft|hard`. `_conversation_status_fields` reads real `escalationMode` + `aiMuted` from storage (Brief 211 placeholders gone). AI-mute enforcement at four call sites: `_process_zernio_event` IG/FB DM branch, `_flush_buffer` Zernio-WhatsApp branch, `_flush_buffer` Meta-legacy branch, and `email_poller.py` after the inbound-append at line ~622 via the new `_should_skip_marina_for_mute()` helper. In every branch the inbound is stored before the early-return so the operator sees the message in the dashboard.

## Tests

966 passing / 0 failures (baseline 955 + 11 new).

## Unexpected findings

Three small fixes during execution, none structural. (1) Tests 9 + 10 cleanup originally referenced a `dm_messages` table — there is no such table; `dm_store_message` writes to `whatsapp_threads`. (2) Cleanup originally targeted `processed_hashes` for the dedup row but the actual dedup table is `whatsapp_processed` — leaked rows across failed runs caused dedup to short-circuit subsequent test runs before the mute check could fire. (3) Output-reviewer flagged tests 9 + 10 as missing the brief's positive "inbound stored for operator visibility" assertion; added that assertion using `dm_get_history`. Also added pre-test dedup cleanup to test 9 so a single failed run doesn't poison repeat runs. Brief's variable-scope hedges in Step 8 (`now = int(time.time())` not ISO; `threads = state["threads"]` local alias) were both correct as live source — used the live names.

## Deployment

Pending — commit/push/deploy in step 16.
