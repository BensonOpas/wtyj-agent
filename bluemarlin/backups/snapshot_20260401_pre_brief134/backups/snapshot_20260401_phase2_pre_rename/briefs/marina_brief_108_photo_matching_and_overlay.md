# BRIEF 108 — Photo Matching + Text Overlay on Real Photos
**Status:** Draft | **Depends on:** Brief 105 (photo library), Brief 107 (asset library UI) | **Blocks:** None

**Files:**
- `bluemarlin/agents/social/content_agent.py` (add photo context to prompt)
- `bluemarlin/agents/social/graphics_engine.py` (photo background + overlay modes)
- `bluemarlin/dashboard/api.py` (auto-match photos after generation)
- `bluemarlin/shared/state_registry.py` (add photo_id to drafts)
- `bluemarlin/tests/social/test_108_photo_matching.py`

## Context
The photo library and Google Drive sync are built. Photos exist in the system. But the content pipeline still ignores them — drafts are generated without images, and publishing falls back to the branded text-on-gradient card.

This brief connects photos to the content pipeline:
1. After generating drafts, auto-match the best photo from the library
2. Based on content class, either use the photo as-is (Class A) or composite text onto the photo (Class B/C/D)
3. The generated image shows up as the draft preview in the dashboard

## Why This Approach
Photo matching happens AFTER draft generation (post-processing), not during. This keeps content_agent.py focused on text and avoids coupling it to the photo library. The graphics engine already handles text rendering — extending it to use a photo background instead of a gradient is a natural evolution, not a rewrite.

Considered having Claude pick the photo during generation — rejected because Claude can't see the photos (no vision in this call) and matching by trip_key/tags is deterministic and simpler. Considered AI vision auto-matching — deferred to future brief.

Content class drives the visual treatment:
- Class A (Evergreen) — photo only, small brand watermark in corner. The photo IS the content.
- Class B (Commercial) — photo with semi-transparent overlay + headline text. Promotional feel.
- Class C/D (Operational/Reactive) — same as B. Text overlay helps communicate urgency/info.
- No photo match — falls back to current gradient + text card (existing behavior unchanged).

## Source Material

### Photo matching logic

New function `match_photo_to_draft(draft: dict) -> dict | None` in a new helper or in content_agent.py:

1. Get the draft's `instagram_caption` and `content_class`
2. Extract trip references from caption — check if any trip `display_name` or `trip_key` from client.json appears in the caption text (case-insensitive)
3. If trip found → `state_registry.get_photos(trip_key=matched_key)` → pick photo with lowest `used_count`
4. If no trip match → `state_registry.get_photos()` → pick any photo with lowest `used_count`
5. If no photos at all → return None (fallback to gradient)
6. Increment `used_count` on the selected photo

### state_registry changes

Add `photo_id` column to `content_drafts` table (ALTER TABLE, same pattern as image_path):
```sql
ALTER TABLE content_drafts ADD COLUMN photo_id INTEGER DEFAULT 0
```

Add function:
```python
def set_draft_photo_id(draft_id: int, photo_id: int) -> bool
def increment_photo_used_count(photo_id: int) -> None
```

### graphics_engine.py changes

Modify `generate_graphic(draft_id)` to accept an optional `photo_path` parameter:

```python
def generate_graphic(draft_id: int, photo_path: str = "") -> str:
```

When `photo_path` is provided and the file exists:

**Class A (photo only + watermark):**
- Load the photo, resize/crop to 1080x1350 (cover fit — fill the frame, crop center)
- Add small semi-transparent brand name in bottom-right corner (subtle watermark)
- Save. No headline text overlay.

**Class B/C/D (photo + text overlay):**
- Load the photo, resize/crop to 1080x1350 (cover fit)
- Draw a semi-transparent dark overlay on the lower 40% of the image (gradient from transparent to 70% black)
- Draw the headline text in the overlay area (white text, same font/sizing logic as current)
- Add brand name in bottom-right corner
- Add accent bar at very bottom (existing behavior)
- Save.

When `photo_path` is empty or file doesn't exist:
- Current behavior unchanged (gradient background + text)

### dashboard/api.py changes

In the `generate` endpoint (POST /drafts/generate), after drafts are stored, run photo matching:

```python
# After storing drafts
for draft in stored:
    photo = _match_photo_to_draft(draft)
    if photo:
        photo_path = os.path.join(_PHOTOS_DIR, photo["filename"])
        state_registry.set_draft_photo_id(draft["id"], photo["id"])
        state_registry.increment_photo_used_count(photo["id"])
        graphics_engine.generate_graphic(draft["id"], photo_path=photo_path)
```

The `_match_photo_to_draft` function lives in api.py (simple trip-key matching, not complex enough for its own module).

Also update the `publish_draft` endpoint: when auto-generating a graphic on publish (the fallback path), pass `photo_path` if the draft has a `photo_id`.

### Trip matching logic

```python
def _match_photo_to_draft(draft: dict) -> dict | None:
    caption = (draft.get("instagram_caption") or "").lower()
    trips = config_loader.get_trips()

    # Try to match by trip name in caption
    for trip_key, trip_data in trips.items():
        display = trip_data.get("display_name", "").lower()
        if display and display in caption:
            photos = state_registry.get_photos(trip_key=trip_key, limit=50)
            if photos:
                # Pick least used
                photos.sort(key=lambda p: p["used_count"])
                return photos[0]
        # Also check trip_key itself
        if trip_key.replace("_", " ") in caption:
            photos = state_registry.get_photos(trip_key=trip_key, limit=50)
            if photos:
                photos.sort(key=lambda p: p["used_count"])
                return photos[0]

    # No trip match — pick any photo, least used
    all_photos = state_registry.get_photos(limit=50)
    if all_photos:
        all_photos.sort(key=lambda p: p["used_count"])
        return all_photos[0]

    return None
```

## Instructions

### state_registry.py

1. Add ALTER TABLE for `photo_id` column (same try/except pattern as image_path):
```python
try:
    conn.execute("ALTER TABLE content_drafts ADD COLUMN photo_id INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass
```

2. Add `set_draft_photo_id(draft_id, photo_id)` — UPDATE photo_id WHERE id = draft_id.

3. Add `increment_photo_used_count(photo_id)` — UPDATE photo_library SET used_count = used_count + 1 WHERE id = photo_id.

4. Include `photo_id` in the SELECT columns and returned dict for `get_content_drafts()` and the drafts query functions. Use the same try/except ALTER TABLE pattern so existing DBs without the column don't break.

### graphics_engine.py

5. Add `photo_path: str = ""` parameter to `generate_graphic()`.

6. When photo_path is provided and exists:
   - Load photo with Pillow, convert to RGB
   - Resize to cover 1080x1350: scale up to fill, then center-crop
   - Get draft's `content_class`
   - **Class A**: photo only + subtle watermark (brand name, bottom-right, semi-transparent white, 20px font)
   - **Class B/C/D**: photo + dark gradient overlay on lower 40% + headline text + brand name + accent bar

7. When no photo_path: existing gradient behavior unchanged.

8. Extract the cover-crop logic into a helper `_cover_crop(img, target_w, target_h)`.

### dashboard/api.py

9. Add `_match_photo_to_draft()` function as described in Source Material.

10. In the `generate` endpoint, after the `content_agent.generate_drafts()` call returns stored drafts, loop through and match+generate graphics for each.

11. In the `publish_draft` endpoint, when auto-generating a graphic (the fallback path at line ~140), check if the draft has a `photo_id`. If so, get the photo and pass `photo_path` to `generate_graphic()`.

## Tests

### File: `bluemarlin/tests/social/test_108_photo_matching.py`

1. `test_match_photo_by_trip_name` — create photo with trip_key="klein_curacao", create draft with caption containing "Klein Curaçao", verify match returns that photo
2. `test_match_photo_by_trip_key` — create photo with trip_key="sunset_cruise", draft caption contains "sunset cruise", verify match
3. `test_match_photo_least_used` — create 2 photos same trip, one with used_count=5, one with used_count=0, verify the unused one is picked
4. `test_match_photo_fallback_any` — create photo with trip_key="other", draft caption has no trip reference, verify it still picks a photo
5. `test_match_photo_no_photos` — empty library, verify returns None
6. `test_set_draft_photo_id` — save draft, set photo_id, get draft, verify photo_id is set
7. `test_increment_used_count` — save photo with used_count=0, increment, verify used_count=1
8. `test_generate_graphic_with_photo_class_a` — create a 100x100 red image file, call generate_graphic with photo_path and a Class A draft, verify output file exists and dimensions are 1080x1350
9. `test_generate_graphic_with_photo_class_b` — same but Class B draft, verify output exists
10. `test_generate_graphic_no_photo_fallback` — call generate_graphic without photo_path, verify gradient fallback still works

## Success Condition
When drafts are generated, each draft automatically gets a matching photo from the library. Class A drafts show the photo with a subtle watermark. Class B/C/D drafts show the photo with headline text overlay. Drafts without matching photos fall back to the gradient card. The dashboard preview shows the composed image.

## Rollback
- Remove photo_id ALTER TABLE from state_registry.py
- Revert generate_graphic to single-parameter signature
- Remove _match_photo_to_draft from api.py
- Remove photo matching loop from generate endpoint
