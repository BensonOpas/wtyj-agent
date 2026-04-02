# OUTPUT 098 — Seasonal Awareness + Post-Publication Control

**Brief:** marina_brief_098_seasonal_and_post_control.md
**Status:** Complete
**Date:** 2026-03-16

## What Was Done

**Part A — Seasonal Awareness:**
1. Added `seasonal_calendar` section to client.json — high/low season with month ranges + 8 Curaçao events (New Year's, Carnival, King's Day, Dia di Rincon, Labour Day, Flag Day, Curaçao Day, Christmas/New Year week).
2. Added `_build_seasonal_context()` to content_agent.py — determines current season (high/low based on month wrap-around logic), finds upcoming events within 30 days (handles year boundary for Dec→Jan), formats as `=== SEASONAL CONTEXT ===` section in user prompt.

**Part B — Post-Publication Control:**
3. Added `late_post_id` and `instagram_url` columns to content_drafts table. Added `set_draft_published_info()` function. Updated `get_content_drafts()` SELECT to include new fields.
4. Added `delete_post()` to social_publisher.py — calls Late SDK `posts.delete()`.
5. Added `--delete <id>` CLI command to auto_poster.py. Updated `cmd_publish()` to store Late post ID and Instagram URL when publishing.

## Test Results
```
seasonal + control tests: 10/10 PASSED
social regression: 175/175 PASSED
```

## Unexpected
Nothing unexpected.
