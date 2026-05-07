# OUTPUT 223 — Backend taskNumber for /tasks

## What was done

Added `task_number INTEGER` column to the existing `tasks` table via idempotent `ALTER TABLE` placed AFTER the `CREATE TABLE tasks` block in `_get_conn()` (correcting a round-1 placement issue where the ALTER would have run before the table existed on first init). Added a per-connection backfill block adjacent to the ALTER: any row with NULL `task_number` gets a number based on `created_at ASC` order, gated by an `if to_backfill:` short-circuit so post-first-run connections only pay the cost of one zero-result SELECT. Updated `tasks_create()` to allocate `MAX(task_number) + 1` inside the same transaction as the INSERT. Updated `tasks_get()` to include `task_number` in the SELECT and the returned dict (column-index shift from 8/9 → 9/10 for `created_at`/`updated_at`). Added `taskNumber: task.get("task_number")` to `_format_task()` in tasks_api.py for camelCase exposure to SR's frontend. Frontend at `use-task-number-overlay.ts:242` already defers to backend-supplied numbers (returns task unchanged when `typeof task.taskNumber === "number"`), so the localStorage overlay becomes a no-op once this lands.

## Tests

1010 passing / 0 failures (1005 baseline + 5 new).

## Unexpected findings

Round-1 brief placed the new ALTER + backfill block BEFORE the `CREATE TABLE tasks` block, which would have failed the ALTER on first init in a fresh container (table didn't exist yet). Caught + fixed during execution by reading the surrounding code rather than trusting the brief's "right after Brief 213 ALTERs" anchor. New comment in source explicitly notes the placement requirement: "Placed AFTER the CREATE TABLE tasks block so the ALTER has a target on first init."

## Deployment

Pending — commit/push/deploy in step 16.
