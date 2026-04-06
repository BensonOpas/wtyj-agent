# BRIEF 092 — Content Agent Core + Draft Store
**Status:** Draft | **Files:** `agents/social/content_agent.py` (NEW), `shared/state_registry.py`, `config/client.json`, `tests/social/test_092_content_agent.py` (NEW) | **Depends on:** Brief 090 (dynamic client context), Brief 077 (state_registry patterns) | **Blocks:** Brief 093 (rejection learning)

## Context
Phase 1 Milestone B (Auto-Posting) begins. The WhatsApp Q&A agent is live and working (Milestone A complete). The roadmap calls for an auto-posting system that generates and publishes promotional content to Instagram and Facebook. SR's operating brief defines this as a human-gated content operations agent — the bot drafts, a human approves, then it publishes. This brief builds the foundation: Claude generates draft social media posts from existing client.json data + calendar availability, and stores them in SQLite for later approval and publishing.

## Why This Approach
We considered building the full pipeline (generation + approval + publishing) in one brief, but that's too large and couples unrelated concerns. We considered starting with just the SQLite schema, but an empty table with no generator delivers zero demo value. Starting with content generation + storage together gives us the smallest useful unit: you can run it, see real draft posts, and validate that Claude can produce premium content from the existing client.json data. The approval workflow and publishing pipeline layer on top in later briefs. The content agent follows the same proven architecture as marina_agent.py: one Claude call, structured JSON response, response defaults for resilience.

**Config vs source tradeoff:** The system prompt contains structural rules that apply to ALL clients (priority stack, content classification definitions, platform word limits, demand-state logic). These are agent behavior, not business data — they stay in source. Client-specific values (brand_voice, content_boundaries, emoji_style, cta_default, hashtag_style) are read from `social_content` in client.json at prompt build time. A new client changes their config, not the code.

## Source Material

### Response schema (content_agent returns this)
```json
{
  "drafts": [
    {
      "content_class": "A|B|C|D",
      "instagram_caption": "caption text for Instagram",
      "facebook_caption": "caption text for Facebook (slightly longer/more informational)",
      "hashtags": ["#Tag1", "#Tag2"],
      "visual_suggestion": "description of ideal accompanying image",
      "reasoning": "why this post, why now, what it achieves"
    }
  ]
}
```

### Content classification (from SR operating brief)
- **Class A — Evergreen brand:** experience highlights, testimonials, tips, storytelling, destination facts, marine life, behind the scenes
- **Class B — Commercial:** promotions, low-booking support, reopened spots, demand stimulation
- **Class C — Operational:** weather, changes, cancellations, sold-out status, availability redirects
- **Class D — Reactive:** UGC, local moments, tagged posts, timely external relevance (holidays, events)

### Brand positioning rules (from SR operating brief — goes into system prompt)
- Premium, polished, aspirational, trustworthy, experience-driven, visually strong
- Tone: premium, confident, clear, attractive, intentional, warm without cheap/sloppy
- Never: cheap, spammy, desperate, generic, cluttered, low-quality, exaggerated
- Priority stack: brand quality > factual correctness > premium perception > commercial goals > content consistency > engagement
- English primary. Emojis minimal and intentional.
- Sound like the company, not a separate persona or named character.
- Never post about: competitors, politics, religion, controversial topics

### social_content config section (add to client.json)
```json
"social_content": {
  "brand_voice": "premium, confident, clear, aspirational, experience-driven",
  "platforms": ["instagram", "facebook"],
  "platform_priority": "instagram",
  "posting_frequency_per_week": "3-5",
  "max_posts_per_day": 2,
  "content_boundaries": ["competitors", "politics", "religion", "controversial topics"],
  "cta_default": "Message us on WhatsApp to book",
  "hashtag_style": "selective, curated, few not maximum",
  "emoji_style": "minimal, intentional, never cheap or cluttered"
}
```

### Availability summary function (state_registry.py)
Queries trip_bookings for the next N days to give the content agent operational awareness. Avoids cross-agent import from gws_calendar.py.

```python
def get_availability_summary(days_ahead=7) -> list:
    """Get booking counts for all trip slots in the next N days.
    Returns list of {trip_key, date, departure_time, booked_guests, capacity}.
    Caller computes spots_remaining = capacity - booked_guests."""
```

This function:
1. Calls `expire_stale_holds()` first
2. Gets all trips + departures from config_loader
3. For each trip, determines which dates in the next N days it operates on (using `days_available`)
4. Queries trip_bookings for booked guest counts per slot
5. Returns list with capacity from config

Day-of-week mapping for `days_available`:
- `"daily"` → all 7 days
- `"Fridays only"` → Friday
- `"Wednesdays and Sundays"` → Wednesday, Sunday
- `"Tuesday, Thursday, Friday, Saturday"` → those 4 days

## Instructions

### Step 1 — Add `social_content` section to client.json

Add the `social_content` key after the `common_sense_knowledge` section (before the closing `}`). Use the exact JSON from Source Material above.

### Step 2 — Add content_drafts table + CRUD + availability summary to state_registry.py

**2a.** Add this table creation inside `_get_conn()`, after the `pending_notifications` table (after line 111, before the ALTER TABLE block):

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS content_drafts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "content_class TEXT NOT NULL, "
        "instagram_caption TEXT, "
        "facebook_caption TEXT, "
        "hashtags_json TEXT DEFAULT '[]', "
        "visual_suggestion TEXT DEFAULT '', "
        "reasoning TEXT DEFAULT '', "
        "status TEXT DEFAULT 'pending', "
        "rejection_reason TEXT DEFAULT '', "
        "created_at TEXT NOT NULL, "
        "approved_at TEXT, "
        "published_at TEXT"
        ")"
    )
```

**2b.** Add these CRUD functions at the end of state_registry.py, just above the final `_get_conn().close()` line (line 581 — the module-level DB init call):

```python
def save_content_draft(content_class: str, instagram_caption: str,
                       facebook_caption: str, hashtags: list,
                       visual_suggestion: str, reasoning: str) -> int:
    """Save a content draft. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO content_drafts "
        "(content_class, instagram_caption, facebook_caption, hashtags_json, "
        "visual_suggestion, reasoning, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (content_class, instagram_caption, facebook_caption,
         json.dumps(hashtags, ensure_ascii=False), visual_suggestion, reasoning,
         datetime.now(timezone.utc).isoformat())
    )
    draft_id = cur.lastrowid
    conn.commit()
    conn.close()
    return draft_id


def get_content_drafts(status: str = None, limit: int = 50) -> list:
    """Get content drafts, optionally filtered by status. Newest first."""
    conn = _get_conn()
    if status:
        rows = conn.execute(
            "SELECT id, content_class, instagram_caption, facebook_caption, "
            "hashtags_json, visual_suggestion, reasoning, status, rejection_reason, "
            "created_at, approved_at, published_at "
            "FROM content_drafts WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content_class, instagram_caption, facebook_caption, "
            "hashtags_json, visual_suggestion, reasoning, status, rejection_reason, "
            "created_at, approved_at, published_at "
            "FROM content_drafts ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "content_class": r[1], "instagram_caption": r[2],
            "facebook_caption": r[3], "hashtags": json.loads(r[4] or "[]"),
            "visual_suggestion": r[5], "reasoning": r[6], "status": r[7],
            "rejection_reason": r[8], "created_at": r[9], "approved_at": r[10],
            "published_at": r[11],
        }
        for r in rows
    ]


def update_draft_status(draft_id: int, status: str,
                        rejection_reason: str = "") -> bool:
    """Update draft status. For 'approved', sets approved_at. For 'published', sets published_at.
    For 'rejected', stores rejection_reason. Returns True if row updated."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    if status == "approved":
        cur = conn.execute(
            "UPDATE content_drafts SET status = ?, approved_at = ? WHERE id = ?",
            (status, now, draft_id)
        )
    elif status == "published":
        cur = conn.execute(
            "UPDATE content_drafts SET status = ?, published_at = ? WHERE id = ?",
            (status, now, draft_id)
        )
    elif status == "rejected":
        cur = conn.execute(
            "UPDATE content_drafts SET status = ?, rejection_reason = ? WHERE id = ?",
            (status, rejection_reason, draft_id)
        )
    else:
        cur = conn.execute(
            "UPDATE content_drafts SET status = ? WHERE id = ?",
            (status, draft_id)
        )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_availability_summary(days_ahead: int = 7) -> list:
    """Get booking counts for all trip slots in the next N days.
    Returns list of {trip_key, date, departure_time, booked_guests, capacity, spots_remaining}.
    Used by content_agent to generate operationally-aware posts."""
    from shared import config_loader

    expire_stale_holds()
    trips = config_loader.get_trips()
    now_curacao = datetime.now(timezone(timedelta(hours=-4)))
    today = now_curacao.date()

    day_name_map = {
        0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
        4: "Friday", 5: "Saturday", 6: "Sunday"
    }

    results = []
    conn = _get_conn()

    for trip_key, trip_data in trips.items():
        capacity = trip_data.get("capacity", 0)
        days_available = trip_data.get("days_available", "daily")
        departures = trip_data.get("departures", [])

        # Parse which days this trip operates
        if days_available.lower() == "daily":
            valid_days = set(range(7))
        else:
            valid_days = set()
            for d_idx, d_name in day_name_map.items():
                if d_name.lower() in days_available.lower():
                    valid_days.add(d_idx)
            # Handle plural forms: "Fridays" → "Friday"
            if not valid_days:
                for d_idx, d_name in day_name_map.items():
                    if d_name.lower() + "s" in days_available.lower():
                        valid_days.add(d_idx)

        for day_offset in range(days_ahead):
            check_date = today + timedelta(days=day_offset)
            if check_date.weekday() not in valid_days:
                continue
            date_str = check_date.isoformat()

            for dep in departures:
                dep_time = dep.get("time", "")
                now_utc = datetime.now(timezone.utc).isoformat()
                row = conn.execute(
                    "SELECT COALESCE(SUM(guests), 0) FROM trip_bookings "
                    "WHERE trip_key=? AND date=? AND departure_time=? "
                    "AND status IN ('soft_hold', 'confirmed') "
                    "AND (status='confirmed' OR expires_at > ?)",
                    (trip_key, date_str, dep_time, now_utc)
                ).fetchone()
                booked = row[0] if row else 0
                results.append({
                    "trip_key": trip_key,
                    "date": date_str,
                    "departure_time": dep_time,
                    "booked_guests": booked,
                    "capacity": capacity,
                    "spots_remaining": max(0, capacity - booked),
                })

    conn.close()
    return results
```

**2c.** Update the file header to `# Last modified: Brief 092`.

### Step 3 — Create content_agent.py

Create `agents/social/content_agent.py` with the following structure:

**File header:**
```python
# bluemarlin/agents/social/content_agent.py
# Created: Brief 092
# Last modified: Brief 092
# Purpose: Social media content generation agent. Generates draft posts from client.json + calendar data.
```

**Imports:**
```python
import json
import os
import re
from datetime import datetime, timezone, timedelta

import anthropic
from shared import config_loader, state_registry, bm_logger
```

**Constants:**
```python
_CURACAO_TZ = timezone(timedelta(hours=-4))

_INTERNAL_KEYS = {"spreadsheet_id", "demo_support_email", "agent_signature",
                  "calendar_id"}

_DRAFT_DEFAULTS = {
    "content_class": "A",
    "instagram_caption": "",
    "facebook_caption": "",
    "hashtags": [],
    "visual_suggestion": "",
    "reasoning": "",
}
```

**`_build_client_context()` function:**
Same pattern as marina_agent.py. Implement these three pieces in content_agent.py:
- `_SKIP_TOP_LEVEL = {"trip_aliases"}` — same as marina_agent, filters keys handled elsewhere
- `_strip_verify(obj)` — recursively strips `[VERIFY...]` placeholders. Same logic as marina_agent.py.
- `_build_client_context()` — reads `config_loader.get_raw()`, iterates top-level keys, skips `_SKIP_TOP_LEVEL`, filters `_INTERNAL_KEYS` from nested dicts, strips `calendar_id` from trip departures, returns `=== SECTION ===\n{json}` sections joined by `\n\n`. Same logic as marina_agent.py.

Use the `_INTERNAL_KEYS` defined in the Constants section above (does NOT include `support_email` — that's customer-facing data the content agent may reference for CTAs).

**`_build_system_prompt(count)` function:**

Takes `count` (int) — the number of drafts to request. Returns the system prompt string. Reads client-specific values from config at build time.

```python
def _build_system_prompt(count: int) -> str:
```

At the top of the function, load config values:
```python
    business = config_loader.get_business()
    business_name = business.get("name", "the business")
    raw = config_loader.get_raw()
    sc = raw.get("social_content", {})
    brand_voice = sc.get("brand_voice", "premium, confident, clear")
    boundaries = sc.get("content_boundaries", ["competitors", "politics", "religion"])
    cta = sc.get("cta_default", "Contact us to book")
    emoji_style = sc.get("emoji_style", "minimal, intentional")
    hashtag_style = sc.get("hashtag_style", "selective, curated, few not maximum")
```

Then build the prompt string with ALL of the following sections in this order:

1. **Role:** "You are the social media content strategist for {business_name}. You generate draft social media posts. You do not publish — a human reviews and approves every post."

2. **Brand positioning:** (read from config) "BRAND VOICE: {brand_voice}. The brand shows the world what it does and what it has. Premium, polished, aspirational, trustworthy, experience-driven, visually strong."

3. **Tone rules:** (structural — same for all clients) "Tone: professional without cold, warm without cheap or sloppy."

4. **Priority stack:** (structural) "If tradeoffs appear: 1. protect brand quality, 2. protect factual correctness, 3. protect premium perception, 4. support commercial goals, 5. maintain content consistency, 6. optimize engagement."

5. **Content classification:** (structural) Define all four classes (A, B, C, D) with examples from the Source Material above. Instruct: "Maintain a healthy mix across classes. Do not generate multiple posts of the same class in a row."

6. **Voice rules:** (mix of config + structural)
   - Sound like the company, not a separate persona
   - English primary
   - "Emojis: {emoji_style}"
   - Never use: cheap, spammy, urgency tactics, exaggerated language, "Don't miss out!", "Book NOW!", "Limited spots!!", excessive exclamation marks
   - Desired style: premium, aspirational, polished, clear, confident

7. **Platform rules:** (structural)
   - Instagram (primary): shorter captions, punchy, visual-first. Max 150 words.
   - Facebook (secondary): slightly longer, more informational, same core message. Max 200 words.
   - Both get the same concept but adapted per platform.

8. **Content boundaries:** (from config) "NEVER post about: {', '.join(boundaries)}"

9. **Hashtag rules:** (from config) "Hashtag style: {hashtag_style}"

10. **CTA default:** (from config) "Default call to action: {cta}"

11. **Demand-state rules:** (structural)
    - Low bookings: propose content to attract interest. Never sound desperate.
    - Sold out: don't stop posting. Redirect to next available option. Turn full capacity into social proof.
    - Cancellation reopens spots: propose timely content reflecting the opportunity.

12. **Response format:** The exact JSON schema from Source Material above. Instruct: "Return ONLY a JSON object. No explanation. No markdown. No code fences. The `drafts` array must contain exactly {count} items."

**`_build_user_prompt(count, days_ahead=7)` function:**

```python
def _build_user_prompt(count: int, days_ahead: int = 7) -> str:
```

Returns the user prompt string. Must include:

1. `TODAY (Curaçao time): {YYYY-MM-DD}`
2. `DAY OF WEEK: {Monday/Tuesday/etc}`
3. `=== CLIENT DATA ===\n{_build_client_context()}`
4. `=== AVAILABILITY (next {days_ahead} days) ===` — call `state_registry.get_availability_summary(days_ahead)`. Format each slot as one line: `{trip_display_name} | {date} {departure_time} | {spots_remaining}/{capacity} spots`. If no availability data (empty list), write: `"No booking data available. Focus on Class A (evergreen) and Class D (reactive) content."`
5. `=== RECENT DRAFTS (last 14 days) ===` — call `state_registry.get_content_drafts(limit=20)`, filter to last 14 days by created_at. For each, show one line: `[{content_class}] {instagram_caption[:80]}...`. If none: `"No recent drafts."`
6. `=== REJECTION HISTORY ===` — call `state_registry.get_content_drafts(status="rejected", limit=10)`. For each with a rejection_reason, show: `REJECTED: "{instagram_caption[:60]}..." — Reason: {rejection_reason}`. If none: `"No rejections yet."`
7. `Generate {count} draft posts for the coming week.`

**`generate_drafts(count=3, days_ahead=7)` function:**

The main entry point. Single Claude call.

1. Build system prompt via `_build_system_prompt(count)`
2. Build user prompt via `_build_user_prompt(count, days_ahead)`
3. Call Claude API:
   - Model: `claude-sonnet-4-6`
   - Max tokens: 4096 (larger than marina_agent because multiple drafts)
   - System: system_prompt
   - Messages: [{"role": "user", "content": user_prompt}]
4. Strip markdown code fences (same regex as marina_agent.py lines 503-504)
5. Parse JSON
6. Validate: result must be a dict with a "drafts" key containing a list
7. For each draft in the list:
   - Apply `_DRAFT_DEFAULTS` for missing fields (same pattern as marina_agent `_RESPONSE_DEFAULTS`)
   - Validate `content_class` is one of A, B, C, D (default to "A" if invalid)
   - Skip drafts where both `instagram_caption` and `facebook_caption` are empty
   - Call `state_registry.save_content_draft()` to store
8. Log: `bm_logger.log("content_drafts_generated", count=len(stored_drafts))`
9. Log API usage: `bm_logger.log("api_usage", input_tokens=..., output_tokens=..., model="claude-sonnet-4-6", channel="content")`
10. Return the list of stored draft dicts (with id from SQLite)

**Error handling:**
- If Claude API fails: log `bm_logger.log("content_api_error", error=str(exc)[:200])`, return empty list
- If JSON parse fails: log `bm_logger.log("content_response_invalid", reason="json_parse_error", raw_preview=raw[:300])`, return empty list
- If result is not a dict or has no "drafts" key: log `bm_logger.log("content_response_invalid", reason="missing_drafts_key")`, return empty list

### Step 4 — Create test file

Create `tests/social/test_092_content_agent.py`:

**File header:**
```python
# bluemarlin/tests/social/test_092_content_agent.py
# Created: Brief 092
# Purpose: Tests for content agent core + draft store
```

**Setup:** Same pattern as test_077 — sys.path insert, set WhatsApp env vars, import modules.

**Helper:** `_cleanup_drafts()` — deletes all rows from content_drafts table.

**Tests (14 total):**

1. **`test_system_prompt_includes_brand_rules`** — Call `_build_system_prompt(3)`. Assert the returned string contains: "premium", "brand quality", "factual correctness", "Class A", "Class B", "Class C", "Class D".

2. **`test_system_prompt_includes_response_format`** — Call `_build_system_prompt(3)`. Assert contains: "instagram_caption", "facebook_caption", "hashtags", "visual_suggestion", "reasoning".

3. **`test_system_prompt_reads_config_values`** — Call `_build_system_prompt(3)`. Assert contains the `brand_voice` value from client.json social_content ("premium, confident, clear, aspirational, experience-driven"). Assert contains "Message us on WhatsApp to book" (the cta_default). Assert contains "competitors" (from content_boundaries).

4. **`test_user_prompt_includes_client_data`** — Call `_build_user_prompt(3, days_ahead=7)`. Assert contains: "Klein" (from Klein Curaçao trip), "Sunset" (from Sunset Cruise), "CLIENT DATA".

5. **`test_user_prompt_includes_availability`** — Mock `state_registry.get_availability_summary` to return `[{"trip_key": "klein_curacao", "date": "2026-03-20", "departure_time": "08:00", "booked_guests": 25, "capacity": 30, "spots_remaining": 5}]`. Call `_build_user_prompt(3, days_ahead=7)`. Assert contains "5/30" or "spots".

6. **`test_user_prompt_no_availability_graceful`** — Mock `state_registry.get_availability_summary` to return `[]`. Call `_build_user_prompt(3, days_ahead=7)`. Assert contains "No booking data available" and "evergreen".

7. **`test_generate_drafts_stores_in_db`** — Mock the Claude API to return valid JSON with 2 drafts (one Class A, one Class C). Call `generate_drafts(count=2)`. Assert `state_registry.get_content_drafts()` returns 2 rows. Assert first row has `status == "pending"`. Cleanup after.

8. **`test_generate_drafts_returns_structured`** — Mock Claude API to return valid JSON with 1 draft. Call `generate_drafts(count=1)`. Assert returned list has 1 item with keys: `id`, `content_class`, `instagram_caption`, `facebook_caption`, `hashtags`, `visual_suggestion`, `reasoning`, `status`. Cleanup after.

9. **`test_draft_defaults_missing_fields`** — Mock Claude API to return JSON where draft is missing `hashtags` and `visual_suggestion`. Call `generate_drafts(count=1)`. Assert stored draft has `hashtags == []` and `visual_suggestion == ""`. Cleanup after.

10. **`test_content_class_validation`** — Mock Claude API to return draft with `content_class: "Z"` (invalid). Call `generate_drafts(count=1)`. Assert stored draft has `content_class == "A"` (defaulted). Cleanup after.

11. **`test_generate_drafts_api_error_returns_empty`** — Mock Claude API to raise an exception. Call `generate_drafts(count=3)`. Assert returns empty list. Assert no rows in content_drafts.

12. **`test_update_draft_status_approved`** — Save a draft via `state_registry.save_content_draft(...)`. Call `state_registry.update_draft_status(draft_id, "approved")`. Fetch it back. Assert `status == "approved"` and `approved_at` is not None. Cleanup after.

13. **`test_update_draft_status_rejected_with_reason`** — Save a draft. Call `state_registry.update_draft_status(draft_id, "rejected", rejection_reason="too salesy")`. Fetch it back. Assert `status == "rejected"` and `rejection_reason == "too salesy"`. Cleanup after.

14. **`test_availability_summary_returns_correct_structure`** — Call `state_registry.get_availability_summary(days_ahead=3)`. Assert returns a list. If non-empty, assert each item has keys: `trip_key`, `date`, `departure_time`, `booked_guests`, `capacity`, `spots_remaining`. Assert `spots_remaining == capacity - booked_guests` for each.

For mock Claude responses, use this template:
```python
MOCK_CLAUDE_RESPONSE_2 = json.dumps({
    "drafts": [
        {
            "content_class": "A",
            "instagram_caption": "Crystal-clear waters and white sand. Klein Curaçao is waiting.",
            "facebook_caption": "There's a small uninhabited island just off the coast of Curaçao with crystal-clear waters, white sand beaches, and sea turtles swimming right past you. That's Klein Curaçao — and we go there every day.",
            "hashtags": ["#KleinCuracao", "#BlueFinnCharters", "#CuracaoBoatTrip"],
            "visual_suggestion": "aerial shot of Klein Curaçao beach with turquoise water",
            "reasoning": "Class A evergreen — showcases flagship experience, builds brand awareness"
        },
        {
            "content_class": "C",
            "instagram_caption": "Saturday's Klein Curaçao trip is fully booked. Sunday still has spots — same water, same turtles, same open bar.",
            "facebook_caption": "This Saturday's Klein Curaçao trip is at full capacity — but don't worry. Sunday's departure still has spots available. Same crystal-clear water, same white sand, same sea turtles, and the same premium open bar from lunch. Book your spot before Sunday fills up too.",
            "hashtags": ["#KleinCuracao", "#BlueFinnCharters", "#SundayVibes"],
            "visual_suggestion": "photo of guests snorkeling near Klein Curaçao",
            "reasoning": "Class C operational — Saturday sold out, redirects demand to Sunday"
        }
    ]
})
```

## Tests
Run: `cd bluemarlin && python -m pytest tests/social/test_092_content_agent.py -v`

All 14 tests must pass. Tests 1-3 verify prompt construction reads from config. Tests 4-6 verify user prompt content. Tests 7-11 verify generation + storage with mocked Claude API. Tests 12-13 verify draft status CRUD. Test 14 verifies availability summary structure. Values tested against real client.json data (Klein Curaçao exists, Sunset Cruise exists, brand_voice and cta_default from social_content section).

## Success Condition
`generate_drafts(count=3)` produces structured draft posts from client.json data, stores them in SQLite with status "pending", and handles missing fields + API errors gracefully. The system prompt enforces premium brand positioning per SR's operating brief.

## Rollback
1. Delete `agents/social/content_agent.py`
2. Revert `shared/state_registry.py` to Brief 077 version
3. Remove `social_content` section from `config/client.json`
4. Delete `tests/social/test_092_content_agent.py`
