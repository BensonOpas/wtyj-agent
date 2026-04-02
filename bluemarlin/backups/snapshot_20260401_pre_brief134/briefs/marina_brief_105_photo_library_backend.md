# BRIEF 105 — Photo Library Backend
**Status:** Draft | **Depends on:** None | **Blocks:** Brief 106 (Drive sync), Brief 107 (frontend)

**Files:**
- `bluemarlin/shared/state_registry.py` (new table + functions)
- `bluemarlin/dashboard/api.py` (new endpoints)
- `bluemarlin/tests/social/test_105_photo_library.py`

## Context
The content pipeline currently generates branded text cards as placeholder images. Business owners have real photos (boats, sunsets, experiences) that would dramatically improve post quality. Before we can integrate Google Drive or any other source, we need the underlying photo library — a place to store, tag, serve, and manage photos.

This brief builds the storage layer and API. Brief 106 adds Google Drive ingestion. Brief 107 adds the frontend UI.

## Why This Approach
Photo library is the foundation — every ingestion method (dashboard upload, Google Drive sync, future Dropbox/OneDrive) feeds into the same table and file storage. Building this first means Brief 106 and 107 just add ingestion and UI on top of a working backend.

Considered using cloud storage (S3, Cloudinary) — rejected because VPS filesystem is simpler, free, and sufficient for MVP. Photos are resized on ingest so storage stays lean. Can migrate to cloud storage later without changing the API surface.

Manual tags only (mapped to trip keys from client.json). No AI auto-categorization yet — that's a future feature.

## Source Material

### Database table: `photo_library`
```sql
CREATE TABLE IF NOT EXISTS photo_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    tags_json TEXT DEFAULT '[]',
    trip_key TEXT DEFAULT '',
    source TEXT DEFAULT 'upload',
    source_id TEXT DEFAULT '',
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    file_size INTEGER DEFAULT 0,
    used_count INTEGER DEFAULT 0,
    uploaded_at TEXT NOT NULL
)
```

- `filename`: stored filename on disk (e.g., `photo_17_abc123.jpg`)
- `original_filename`: what the operator uploaded (e.g., `sunset_klein_curacao.jpg`)
- `tags_json`: JSON array of string tags (e.g., `["sunset", "klein_curacao", "boat"]`)
- `trip_key`: maps to a trip in client.json (e.g., `klein_curacao`). Empty = general/untagged.
- `source`: `"upload"` or `"google_drive"` (for Brief 106)
- `source_id`: external ID for dedup (e.g., Google Drive file ID). Empty for uploads.
- `width`, `height`: pixel dimensions after resize
- `file_size`: bytes on disk after resize
- `used_count`: how many times this photo was used in a published post (incremented by publish flow — not in this brief)

### File storage
- Directory: `data/photos/` (relative to project root, same level as `data/state_registry.db`)
- Filename format: `photo_{id}_{8-char-hex}.jpg`
- All photos converted to JPEG on ingest, resized to max 1080px wide (maintaining aspect ratio)
- Use Pillow for resize/convert (already a dependency from graphics_engine)

### API endpoints

All endpoints are on the existing dashboard router, so actual URLs are `/dashboard/api/photos/...`.

```
POST /dashboard/api/photos/upload
  Content-Type: multipart/form-data
  Fields: file (required), tags (optional, comma-separated string), trip_key (optional)
  Response: {"ok": true, "photo": {photo object}}
  Resizes + stores + inserts into DB.

GET /dashboard/api/photos
  Query params: ?trip_key=klein_curacao&limit=50
  Response: [{photo object}, ...]
  Sorted by uploaded_at DESC.

GET /dashboard/api/photos/{photo_id}/image
  Response: JPEG file
  Content-Type: image/jpeg

PUT /dashboard/api/photos/{photo_id}
  Body: {"tags": ["sunset", "boat"], "trip_key": "klein_curacao"}
  Response: {"ok": true}

DELETE /dashboard/api/photos/{photo_id}
  Response: {"ok": true}
  Deletes file from disk + row from DB.

GET /dashboard/api/photos/stats
  Response: {"total": 42, "by_trip": {"klein_curacao": 15, "sunset_cruise": 8, "untagged": 19}}
```

### Photo object shape
```json
{
  "id": 1,
  "filename": "photo_1_a3f8c2d1.jpg",
  "original_filename": "IMG_2847.jpg",
  "tags": ["sunset", "boat"],
  "trip_key": "klein_curacao",
  "source": "upload",
  "width": 1080,
  "height": 810,
  "file_size": 245000,
  "used_count": 0,
  "uploaded_at": "2026-03-17T22:00:00+00:00"
}
```

### Pydantic models
```python
class PhotoUpdateRequest(BaseModel):
    tags: list[str] = None
    trip_key: str = None
```

## Instructions

### state_registry.py

1. In `_get_conn()`, add the `photo_library` CREATE TABLE statement after the `content_learnings` table.

2. Add functions:
   - `save_photo(filename, original_filename, tags, trip_key, source, source_id, width, height, file_size) -> int` — INSERT, returns row ID
   - `get_photos(trip_key=None, limit=50) -> list` — SELECT with optional trip_key filter, newest first. Returns list of dicts with `tags_json` parsed to `tags` list.
   - `get_photo_by_id(photo_id) -> dict | None` — single photo by ID
   - `get_photo_by_source_id(source_id) -> dict | None` — lookup by external ID (for Drive dedup in Brief 106)
   - `update_photo(photo_id, tags=None, trip_key=None) -> bool` — UPDATE non-None fields
   - `delete_photo(photo_id) -> str | None` — DELETE row, return filename (caller deletes file). Returns None if not found.
   - `get_photo_stats() -> dict` — count total and group by trip_key

### dashboard/api.py

3. Add imports: `from fastapi import File, UploadFile, Form` and `from PIL import Image` and `import io`. Note: `secrets` is already imported at line 7 — reuse it, do not re-import.

4. Add `PhotoUpdateRequest` Pydantic model.

5. Add `_PHOTOS_DIR` constant: `os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "photos")`. Create the directory in a module-level `os.makedirs(_PHOTOS_DIR, exist_ok=True)`.

6. Add helper `_process_upload(file_bytes: bytes, photo_id: int) -> tuple[str, int, int, int]`:
   - Open with Pillow
   - Convert to RGB (handles PNG transparency, RGBA, etc.)
   - Resize if width > 1080 (maintain aspect ratio)
   - Generate filename: `photo_{photo_id}_{secrets.token_hex(4)}.jpg`
   - Save as JPEG quality=85
   - Return (filename, width, height, file_size_bytes)

7. Add the 6 endpoints listed in Source Material above. All require `_check_auth` dependency.

8. For `POST /photos/upload`:
   - Accept `file: UploadFile`, `tags: str = Form("")`, `trip_key: str = Form("")`
   - Read file bytes, validate it's an image (try Pillow open, catch errors → 400)
   - Process the image first with `_process_upload(file_bytes, 0)` using temp ID 0
   - Call `save_photo()` with the processed filename, dimensions, file_size
   - Rename the file from `photo_0_xxx.jpg` to `photo_{actual_id}_xxx.jpg` using `os.rename()`
   - Update the filename in DB via a new `update_photo_filename(photo_id, filename) -> bool` function in state_registry
   - Parse tags from comma-separated string, stripping whitespace
   - Return the photo object

   Add `update_photo_filename(photo_id, filename) -> bool` to state_registry.py — simple UPDATE of filename column by id.

9. For `DELETE /photos/{photo_id}`:
   - Call `state_registry.delete_photo()` to get filename
   - Delete file from disk: `os.remove(os.path.join(_PHOTOS_DIR, filename))`
   - Handle file-not-found gracefully (photo may have been manually deleted)

## Tests

### File: `bluemarlin/tests/social/test_105_photo_library.py`

1. `test_save_and_get_photo` — save a photo record, get_photos returns it with correct fields
2. `test_get_photos_filter_by_trip` — save 2 photos with different trip_keys, filter returns only matching
3. `test_get_photo_by_id` — save photo, retrieve by ID, verify fields
4. `test_get_photo_by_source_id` — save with source_id, retrieve by source_id
5. `test_update_photo_tags` — save photo, update tags, verify changed
6. `test_update_photo_trip_key` — save photo, update trip_key, verify changed
7. `test_delete_photo` — save photo, delete returns filename, get_photo_by_id returns None
8. `test_delete_photo_nonexistent` — delete ID 9999, returns None
9. `test_get_photo_stats` — save 3 photos (2 same trip, 1 different), verify stats counts
10. `test_api_upload_endpoint` — use TestClient with a 10x10 red PNG bytes as upload file, tags="sunset,boat", trip_key="klein_curacao". Assert 200, response has `photo.original_filename`, `photo.source == "upload"`, `photo.trip_key == "klein_curacao"`, `photo.tags == ["sunset", "boat"]`. Verify file exists on disk.
11. `test_api_list_photos` — upload 2 photos via TestClient, call GET /dashboard/api/photos, assert response is a list of length 2.
12. `test_api_delete_photo` — upload a photo, get its ID, call DELETE, assert 200, verify GET by ID returns 404.

## Success Condition
Photos can be uploaded through the API, stored as resized JPEGs, tagged, listed, served, and deleted. The photo library table is ready for Google Drive sync (Brief 106) and frontend (Brief 107).

## Rollback
- Remove photo_library table creation from state_registry.py
- Remove photo functions from state_registry.py
- Remove photo endpoints from api.py
- Delete `data/photos/` directory
