# OUTPUT 249 — Server-side per-conversation archive endpoints + resolved escalations history

## What was done

P0/P1 fix for issue #18 — desktop and mobile dashboards showed different inbox states because archive was localStorage-only on the React frontend. Brief 249 ships the server-side persistence the frontend needs for cross-device consistency, **plus fixes a latent Brief 237 bug** (the WhatsApp-side bulk archive sweep had been silently throwing `OperationalError` since it shipped because the `conversation_status.deleted` column it wrote to never existed in the schema). Per-step shipped:

0. **NEW Step 0 — Schema migration:** added `ALTER TABLE conversation_status ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0` to `wtyj/shared/state_registry.py` right after the existing `blocked` column ALTER (line 343 area). Try/except `sqlite3.OperationalError: pass` pattern matches the existing migration style at lines 329, 334, 343. **This was the round-1 reviewer's critical catch:** Brief 237 introduced read+write of this column without a migration; verified via grep + live SQLite inspection that the column never existed in source nor on the live unboks DB. Step 0 finally adds it. Side effect (honestly disclosed): Brief 237's WA-side bulk archive sweep starts working for the first time on the next nightly cron — operators may see WA conversation counts drop after the first sweep as the latent backlog of "should-have-been-archived" rows finally takes effect.
1. **4 new helpers in `state_registry.py`** (after `email_list_conversations`):
   - `email_set_archived(thread_key, archived)` — toggles `flags.deleted` in `email_thread_state.json`. Returns False when thread_key missing (caller raises 404).
   - `wa_set_archived(conversation_id, archived)` — UPSERTs `conversation_status.deleted` for WA/IG/FB. Idempotent; works whether the conversation_status row pre-exists or not.
   - `email_list_archived_conversations()` — inverse filter of `email_list_conversations`; returns same response shape with `status="archived"`.
   - `wa_list_archived_conversations()` — inverse filter for WA; same response shape.
2. **Fixed `wa_list_conversations` to filter archived rows** at `state_registry.py:1342-1402`. Added `LEFT JOIN conversation_status cs ON t.phone = cs.conversation_id WHERE cs.deleted IS NULL OR cs.deleted = 0`. The LEFT JOIN preserves conversations that have NO conversation_status row at all (most active ones). Only rows with explicit `deleted=1` are excluded.
3. **(Step 3's two list-archived helpers `email_list_archived_conversations` and `wa_list_archived_conversations` were shipped together with Step 1's set-archived helpers in the same `state_registry.py` insertion block — implementation grouping. All 4 helpers present: 2 setters + 2 listers.)**
4. **3 new endpoints in `dashboard/api.py`** (after the existing `list_conversations`):
   - `GET /messages/conversations/archived` — merged WA + email archived list, same response shape as the active endpoint.
   - `POST /messages/conversations/{conv_id:path}/archive` — accepts both `email::...` and bare-phone formats. 404 only for missing email thread_keys. Idempotent.
   - `POST /messages/conversations/{conv_id:path}/unarchive` — inverse of archive. Idempotent.
   Also extended `GET /escalations` at `api.py:2014-2024` with new `status: str = None` query param. Filters `get_all_escalations()` results by `r.get("status") == status` when provided. Backward compatible (no param → no filter).
5. **6 new tests** in NEW file `wtyj/tests/social/test_249_server_side_archive.py`. Tests cover: WA archive moves out of active + into archived; WA unarchive restores to active; email archive same; email 404 for missing thread_key; Brief 237 archived rows correctly filtered (the regression-fix bridge); `?status=resolved` filter returns only resolved escalations. Tests use real DB + `_wipe_wa_phone` cleanup helpers, plus `monkeypatch+tmp_path` for email file isolation. Test 6 wrapped in try/finally so cleanup runs even on assertion failure (round-1 reviewer fix).

**Brief-reviewer:** FAIL round 1 with 4 issues — most critical was the missing `conversation_status.deleted` column (would have crashed `wa_set_archived` on first call AND silent-broken Brief 237 confirmed pre-existing). Round 2 PASS zero issues after adding Step 0 migration + clarifying baseline (1064 not stale-MEMORY's 1015) + tightening Test 6 cleanup + honest Brief-237 side-effect disclosure.

## Tests

1070 passing / 0 failures (1064 baseline + 6 new = 1070). New file `wtyj/tests/social/test_249_server_side_archive.py` runs 6/6.

## Frontend contract for SR

**No breaking changes — all additive.** The frontend's React app should:

1. **Replace localStorage archive state** with calls to the new endpoints.
2. **`GET /dashboard/api/messages/conversations`** — active inbox (now correctly excludes archived for both WA and email).
3. **`GET /dashboard/api/messages/conversations/archived`** — Archived view. Same response shape as the active endpoint.
4. **`POST /dashboard/api/messages/conversations/{conv_id:path}/archive`** — body empty; auth required. Accepts both `email::<thread_key>` and bare-phone IDs. Returns `{ok, conversationId, channel, archived: true}`. 404 only for missing email threads.
5. **`POST /dashboard/api/messages/conversations/{conv_id:path}/unarchive`** — same shape; `archived: false` in response.
6. **`GET /dashboard/api/escalations?status=resolved`** — Resolved/History view. Also accepts `?status=sent`, `?status=pending`, `?status=replied`, `?status=all` (all = no filter, same as omitting the param).

**Cross-device consistency:** archive state is now persisted in:
- Email: `email_thread_state.json` per-thread `flags.deleted` (existing field; same semantic Brief 237 uses).
- WhatsApp: `conversation_status.deleted` column (newly added in Step 0; same semantic Brief 237 was already trying to use).

The naming of the underlying flag (`deleted` rather than `archived`) is invisible to the frontend — the API uses `archived` consistently in URLs and response bodies. Inherited from Brief 218; cleanup deferred per Step 6.

## Deployment

Source commit pending. Will deploy via the standard CI pipeline. **First deploy adds the `deleted` column to all 4 tenant DBs.** Subsequent boots see the column exists and the ALTER raises `duplicate column name: deleted` which gets swallowed by the existing `try/except sqlite3.OperationalError: pass` pattern. Briefs 238-248 all preserved — only `state_registry.py` (1 schema migration + 4 new helpers + 1 SQL filter change in existing `wa_list_conversations`) and `dashboard/api.py` (3 new endpoints + 1 query-param extension) touched.

## Out-of-scope (deferred per brief Step 6)

- Renaming `flags.deleted` → `flags.archived` — purely cosmetic; deferred.
- Pagination on the archived list — defer until volume justifies.
- Auto-unarchive on new customer message — product decision; deferred.
- Frontend integration — SR's React app at `unboks-org/unboks-dashboard-api`.
- Bulk archive endpoint — convenience UX; defer until operators ask.
