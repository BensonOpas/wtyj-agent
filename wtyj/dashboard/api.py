# bluemarlin/dashboard/api.py
# Created: Brief 099
# Last modified: Brief 102
# Purpose: REST API endpoints for the operator dashboard.

import io
import json
import os
import re
import secrets
import urllib.parse
import anthropic
import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Header, File, UploadFile, Form, Query
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from PIL import Image

from shared import state_registry, config_loader, bm_logger
from agents.social import content_agent, social_publisher, graphics_engine
from agents.social.whatsapp_client import send_whatsapp_message
from agents.marina import marina_agent
from agents.social.content_agent import _build_seasonal_context

_GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
_GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
_GOOGLE_REDIRECT_URI = "https://api.wetakeyourjob.com/dashboard/api/google/callback"
_GOOGLE_SCOPES = "https://www.googleapis.com/auth/drive.readonly"

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
    service_key: str = None


class ComposeRequest(BaseModel):
    mode: str  # "photo_text", "photo_only", "ai_generate", "text_card"
    photo_id: int = 0


class BrandRuleRequest(BaseModel):
    category: str
    rule: str


class BrandRuleUpdateRequest(BaseModel):
    rule: str = None
    category: str = None


_PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "photos")
os.makedirs(_PHOTOS_DIR, exist_ok=True)
_TRAINING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "training")
os.makedirs(_TRAINING_DIR, exist_ok=True)


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
    # Auto-compose image on approval
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if draft:
        prompt = draft.get("visual_suggestion") or draft.get("instagram_caption") or ""
        if prompt:
            ai_path = _generate_ai_image(prompt, draft_id)
            if ai_path:
                graphics_engine.generate_composite(draft_id, photo_path=ai_path, mode="photo_only")
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
    if draft["status"] not in ("approved", "scheduled"):
        raise HTTPException(status_code=400, detail="Draft must be approved or scheduled before publishing")
    from agents.social.scheduler import execute_publish
    result = execute_publish(draft)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Publish failed"))
    return result


@router.post("/drafts/{draft_id}/graphics", dependencies=[Depends(_check_auth)])
async def generate_graphic_for_draft(draft_id: int):
    path = graphics_engine.generate_graphic(draft_id)
    if not path:
        raise HTTPException(status_code=400, detail="Could not generate graphic (no caption?)")
    return {"ok": True, "image_path": path}


@router.post("/drafts/{draft_id}/compose", dependencies=[Depends(_check_auth)])
async def compose_draft(draft_id: int, req: ComposeRequest):
    """Create the visual for a draft. Modes: photo_text, photo_only, ai_generate, text_card."""
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    ai_generated = False
    photo_path = ""

    if req.mode in ("photo_text", "photo_only"):
        if not req.photo_id:
            raise HTTPException(status_code=400, detail="photo_id required for photo modes")
        photo = state_registry.get_photo_by_id(req.photo_id)
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")
        photo_path = os.path.join(_PHOTOS_DIR, photo["filename"])
        state_registry.set_draft_photo_id(draft_id, req.photo_id)
        state_registry.increment_photo_used_count(req.photo_id)

    elif req.mode == "ai_generate":
        prompt = draft.get("visual_suggestion") or draft.get("instagram_caption") or ""
        if not prompt:
            raise HTTPException(status_code=400, detail="No visual suggestion or caption to generate from")
        photo_path = _generate_ai_image(prompt, draft_id)
        if not photo_path:
            raise HTTPException(status_code=500, detail="AI image generation failed — check API key configuration")
        ai_generated = True

    # Generate the composed image
    path = graphics_engine.generate_composite(draft_id, photo_path=photo_path, mode=req.mode if req.mode != "ai_generate" else "photo_text")
    if not path:
        raise HTTPException(status_code=500, detail="Image composition failed")

    return {"ok": True, "image_path": path, "ai_generated": ai_generated}


def _generate_ai_image(prompt: str, draft_id: int) -> str:
    """Generate an image using OpenAI GPT Image 1.5 API. Returns file path or empty string."""
    import base64 as _b64
    api_key = os.environ.get("OPENAI_API", "")
    if not api_key:
        bm_logger.log("ai_image_no_api_key")
        return ""
    try:
        # Inject visual style rules into the prompt
        visual_rules = state_registry.get_brand_rules(category="visual_rules")
        if visual_rules:
            style_desc = ". ".join(r["rule"] for r in visual_rules)
            prompt = f"Visual style: {style_desc}. Scene: {prompt}"

        resp = http_requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-image-1",
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",
                "quality": "medium",
            },
        )
        if resp.status_code != 200:
            bm_logger.log("ai_image_api_error", status=resp.status_code, body=resp.text[:200])
            return ""
        data = resp.json()
        b64_data = data.get("data", [{}])[0].get("b64_json", "")
        if not b64_data:
            # Try URL format
            image_url = data.get("data", [{}])[0].get("url", "")
            if image_url:
                img_resp = http_requests.get(image_url)
                if img_resp.status_code != 200:
                    return ""
                img_bytes = img_resp.content
            else:
                return ""
        else:
            img_bytes = _b64.b64decode(b64_data)
        path = os.path.join(_PHOTOS_DIR, f"ai_draft_{draft_id}.jpg")
        # Convert to JPEG via Pillow (API may return PNG)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.save(path, "JPEG", quality=90)
        bm_logger.log("ai_image_generated", draft_id=draft_id, path=path)
        return path
    except Exception as exc:
        bm_logger.log("ai_image_generation_failed", error=str(exc)[:200])
        return ""


def _match_photo_to_draft(draft: dict):
    """Find the best matching photo from the library for a draft. Returns photo dict or None."""
    caption = (draft.get("instagram_caption") or "").lower()
    trips = config_loader.get_services()
    # Try to match by service name in caption
    for service_key, trip_data in trips.items():
        display = trip_data.get("display_name", "").lower()
        if display and display in caption:
            photos = state_registry.get_photos(service_key=service_key, limit=50)
            if photos:
                photos.sort(key=lambda p: p["used_count"])
                return photos[0]
        if service_key.replace("_", " ") in caption:
            photos = state_registry.get_photos(service_key=service_key, limit=50)
            if photos:
                photos.sort(key=lambda p: p["used_count"])
                return photos[0]
    # No service match — pick any photo, least used
    all_photos = state_registry.get_photos(limit=50)
    if all_photos:
        all_photos.sort(key=lambda p: p["used_count"])
        return all_photos[0]
    return None


@router.delete("/drafts/{draft_id}", dependencies=[Depends(_check_auth)])
async def delete_draft(draft_id: int):
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft["status"] != "published":
        raise HTTPException(status_code=400, detail="Only published drafts can be deleted from Instagram")
    late_id = draft.get("late_post_id", "")
    ig_deleted = False
    if late_id:
        ig_deleted = social_publisher.delete_post(late_id)
    state_registry.update_draft_status(draft_id, "deleted")
    return {"ok": True, "instagram_deleted": ig_deleted}


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
async def upload_photo(file: UploadFile = File(...), tags: str = Form(""), service_key: str = Form("")):
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
        tags=parsed_tags, service_key=service_key, source="upload",
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
async def list_photos(service_key: str = None, limit: int = 50):
    return state_registry.get_photos(service_key=service_key, limit=limit)


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
    ok = state_registry.update_photo(photo_id, tags=req.tags, service_key=req.service_key)
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


# --- Google Drive OAuth ---


@router.get("/google/auth")
async def google_auth(redirect_to: str = Query("")):
    """Redirect operator to Google's OAuth consent screen."""
    if not _GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    params = {
        "client_id": _GOOGLE_CLIENT_ID,
        "redirect_uri": _GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": _GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": redirect_to or "",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(code: str = Query(""), error: str = Query(""), state: str = Query("")):
    """Google redirects here after consent. Exchange code for tokens."""
    if error:
        if state:
            return RedirectResponse(f"{state}?google_error={error}")
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code")
    # Exchange code for tokens
    resp = http_requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": _GOOGLE_CLIENT_ID,
        "client_secret": _GOOGLE_CLIENT_SECRET,
        "redirect_uri": _GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Token exchange failed")
    data = resp.json()
    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 3600)
    from datetime import datetime, timezone, timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    state_registry.save_oauth_tokens("google_drive", access_token, refresh_token, expires_at)
    # Redirect back to dashboard
    redirect = state or "/"
    sep = "&" if "?" in redirect else "?"
    return RedirectResponse(f"{redirect}{sep}google_connected=true")


def _get_google_access_token() -> str:
    """Get a valid Google access token, refreshing if expired."""
    tokens = state_registry.get_oauth_tokens("google_drive")
    if not tokens:
        return ""
    # Check if expired
    from datetime import datetime, timezone
    expires_at = tokens.get("expires_at", "")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) >= exp:
                # Refresh
                resp = http_requests.post("https://oauth2.googleapis.com/token", data={
                    "client_id": _GOOGLE_CLIENT_ID,
                    "client_secret": _GOOGLE_CLIENT_SECRET,
                    "refresh_token": tokens["refresh_token"],
                    "grant_type": "refresh_token",
                })
                if resp.status_code == 200:
                    data = resp.json()
                    new_token = data.get("access_token", "")
                    expires_in = data.get("expires_in", 3600)
                    from datetime import timedelta
                    new_expires = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
                    state_registry.save_oauth_tokens(
                        "google_drive", new_token,
                        tokens["refresh_token"], new_expires
                    )
                    return new_token
                return ""
        except (ValueError, TypeError):
            pass
    return tokens["access_token"]


@router.get("/google/status", dependencies=[Depends(_check_auth)])
async def google_status():
    """Check if Google Drive is connected."""
    tokens = state_registry.get_oauth_tokens("google_drive")
    if not tokens:
        return {"connected": False}
    return {
        "connected": True,
        "folder_id": tokens.get("folder_id", ""),
        "updated_at": tokens.get("updated_at", ""),
    }


@router.post("/google/disconnect", dependencies=[Depends(_check_auth)])
async def google_disconnect():
    """Remove Google Drive connection."""
    state_registry.delete_oauth_tokens("google_drive")
    return {"ok": True}


@router.get("/google/folders", dependencies=[Depends(_check_auth)])
async def google_folders():
    """List top-level folders in the operator's Google Drive."""
    token = _get_google_access_token()
    if not token:
        raise HTTPException(status_code=400, detail="Google Drive not connected")
    resp = http_requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "q": "mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false",
            "fields": "files(id,name)",
            "pageSize": "100",
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to list Drive folders")
    return resp.json().get("files", [])


class FolderSelectRequest(BaseModel):
    folder_id: str


@router.post("/google/folder", dependencies=[Depends(_check_auth)])
async def set_google_folder(req: FolderSelectRequest):
    """Set which Drive folder to sync from."""
    ok = state_registry.set_oauth_folder("google_drive", req.folder_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Google Drive not connected")
    return {"ok": True}


@router.post("/google/sync", dependencies=[Depends(_check_auth)])
async def google_sync():
    """Sync photos from the selected Google Drive folder."""
    tokens = state_registry.get_oauth_tokens("google_drive")
    if not tokens or not tokens.get("folder_id"):
        raise HTTPException(status_code=400, detail="No Drive folder selected")
    token = _get_google_access_token()
    if not token:
        raise HTTPException(status_code=400, detail="Google Drive not connected")
    folder_id = tokens["folder_id"]
    # List image files in folder
    resp = http_requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "q": f"'{folder_id}' in parents and mimeType contains 'image/' and trashed=false",
            "fields": "files(id,name,size)",
            "pageSize": "100",
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to list Drive files")
    files = resp.json().get("files", [])
    synced = 0
    for f in files:
        drive_id = f["id"]
        # Skip if already synced
        if state_registry.get_photo_by_source_id(drive_id):
            continue
        # Download file
        dl_resp = http_requests.get(
            f"https://www.googleapis.com/drive/v3/files/{drive_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"alt": "media"},
        )
        if dl_resp.status_code != 200:
            continue
        file_bytes = dl_resp.content
        try:
            Image.open(io.BytesIO(file_bytes))
        except Exception:
            continue
        # Process and store
        filename, width, height, file_size = _process_upload(file_bytes, 0)
        photo_id = state_registry.save_photo(
            filename=filename, original_filename=f.get("name", "drive_photo.jpg"),
            tags=[], service_key="", source="google_drive", source_id=drive_id,
            width=width, height=height, file_size=file_size,
        )
        new_filename = f"photo_{photo_id}_{secrets.token_hex(4)}.jpg"
        os.rename(
            os.path.join(_PHOTOS_DIR, filename),
            os.path.join(_PHOTOS_DIR, new_filename),
        )
        state_registry.update_photo_filename(photo_id, new_filename)
        synced += 1
    return {"ok": True, "synced": synced, "total_in_folder": len(files)}


# --- Dry Run ---

@router.get("/settings/dry-run", dependencies=[Depends(_check_auth)])
async def get_dry_run():
    return {"dry_run": state_registry.is_dry_run()}


@router.post("/settings/dry-run", dependencies=[Depends(_check_auth)])
async def toggle_dry_run():
    current = state_registry.is_dry_run()
    state_registry.set_setting("dry_run", "false" if current else "true")
    return {"dry_run": not current}


# --- Scheduling ---

class ScheduleRequest(BaseModel):
    scheduled_at: str = ""  # ISO 8601, empty = auto-assign next slot


class ScheduleSlotsRequest(BaseModel):
    slots: list  # [{"day_of_week": "Tuesday", "time_utc": "16:00"}, ...]


@router.post("/drafts/{draft_id}/schedule", dependencies=[Depends(_check_auth)])
async def schedule_draft(draft_id: int, req: ScheduleRequest):
    scheduled_at = req.scheduled_at
    if not scheduled_at:
        scheduled_at = state_registry.get_next_open_slot()
        if not scheduled_at:
            raise HTTPException(status_code=400, detail="No open schedule slots. Set a time manually or configure weekly slots.")
    ok = state_registry.schedule_draft(draft_id, scheduled_at)
    if not ok:
        raise HTTPException(status_code=400, detail="Draft not found or not in approved status")
    return {"ok": True, "scheduled_at": scheduled_at}


@router.post("/drafts/{draft_id}/unschedule", dependencies=[Depends(_check_auth)])
async def unschedule_draft(draft_id: int):
    ok = state_registry.unschedule_draft(draft_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Draft not found or not in scheduled status")
    return {"ok": True}


@router.get("/schedule/slots", dependencies=[Depends(_check_auth)])
async def get_schedule_slots():
    return state_registry.get_schedule_slots()


@router.put("/schedule/slots", dependencies=[Depends(_check_auth)])
async def update_schedule_slots(req: ScheduleSlotsRequest):
    state_registry.save_schedule_slots(req.slots)
    return {"ok": True, "slots": state_registry.get_schedule_slots()}


@router.get("/schedule/upcoming", dependencies=[Depends(_check_auth)])
async def get_upcoming_schedule():
    scheduled = state_registry.get_content_drafts(status="scheduled")
    return scheduled


# --- Platforms ---

class PlatformsRequest(BaseModel):
    platforms: list[str]


@router.get("/platforms/available", dependencies=[Depends(_check_auth)])
async def get_available_platforms():
    platforms = social_publisher.get_available_platforms()
    return {"platforms": platforms}


@router.put("/drafts/{draft_id}/platforms", dependencies=[Depends(_check_auth)])
async def update_draft_platforms(draft_id: int, req: PlatformsRequest):
    available = set(social_publisher.get_available_platforms()) or {"instagram", "facebook"}
    filtered = [p for p in req.platforms if p in available]
    ok = state_registry.update_draft_platforms(draft_id, filtered)
    if not ok:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True, "platforms": filtered}


# --- Brand Training ---

@router.post("/training/examples", dependencies=[Depends(_check_auth)])
async def upload_training_example(caption_text: str = Form(""), platform: str = Form(""),
                                   file: UploadFile = File(None)):
    """Upload a training example (caption + optional image)."""
    if not caption_text.strip():
        raise HTTPException(status_code=400, detail="Caption text is required")
    image_path = ""
    if file:
        file_bytes = await file.read()
        try:
            img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            if img.width > 1080:
                ratio = 1080 / img.width
                img = img.resize((1080, int(img.height * ratio)), Image.LANCZOS)
            fname = f"training_{secrets.token_hex(6)}.jpg"
            path = os.path.join(_TRAINING_DIR, fname)
            img.save(path, "JPEG", quality=85)
            image_path = path
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid image file")
    example_id = state_registry.save_training_example(
        caption_text=caption_text.strip(), image_path=image_path, platform=platform
    )
    return {"ok": True, "id": example_id}


@router.get("/training/examples", dependencies=[Depends(_check_auth)])
async def list_training_examples():
    return state_registry.get_training_examples()


@router.delete("/training/examples/{example_id}", dependencies=[Depends(_check_auth)])
async def delete_training_example(example_id: int):
    image_path = state_registry.delete_training_example(example_id)
    if image_path:
        try:
            os.remove(image_path)
        except FileNotFoundError:
            pass
    return {"ok": True}


@router.get("/training/examples/{example_id}/image", dependencies=[Depends(_check_auth)])
async def get_training_image(example_id: int):
    examples = state_registry.get_training_examples()
    ex = next((e for e in examples if e["id"] == example_id), None)
    if not ex or not ex.get("image_path") or not os.path.exists(ex["image_path"]):
        raise HTTPException(status_code=404, detail="No image")
    return FileResponse(ex["image_path"], media_type="image/jpeg")


@router.post("/training/analyze", dependencies=[Depends(_check_auth)])
async def analyze_training():
    """Analyze all training examples and extract brand profile rules."""
    from agents.social.content_agent import analyze_training_examples
    result = analyze_training_examples()
    if not result:
        raise HTTPException(status_code=400, detail="No examples to analyze or analysis failed")
    # Return the full updated profile
    all_rules = state_registry.get_brand_rules()
    grouped = {}
    for r in all_rules:
        grouped.setdefault(r["category"], []).append(r)
    return {"ok": True, "rules": grouped, "categories_analyzed": len(result)}


@router.post("/training/analyze-visual", dependencies=[Depends(_check_auth)])
async def analyze_visual():
    """Analyze Drive photos with Claude Vision to extract visual style rules."""
    from agents.social.content_agent import analyze_visual_style
    rules = analyze_visual_style()
    if not rules:
        raise HTTPException(status_code=400, detail="No photos to analyze or analysis failed")
    return {"ok": True, "visual_rules": rules, "count": len(rules)}


# --- Brand Profile ---

@router.get("/training/profile", dependencies=[Depends(_check_auth)])
async def get_brand_profile():
    rules = state_registry.get_brand_rules()
    grouped = {}
    for r in rules:
        grouped.setdefault(r["category"], []).append(r)
    return grouped


@router.post("/training/profile", dependencies=[Depends(_check_auth)])
async def add_brand_rule(req: BrandRuleRequest):
    if req.category not in ("voice_rules", "visual_rules", "content_rules", "boundaries"):
        raise HTTPException(status_code=400, detail="Invalid category")
    rule_id = state_registry.save_brand_rule(category=req.category, rule=req.rule, source="manual")
    return {"ok": True, "id": rule_id}


@router.put("/training/profile/{rule_id}", dependencies=[Depends(_check_auth)])
async def update_brand_rule_endpoint(rule_id: int, req: BrandRuleUpdateRequest):
    ok = state_registry.update_brand_rule(rule_id, rule=req.rule, category=req.category)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}


@router.delete("/training/profile/{rule_id}", dependencies=[Depends(_check_auth)])
async def delete_brand_rule_endpoint(rule_id: int):
    ok = state_registry.delete_brand_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found or already inactive")
    return {"ok": True}


# ── Messages (WhatsApp conversations) ────────────────────────────────────────

@router.get("/messages/conversations", dependencies=[Depends(_check_auth)])
async def list_conversations():
    """Brief 171: List WhatsApp + email conversations merged, sorted newest first.
    Email conversation rows have phone prefixed with `email::` so the detail
    endpoint can route to the email helper."""
    wa_convos = state_registry.wa_list_conversations()
    # WhatsApp rows get a channel tag if missing (some rows come from dm_messages
    # via dm_store_message which already sets it; legacy rows default to 'whatsapp').
    for c in wa_convos:
        c.setdefault("channel", "whatsapp")
    email_convos = state_registry.email_list_conversations()
    merged = wa_convos + email_convos
    merged.sort(key=lambda r: r.get("last_message_at") or "", reverse=True)
    return merged


@router.get("/messages/conversations/{phone:path}", dependencies=[Depends(_check_auth)])
async def get_conversation(phone: str):
    """Get full conversation thread + booking state. Brief 171: routes to the
    email helper when phone starts with 'email::'. Brief 201: each message dict
    is enriched with `content` (alias of text) and `timestamp` (alias of
    created_at) so SR's dashboard frontend can read them directly. Original
    `text`/`created_at` keys preserved for backward compat."""
    if phone.startswith("email::"):
        thread_key = phone[len("email::"):]
        return state_registry.email_get_conversation(thread_key)
    messages = state_registry.wa_get_full_history(phone, limit=200)
    # Brief 201: add frontend-friendly field aliases without removing originals.
    for m in messages:
        m["content"] = m.get("text", "")
        m["timestamp"] = m.get("created_at", "")
    booking_state = state_registry.wa_get_booking_state(phone)
    return {
        "phone": phone,
        "messages": messages,
        "booking_state": booking_state,
    }


@router.delete("/messages/conversations/{phone}", dependencies=[Depends(_check_auth)])
async def delete_conversation(phone: str):
    """Brief 165: hard-delete a conversation (all messages + booking state rows).
    Destructive — no audit trail. Used by the trash button on the Messages page
    to remove test pollution and unwanted threads."""
    count = state_registry.wa_delete_conversation(phone)
    return {"ok": True, "deleted_rows": count, "phone": phone}


# ── Customers (Brief 166/167) ────────────────────────────────────────────────

@router.get("/customers/by-identifier/{type_}/{value}", dependencies=[Depends(_check_auth)])
async def get_customer_by_identifier(type_: str, value: str):
    """Brief 167: resolve a customer by identifier. Returns the full customer file
    (display_name, all identifiers grouped by type, recent interactions) or null.
    Used by the dashboard to translate Zernio conversation_ids into real phone
    numbers / display names when available."""
    cust = state_registry.customer_lookup(type_, value)
    if not cust:
        return None
    return state_registry.customer_get_full(cust["id"])


# ── Escalations ──────────────────────────────────────────────────────────────

@router.get("/escalations", dependencies=[Depends(_check_auth)])
async def list_escalations():
    """List all escalation notifications."""
    return state_registry.get_all_escalations()


@router.get("/escalations/{escalation_id}", dependencies=[Depends(_check_auth)])
async def get_escalation(escalation_id: int):
    """Get a single escalation by ID."""
    all_esc = state_registry.get_all_escalations()
    esc = next((e for e in all_esc if e["id"] == escalation_id), None)
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return esc


@router.post("/escalations/{escalation_id}/resolve", dependencies=[Depends(_check_auth)])
async def resolve_escalation(escalation_id: int):
    """Mark an escalation as resolved and return conversation to AI."""
    ok = state_registry.update_notification_status(escalation_id, "resolved")
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found")
    # Brief 188: clear fully_escalated + set conversation status to resolved
    state_registry.resolve_conversation_from_escalation(escalation_id)
    return {"ok": True}


@router.delete("/escalations/{escalation_id}", dependencies=[Depends(_check_auth)])
async def delete_escalation_endpoint(escalation_id: int):
    """Brief 172: hard-delete an escalation. SR built an archive-first UX
    (localStorage hide, then trash button visible only in archive view).
    This endpoint handles the actual permanent delete."""
    ok = state_registry.delete_escalation(escalation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return {"ok": True, "id": escalation_id}


# ── Manual Draft Creation ────────────────────────────────────────────────────

class ManualDraftRequest(BaseModel):
    instagram_caption: str
    facebook_caption: str = ""
    hashtags: list = []
    content_class: str = "D"
    visual_suggestion: str = ""
    platforms: list = []

@router.post("/drafts/manual", dependencies=[Depends(_check_auth)])
async def create_manual_draft(req: ManualDraftRequest):
    """Create a manually-written draft. Status = approved (human authored)."""
    fb_caption = req.facebook_caption or req.instagram_caption
    draft_id = state_registry.save_content_draft(
        content_class=req.content_class,
        instagram_caption=req.instagram_caption,
        facebook_caption=fb_caption,
        hashtags=req.hashtags,
        visual_suggestion=req.visual_suggestion,
        reasoning="Manually created by operator",
    )
    # Set status to approved
    state_registry.update_draft_status(draft_id, "approved")
    # Set platforms (from request or config default)
    plats = req.platforms or config_loader.get_raw().get("social_content", {}).get("platforms", ["instagram"])
    state_registry.update_draft_platforms(draft_id, plats)
    # Auto-generate image (same as approve flow)
    try:
        prompt = req.visual_suggestion or req.instagram_caption[:200]
        ai_path = _generate_ai_image(prompt, draft_id)
        if ai_path:
            from agents.social import graphics_engine
            image_path = graphics_engine.generate_composite(draft_id, photo_path=ai_path, mode="photo_only")
            if image_path:
                state_registry.update_draft_image(draft_id, image_path)
    except Exception:
        pass  # Image gen failure shouldn't block draft creation
    return {"ok": True, "id": draft_id}


# ── Suggest Reply ────────────────────────────────────────────────────────────

class SuggestReplyRequest(BaseModel):
    phone: str
    draft_text: str = ""

@router.post("/messages/suggest-reply", dependencies=[Depends(_check_auth)])
async def suggest_reply(req: SuggestReplyRequest):
    """Generate an AI-suggested email reply based on WhatsApp conversation."""
    if not req.phone:
        raise HTTPException(status_code=400, detail="Phone number required")

    messages = state_registry.wa_get_full_history(req.phone, limit=30)
    if not messages:
        raise HTTPException(status_code=404, detail="No conversation found")

    booking_state = state_registry.wa_get_booking_state(req.phone)
    business = config_loader.get_business()
    trips = config_loader.get_services()
    signature = config_loader.get_agent_signature()

    # Format conversation
    thread_lines = []
    for msg in messages:
        label = "Customer" if msg["role"] == "user" else config_loader.get_business().get("agent_name", "CSA")
        thread_lines.append(f"{label}: {msg['text']}")
    thread_text = "\n\n".join(thread_lines)

    # Format booking context
    fields = booking_state.get("fields", {})
    completed = booking_state.get("completed_bookings", [])
    booking_parts = []
    if fields:
        booking_parts.append("Current booking fields: " + json.dumps(fields, default=str))
    if completed:
        booking_parts.append("Completed bookings: " + json.dumps(completed, default=str))
    booking_context = "\n".join(booking_parts)

    # Format trips
    trip_lines = []
    for key, data in trips.items():
        name = data.get("display_name", key)
        price = data.get("price_pp", "")
        trip_lines.append(f"- {name}: ${price}/person" if price else f"- {name}")

    agent_name = business.get("agent_name", "CSA")
    company_name = business.get("name", "the business")
    persona_block = marina_agent._build_agent_persona_block()

    system_prompt = f"""You are {agent_name}, the booking agent for {company_name}.

AGENT PERSONA:
{persona_block}

WRITING STYLE FOR EMAIL:
Write as a real member of the {company_name} team. Warm, practical, human.
Mirror the customer's tone. Use contractions. Plain language.
No em dashes, no forced enthusiasm, no "I'd be happy to" or "Great choice".
Emails are slightly longer and more structured than WhatsApp but still conversational.

AVAILABLE TRIPS:
{chr(10).join(trip_lines)}

AGENT SIGNATURE:
{signature}

Return a JSON object with exactly two keys:
- "subject": a short email subject line (no "Re:" prefix)
- "body": the full email body including signature at the end

Return ONLY the JSON object. No markdown fences, no extra text."""

    if req.draft_text:
        user_prompt = f"""WHATSAPP CONVERSATION:
{thread_text}

{booking_context}

The operator wrote this draft reply:
---
{req.draft_text}
---

Rewrite this draft as a polished, professional email from {agent_name}. Keep the operator's intent and key points. Improve tone, clarity, and structure. Include the agent signature."""
    else:
        user_prompt = f"""WHATSAPP CONVERSATION:
{thread_text}

{booking_context}

Write an email reply from {agent_name} to this customer. Address open questions, confirm bookings, or provide next steps as appropriate."""

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())
        result = json.loads(raw)
        return {
            "subject": result.get("subject", ""),
            "body": result.get("body", ""),
        }
    except json.JSONDecodeError:
        return {
            "subject": f"{company_name} — Follow-up",
            "body": raw if raw else "Could not generate suggestion.",
        }
    except Exception as exc:
        bm_logger.log("suggest_reply_error", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to generate suggestion")


# ── Escalation Reply ─────────────────────────────────────────────────────────

class EscalationReplyRequest(BaseModel):
    answer: str

@router.post("/escalations/{escalation_id}/reply", dependencies=[Depends(_check_auth)])
async def reply_to_escalation(escalation_id: int, req: EscalationReplyRequest):
    """Reply to a semi escalation. Marina reformulates and sends to customer."""
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Answer text required")

    all_esc = state_registry.get_all_escalations()
    esc = next((e for e in all_esc if e["id"] == escalation_id), None)
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")

    channel = esc.get("channel", "whatsapp")
    customer_id = esc.get("customer_id", "")

    if channel == "whatsapp" and customer_id:
        wa_state = state_registry.wa_get_booking_state(customer_id)
        wa_fields = wa_state.get("fields", {})
        wa_flags = wa_state.get("flags", {})
        wa_history = state_registry.wa_get_history(customer_id, limit=10)

        agent_flags = dict(wa_flags)
        # Brief 159: keep awaiting_relay so Marina enters RELAY MODE and
        # reformulates the operator's answer instead of generating a fresh reply.
        # Mirrors email_poller.py:661-663 which does the same.
        for rk in ("relay_token", "reply_times"):
            agent_flags.pop(rk, None)

        relay_result = marina_agent.process_message(
            customer_id, "", req.answer.strip(),
            wa_fields, agent_flags,
            channel="whatsapp", messages=wa_history,
        )
        relay_reply = relay_result.get("reply", "")

        if not relay_reply:
            raise HTTPException(status_code=500, detail="Marina returned empty reply")
        sent_ok = send_whatsapp_message(customer_id, relay_reply)
        if not sent_ok:
            raise HTTPException(status_code=500, detail="Failed to send WhatsApp reply (Zernio account missing or send failed)")
        state_registry.wa_store_message(customer_id, "assistant", relay_reply)
        bm_logger.log("dashboard_relay_sent", phone=customer_id, escalation_id=escalation_id)

        wa_flags.pop("awaiting_relay", None)
        wa_flags.pop("relay_token", None)
        wa_flags.pop("relay_question", None)
        state_registry.wa_save_booking_state(
            customer_id, wa_fields, wa_flags,
            wa_state.get("completed_bookings", []))

        state_registry.update_notification_status(escalation_id, "replied")

        return {"ok": True, "reply": relay_reply}
    else:
        raise HTTPException(status_code=400, detail=f"Channel '{channel}' reply not supported from dashboard")
