# BRIEF 098 — Seasonal Awareness + Post-Publication Control
**Status:** Draft | **Files:** `config/client.json`, `agents/social/content_agent.py`, `agents/social/social_publisher.py`, `agents/social/auto_poster.py`, `shared/state_registry.py`, `tests/social/test_098_seasonal_and_control.py` (NEW) | **Depends on:** Brief 096 (Late publishing), Brief 097 (graphics overhaul) | **Blocks:** None

## Context
Two independent features in one brief. Part A: the content agent has no concept of time beyond "today's date" — it doesn't know about Curaçao's high/low season, Carnival, holidays, or school holiday periods. Adding a seasonal calendar to client.json lets the content agent generate timely Class D posts and adjust commercial tone by season. Part B: once a post is live on Instagram, there's no way to delete it through our system. Also, the Late post ID and Instagram URL aren't stored when publishing — just logged and forgotten. Fixing both gives operational control over published content.

## Why This Approach
Both features are additive and touch different file sections with no overlap. Seasonal data goes in client.json (Rule 4 — business data in config, not code). The content agent reads it and injects a `=== SEASONAL CONTEXT ===` section into the user prompt — same pattern as availability. Post control uses Late SDK's `posts.delete()` (verified: exists in SDK). Storing `late_post_id` and `instagram_url` in the existing `content_drafts` table (via ALTER TABLE) is simpler than a separate table and keeps all draft lifecycle data in one place.

## Source Material

### seasonal_calendar config (add to client.json)
```json
"seasonal_calendar": {
  "high_season": {"start_month": 12, "end_month": 4, "label": "High season — peak tourism, premium positioning"},
  "low_season": {"start_month": 5, "end_month": 11, "label": "Low season — awareness building, occupancy support"},
  "events": [
    {"month": 1, "day": 1, "name": "New Year's Day"},
    {"month": 2, "day": 1, "duration_days": 45, "name": "Carnival season", "note": "Biggest cultural event in Curaçao"},
    {"month": 4, "day": 27, "name": "King's Day", "note": "Dutch national holiday, celebrated in Curaçao"},
    {"month": 4, "day": 30, "name": "Dia di Rincon", "note": "Curaçao cultural celebration"},
    {"month": 5, "day": 1, "name": "Labour Day"},
    {"month": 7, "day": 2, "name": "Flag Day", "note": "Curaçao national flag day"},
    {"month": 10, "day": 10, "name": "Curaçao Day", "note": "Autonomy day — national holiday"},
    {"month": 12, "day": 25, "duration_days": 7, "name": "Christmas/New Year week", "note": "Peak bookings period"}
  ]
}
```

### Seasonal context format in user prompt
```
=== SEASONAL CONTEXT ===
Season: High season — peak tourism, premium positioning
Upcoming events (next 30 days):
  Carnival season (Feb 1 — ongoing, 12 days remaining)
  King's Day (Apr 27 — in 26 days)
```
If no upcoming events: `"No events in the next 30 days."`

### Late post delete (SDK verified)
```python
client.posts.delete(post_id="late_post_id_here")
# Returns PostDeleteResponse
```

### New columns for content_drafts
```sql
ALTER TABLE content_drafts ADD COLUMN late_post_id TEXT DEFAULT '';
ALTER TABLE content_drafts ADD COLUMN instagram_url TEXT DEFAULT '';
```

## Instructions

### Step 1 — Add seasonal_calendar to client.json

Add the `seasonal_calendar` section as a top-level key after `social_content` (before the closing `}`). Use the exact JSON from Source Material above.

### Step 2 — Add seasonal context to content_agent.py user prompt

**2a.** Add a `_build_seasonal_context()` function in content_agent.py, after `_build_client_context()` (after line 74) and before `_build_system_prompt()`:

```python
def _build_seasonal_context() -> str:
    """Build seasonal context from client.json seasonal_calendar."""
    raw = config_loader.get_raw()
    cal = raw.get("seasonal_calendar", {})
    if not cal:
        return "No seasonal data configured."

    today = datetime.now(_CURACAO_TZ)
    current_month = today.month
    lines = []

    # Determine current season
    high = cal.get("high_season", {})
    if high:
        start = high.get("start_month", 12)
        end = high.get("end_month", 4)
        # Handle wrap-around (Dec-Apr)
        if start > end:
            in_high = current_month >= start or current_month <= end
        else:
            in_high = start <= current_month <= end
        label = high.get("label", "High season") if in_high else cal.get("low_season", {}).get("label", "Low season")
        lines.append(f"Season: {label}")

    # Find upcoming events (next 30 days)
    events = cal.get("events", [])
    upcoming = []
    for event in events:
        e_month = event.get("month", 1)
        e_day = event.get("day", 1)
        e_name = event.get("name", "")
        duration = event.get("duration_days", 1)
        note = event.get("note", "")

        # Try this year and next year (handles Dec→Jan boundary)
        candidates = []
        for year in [today.year, today.year + 1]:
            try:
                candidates.append(today.replace(year=year, month=e_month, day=e_day))
            except ValueError:
                continue

        # Pick the nearest future or ongoing occurrence
        best = None
        for c in candidates:
            days_until_c = (c - today).days
            if -duration < days_until_c <= 30:
                best = c
                break
        if best is None:
            continue

        e_date = best
        days_until = (e_date - today).days
        event_end = e_date + timedelta(days=duration)
        days_remaining = (event_end - today).days

        if True:  # already filtered above
            if days_until < 0 and days_remaining > 0:
                desc = f"  {e_name} — ongoing, {days_remaining} days remaining"
            elif days_until == 0:
                desc = f"  {e_name} — today"
            else:
                desc = f"  {e_name} — in {days_until} days"
            if note:
                desc += f" ({note})"
            upcoming.append(desc)

    if upcoming:
        lines.append("Upcoming events (next 30 days):")
        lines.extend(upcoming)
    else:
        lines.append("No events in the next 30 days.")

    return "\n".join(lines)
```

**2b.** In `_build_user_prompt()`, add a seasonal context section after the availability section. Insert between the `=== AVAILABILITY ===` block and the `=== RECENT DRAFTS ===` block:

```python
    # Seasonal context
    seasonal_context = _build_seasonal_context()
```

And in the return f-string, add after `{avail_section}`:
```
=== SEASONAL CONTEXT ===
{seasonal_context}
```

**2c.** Update content_agent.py header to `# Last modified: Brief 098`.

### Step 3 — Add post tracking columns + delete support to state_registry.py

**3a.** Add ALTER TABLE statements inside `_get_conn()`, after the `image_path` ALTER TABLE:

```python
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN late_post_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE content_drafts ADD COLUMN instagram_url TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
```

**3b.** Add a function to store post tracking data, before `save_content_learning()`:

```python
def set_draft_published_info(draft_id: int, late_post_id: str, instagram_url: str) -> bool:
    """Store the Late post ID and Instagram URL after publishing."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_drafts SET late_post_id = ?, instagram_url = ? WHERE id = ?",
        (late_post_id, instagram_url, draft_id)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed
```

**3c.** Update both `get_content_drafts()` SELECT statements — change:
```
"created_at, approved_at, published_at, image_path "
```
to:
```
"created_at, approved_at, published_at, image_path, late_post_id, instagram_url "
```
And add to the return dict after `"image_path": r[12],`:
```python
            "late_post_id": r[13], "instagram_url": r[14],
```

**3d.** Update state_registry.py header to `# Last modified: Brief 098`.

### Step 4 — Add delete function to social_publisher.py

Add after `publish_to_instagram()`:

```python
def delete_post(late_post_id: str) -> bool:
    """Delete a published post from Instagram via Late. Returns True on success."""
    if not late_post_id:
        bm_logger.log("late_delete_no_post_id")
        return False
    client = _get_client()
    if not client:
        return False
    try:
        client.posts.delete(late_post_id)
        bm_logger.log("late_post_deleted", post_id=late_post_id)
        return True
    except Exception as e:
        bm_logger.log("late_delete_failed", post_id=late_post_id, error=str(e)[:200])
        return False
```

Update social_publisher.py header to `# Last modified: Brief 098`.

### Step 5 — Update auto_poster.py

**5a.** Update `cmd_publish()` — after `state_registry.update_draft_status(draft["id"], "published")`, add:

```python
            state_registry.set_draft_published_info(
                draft["id"],
                late_post_id=result.get("post_id", ""),
                instagram_url=result.get("post_url", "")
            )
```

**5b.** Add `cmd_delete(draft_id)` function:

```python
def cmd_delete(draft_id):
    """Delete a published post from Instagram."""
    drafts = state_registry.get_content_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        print(f"Draft #{draft_id} not found.")
        return
    if draft["status"] != "published":
        print(f"Draft #{draft_id} is not published (status: {draft['status']}).")
        return
    late_id = draft.get("late_post_id", "")
    if not late_id:
        print(f"Draft #{draft_id} has no Late post ID — cannot delete from Instagram.")
        return

    print(f"Deleting #{draft_id} from Instagram...")
    if social_publisher.delete_post(late_id):
        state_registry.update_draft_status(draft_id, "deleted")
        print(f"  → Deleted.")
    else:
        print(f"  → Delete failed (check logs).")
```

**5c.** Add argparse argument:
```python
parser.add_argument("--delete", type=int, metavar="ID", help="Delete a published post by draft ID")
```

**5d.** Add to the `any()` check:
```python
if not any([args.generate, args.review, args.publish, args.distill, args.status, args.graphics, args.delete]):
```

**5e.** Add to execution block:
```python
    if args.delete:
        cmd_delete(args.delete)
```

**5f.** Update auto_poster.py header to `# Last modified: Brief 098`.

### Step 6 — Create test file

Create `tests/social/test_098_seasonal_and_control.py`:

**Setup:** sys.path insert, env vars (including LATE_API_KEY).

**Imports:**
```python
from agents.social.content_agent import _build_seasonal_context, _build_user_prompt
from agents.social.auto_poster import cmd_delete
from agents.social import social_publisher
from shared import state_registry, config_loader
```

**Helpers:** `_cleanup_all()` — deletes content_drafts + content_learnings.

**Tests (10 total):**

1. **`test_seasonal_calendar_in_config`** — Call `config_loader.get_raw()`. Assert `"seasonal_calendar"` key exists. Assert `events` is a list with at least 5 items. Assert first event has `"name"` key.

2. **`test_build_seasonal_context_includes_season`** — Call `_build_seasonal_context()`. Assert result contains "Season:".

3. **`test_build_seasonal_context_in_user_prompt`** — Call `_build_user_prompt(3, days_ahead=7)`. Assert contains "SEASONAL CONTEXT".

4. **`test_set_draft_published_info`** — Save a draft, publish it. Call `state_registry.set_draft_published_info(draft_id, "late_123", "https://ig/p/test")`. Fetch draft back. Assert `late_post_id == "late_123"` and `instagram_url == "https://ig/p/test"`. Cleanup.

5. **`test_get_content_drafts_includes_new_fields`** — Save a draft. Fetch via `get_content_drafts()`. Assert returned dict has keys `late_post_id` and `instagram_url`. Cleanup.

6. **`test_seasonal_high_season_in_december`** — Use a datetime subclass mock to freeze time:
```python
from datetime import datetime as real_datetime, timezone, timedelta
_CURACAO_TZ = timezone(timedelta(hours=-4))

class FakeDatetimeDec(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 12, 15, 12, 0, 0, tzinfo=tz)

with patch("agents.social.content_agent.datetime", FakeDatetimeDec):
    result = _build_seasonal_context()
assert "High season" in result
assert "Low season" not in result
```

7. **`test_seasonal_low_season_in_june`** — Same technique with June:
```python
class FakeDatetimeJun(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 6, 15, 12, 0, 0, tzinfo=tz)

with patch("agents.social.content_agent.datetime", FakeDatetimeJun):
    result = _build_seasonal_context()
assert "Low season" in result
assert "High season" not in result
```
The subclass preserves `.replace()`, `.year`, `.month`, and timedelta arithmetic since it inherits from real `datetime`.

8. **`test_delete_post_success`** — Mock `Late` constructor via `patch("agents.social.social_publisher.Late")`. Set `mock_client.posts.delete.return_value = MagicMock()`. Call `social_publisher.delete_post("lp_1")`. Assert returns True. Cleanup.

9. **`test_delete_post_no_id`** — Call `social_publisher.delete_post("")`. Assert returns False.

10. **`test_cmd_delete_updates_status`** — Save a draft, set status to published, set published info with `late_post_id="lp_2"`. Mock `auto_poster.social_publisher.delete_post` to return True. Call `cmd_delete(draft_id)` with capsys. Assert stdout contains "Deleted". Assert draft status is "deleted". Cleanup.

## Tests
Run: `cd bluemarlin && python3 -m pytest tests/social/test_098_seasonal_and_control.py -v`

All 10 tests must pass. Tests 1-3 verify seasonal config and prompt injection. Tests 6-7 verify seasonal logic with patched dates. Tests 4-5 verify post tracking columns. Tests 8-10 verify delete functionality.

## Success Condition
Content agent user prompt includes seasonal context (current season + upcoming events from client.json). Published posts store their Late post ID and Instagram URL. `auto_poster.py --delete <id>` removes a post from Instagram and marks it as deleted.

## Rollback
1. Revert `config/client.json` — remove `seasonal_calendar` section
2. Revert `agents/social/content_agent.py` to Brief 093 version
3. Revert `agents/social/social_publisher.py` to Brief 096 version
4. Revert `agents/social/auto_poster.py` to Brief 096 version
5. Revert `shared/state_registry.py` to Brief 095 version
6. Delete `tests/social/test_098_seasonal_and_control.py`
