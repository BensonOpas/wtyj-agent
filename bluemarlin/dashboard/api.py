# bluemarlin/dashboard/api.py
# Created: Brief 099
# Last modified: Brief 102
# Purpose: REST API endpoints for the operator dashboard.

import io
import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Header, File, UploadFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image

from shared import state_registry, config_loader, bm_logger
from agents.social import content_agent, social_publisher, graphics_engine
from agents.social.content_agent import _build_seasonal_context

_SESSION_TOKEN = secrets.token_hex(32)


def _check_auth(authorization: str = Header(default="")):
    """Verify bearer token on all dashboard endpoints."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization[7:]
    if token != _SESSION_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


class LoginRequest(BaseModel):
    password: str


class GenerateRequest(BaseModel):
    count: int = 3


class RejectRequest(BaseModel):
    reason: str


class UpdateDraftRequest(BaseModel):
    instagram_caption: str = None
    facebook_caption: str = None
    hashtags: list = None


class PhotoUpdateRequest(BaseModel):
    tags: list[str] = None
    trip_key: str = None


_PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "photos")
os.makedirs(_PHOTOS_DIR, exist_ok=True)


def _process_upload(file_bytes: bytes, photo_id: int) -> tuple:
    """Process uploaded image: convert to RGB JPEG, resize if >1080px wide.
    Returns (filename, width, height, file_size_bytes)."""
    img = Image.open(io.BytesIO(file_bytes))
    img = img.convert("RGB")
    if img.width > 1080:
        ratio = 1080 / img.width
        img = img.resize((1080, int(img.height * ratio)), Image.LANCZOS)
    filename = f"photo_{photo_id}_{secrets.token_hex(4)}.jpg"
    path = os.path.join(_PHOTOS_DIR, filename)
    img.save(path, "JPEG", quality=85)
    file_size = os.path.getsize(path)
    return filename, img.width, img.height, file_size


router = APIRouter(prefix="/dashboard/api", tags=["dashboard"])


# --- Auth ---

@router.post("/login")
async def login(req: LoginRequest):
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not password:
        raise HTTPException(status_code=500, detail="Dashboard password not configured")
    if req.password != password:
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": _SESSION_TOKEN}


# --- Status ---

@router.get("/status", dependencies=[Depends(_check_auth)])
async def get_status():
    pending = len(state_registry.get_content_drafts(status="pending"))
    approved = len(state_registry.get_content_drafts(status="approved"))
    rejected = len(state_registry.get_content_drafts(status="rejected"))
    published = len(state_registry.get_content_drafts(status="published"))
    deleted = len(state_registry.get_content_drafts(status="deleted"))
    learnings = len(state_registry.get_active_learnings())
    season = _build_seasonal_context()
    return {
        "pending": pending, "approved": approved, "rejected": rejected,
        "published": published, "deleted": deleted, "learnings": learnings,
        "season": season,
    }


# --- Drafts ---

@router.get("/drafts", dependencies=[Depends(_check_auth)])
async def list_drafts(status: str = None, limit: int = 50):
    return state_registry.get_content_drafts(status=status, limit=limit)


@router.get("/drafts/{draft_id}", dependencies=[Depends(_check_auth)])
async def get_draft(draft_id: int):
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.put("/drafts/{draft_id}", dependencies=[Depends(_check_auth)])
async def update_draft(draft_id: int, req: UpdateDraftRequest):
    ok = state_registry.update_draft_content(
        draft_id,
        instagram_caption=req.instagram_caption,
        facebook_caption=req.facebook_caption,
        hashtags=req.hashtags,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Draft not found or not in pending status")
    return {"ok": True}


@router.post("/drafts/generate", dependencies=[Depends(_check_auth)])
async def generate(req: GenerateRequest):
    drafts = content_agent.generate_drafts(count=req.count)
    return {"drafts": drafts, "count": len(drafts)}


@router.post("/drafts/{draft_id}/approve", dependencies=[Depends(_check_auth)])
async def approve_draft(draft_id: int):
    ok = state_registry.update_draft_status(draft_id, "approved")
    if not ok:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True}


@router.post("/drafts/{draft_id}/reject", dependencies=[Depends(_check_auth)])
async def reject_draft(draft_id: int, req: RejectRequest):
    ok = state_registry.update_draft_status(draft_id, "rejected", rejection_reason=req.reason)
    if not ok:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True}


@router.post("/drafts/{draft_id}/publish", dependencies=[Depends(_check_auth)])
async def publish_draft(draft_id: int):
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft["status"] != "approved":
        raise HTTPException(status_code=400, detail="Draft must be approved before publishing")

    # Auto-generate graphic if missing
    image_path = draft.get("image_path", "")
    if not image_path or not os.path.exists(image_path):
        image_path = graphics_engine.generate_graphic(draft_id)
        if not image_path:
            raise HTTPException(status_code=500, detail="Could not generate graphic")

    # Get Instagram account
    account_id = social_publisher.get_instagram_account_id()
    if not account_id:
        raise HTTPException(status_code=500, detail="No Instagram account found")

    # Upload + publish
    media_url = social_publisher.upload_media(image_path)
    if not media_url:
        raise HTTPException(status_code=500, detail="Image upload failed")

    caption = draft.get("instagram_caption") or draft.get("facebook_caption") or ""
    hashtags = draft.get("hashtags") or []
    result = social_publisher.publish_to_instagram(
        caption=caption, media_url=media_url,
        account_id=account_id, hashtags=hashtags
    )
    if not result:
        raise HTTPException(status_code=500, detail="Publish failed")

    state_registry.update_draft_status(draft_id, "published")
    state_registry.set_draft_published_info(
        draft_id,
        late_post_id=result.get("post_id", ""),
        instagram_url=result.get("post_url", "")
    )
    return {"ok": True, "post_url": result.get("post_url", "")}


@router.post("/drafts/{draft_id}/graphics", dependencies=[Depends(_check_auth)])
async def generate_graphic_for_draft(draft_id: int):
    path = graphics_engine.generate_graphic(draft_id)
    if not path:
        raise HTTPException(status_code=400, detail="Could not generate graphic (no caption?)")
    return {"ok": True, "image_path": path}


@router.delete("/drafts/{draft_id}", dependencies=[Depends(_check_auth)])
async def delete_draft(draft_id: int):
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft["status"] != "published":
        raise HTTPException(status_code=400, detail="Only published drafts can be deleted from Instagram")
    late_id = draft.get("late_post_id", "")
    if not late_id:
        raise HTTPException(status_code=400, detail="No Late post ID — cannot delete")
    if not social_publisher.delete_post(late_id):
        raise HTTPException(status_code=500, detail="Delete failed")
    state_registry.update_draft_status(draft_id, "deleted")
    return {"ok": True}


@router.get("/drafts/{draft_id}/image", dependencies=[Depends(_check_auth)])
async def get_draft_image(draft_id: int):
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    image_path = draft.get("image_path", "")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="No image")
    return FileResponse(image_path, media_type="image/jpeg")


# --- Learnings ---

@router.get("/learnings", dependencies=[Depends(_check_auth)])
async def list_learnings():
    return state_registry.get_active_learnings()


@router.post("/learnings/distill", dependencies=[Depends(_check_auth)])
async def distill():
    learnings = content_agent.distill_learnings()
    return {"learnings": learnings, "count": len(learnings)}


@router.delete("/learnings/{learning_id}", dependencies=[Depends(_check_auth)])
async def deactivate_learning(learning_id: int):
    ok = state_registry.deactivate_learning(learning_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Learning not found or already inactive")
    return {"ok": True}


# --- Data ---

@router.get("/availability", dependencies=[Depends(_check_auth)])
async def get_availability(days: int = 7):
    return state_registry.get_availability_summary(days_ahead=days)


@router.get("/config", dependencies=[Depends(_check_auth)])
async def get_config():
    from agents.social.content_agent import _build_client_context
    return {"context": _build_client_context()}


# --- Photos ---

@router.post("/photos/upload", dependencies=[Depends(_check_auth)])
async def upload_photo(file: UploadFile = File(...), tags: str = Form(""), trip_key: str = Form("")):
    file_bytes = await file.read()
    try:
        Image.open(io.BytesIO(file_bytes))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")
    parsed_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    # Process image first with temp id
    filename, width, height, file_size = _process_upload(file_bytes, 0)
    # Save record
    photo_id = state_registry.save_photo(
        filename=filename, original_filename=file.filename or "unknown.jpg",
        tags=parsed_tags, trip_key=trip_key, source="upload",
        width=width, height=height, file_size=file_size,
    )
    # Rename file with real id
    new_filename = f"photo_{photo_id}_{secrets.token_hex(4)}.jpg"
    os.rename(
        os.path.join(_PHOTOS_DIR, filename),
        os.path.join(_PHOTOS_DIR, new_filename),
    )
    state_registry.update_photo_filename(photo_id, new_filename)
    photo = state_registry.get_photo_by_id(photo_id)
    return {"ok": True, "photo": photo}


@router.get("/photos", dependencies=[Depends(_check_auth)])
async def list_photos(trip_key: str = None, limit: int = 50):
    return state_registry.get_photos(trip_key=trip_key, limit=limit)


@router.get("/photos/stats", dependencies=[Depends(_check_auth)])
async def photo_stats():
    return state_registry.get_photo_stats()


@router.get("/photos/{photo_id}/image", dependencies=[Depends(_check_auth)])
async def get_photo_image(photo_id: int):
    photo = state_registry.get_photo_by_id(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = os.path.join(_PHOTOS_DIR, photo["filename"])
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Image file missing")
    return FileResponse(path, media_type="image/jpeg")


@router.put("/photos/{photo_id}", dependencies=[Depends(_check_auth)])
async def update_photo_endpoint(photo_id: int, req: PhotoUpdateRequest):
    ok = state_registry.update_photo(photo_id, tags=req.tags, trip_key=req.trip_key)
    if not ok:
        raise HTTPException(status_code=404, detail="Photo not found")
    return {"ok": True}


@router.delete("/photos/{photo_id}", dependencies=[Depends(_check_auth)])
async def delete_photo_endpoint(photo_id: int):
    filename = state_registry.delete_photo(photo_id)
    if not filename:
        raise HTTPException(status_code=404, detail="Photo not found")
    try:
        os.remove(os.path.join(_PHOTOS_DIR, filename))
    except FileNotFoundError:
        pass
    return {"ok": True}
