# OUTPUT 096 — Late Publishing Integration

**Brief:** marina_brief_096_late_publishing.md
**Status:** Complete
**Date:** 2026-03-16

## What Was Done

1. **social_publisher.py** created in agents/social/ — publishes to Instagram via Late SDK (`late-sdk` v1.2.89). Three functions: `get_instagram_account_id()` discovers connected Instagram account at runtime, `upload_media()` uploads JPEG to Late's media storage, `publish_to_instagram()` creates and publishes a post with caption + hashtags + image.

2. **cmd_publish() upgraded** in auto_poster.py — replaces stub with real Late API flow: discover account → auto-generate graphic if missing → upload image → publish to Instagram → update draft status. Errors handled at each step with skip + continue.

3. **test_094 updated** — `test_cmd_publish_stub` renamed to `test_cmd_publish_with_mocked_publisher` (mocks all publisher functions). `LATE_API_KEY` env var added to test setup.

## Test Results
```
publisher tests: 10/10 PASSED
test_094 regression: 10/10 PASSED
social regression: 163/163 PASSED
```

## Unexpected
Nothing unexpected. API endpoints were verified against real Late API before implementation — SDK handles presigned URL flow internally.
