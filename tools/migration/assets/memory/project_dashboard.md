---
name: Dashboard architecture
description: SR is building the React dashboard frontend, we build the API backend
type: project
---

The operator dashboard is the main product interface for business owners. SR is building the frontend (React + Tailwind + shadcn/ui). We build the backend API endpoints.

**Architecture split:**
- Our side: FastAPI endpoints at `/dashboard/api/*` (Brief 099, mounted on webhook_server.py)
- SR's side: React frontend consuming those endpoints
- Dashboard context doc for SR: `briefs/dashboard_context_for_sr.md`

**SR's 6-module vision (from his operating brief):**
1. Content Inbox — draft review, approve/reject, publish
2. Marina Escalation Center — urgent conversations, complaints
3. Client Submission Area — post ideas, upload photos, campaign instructions
4. Knowledge/Source of Truth Manager — edit trips, prices, FAQ, policies
5. Asset Library — approved photos/videos, brand assets
6. Activity/Audit Log — what the system did, who changed what

**Current API state:** Module 1 endpoints exist. Modules 2-6 need backend endpoints built when SR needs them.

**Dashboard password:** `demo` (stored as DASHBOARD_PASSWORD in bluemarlin.env on VPS)

**Why:** This is a white-label product feature sold to every client. Design must be client-agnostic — business name, colors, data change per client, dashboard stays the same.
