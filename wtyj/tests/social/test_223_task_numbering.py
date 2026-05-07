# test_223_task_numbering.py
# Brief 223: tasks table gets task_number INTEGER column, allocated on
# tasks_create via MAX+1, backfilled on schema-init for pre-existing
# NULL rows in created_at order, exposed in /tasks JSON as taskNumber
# (camelCase) for SR's frontend.

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _wipe_tasks():
    """Clean slate: drop all tasks + attachments before each test."""
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM task_attachments")
    conn.execute("DELETE FROM tasks")
    conn.commit()
    conn.close()


# --- Test 1: First task gets number 1 when table is empty
def test_first_task_gets_number_one_when_table_empty():
    from shared import state_registry
    try:
        _wipe_tasks()
        result = state_registry.tasks_create(
            task_id="223_first",
            body_html="", body_text="first task",
            created_by="Jr", assigned_to="Jr",
        )
        assert result["task_number"] == 1
    finally:
        _wipe_tasks()


# --- Test 2: Subsequent tasks get sequential numbers
def test_subsequent_tasks_get_sequential_numbers():
    from shared import state_registry
    try:
        _wipe_tasks()
        t1 = state_registry.tasks_create(
            task_id="223_seq_1", body_html="", body_text="one",
            created_by="Jr", assigned_to="Jr")
        t2 = state_registry.tasks_create(
            task_id="223_seq_2", body_html="", body_text="two",
            created_by="Jr", assigned_to="Jr")
        t3 = state_registry.tasks_create(
            task_id="223_seq_3", body_html="", body_text="three",
            created_by="Jr", assigned_to="Jr")
        assert t1["task_number"] == 1
        assert t2["task_number"] == 2
        assert t3["task_number"] == 3
    finally:
        _wipe_tasks()


# --- Test 3: PATCH (status update) does NOT change task_number
def test_patch_status_does_not_change_task_number():
    from shared import state_registry
    try:
        _wipe_tasks()
        created = state_registry.tasks_create(
            task_id="223_patch", body_html="", body_text="patch test",
            created_by="Jr", assigned_to="Jr")
        original_num = created["task_number"]
        assert original_num == 1

        state_registry.tasks_update_status("223_patch", "done", completed_by="Jr")
        after_done = state_registry.tasks_get("223_patch")
        assert after_done["task_number"] == original_num

        state_registry.tasks_update_status("223_patch", "open")
        after_reopen = state_registry.tasks_get("223_patch")
        assert after_reopen["task_number"] == original_num
    finally:
        _wipe_tasks()


# --- Test 4: GET /tasks response includes taskNumber (camelCase) integer
def test_get_tasks_response_includes_task_number_camelcase():
    from shared import state_registry
    try:
        _wipe_tasks()
        state_registry.tasks_create(
            task_id="223_camel", body_html="", body_text="camel case",
            created_by="Jr", assigned_to="Jr")

        token = _login()
        r = client.get("/tasks", headers=_auth(token))
        assert r.status_code == 200, r.text
        rows = r.json()
        # Find our test row (others may exist if tests ran in parallel,
        # though _wipe_tasks should have left only this one)
        row = next((t for t in rows if t["id"] == "223_camel"), None)
        assert row is not None
        # camelCase key MUST be present
        assert "taskNumber" in row
        assert isinstance(row["taskNumber"], int)
        assert row["taskNumber"] == 1
        # snake_case key must NOT leak through
        assert "task_number" not in row
    finally:
        _wipe_tasks()


# --- Test 5: Pre-existing NULL rows get backfilled in chronological order
def test_existing_null_rows_get_backfilled_in_chronological_order():
    from shared import state_registry
    try:
        _wipe_tasks()
        # INSERT 3 rows directly with task_number NULL and explicit
        # created_at values; then explicitly clear task_number to simulate
        # rows that existed before Brief 223 added the column.
        conn = state_registry._get_conn()
        for tid, ts in [
            ("223_old_b", "2026-02-01T12:00:00+00:00"),
            ("223_old_c", "2026-03-01T12:00:00+00:00"),
            ("223_old_a", "2026-01-01T12:00:00+00:00"),
        ]:
            conn.execute(
                "INSERT INTO tasks (id, body_html, body_text, created_by, "
                "assigned_to, status, task_number, created_at, updated_at) "
                "VALUES (?, '', ?, 'Jr', 'Jr', 'open', NULL, ?, ?)",
                (tid, tid, ts, ts))
        conn.commit()
        conn.close()

        # Trigger a fresh _get_conn() — the per-connection schema-init
        # block runs the backfill SELECT and assigns numbers to the NULL
        # rows in created_at ASC order.
        _ = state_registry._get_conn()

        # After backfill: oldest (a, 2026-01-01) = 1, then b, then c
        row_a = state_registry.tasks_get("223_old_a")
        row_b = state_registry.tasks_get("223_old_b")
        row_c = state_registry.tasks_get("223_old_c")
        assert row_a["task_number"] is not None
        assert row_b["task_number"] is not None
        assert row_c["task_number"] is not None
        # Chronological ordering preserved
        assert row_a["task_number"] < row_b["task_number"] < row_c["task_number"]
    finally:
        _wipe_tasks()
