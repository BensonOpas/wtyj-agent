# OUTPUT 099 — Dashboard API Endpoints

**Brief:** marina_brief_099_dashboard_api.md
**Status:** Complete
**Date:** 2026-03-16

## What Was Done

1. **dashboard/api.py** created — FastAPI router with 15 endpoints: login, status, drafts CRUD (list/get/generate/approve/reject/publish/graphics/delete), image serving, learnings (list/distill/deactivate), availability, config. All endpoints are thin wrappers calling existing functions from Briefs 092-098.

2. **Auth system** — password from `DASHBOARD_PASSWORD` env var, verified at login, returns a session token. All endpoints require Bearer token. Password read at call time (not import time) to avoid test ordering issues.

3. **CORS middleware** added to webhook_server.py — allows localhost dev servers and production domain.

4. **Router mounted** on existing webhook_server.py — same process, same port. Dashboard routes at `/dashboard/api/*`, WhatsApp routes unchanged.

## Test Results
```
dashboard API tests: 12/12 PASSED
social regression: 187/187 PASSED
```

## Unexpected
Import-time env var read for `DASHBOARD_PASSWORD` caused 500 errors when running the full test suite (module imported before test's `setdefault` ran). Fixed by reading password at call time in the login endpoint.
