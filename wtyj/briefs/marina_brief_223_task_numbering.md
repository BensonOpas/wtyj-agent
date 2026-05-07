# BRIEF 223 — Backend taskNumber for /tasks
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/tasks_api.py`, `wtyj/tests/social/test_223_task_numbering.py` | **Depends on:** Brief 207 (tasks API + table) | **Blocks:** SR's task `b702c18f412f` ("Tasks need a stable per-workspace task number")

## Context

SR's frontend displays a TASK-### badge on every task card. Today the number lives in browser localStorage — the `useTaskNumberOverlay` hook in `unboks-dashboard-api/artifacts/unboks/src/hooks/use-task-number-overlay.ts:48-98` allocates a number per server task id at render time, persisting to `localStorage["unboks_task_numbers"]`. That works for a single browser session, but it's fragile:

- Clear browser data → numbers reset; same task gets a new number on next render.
- Open in a second browser → that browser allocates fresh numbers, so the same task can be TASK-014 in Calvin's Chrome and TASK-022 in Benson's Safari.
- Two operators can't reference a task by number reliably.

SR's task `b702c18f412f` (open, assigned to Jr) calls this out:

```
Jr, Tasks need a stable per-workspace task number.
Please add a backend field: taskNumber: integer
Display format in frontend: TASK-001, TASK-002, TASK-003
Rules:
- Unique per workspace/client.
- Assigned when task is created.
- Never changes after creation.
- Edit/Park/Done/Reopen must not change it.
- Backend should return taskNumber in GET /tasks.
- POST /tasks should assign next taskNumber automatically.
- Do not rely only on UUIDs for human reference. UUIDs stay internal,
  taskNumber is for users.
```

"Per workspace" maps cleanly to our architecture: each tenant runs in its own container with its own SQLite, so the tasks table is already workspace-isolated. Numbering is just `MAX(task_number) + 1` within the table.

The frontend's overlay code at `use-task-number-overlay.ts:238-252` already handles a backend-supplied number gracefully — `apply()` checks `typeof task.taskNumber === "number"` and returns the task unchanged if so, falling through to `ensureAllocated()` only when the backend didn't supply one. So a backend that ships `taskNumber` immediately wins; the localStorage overlay becomes a no-op for backend-numbered tasks.

## Why This Approach

**Considered:** keep the frontend as the source of truth (localStorage only). Rejected: cross-device + cross-browser inconsistency is the entire reason SR filed the task.

**Considered:** sync the localStorage map up to the backend on every page load (operator's localStorage → backend on first read). Rejected: requires a new sync endpoint, doesn't fix the cross-browser problem (which browser wins?), and existing operators have inconsistent localStorage state across machines that we'd be canonicalizing arbitrarily.

**Considered:** use a sequence/counter table separate from `tasks`. Rejected: adds an INSERT-and-SELECT round-trip for every create with no benefit over `MAX(task_number) + 1` on a small table. SQLite isn't going to deadlock on this.

**Chosen:** add `task_number INTEGER` to the existing `tasks` table via idempotent `ALTER TABLE` (the standard pattern at `state_registry.py:266-272` for Brief 213's columns). On `tasks_create`, compute next number from `MAX(task_number) + 1` inside the same transaction as the INSERT. Backfill any pre-existing rows (which have NULL after the ALTER) by assigning numbers in `created_at ASC` order — the chronologically oldest task gets `taskNumber=1`. Then return `taskNumber` from `tasks_get`/`tasks_list` and rename to camelCase in `_format_task`.

**About the backfill location:** schema init in this codebase lives inside `_get_conn()` itself — every new connection runs the CREATE TABLE / ALTER TABLE block, including Brief 213's pattern at lines 266-272. There is no separate `_init_db` function. That means our backfill SELECT (`SELECT id FROM tasks WHERE task_number IS NULL`) ALSO runs on every connection. After the first execution there are no NULL rows, so the SELECT returns zero rows and the `if to_backfill:` guard short-circuits — but the SELECT itself still runs. Acceptable: it's a single index-friendly query against a small table (operator tasks, not customer messages); cheaper than the existing CREATE TABLE IF NOT EXISTS and ALTER TABLE statements that already run on the same hot path. If profiling later flags this, it's a one-shot move into a global-flag-guarded "first connection in process" gate. Not worth gating today — match the existing pattern.

**Tradeoff:** existing tasks that operators already saw with localStorage-allocated numbers may suddenly show DIFFERENT numbers after this lands (the backfill assigns them by created_at order, which doesn't match SR's localStorage counter order). One-time visual hiccup. Mitigation: the new numbers are STABLE going forward — once backfilled, they never change. SR can re-establish the mapping after one render.

## Instructions

### Step 1: Schema column + backfill inside `_get_conn()`

In `wtyj/shared/state_registry.py`, find the existing Brief 213 ALTER block at lines 266-272 (inside `_get_conn()`). Add a parallel block for the tasks table directly after the Brief 213 ALTERs and before the `# Brief 217` comment (around line 273):

```python
# Brief 223: tasks.task_number (per-workspace stable integer for the
# TASK-### badge SR's frontend displays). Idempotent ALTER + backfill
# of pre-existing rows in chronological order so the oldest task is
# TASK-001. Backfill runs on every _get_conn() call (matching the
# existing per-connection schema-init pattern); after the first run
# the SELECT returns zero rows and the if-guard short-circuits.
try:
    conn.execute("ALTER TABLE tasks ADD COLUMN task_number INTEGER")
except sqlite3.OperationalError:
    pass
to_backfill = conn.execute(
    "SELECT id FROM tasks WHERE task_number IS NULL ORDER BY created_at ASC"
).fetchall()
if to_backfill:
    cur_max = conn.execute(
        "SELECT COALESCE(MAX(task_number), 0) FROM tasks"
    ).fetchone()[0]
    for offset, (row_id,) in enumerate(to_backfill, start=1):
        conn.execute(
            "UPDATE tasks SET task_number = ? WHERE id = ?",
            (cur_max + offset, row_id))
    conn.commit()
```

### Step 2: `tasks_create` allocates the next number

Update `tasks_create()` at `state_registry.py:2971-2983` to compute `MAX(task_number) + 1` and INSERT it as part of the row:

```python
def tasks_create(task_id: str, body_html: str, body_text: str,
                 created_by: str, assigned_to: str) -> dict:
    """Insert a new task. Returns the task dict (with empty attachments).
    Brief 223: also allocates the next per-workspace task_number."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    next_num = (conn.execute(
        "SELECT COALESCE(MAX(task_number), 0) + 1 FROM tasks"
    ).fetchone()[0])
    conn.execute(
        "INSERT INTO tasks (id, body_html, body_text, created_by, assigned_to, "
        "status, task_number, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)",
        (task_id, body_html, body_text, created_by, assigned_to,
         next_num, now, now)
    )
    conn.commit()
    conn.close()
    return tasks_get(task_id)
```

### Step 3: `tasks_get` returns `task_number` in the dict

Update `tasks_get()` at `state_registry.py:2986-3013` so the SELECT includes `task_number` and the returned dict includes it:

```python
row = conn.execute(
    "SELECT id, body_html, body_text, created_by, assigned_to, status, "
    "completed_at, completed_by, task_number, created_at, updated_at "
    "FROM tasks WHERE id = ?", (task_id,)
).fetchone()
# ... unchanged attachment query ...
return {
    "id": row[0], "body_html": row[1], "body_text": row[2],
    "created_by": row[3], "assigned_to": row[4], "status": row[5],
    "completed_at": row[6], "completed_by": row[7],
    "task_number": row[8],
    "created_at": row[9], "updated_at": row[10],
    "attachments": [...]
}
```

(The trailing `created_at`/`updated_at` indices shift from 8/9 to 9/10 because of the new column position.)

### Step 4: `_format_task` exposes camelCase `taskNumber`

In `wtyj/dashboard/tasks_api.py:42-69` (`_format_task`), add `"taskNumber": task["task_number"]` to the returned dict, matching SR's frontend expectation.

### Step 5: Test file `wtyj/tests/social/test_223_task_numbering.py`

Mirror the test harness pattern at `wtyj/tests/social/test_211_dashboard_contract_fields.py` (login + auth helper + TestClient). Use `state_registry._get_conn()` to clean up seeded rows in try/finally so repeated runs don't accumulate state.

Required tests (5):

1. **`test_first_task_gets_number_one_when_table_empty`** — DELETE FROM tasks (clean slate), then `state_registry.tasks_create(...)` once. Returned dict has `task_number == 1`.
2. **`test_subsequent_tasks_get_sequential_numbers`** — clean slate, create 3 tasks, assert numbers are `1, 2, 3` in creation order.
3. **`test_patch_status_does_not_change_task_number`** — create a task (gets number N), then `tasks_update_status(task_id, "done")`, then `tasks_get(task_id)`. Task number is still N.
4. **`test_get_tasks_response_includes_task_number_camelcase`** — POST to `/tasks` (or seed via state_registry), GET `/tasks`, assert each row has key `taskNumber` with integer value. NOT `task_number` snake_case.
5. **`test_existing_null_rows_get_backfilled_in_chronological_order`** — DELETE FROM tasks (clean slate). Manually INSERT 3 rows directly via `_get_conn().execute(...)` with `task_number = NULL` and explicit `created_at` values (e.g., 2026-01-01, 2026-02-01, 2026-03-01); since the schema-init in `_get_conn()` would backfill them on the very next connection, the test should INSERT in a single connection and then call `_get_conn()` again to trigger the backfill, then read each row's `task_number`; oldest → smallest number, newest → largest. Acceptable alternative: monkey-patch the backfill block to run as a one-off function call inside the test; the goal is asserting the chronological-order guarantee, not exercising the per-connection trigger pattern.

For all tests: cleanup deletes from `tasks` and `task_attachments` tables.

## Tests

5 tests covering allocation, persistence across status updates, response shape (camelCase), and backfill ordering. All assertions check real return values from the helpers + the JSON response.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` passes at **1010 / 0** (1005 baseline confirmed at start of session + 5 new). Live verification post-deploy: `GET /api/unboks/dashboard/api/tasks` returns rows where each task has a `taskNumber` integer field. Existing tasks have backfilled numbers (oldest = 1, newest = N). New tasks created via `POST /tasks` get incrementing numbers.

## Rollback

`git revert <commit>` and redeploy. The `task_number` column stays in the schema (revert can't remove a column without a table rebuild) but becomes unused — `tasks_create` stops allocating, `tasks_get` stops reading it, `_format_task` stops emitting it. Frontend overlay at `use-task-number-overlay.ts` continues to render TASK-### from localStorage as before. Schema-leftover-column is harmless dead state, no migration needed to clean up.
