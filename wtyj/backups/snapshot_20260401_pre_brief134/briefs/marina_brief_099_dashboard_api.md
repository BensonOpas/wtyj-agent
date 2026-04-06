# BRIEF 099 — Dashboard API Endpoints
**Status:** Draft | **Files:** `dashboard/__init__.py` (NEW), `dashboard/api.py` (NEW), `agents/social/webhook_server.py`, `tests/social/test_099_dashboard_api.py` (NEW) | **Depends on:** Briefs 092-098 (content pipeline) | **Blocks:** Brief 100 (React dashboard frontend)

## Context
The content pipeline works via CLI commands on the VPS. Business owners won't use a terminal. The React dashboard (Brief 100) needs a way to call our Python functions over HTTP. This brief creates URL routes on the existing FastAPI server — when the dashboard visits a URL, the server runs the corresponding Python function and returns the result as JSON. No new server or process — the routes are added to the same FastAPI app that handles WhatsApp.

## Why This Approach
Adding a router to the existing webhook_server.py is simpler than running a second server. FastAPI routers isolate the dashboard routes from WhatsApp routes — different URL paths, same process. Each endpoint is a thin wrapper (5-15 lines) calling existing functions from Briefs 092-098. Password auth via env var follows the same pattern as `WHATSAPP_VERIFY_TOKEN` and `LATE_API_KEY`. CORS middleware is one line — needed only so the React dev server (localhost) can talk to the VPS during development. CORS origins are hardcoded (localhost dev ports + production domain) — acceptable for now since the domain is stable and dev ports are standard.

**Known auth limitation:** A single static session token is generated at server start. All logins return the same token. This means: no per-session invalidation, server restart logs everyone out. Acceptable for a single-operator dashboard. Upgrade to JWT or per-session tokens when multi-user support is added.

## Source Material

### URL routes the dashboard will call

**Auth:**
```
POST /dashboard/api/login
  Body: {"password": "..."}
  Returns: {"token": "..."} or 401
```

**Overview:**
```
GET /dashboard/api/status
  Returns: {pending, approved, rejected, published, deleted, learnings, season}
```

**Drafts:**
```
GET /dashboard/api/drafts?status=pending&limit=20
  Returns: [{id, content_class, instagram_caption, facebook_caption, hashtags, status, created_at, image_path, ...}]

GET /dashboard/api/drafts/{id}
  Returns: single draft dict

POST /dashboard/api/drafts/generate
  Body: {"count": 3}
  Returns: [{generated drafts}]

POST /dashboard/api/drafts/{id}/approve
  Returns: {"ok": true}

POST /dashboard/api/drafts/{id}/reject
  Body: {"reason": "too salesy"}
  Returns: {"ok": true}

POST /dashboard/api/drafts/{id}/publish
  Returns: {"ok": true, "post_url": "https://instagram.com/p/..."}

POST /dashboard/api/drafts/{id}/graphics
  Returns: {"ok": true, "image_path": "/path/to/file.jpg"}

DELETE /dashboard/api/drafts/{id}
  Returns: {"ok": true}
```

**Drafts image serving:**
```
GET /dashboard/api/drafts/{id}/image
  Returns: JPEG file (Content-Type: image/jpeg)
```

**Learnings:**
```
GET /dashboard/api/learnings
  Returns: [{id, rule, created_at}]

POST /dashboard/api/learnings/distill
  Returns: [{new learnings}]

DELETE /dashboard/api/learnings/{id}
  Returns: {"ok": true}
```

**Data:**
```
GET /dashboard/api/availability?days=7
  Returns: [{trip_key, date, departure_time, booked_guests, capacity, spots_remaining}]

GET /dashboard/api/config
  Returns: full client.json (with internal keys filtered)
```

### Auth mechanism
- `DASHBOARD_PASSWORD` env var on VPS (same file as other secrets: `config/bluemarlin.env`)
- POST /login verifies password, returns a hex token (generated once at server start via `secrets.token_hex(32)`)
- All other endpoints check `Authorization: Bearer {token}` header
- Invalid/missing token returns 401
- Token lives in memory — server restart invalidates it (user re-logs)

### CORS
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "https://api.wetakeyourjob.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Instructions

### Step 1 — Create dashboard package

Create `dashboard/__init__.py` (empty file).

Create `dashboard/api.py`:

**File header:**
```python
# bluemarlin/dashboard/api.py
# Created: Brief 099
# Last modified: Brief 099
# Purpose: REST API endpoints for the operator dashboard.
```

**Imports:**
```python
import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel

from shared import state_registry, config_loader, bm_logger
from agents.social import content_agent, social_publisher, graphics_engine
from agents.social.content_agent import _build_seasonal_context
```

**Auth setup:**
```python
_DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
_SESSION_TOKEN = secrets.token_hex(32)


def _check_auth(authorization: str = Header(default="")):
    """Verify bearer token on all dashboard endpoints."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization[7:]
    if token != _SESSION_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
```

**Request body models:**
```python
class LoginRequest(BaseModel):
    password: str

class GenerateRequest(BaseModel):
    count: int = 3

class RejectRequest(BaseModel):
    reason: str
```

**Router:**
```python
router = APIRouter(prefix="/dashboard/api", tags=["dashboard"])
```

**Login endpoint (no auth required):**
```python
@router.post("/login")
async def login(req: LoginRequest):
    if not _DASHBOARD_PASSWORD:
        raise HTTPException(status_code=500, detail="Dashboard password not configured")
    if req.password != _DASHBOARD_PASSWORD:
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": _SESSION_TOKEN}
```

**Status endpoint:**
```python
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
```

**Draft endpoints (all require auth):**

```python
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
    # Get the draft
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
```

**Learning endpoints:**
```python
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
```

**Data endpoints:**
```python
@router.get("/availability", dependencies=[Depends(_check_auth)])
async def get_availability(days: int = 7):
    return state_registry.get_availability_summary(days_ahead=days)

@router.get("/config", dependencies=[Depends(_check_auth)])
async def get_config():
    from agents.social.content_agent import _build_client_context
    return {"context": _build_client_context()}
```

### Step 2 — Mount router on webhook_server.py

**2a.** Add CORS middleware after `app = FastAPI(...)`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "https://api.wetakeyourjob.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**2b.** Add router import and mount after the CORS middleware:

```python
from dashboard.api import router as dashboard_router
app.include_router(dashboard_router)
```

**2c.** Update webhook_server.py header to `# Last modified: Brief 099`.

### Step 3 — Create test file

Create `tests/social/test_099_dashboard_api.py`:

**Setup:** sys.path, env vars (WHATSAPP + LATE_API_KEY + DASHBOARD_PASSWORD).
```python
os.environ.setdefault("DASHBOARD_PASSWORD", "test_password_099")
```

**Imports:**
```python
from fastapi.testclient import TestClient
from agents.social.webhook_server import app
```

**Helpers:**
```python
def _cleanup_all():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM content_drafts")
    conn.execute("DELETE FROM content_learnings")
    conn.commit()
    conn.close()

def _login(client):
    resp = client.post("/dashboard/api/login", json={"password": "test_password_099"})
    return resp.json()["token"]

def _auth(token):
    return {"Authorization": f"Bearer {token}"}
```

**Tests (12 total):**

1. **`test_login_success`** — POST `/dashboard/api/login` with `{"password": "test_password_099"}`. Assert 200. Assert response has `"token"`.

2. **`test_login_wrong_password`** — POST `/dashboard/api/login` with `{"password": "wrong"}`. Assert 401.

3. **`test_status_requires_auth`** — GET `/dashboard/api/status` with no token. Assert 401.

4. **`test_status_returns_counts`** — Login, save 2 pending drafts + 1 learning. GET `/dashboard/api/status` with token. Assert response has `pending == 2` and `learnings == 1`. Assert `"season"` key exists in response and is a non-empty string (the _build_seasonal_context function from Brief 098 always returns a string with content when seasonal_calendar exists in client.json). Cleanup.

5. **`test_list_drafts`** — Login, save 3 drafts. GET `/dashboard/api/drafts`. Assert returns 3 items. Cleanup.

6. **`test_list_drafts_filter_by_status`** — Login, save 2 pending + 1 approved. GET `/dashboard/api/drafts?status=pending`. Assert returns 2. Cleanup.

7. **`test_approve_draft`** — Login, save 1 draft. POST `/dashboard/api/drafts/{id}/approve`. Assert 200. Verify draft status is "approved" in DB. Cleanup.

8. **`test_reject_draft`** — Login, save 1 draft. POST `/dashboard/api/drafts/{id}/reject` with `{"reason": "too generic"}`. Assert 200. Verify draft status is "rejected" and rejection_reason is "too generic". Cleanup.

9. **`test_generate_drafts`** — Login. Mock `content_agent.generate_drafts` to return 2 mock drafts. POST `/dashboard/api/drafts/generate` with `{"count": 2}`. Assert response has `count == 2`. Cleanup.

10. **`test_get_learnings`** — Login, save 2 learnings. GET `/dashboard/api/learnings`. Assert returns 2 items. Cleanup.

11. **`test_deactivate_learning`** — Login, save 1 learning. DELETE `/dashboard/api/learnings/{id}`. Assert 200. Assert `get_active_learnings()` returns 0. Cleanup.

12. **`test_availability`** — Login. GET `/dashboard/api/availability?days=7`. Assert returns a list. Assert list is non-empty (client.json has daily trips like Klein Curaçao and Jet Ski, so 7 days always produces results). Assert first item has keys `trip_key`, `date`, `spots_remaining`, `capacity`. Assert first item `capacity > 0`.

## Tests
Run: `cd bluemarlin && python3 -m pytest tests/social/test_099_dashboard_api.py -v`

All 12 tests must pass. Tests use FastAPI's TestClient (no real HTTP server needed). All external APIs (Claude, Late) are mocked where called.

## Success Condition
All dashboard API endpoints are accessible at `/dashboard/api/*` on the existing webhook server. Auth works (login returns token, all endpoints reject requests without token). The React dashboard (Brief 100) can call these endpoints to show and manage content.

## Rollback
1. Delete `dashboard/__init__.py` and `dashboard/api.py`
2. Revert `agents/social/webhook_server.py` to Brief 089 version
3. Delete `tests/social/test_099_dashboard_api.py`
