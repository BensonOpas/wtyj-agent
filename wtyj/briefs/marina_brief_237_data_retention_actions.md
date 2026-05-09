# BRIEF 237 — Data Retention Action Endpoints

**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/shared/state_registry.py`, `wtyj/tests/social/test_229_data_retention.py` | **Depends on:** Brief 229 (settings storage), Brief 232 (archive flag), Brief 235 (escalation status filter) | **Blocks:** none

## Context

Brief 229 shipped data retention settings storage (GET/PUT `/settings/data-retention`) but the three action endpoints were left as honest 501 stubs at `wtyj/dashboard/api.py:913-942`:

- `POST /data-retention/archive-now`
- `POST /data-retention/export`
- `POST /data-retention/delete-customer-data`

SR's task `ab7d8f1eb97c` (#56) explicitly asks for both the settings AND these three action endpoints. SR's frontend already calls them and renders 501 errors as "not yet implemented" placeholders — this brief flips them to live behavior. Brief 229's stubs return helpful 501 messages today; the frontend reads `policyActive` from the GET response (false until this ships) so no client-facing UI lies about automation running.

The task body lists 10 backend rules (`ab7d8f1eb97c` lines 41-58 of show output), of which the load-bearing ones for this brief are:
- Rule 6: Archive sets a flag, doesn't delete (consistent with Brief 218/232's `flags.deleted`).
- Rule 5: Approved learnings stay even after raw messages clear (`escalation_learnings` table is separate, won't be touched).
- Rule 8: Never delete active unresolved escalations.
- Rule 9: Never delete human takeover conversations while unresolved.
- Rule 10: Do not silently delete — log retention actions.

## Why This Approach

**Considered:** ship just `archive-now` first (safest), defer `export` + `delete-customer-data` to a follow-up — rejected. SR's task lists all three together; splitting churns the frontend's "not yet implemented" handling twice. Single brief is cleaner.

**Considered:** synchronous in-request execution vs background job — chose synchronous. Volume on unboks is small (we just wiped to 0 messages). The biggest tenant (BlueMarlin) has hundreds of threads, not millions. A `for thread in threads: check_age()` sweep over a few hundred rows finishes in under a second. If volume grows enough to need backgrounding, that's a separate brief — premature optimization now.

**Considered:** physical row deletion vs anonymization for `endOfRetentionAction` — chose to honor whatever the saved setting says, with a hard floor that approved learnings are never touched (Rule 5). Anonymize replaces PII fields with `[redacted]` strings rather than dropping rows, so historical aggregates still work. Delete drops the rows entirely.

**Tradeoff accepted:** export writes a JSON file to disk under `data/exports/{tenant}-{timestamp}.json` and returns the path + record counts in the response, NOT a raw file stream. Reasoning: a streaming download endpoint adds complexity (signed URLs, expiry, MIME negotiation, etc.) that SR's frontend doesn't actually need today. The frontend's "Download export" button can hit a separate `/data-retention/exports/{filename}` endpoint later. Out of scope for this brief.

## Instructions

### Part A — Helpers in `wtyj/shared/state_registry.py`

Read `wtyj/shared/state_registry.py:1135-1162` (existing `email_mark_deleted`) and `wtyj/shared/state_registry.py:1952-2005` (Brief 229 helpers) before editing — the new helpers slot in alongside Brief 229's storage helpers around line 2005.

Add these three module-level helper functions:

1. **`archive_inactive_conversations(active_inbox_archive_after_days: int) -> dict`**
   - Computes `cutoff = datetime.now(timezone.utc) - timedelta(days=N)`.
   - Iterates the email thread state JSON (use existing `_get_email_state_path()` reader pattern from `email_mark_deleted` line 1140-1147).
   - For each thread: if `last_activity < cutoff` AND `flags.deleted` is not already true AND `flags.fully_escalated` is not true (active unresolved escalation guard, Rule 8) AND `flags.ai_muted` is not true (human takeover guard, Rule 9), set `flags.deleted = True` + update `last_activity` to now.
   - Iterates `whatsapp_threads` rows: group by phone, find the max `created_at` per phone, if older than cutoff AND `conversation_status` row for that phone has neither `deleted=1` nor `blocked=1` already AND no active `pending_notifications` row exists (status IN ('pending','sent') — same filter as Brief 235), upsert `conversation_status` with `deleted=1`.
   - Returns `{"archivedCount": N_emails + N_phones, "skippedActiveEscalation": K, "skippedHumanTakeover": M, "alreadyArchived": A}`.
   - Both writes go through atomic file replace (email JSON) and a single transaction (DB) so a partial failure leaves a consistent state.

2. **`export_all_customer_data(export_dir: str, tenant: str) -> dict`**
   - Computes `now_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")` and builds path `f"{export_dir}/{tenant}-{now_iso}.json"`.
   - Builds a single dict with: `customers` (full rows), `customer_identifiers`, `whatsapp_threads`, `pending_notifications`, `appointments` (Brief 228), `bookings`, plus the email thread state JSON contents under key `email_threads`.
   - Use atomic write pattern: write to `{path}.tmp`, then `os.replace(tmp, path)`.
   - Returns `{"exportPath": path, "recordCounts": {...per-table counts...}, "exportedAt": now_iso}`.
   - Approved learnings (`escalation_learnings`) and `tasks` are NOT included — those are operator-curated artifacts, not customer data.

3. **`delete_customer_data(identifier_value: str, identifier_type: str, action: str, keep_approved_learnings: bool) -> dict`**
   - `identifier_type` is one of `"phone"`, `"email"`, `"conversation_id"`. `action` is one of `"delete"`, `"anonymize"`. `"keep"` returns `{"ok": False, "reason": "action=keep is no-op"}` early without touching anything.
   - **Identifier resolution chain (load-bearing for safety + correctness — table schemas differ).**
     - Query `customer_identifiers` for the row matching `(type=identifier_type, value=identifier_value)` to get the integer `customer_id` PK.
     - If no match: the customer doesn't exist. Return `{"ok": True, "action": action, "deletedCount": 0, "anonymizedCount": 0}` (idempotent — no-op).
     - With the integer `customer_id`, fetch ALL `customer_identifiers.value` rows for this customer grouped by type. Build three sets: `phones = {values where type='phone' or type='wa_conversation_id'}`, `emails = {values where type='email'}`, `conv_ids = phones ∪ {values where type='conversation_id'}`. These are the keys used at insert time by other tables (which store TEXT, not the integer PK).
   - **Active-escalation guard (Rule 8) — CRITICAL.** `pending_notifications.customer_id` is `TEXT NOT NULL` (state_registry.py:257); rows store the conversation_id/phone/email string at insert time, NOT `customers.id`. The guard query is therefore: `SELECT 1 FROM pending_notifications WHERE customer_id IN (?...) AND status IN ('pending','sent') LIMIT 1`, with the placeholder list bound to `conv_ids ∪ emails` (every text identifier the customer was ever filed under). If any match: write the audit log row with `action='delete_customer:blocked_by_active_escalation'`, then return `{"ok": False, "reason": "active_escalation"}`. DO NOT touch any data.
   - **For `action="delete"`** — DELETE rows from each table using the resolved sets:
     - `whatsapp_threads WHERE phone IN (?...)` bound to `phones`
     - `pending_notifications WHERE customer_id IN (?...) AND status NOT IN ('pending','sent')` bound to `conv_ids ∪ emails` (only resolved escalations; active was already guarded above)
     - `appointments WHERE conversation_id IN (?...)` bound to `conv_ids ∪ emails` (matches Brief 228's `email::{thread_key}` and bare phone forms)
     - `bookings` and `service_bookings` WHERE customer_id matches the integer PK (these tables use the integer FK per `customers.id`)
     - `customer_interactions WHERE customer_id IN (?...)` bound to `conv_ids ∪ emails` (this table also stores the text identifier at insert time — verify schema before binding)
     - `customer_identifiers WHERE customer_id = ?` bound to the integer PK
     - `customers WHERE id = ?` bound to the integer PK
     - Email side: load `email_thread_state.json`, drop any thread whose `from_email` is in the `emails` set.
   - **For `action="anonymize"`** — UPDATE rows in place rather than DELETE:
     - `customers SET display_name='[redacted]', phone='[redacted]', email='[redacted]' WHERE id = ?` (integer PK)
     - `customer_identifiers SET value='[redacted]' WHERE customer_id = ?`
     - `whatsapp_threads SET text='[redacted message]', sender_name='[redacted]' WHERE phone IN (?...)`
     - Email JSON: rewrite each thread's `messages[].text='[redacted message]'`, `messages[].from_email='[redacted]'`, top-level `from_email='[redacted]'`.
     - Keep row IDs + timestamps so aggregates still work.
   - **If `keep_approved_learnings` is True (Rule 5):** SKIP `escalation_learnings` and `info_updates` rows tied to this customer. These tables also use TEXT customer-id keys — same `IN (?...)` pattern with the resolved sets. Otherwise (false): treat like other PII tables — DELETE on `delete`, set `customer_text='[redacted]'` on `anonymize`.
   - Write the audit log row (regardless of ok/blocked status — see audit-write rule in Notes for executor) with `action`, `identifier_value`, `identifier_type`, `affected_table_counts`, `actor`, `created_at`. This satisfies Rule 10.
   - Returns `{"ok": True, "action": "delete"|"anonymize", "deletedCount": N, "anonymizedCount": M, "skippedLearnings": L}`.

Add the audit log table schema near the other CREATE TABLEs (search for `CREATE TABLE IF NOT EXISTS data_retention_settings` ~ line 477 and add a sibling):

```python
"CREATE TABLE IF NOT EXISTS data_retention_audit_log ("
"id INTEGER PRIMARY KEY AUTOINCREMENT,"
"action TEXT NOT NULL,"
"identifier_type TEXT,"
"identifier_value TEXT,"
"affected_counts_json TEXT,"
"actor TEXT,"
"created_at TEXT NOT NULL)"
```

Idempotent CREATE — runs at every container start, no-ops if exists.

### Part B — Replace 501 stubs in `wtyj/dashboard/api.py`

Read `wtyj/dashboard/api.py:885-942` before editing. The Pydantic model at line 885 (`DataRetentionUpdate`) stays. The three 501-stub handlers at lines 913-942 get replaced with real implementations.

1. **Replace `data_retention_archive_now()` (lines 913-922)** with:

```python
@router.post("/data-retention/archive-now",
             dependencies=[Depends(_check_auth)])
async def data_retention_archive_now():
    """Brief 237: archive conversations inactive longer than the
    configured activeInboxArchiveAfterDays. Sets flags.deleted=true on
    email threads and conversation_status.deleted=1 on WA/IG/FB; skips
    active escalations and human takeover conversations."""
    settings = state_registry.get_data_retention_settings()
    n = settings.get("activeInboxArchiveAfterDays")
    if n is None:
        raise HTTPException(status_code=400, detail=(
            "activeInboxArchiveAfterDays is null — archive disabled. "
            "Set a value before running archive-now."))
    result = state_registry.archive_inactive_conversations(n)
    state_registry.data_retention_audit_write(
        action="archive_now",
        identifier_type=None,
        identifier_value=None,
        affected_counts=result,
        actor="dashboard",
    )
    return {"ok": True, **result}
```

2. **Replace `data_retention_export()` (lines 925-932)** with:

```python
class DataRetentionExportReq(BaseModel):
    tenant: str = "unboks"  # frontend pins per dashboard

@router.post("/data-retention/export",
             dependencies=[Depends(_check_auth)])
async def data_retention_export(req: DataRetentionExportReq):
    """Brief 237: dump all customer data to a JSON file under
    data/exports/. Returns path + record counts. The file lives on
    disk; a separate download endpoint can stream it later."""
    export_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "data", "exports")
    os.makedirs(export_dir, exist_ok=True)
    result = state_registry.export_all_customer_data(export_dir, req.tenant)
    state_registry.data_retention_audit_write(
        action="export",
        identifier_type=None,
        identifier_value=None,
        affected_counts=result.get("recordCounts", {}),
        actor="dashboard",
    )
    return {"ok": True, **result}
```

3. **Replace `data_retention_delete_customer()` (lines 935-942)** with:

```python
class DataRetentionDeleteReq(BaseModel):
    identifierValue: str
    identifierType: Literal["phone", "email", "conversation_id"]

@router.post("/data-retention/delete-customer-data",
             dependencies=[Depends(_check_auth)])
async def data_retention_delete_customer(req: DataRetentionDeleteReq):
    """Brief 237: apply the configured endOfRetentionAction
    ('anonymize' or 'delete') to a specific customer. Active
    escalations block this action. Approved learnings preserved per
    keepApprovedLearnings setting."""
    settings = state_registry.get_data_retention_settings()
    action = settings.get("endOfRetentionAction") or "anonymize"
    if action == "keep":
        raise HTTPException(status_code=400, detail=(
            "endOfRetentionAction is 'keep' — deletion disabled. "
            "Update the policy first."))
    result = state_registry.delete_customer_data(
        identifier_value=req.identifierValue,
        identifier_type=req.identifierType,
        action=action,
        keep_approved_learnings=bool(settings.get("keepApprovedLearnings", True)),
    )
    # Brief 237 Rule 10: audit log fires for ALL outcomes (success AND
    # blocked-by-active-escalation). The audit row is written here before
    # any raise so the blocked path is visible in the log.
    if not result.get("ok"):
        state_registry.data_retention_audit_write(
            action=f"delete_customer:blocked_by_{result.get('reason') or 'unknown'}",
            identifier_type=req.identifierType,
            identifier_value=req.identifierValue,
            affected_counts={"reason": result.get("reason")},
            actor="dashboard",
        )
        raise HTTPException(status_code=409, detail=result.get("reason"))
    state_registry.data_retention_audit_write(
        action=f"delete_customer:{action}",
        identifier_type=req.identifierType,
        identifier_value=req.identifierValue,
        affected_counts=result,
        actor="dashboard",
    )
    return {"ok": True, **result}
```

Add `data_retention_audit_write` as a small helper in `state_registry.py` (writes one row to `data_retention_audit_log`).

### Part C — Add `manualActionsAvailable` to `get_data_retention_settings`

Currently `wtyj/shared/state_registry.py:1979` hard-codes `"status": {"policyActive": False}`. Per the brief-reviewer's correctness call: `policyActive` reads as "the policy is RUNNING" — but after this brief only manual-trigger archive runs, no cron. Setting it to True would be exactly the "fake success" SR's Q6 in `f61c511ffd3c` explicitly called out.

Keep `policyActive=False` (the cron isn't shipped). Add a sibling boolean `manualActionsAvailable=True` so SR's frontend can stop showing "not yet implemented" placeholders for the three action buttons while still honestly displaying that the automatic policy isn't running:

```python
"status": {
    "policyActive": False,         # No cron yet — manual triggers only
    "manualActionsAvailable": True, # Brief 237: the 3 action endpoints are live
    "nextCleanupAt": None,
},
```

When the cron ships (future brief), `policyActive` flips to True and `nextCleanupAt` becomes a real ISO timestamp. Until then, the new field gives the frontend the truth without lying about automation.

## Tests

Extend `wtyj/tests/social/test_229_data_retention.py` rather than creating a new `test_237_*.py` file (per Brief 236's new test convention — extend the existing per-feature test file). Add the following test functions:

1. `test_archive_now_with_null_setting_returns_400` — set `activeInboxArchiveAfterDays=null` via PUT, then POST `/archive-now`, expect 400.
2. `test_archive_now_archives_old_email_thread_and_skips_recent` — write email JSON state with one 100-day-old thread + one 5-day-old thread, POST `/archive-now` with default 90-day setting, verify old has `flags.deleted=true` and recent does not, response shows `archivedCount=1`.
3. `test_archive_now_skips_thread_with_active_escalation` — write a 100-day-old email thread with `flags.fully_escalated=true`, run archive, verify it was NOT archived and `skippedActiveEscalation=1`.
4. `test_export_writes_file_and_returns_path` — POST `/export`, verify response has `exportPath`, file exists on disk, file is valid JSON, contains `customers` + `email_threads` keys.
5. `test_delete_customer_anonymize_preserves_row_ids` — insert a customer + 3 wa_messages, set `endOfRetentionAction=anonymize`, POST `/delete-customer-data`, verify the rows still exist (count unchanged) but `display_name` is `"[redacted]"` and message text is `"[redacted message]"`.
6. `test_delete_customer_delete_drops_rows` — insert customer, set `endOfRetentionAction=delete`, POST, verify the customer row + message rows are gone.
7. `test_delete_customer_blocked_by_active_escalation` — insert customer with active `pending_notifications` (status='sent', customer_id bound to one of the customer's identifier values, NOT the integer PK), POST delete, expect 409 + reason mentions active_escalation, verify NO PII rows were touched (count unchanged on customers/identifiers/whatsapp_threads), AND verify a row was written to `data_retention_audit_log` with `action LIKE 'delete_customer:blocked_by_%'` (Rule 10: log even on the blocked path).
8. `test_delete_customer_keep_learnings_skips_escalation_learnings` — insert customer + escalation_learnings row tied to them, with `keepApprovedLearnings=true` and action=delete, verify learnings row survives.
9. `test_audit_log_row_written_on_archive_now` — call `/archive-now`, query `data_retention_audit_log`, verify a row exists with `action='archive_now'` and JSON `affected_counts_json` populated.

Total: 9 tests on a brief that genuinely covers 3 endpoints + audit logging + settings interaction (Rule of 10 from CLAUDE.md template — 9 ≤ 10, justified by the multi-endpoint scope).

## Success Condition

After commit + deploy:
- `curl -X POST https://api.unboks.org/api/unboks/dashboard/api/data-retention/archive-now -H "Authorization: Bearer ..."` returns `{"ok": true, "archivedCount": 0, ...}` (count=0 because we just wiped unboks tonight).
- `curl -X POST .../data-retention/export -H "..." -d '{"tenant":"unboks"}'` writes a file under `data/exports/unboks-*.json` and returns its path; the file exists and is valid JSON.
- `curl -X POST .../data-retention/delete-customer-data -H "..." -d '{"identifierValue":"test@example.com","identifierType":"email"}'` returns `{"ok": true, "anonymizedCount": 0}` (no test customer in unboks post-wipe, but the call doesn't crash).
- Test suite passes 1016 / 0 failures (1007 baseline + 9 new).
- `data_retention_audit_log` table exists in all 4 tenants' state_registry.db files (idempotent CREATE runs on container start).

## Rollback

`git revert <commit-sha>` restores the 501 stubs and removes the helpers. The new `data_retention_audit_log` table created at first run remains (harmless empty table; `IF NOT EXISTS` makes the rollback idempotent). To fully clean up: `DROP TABLE data_retention_audit_log` on each tenant's DB (manual SQL), but this is optional — the orphan table costs nothing.

If a destructive call has already deleted real customer data before rollback, restore from the most recent SQLite backup at `/root/clients/{tenant}/data/state_registry.db.bak.*`. Backups are retained on the VPS — not git.

## Notes for executor

- **Read every file before editing.** Especially `state_registry.py:1130-1180` for `email_mark_deleted` patterns (use the same atomic-write idiom) and `state_registry.py:1380-1410` for the dedup query (use the same `IN ('pending','sent')` filter from Brief 235 — do not reintroduce the `'pending'`-only bug).
- **Anonymize string is `"[redacted]"` for fields, `"[redacted message]"` for message bodies.** Use those exact strings; tests will assert on them. Spanish equivalents are NOT required — the audit log + customer-facing experience uses English placeholders consistent with how operators read raw rows.
- **Active-escalation guard MUST use `status IN ('pending','sent')`**, not just `'pending'`. Brief 235's lesson — production escalations transition pending→sent on insert.
- **Audit log writes happen even when the action returns ok=false** (e.g., active-escalation block). The audit row records the attempt with `action='delete_customer:blocked_by_active_escalation'` so SR can see what was tried. Adjust the dashboard handler accordingly.
- **Reviewer pass is mandatory** (brief-reviewer + output-reviewer per workflow).
- **Deploy IS required.** This brief changes runtime behavior (real endpoints replace 501 stubs). Background deploy per workflow step b.
