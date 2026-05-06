# BRIEF 207 — Tasks backend endpoints for SR's dashboard Tasks page

**Status:** Draft
**Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/tasks_api.py` (new), `wtyj/agents/social/webhook_server.py`, `wtyj/tests/test_207_tasks_api.py` (new)
**Depends on:** Brief 200 (api.unboks.org nginx routing), Brief 205-rolled-back (sessions persist via SESSION_TOKEN — not strictly required, but tasks would be more usable with persistent sessions; out of scope here).
**Blocks:** SR's frontend Tasks page (currently shows "Couldn't load tasks: Tasks backend not available yet").

---

## Context

SR built a Tasks page at `dashboard.unboks.org/tasks` for Calvin and Jr to share work between them. The frontend currently shows: *"Couldn't load tasks: Tasks backend not available yet. Ask the API team to ship /api/unboks/tasks."* This brief ships the backend.

**Required endpoints (from SR's spec):**
- `GET /api/unboks/tasks` — list all tasks
- `POST /api/unboks/tasks` — create. Body: `{assignedTo, bodyHtml, bodyText, attachments}`
- `PATCH /api/unboks/tasks/:id` — update status. Body: `{status: "open"|"done"}`
- `POST /api/unboks/tasks/uploads` — image upload (PNG/JPEG/WebP) for pasted screenshots
- (implicit: `GET /api/unboks/tasks/uploads/:filename` — serve uploaded files via FileResponse)

**Required task shape:**
```json
{
  "id": "string",
  "bodyHtml": "string",
  "bodyText": "string",
  "createdBy": "Calvin" | "Jr",
  "assignedTo": "Calvin" | "Jr",
  "status": "open" | "done",
  "attachments": [
    {"id", "fileName", "mimeType", "sizeBytes", "url", "createdAt"}
  ],
  "createdAt": "ISO timestamp",
  "updatedAt": "ISO timestamp",
  "completedAt": "ISO timestamp or null",
  "completedBy": "Calvin" | "Jr" | null
}
```

**SR's hard requirements:** shared storage (not browser localStorage), persistent across restarts, persistent screenshots after refresh. No comments, priority, deadlines, or notifications yet.

### URL routing reality

SR's frontend hits `https://api.unboks.org/api/unboks/tasks`. Brief 200's nginx routing maps `/api/unboks/` → `127.0.0.1:8004/` with prefix-strip, so the backend container receives `/tasks`. Routes need to be at the FastAPI app's root level (not under the existing `/dashboard/api/` prefix used by the dashboard router). New router with `prefix="/tasks"`.

### Out of scope

- Real per-user identity (single dashboard password today; `createdBy`/`assignedTo` are trusted strings from the frontend).
- Task deletion (SR didn't list it; can add later).
- Notifications when a task is assigned (SR explicitly said no).
- Task editing of body content (only status changes per the PATCH spec).
- Pagination / search / filter (SR didn't ask).

---

## Why This Approach

**Storage:** SQLite tables (`tasks` + `task_attachments`) in the existing per-tenant `state_registry.db`. Same pattern as `pending_notifications`, `content_drafts`, `photo_library`. Tasks are tenant-scoped automatically (each container has its own DB).

**File uploads:** disk storage at `/app/data/task_uploads/` served via FastAPI `FileResponse`. Same pattern as `_PHOTOS_DIR` in `wtyj/dashboard/api.py:80-84`. Stored with collision-resistant filenames (`secrets.token_hex(8)` suffix, like the existing photo upload at api.py:94).

**Routing:** new file `wtyj/dashboard/tasks_api.py` with a router (`prefix="/tasks"`) registered at app level in `webhook_server.py`. Reuses `_check_auth` from `dashboard/api.py` so the same Bearer token model SR's frontend already uses for other endpoints applies. Doesn't pollute the dashboard router's `/dashboard/api/` namespace.

**ID format:** `secrets.token_hex(8)` strings (16-char hex). Frontend treats as opaque. Avoids the SQLite-rowid-as-integer pattern leaking into URLs and avoids needing UUID dep for one feature.

**Considered alternatives:**

1. **Add tasks to dashboard router → frontend hits `/api/unboks/dashboard/api/tasks`.** Inconsistent with SR's frontend's hardcoded URLs. Would require SR to push frontend changes. Rejected.
2. **JSON-file storage instead of SQLite.** Faster to write, but breaks the established per-tenant SQLite-everywhere pattern. Rejected — SQLite is right.
3. **Store uploaded image bytes in a SQLite BLOB column.** Tighter atomicity but bigger migration risk + larger DB churn. Disk + URL is simpler and matches photo upload precedent. Rejected.
4. **Skip attachments entirely** (SR said "optional but needed soon"). Could ship faster, but SR's frontend already supports paste-screenshot UX and would just look broken. Worth the extra hour to ship together. Rejected the skip.

---

## Instructions

### Part 1 — Two new tables in `wtyj/shared/state_registry.py`

In the `_get_conn` initialization block (around line 220, where `pending_notifications` and `content_drafts` are created), add two new `CREATE TABLE IF NOT EXISTS` statements:

```python
conn.execute(
    "CREATE TABLE IF NOT EXISTS tasks ("
    "id TEXT PRIMARY KEY, "                  # 16-char hex from secrets.token_hex(8)
    "body_html TEXT NOT NULL DEFAULT '', "
    "body_text TEXT NOT NULL DEFAULT '', "
    "created_by TEXT NOT NULL, "             # "Calvin" or "Jr"
    "assigned_to TEXT NOT NULL, "
    "status TEXT NOT NULL DEFAULT 'open', "  # "open" or "done"
    "completed_at TEXT, "                     # ISO timestamp or NULL
    "completed_by TEXT, "                     # "Calvin"/"Jr" or NULL
    "created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL"
    ")"
)
conn.execute(
    "CREATE TABLE IF NOT EXISTS task_attachments ("
    "id TEXT PRIMARY KEY, "                  # 16-char hex
    "task_id TEXT NOT NULL, "
    "file_name TEXT NOT NULL, "
    "mime_type TEXT NOT NULL, "
    "size_bytes INTEGER NOT NULL, "
    "stored_filename TEXT NOT NULL, "        # actual on-disk filename (collision-safe)
    "created_at TEXT NOT NULL, "
    "FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE"
    ")"
)
```

Add 5 helper functions at the end of `state_registry.py`:

```python
def tasks_create(task_id: str, body_html: str, body_text: str,
                  created_by: str, assigned_to: str) -> dict:
    """Insert a new task. Returns the task dict."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO tasks (id, body_html, body_text, created_by, assigned_to, "
        "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
        (task_id, body_html, body_text, created_by, assigned_to, now, now)
    )
    conn.commit()
    conn.close()
    return tasks_get(task_id)


def tasks_get(task_id: str) -> dict | None:
    """Fetch a single task with its attachments. Returns None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, body_html, body_text, created_by, assigned_to, status, "
        "completed_at, completed_by, created_at, updated_at "
        "FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    attachments = conn.execute(
        "SELECT id, file_name, mime_type, size_bytes, stored_filename, created_at "
        "FROM task_attachments WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,)
    ).fetchall()
    conn.close()
    return {
        "id": row[0], "body_html": row[1], "body_text": row[2],
        "created_by": row[3], "assigned_to": row[4], "status": row[5],
        "completed_at": row[6], "completed_by": row[7],
        "created_at": row[8], "updated_at": row[9],
        "attachments": [
            {"id": a[0], "file_name": a[1], "mime_type": a[2],
             "size_bytes": a[3], "stored_filename": a[4], "created_at": a[5]}
            for a in attachments
        ],
    }


def tasks_list() -> list:
    """List all tasks newest first, with attachments."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id FROM tasks ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [tasks_get(r[0]) for r in rows]


def tasks_update_status(task_id: str, status: str,
                         completed_by: str = None) -> dict | None:
    """Update task status. When status='done', sets completed_at + completed_by.
    When status='open', clears them. Returns updated task or None if not found."""
    if status not in ("open", "done"):
        raise ValueError(f"Invalid status: {status}")
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    if status == "done":
        conn.execute(
            "UPDATE tasks SET status = 'done', completed_at = ?, "
            "completed_by = ?, updated_at = ? WHERE id = ?",
            (now, completed_by, now, task_id)
        )
    else:
        conn.execute(
            "UPDATE tasks SET status = 'open', completed_at = NULL, "
            "completed_by = NULL, updated_at = ? WHERE id = ?",
            (now, task_id)
        )
    conn.commit()
    conn.close()
    return tasks_get(task_id)


def tasks_add_attachment(task_id: str, attachment_id: str, file_name: str,
                          mime_type: str, size_bytes: int,
                          stored_filename: str) -> dict:
    """Insert an attachment row for an existing task. Returns the attachment dict."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO task_attachments (id, task_id, file_name, mime_type, "
        "size_bytes, stored_filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (attachment_id, task_id, file_name, mime_type, size_bytes,
         stored_filename, now)
    )
    # Bump task's updated_at so frontend sees fresh ordering after attachment
    conn.execute(
        "UPDATE tasks SET updated_at = ? WHERE id = ?", (now, task_id)
    )
    conn.commit()
    conn.close()
    return {
        "id": attachment_id, "file_name": file_name, "mime_type": mime_type,
        "size_bytes": size_bytes, "stored_filename": stored_filename,
        "created_at": now,
    }
```

### Part 2 — New file `wtyj/dashboard/tasks_api.py`

Create this file with a FastAPI router at `prefix="/tasks"`. Endpoints:

```python
"""Brief 207: Tasks API for SR's dashboard Tasks page.
Routes are mounted at the FastAPI app's root level (not under /dashboard/api/)
because nginx strips /api/unboks/ → backend receives /tasks.
"""
import io
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from shared import state_registry
from dashboard.api import _check_auth

_TASK_UPLOADS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "task_uploads"
)
os.makedirs(_TASK_UPLOADS_DIR, exist_ok=True)

_ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    assignedTo: str
    bodyHtml: str = ""
    bodyText: str = ""
    attachments: list = []  # list of {id} dicts referencing already-uploaded files
    createdBy: str = "Jr"   # default — frontend should override


class UpdateStatusRequest(BaseModel):
    status: str  # "open" or "done"
    completedBy: str | None = None  # required when status="done"


def _format_task(task: dict) -> dict:
    """Convert state_registry's snake_case task dict into the camelCase shape
    SR's frontend expects, including attachment URLs."""
    if not task:
        return None
    return {
        "id": task["id"],
        "bodyHtml": task["body_html"],
        "bodyText": task["body_text"],
        "createdBy": task["created_by"],
        "assignedTo": task["assigned_to"],
        "status": task["status"],
        "createdAt": task["created_at"],
        "updatedAt": task["updated_at"],
        "completedAt": task["completed_at"],
        "completedBy": task["completed_by"],
        "attachments": [
            {
                "id": a["id"],
                "fileName": a["file_name"],
                "mimeType": a["mime_type"],
                "sizeBytes": a["size_bytes"],
                "url": f"/tasks/uploads/{a['stored_filename']}",
                "createdAt": a["created_at"],
            }
            for a in task.get("attachments", [])
        ],
    }


@router.get("", dependencies=[Depends(_check_auth)])
async def list_tasks():
    return [_format_task(t) for t in state_registry.tasks_list()]


@router.post("", dependencies=[Depends(_check_auth)])
async def create_task(req: CreateTaskRequest):
    task_id = secrets.token_hex(8)
    state_registry.tasks_create(
        task_id=task_id,
        body_html=req.bodyHtml,
        body_text=req.bodyText,
        created_by=req.createdBy,
        assigned_to=req.assignedTo,
    )
    # Attach any pre-uploaded attachments (they were uploaded via /tasks/uploads
    # and the frontend now passes their IDs back in the create request).
    # Each entry in req.attachments is expected to contain at minimum {id,
    # fileName, mimeType, sizeBytes, storedFilename} as returned by the upload
    # endpoint.
    for att in req.attachments or []:
        if not isinstance(att, dict):
            continue
        try:
            state_registry.tasks_add_attachment(
                task_id=task_id,
                attachment_id=att["id"],
                file_name=att["fileName"],
                mime_type=att["mimeType"],
                size_bytes=int(att["sizeBytes"]),
                stored_filename=att["storedFilename"],
            )
        except (KeyError, ValueError, TypeError):
            # Skip malformed attachment entries; task itself is still created
            continue
    return _format_task(state_registry.tasks_get(task_id))


@router.patch("/{task_id}", dependencies=[Depends(_check_auth)])
async def update_task(task_id: str, req: UpdateStatusRequest):
    if req.status not in ("open", "done"):
        raise HTTPException(status_code=400, detail="status must be 'open' or 'done'")
    existing = state_registry.tasks_get(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    completed_by = req.completedBy if req.status == "done" else None
    updated = state_registry.tasks_update_status(
        task_id, req.status, completed_by=completed_by
    )
    return _format_task(updated)


@router.post("/uploads", dependencies=[Depends(_check_auth)])
async def upload_attachment(file: UploadFile = File(...)):
    """Upload an image file (screenshot). Returns the attachment metadata
    (id, fileName, mimeType, sizeBytes, storedFilename, url) that the frontend
    then passes back inside POST /tasks's attachments array when creating
    the task."""
    if file.content_type not in _ALLOWED_IMAGE_MIMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mime type {file.content_type}. "
                   f"Allowed: {sorted(_ALLOWED_IMAGE_MIMES)}",
        )
    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(contents)} bytes; max {_MAX_UPLOAD_BYTES})",
        )
    # Collision-safe filename: <timestamp>_<hex>.<ext>
    ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    ext = ext_map[file.content_type]
    stored_filename = f"{int(datetime.now(timezone.utc).timestamp())}_{secrets.token_hex(6)}.{ext}"
    path = os.path.join(_TASK_UPLOADS_DIR, stored_filename)
    with open(path, "wb") as f:
        f.write(contents)
    attachment_id = secrets.token_hex(8)
    return {
        "id": attachment_id,
        "fileName": file.filename or stored_filename,
        "mimeType": file.content_type,
        "sizeBytes": len(contents),
        "storedFilename": stored_filename,
        "url": f"/tasks/uploads/{stored_filename}",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/uploads/{filename}")
async def serve_upload(filename: str):
    """Serve uploaded image files. NO auth on this endpoint so screenshots
    embedded in task bodies render via plain <img> tags. Filename collisions
    are prevented by the upload endpoint's token_hex suffix."""
    # Defensive: prevent path traversal (".." segments etc).
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(_TASK_UPLOADS_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)
```

### Part 3 — Register the router in `wtyj/agents/social/webhook_server.py`

After the existing `app.include_router(dashboard_router)` line (around line 47), add:

```python
from dashboard.tasks_api import router as tasks_router
app.include_router(tasks_router)
```

### Part 4 — Tests in `wtyj/tests/test_207_tasks_api.py`

```python
"""Brief 207: Tasks API endpoints — list, create, update, attachment upload."""

import io
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from fastapi.testclient import TestClient


def _client_and_token():
    from agents.social.webhook_server import app
    client = TestClient(app)
    login = client.post("/dashboard/api/login", json={"password": "testpass"})
    assert login.status_code == 200
    token = login.json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_create_task_returns_full_shape():
    """POST /tasks returns the canonical camelCase task shape with id +
    createdAt + updatedAt + null completed fields."""
    client, headers = _client_and_token()
    resp = client.post("/tasks", json={
        "assignedTo": "Calvin",
        "createdBy": "Jr",
        "bodyHtml": "<p>review the doc</p>",
        "bodyText": "review the doc",
        "attachments": [],
    }, headers=headers)
    assert resp.status_code == 200
    task = resp.json()
    assert len(task["id"]) == 16
    assert task["assignedTo"] == "Calvin"
    assert task["createdBy"] == "Jr"
    assert task["bodyText"] == "review the doc"
    assert task["status"] == "open"
    assert task["completedAt"] is None
    assert task["completedBy"] is None
    assert task["createdAt"]
    assert task["updatedAt"]
    assert task["attachments"] == []


def test_list_tasks_round_trip():
    """POST then GET returns the created task."""
    client, headers = _client_and_token()
    created = client.post("/tasks", json={
        "assignedTo": "Jr", "createdBy": "Calvin",
        "bodyHtml": "", "bodyText": "ping",
    }, headers=headers).json()
    listing = client.get("/tasks", headers=headers).json()
    found = [t for t in listing if t["id"] == created["id"]]
    assert len(found) == 1
    assert found[0]["bodyText"] == "ping"


def test_patch_done_sets_completed_fields():
    """PATCH status=done sets completedAt + completedBy + status."""
    client, headers = _client_and_token()
    created = client.post("/tasks", json={
        "assignedTo": "Calvin", "createdBy": "Jr",
        "bodyHtml": "", "bodyText": "do thing",
    }, headers=headers).json()
    resp = client.patch(f"/tasks/{created['id']}",
                         json={"status": "done", "completedBy": "Calvin"},
                         headers=headers)
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["status"] == "done"
    assert updated["completedBy"] == "Calvin"
    assert updated["completedAt"] is not None


def test_patch_open_clears_completed_fields():
    """PATCH status=open clears completedAt + completedBy (regression for
    re-opening a previously-closed task)."""
    client, headers = _client_and_token()
    created = client.post("/tasks", json={
        "assignedTo": "Jr", "createdBy": "Calvin",
        "bodyHtml": "", "bodyText": "reopen test",
    }, headers=headers).json()
    client.patch(f"/tasks/{created['id']}",
                  json={"status": "done", "completedBy": "Jr"},
                  headers=headers)
    resp = client.patch(f"/tasks/{created['id']}",
                         json={"status": "open"}, headers=headers)
    assert resp.status_code == 200
    reopened = resp.json()
    assert reopened["status"] == "open"
    assert reopened["completedAt"] is None
    assert reopened["completedBy"] is None


def test_upload_attachment_returns_metadata_and_persists_file():
    """POST /tasks/uploads accepts a PNG, returns metadata with URL, and the
    file is retrievable via GET /tasks/uploads/{filename}."""
    client, headers = _client_and_token()
    # 1x1 transparent PNG bytes
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d4944415478da636001000000050001a5f3e2240000000049454e44ae426082"
    )
    resp = client.post("/tasks/uploads",
                        files={"file": ("test.png", io.BytesIO(png_bytes), "image/png")},
                        headers=headers)
    assert resp.status_code == 200, resp.text
    att = resp.json()
    assert att["mimeType"] == "image/png"
    assert att["sizeBytes"] == len(png_bytes)
    assert att["url"].startswith("/tasks/uploads/")
    assert att["fileName"] == "test.png"
    # Fetch back via the URL — no auth required for serve endpoint
    get_resp = client.get(att["url"])
    assert get_resp.status_code == 200
    assert get_resp.content == png_bytes


def test_upload_rejects_disallowed_mime_type():
    """POST /tasks/uploads rejects non-image/non-allowed mime types."""
    client, headers = _client_and_token()
    resp = client.post("/tasks/uploads",
                        files={"file": ("doc.pdf", io.BytesIO(b"fake-pdf"),
                                         "application/pdf")},
                        headers=headers)
    assert resp.status_code == 400
    assert "Unsupported mime type" in resp.json()["detail"]
```

---

## Success Condition

After deploy:
1. Pytest goes from 925 → 931 passing (6 new), 0 failures.
2. SR's frontend at `dashboard.unboks.org/tasks` no longer shows the "backend not ready" error.
3. Manual end-to-end (via dashboard UI):
   - Create a task assigned to Calvin → appears in the list, status open.
   - Mark done → status flips, `completedAt` populated.
   - Refresh page → task still there, status persisted.
   - Paste a screenshot when creating a new task → image uploads, embeds in task body, persists across refresh.
   - Calvin and Jr both see the same task list (shared backend, not browser-local).

---

## Rollback

`git revert <commit>` and redeploy. New tables remain in the SQLite DB after revert (no schema migration to undo); they're orphaned but harmless. Uploaded files in `/app/data/task_uploads/` remain on disk; can be `rm -rf`'d if cleanup is desired but the directory is excluded from any backup-critical paths and won't grow without active usage.

The `tasks_api.router` registration in `webhook_server.py` is the only change that affects request routing — reverting it makes `/tasks/*` endpoints return 404 (which is exactly the pre-brief state). No other tenant or feature is affected.
