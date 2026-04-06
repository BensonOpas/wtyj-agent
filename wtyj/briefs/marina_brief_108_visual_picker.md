# BRIEF 108 — Visual Picker: Post Image Creation Flow
**Status:** Draft | **Depends on:** Brief 105 (photo library), Brief 106 (Drive sync) | **Blocks:** None

**Files:**
- `bluemarlin/dashboard/api.py` (new endpoints: generate AI image, compose photo+text)
- `bluemarlin/agents/social/graphics_engine.py` (photo background modes, AI image integration)
- `bluemarlin/shared/state_registry.py` (photo_id on drafts, increment used_count)
- `wetakeyourjob-dashboard/artifacts/dashboard/src/pages/ContentPipeline.tsx` (visual picker UI)
- `wetakeyourjob-dashboard/artifacts/dashboard/src/lib/api.ts` (new API methods)
- `wetakeyourjob-dashboard/artifacts/dashboard/src/hooks/use-bluemarlin.ts` (new mutations)
- `bluemarlin/tests/social/test_108_visual_picker.py`

## Context
The content pipeline generates text drafts. Photos exist in the library via Google Drive. But there's no connection between them — approved drafts have no image, and publishing uses the old gradient text card.

The operator needs to choose how each post looks AFTER the text is approved, BEFORE publishing. Four visual options, one clear flow.

## Why This Approach
Visual choice is separated from text review. Text gets approved/rejected/edited on its own. The visual is a distinct step — this prevents wasting image generation on drafts that get rejected.

The visual picker replaces the current "Publish Now" button on approved drafts. Instead of instant-publish, the operator chooses a visual style, sees a preview, then publishes.

AI image generation uses Google Imagen 4 (cheapest at $0.02/image, we already have Google Cloud credentials). Alternative considered: GPT Image 1.5 — better quality but requires a separate OpenAI API key. Imagen 4 keeps everything in one Google account.

## Source Material

### The four visual options

When an operator clicks on an approved draft, instead of "Publish Now" they see four choices:

**1. Photo + Text Overlay**
Pick a photo from the library. System composites headline text onto the photo with a dark gradient overlay on the lower 40%. Brand colors, brand font. Good for promos and CTAs.

**2. Photo Only**
Pick a photo from the library. Photo goes to Instagram as-is with a small brand watermark. Caption goes in the Instagram description. Good for experience/lifestyle posts.

**3. AI Generated Image**
System generates an image using the draft's `visual_suggestion` field as the prompt. Uses Google Imagen 4 API. Labeled "AI Generated" in the dashboard so the operator knows. Good for when the library has nothing suitable.

**4. Text Card**
Branded text graphic — the current gradient + text behavior. No photo needed. Good for quick operational posts (schedule changes, announcements).

### Operator flow

```
Approved draft → Click "Design Post" →
  → Pick visual type (4 options) →
  → [If photo needed] Pick from library grid →
  → See preview →
  → "Publish to Instagram" or "Back"
```

### Backend changes

**state_registry.py:**
- Add `photo_id` column to content_drafts (ALTER TABLE, same pattern)
- `set_draft_photo_id(draft_id, photo_id) -> bool`
- `increment_photo_used_count(photo_id) -> None`
- Include `photo_id` in draft SELECT queries

**graphics_engine.py — new function:**
```python
def generate_composite(draft_id: int, photo_path: str = "", mode: str = "photo_text") -> str:
```
Modes:
- `"photo_text"` — photo background + dark gradient overlay bottom 40% + headline text + brand watermark + accent bar
- `"photo_only"` — photo resized/cropped to 1080x1350, small brand watermark bottom-right
- `"text_card"` — current gradient + text behavior (existing code)

Returns output path. Saves to `data/graphics/draft_{id}.jpg`.

Cover-crop helper for photos:
```python
def _cover_crop(img, target_w, target_h):
    """Resize image to cover target dimensions, center-crop to exact size."""
    scale = max(target_w / img.width, target_h / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    left = (img.width - target_w) // 2
    top = (img.height - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))
```

Photo + text overlay composition:
- Load photo, cover-crop to 1080x1350
- Create a gradient overlay: transparent at 60% height → 70% black at bottom
- Paste overlay onto photo using alpha composite
- Draw headline text in the lower 35% area (white, brand font)
- Add brand name small text bottom-right
- Add accent bar at very bottom

**api.py — new endpoints:**

```
POST /drafts/{draft_id}/compose
Body: {"mode": "photo_text", "photo_id": 5}
       {"mode": "photo_only", "photo_id": 5}
       {"mode": "ai_generate"}
       {"mode": "text_card"}
Response: {"ok": true, "image_path": "...", "ai_generated": false}
```
- For photo modes: gets photo path from photo_library, calls graphics_engine.generate_composite()
- For ai_generate: calls Imagen 4 API with the draft's visual_suggestion, saves result, then optionally composites text on it
- For text_card: calls existing gradient generation
- Sets image_path on the draft
- If photo_id provided, sets photo_id on draft and increments used_count

**AI Image Generation (Imagen 4):**
```python
def _generate_ai_image(prompt: str, draft_id: int) -> str:
    """Generate an image using Google Imagen 4. Returns file path."""
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get("GOOGLE_AI_API_KEY", ""))
    model = genai.ImageGenerationModel("imagen-4.0-generate-001")
    result = model.generate_images(prompt=prompt, number_of_images=1)
    # Save the image
    img_bytes = result.images[0]._image_bytes
    path = os.path.join(_PHOTOS_DIR, f"ai_draft_{draft_id}.jpg")
    with open(path, "wb") as f:
        f.write(img_bytes)
    return path
```
Note: The exact SDK may differ — verify the `google-generativeai` package API during execution. If Imagen 4 isn't available via the genai SDK, fall back to REST API calls to `generativelanguage.googleapis.com`.

**Prerequisite (manual):** User needs to enable the "Generative Language API" or "Imagen API" in Google Cloud Console and get/set a `GOOGLE_AI_API_KEY` env var on the VPS. OR use existing OAuth credentials if the API supports it.

### Frontend changes

**ContentPipeline.tsx:**

Replace the "Publish Now" button on approved drafts with "Design Post". Clicking opens a new Dialog with:

1. **Four option cards** in a 2x2 grid:
   - Photo + Text (icon: ImageIcon + Type)
   - Photo Only (icon: ImageIcon)
   - AI Generated (icon: Sparkles)
   - Text Card (icon: AlignLeft)

2. **If photo option selected** → show photo library grid (reuse PhotoThumb from AssetLibrary or create a shared component). Operator clicks a photo → preview generates.

3. **Preview panel** → shows the composed image. Two buttons: "Back" and "Publish to Instagram".

4. **AI Generated** → shows loading spinner while generating → then preview.

5. **Label** → if AI generated, show a small "AI Generated" badge on the preview.

State management:
```
designOpen: boolean
designMode: "photo_text" | "photo_only" | "ai_generate" | "text_card" | null
selectedPhotoId: number | null
previewReady: boolean
composing: boolean
```

**api.ts:**
```typescript
composeDraft: async (draftId: number, mode: string, photoId?: number): Promise<{ok: boolean, image_path: string, ai_generated: boolean}>
```

**use-bluemarlin.ts:**
Add `compose` mutation to `useDraftMutations()`.

### The publish flow change

Currently: approved draft → "Publish Now" → publishes instantly.
New: approved draft → "Design Post" → visual picker → preview → "Publish to Instagram" → publishes.

The actual publish call (`POST /drafts/{id}/publish`) stays the same — it already uses whatever image_path is on the draft. The compose step just sets that image_path before publish is called.

## Instructions

### Backend

1. **state_registry.py**: Add `photo_id` ALTER TABLE, `set_draft_photo_id()`, `increment_photo_used_count()`, include photo_id in draft queries.

2. **graphics_engine.py**: Add `_cover_crop()` helper. Add `generate_composite(draft_id, photo_path, mode)` function with three modes. Keep existing `generate_graphic()` working (it becomes the text_card mode internally).

3. **api.py**: Add `POST /drafts/{draft_id}/compose` endpoint. Add `_generate_ai_image()` helper (Imagen 4 or fallback). Add `ComposeRequest` Pydantic model.

### Frontend

4. **api.ts**: Add `composeDraft()` method.

5. **use-bluemarlin.ts**: Add `compose` mutation.

6. **ContentPipeline.tsx**: Replace "Publish Now" on approved drafts with "Design Post". Add the visual picker Dialog with 4 option cards → photo grid → preview → publish flow.

## Tests

### File: `bluemarlin/tests/social/test_108_visual_picker.py`

1. `test_set_draft_photo_id` — save draft, set photo_id=5, verify get_content_drafts returns photo_id=5
2. `test_increment_used_count` — save photo used_count=0, increment, verify used_count=1
3. `test_cover_crop_landscape` — create 200x100 image, cover_crop to 1080x1350, verify output is 1080x1350
4. `test_cover_crop_portrait` — create 100x200 image, cover_crop to 1080x1350, verify output is 1080x1350
5. `test_generate_composite_photo_text` — create test photo file + test draft (Class B), call generate_composite with mode="photo_text", verify output file exists and is 1080x1350
6. `test_generate_composite_photo_only` — same but mode="photo_only", verify output exists
7. `test_generate_composite_text_card` — call with mode="text_card" (no photo), verify output exists (gradient fallback)
8. `test_compose_endpoint_text_card` — TestClient POST /compose with mode="text_card", mock graphics_engine, verify 200
9. `test_compose_endpoint_photo` — TestClient POST /compose with mode="photo_only" and photo_id, mock graphics_engine + state_registry, verify 200 and photo_id set

## Success Condition
Approved drafts show "Design Post" instead of "Publish Now". Operator picks a visual style, sees a preview, publishes. Photos from library are used with proper text overlay. AI generation works as fallback. Text card still available. The old instant-publish behavior is replaced by the visual picker flow.

## Rollback
- Revert ContentPipeline.tsx "Publish Now" button
- Remove /compose endpoint from api.py
- Remove generate_composite from graphics_engine.py
- Revert state_registry.py photo_id changes
