"""Brief 207: Tasks API for SR's dashboard Tasks page.

Routes are mounted at the FastAPI app's root level (not under /dashboard/api/)
because nginx strips /api/unboks/ → backend receives /tasks. Reuses
_check_auth from dashboard.api so the existing Bearer token model applies.
"""
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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
    attachments: list = []  # list of {id, fileName, mimeType, sizeBytes, storedFilename}
    createdBy: str = "Jr"


class UpdateStatusRequest(BaseModel):
    status: str
    completedBy: str | None = None


def _format_task(task):
    """Convert state_registry's snake_case task dict to the camelCase shape
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
async def upload_attachments(files: list[UploadFile] = File(...)):
    """Upload one or more image files. Frontend sends multipart/form-data
    with field name 'files' (plural, can repeat). Returns {attachments: [...]}
    wrapping the array — matches SR's frontend at tasks-api.ts:115-119."""
    ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    attachments = []
    for f in files:
        if f.content_type not in _ALLOWED_IMAGE_MIMES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported mime type {f.content_type} for {f.filename}. "
                       f"Allowed: {sorted(_ALLOWED_IMAGE_MIMES)}",
            )
        contents = await f.read()
        if len(contents) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large for {f.filename} ({len(contents)} bytes; max {_MAX_UPLOAD_BYTES})",
            )
        ext = ext_map[f.content_type]
        stored_filename = f"{int(datetime.now(timezone.utc).timestamp())}_{secrets.token_hex(6)}.{ext}"
        path = os.path.join(_TASK_UPLOADS_DIR, stored_filename)
        with open(path, "wb") as fh:
            fh.write(contents)
        attachments.append({
            "id": secrets.token_hex(8),
            "fileName": f.filename or stored_filename,
            "mimeType": f.content_type,
            "sizeBytes": len(contents),
            "storedFilename": stored_filename,
            "url": f"/tasks/uploads/{stored_filename}",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
    return {"attachments": attachments}


@router.get("/uploads/{filename}")
async def serve_upload(filename: str):
    """Serve uploaded image files. NO auth so <img> tags render. Path
    traversal guarded by rejecting "/" and ".." in filename."""
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(_TASK_UPLOADS_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)
