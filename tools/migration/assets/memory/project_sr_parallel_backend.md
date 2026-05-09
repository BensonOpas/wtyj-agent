---
name: SR's parallel Node backend (rebrand cleanup)
description: SR built a separate Node backend at api.unboks.org duplicating our Python wtyj-agent. Resolved 2026-05-05 — our Python stack stays canonical, the rebrand changes domain/repo names.
type: project
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
## What SR built (revealed 2026-05-05)

SR built a parallel Node/Express + Postgres backend on Replit (`api.unboks.org` — repo `calvin835/unboks-dashboard-api`) while we were shipping production infra in our Python `wtyj-agent`. He moved `dashboard.unboks.org` to point at his Node backend. His DB is empty. The backend has its own `conversations`/`messages` tables, a Zernio HMAC webhook stub, dashboard auth/JWT, and a stubbed escalation reply route — no AI, no Marina, no dm_agent, no multi-tenant routing, none of our infra.

**No technical reason was given for choosing Node/Express/Postgres.** SR's handover describes WHAT he built but never WHY. Likely just Replit's default Node template + Replit-managed Postgres = path of least resistance on Replit, not a deliberate stack decision.

## Resolved direction (Benson, 2026-05-05)

This is a **rebrand**, not a backend migration. Our Python `wtyj-agent` stays canonical:
- Our stack stays (Python / FastAPI / SQLite)
- Our webhook stays (we're the one Zernio talks to, calvin-csa runs here)
- Our data stays (4 tenants, 907 tests, deploy queue, canary pipeline)
- The repo gets renamed (e.g. `BensonOpas/wtyj-agent` → `BensonOpas/unboks-agent`)
- The API domain moves (`api.wetakeyourjob.com` → `api.unboks.org` or `.com`)

SR's Project 2 (Node backend) gets archived or repurposed.

## How to apply

- **Don't take "audit reports" from SR's Node backend at face value** — when he says "WhatsApp not connected" or "DB empty," that's because his system isn't the one Zernio is wired to. Verify against our Python backend at `api.wetakeyourjob.com` first.
- **Don't build features in `calvin835/unboks-dashboard-api`.** That repo is being archived as part of the rebrand cleanup.
- The "three projects" framing SR uses (public site / dashboard-api / control panel) is HIS Replit project structure — Benson doesn't endorse it. Don't propagate that vocabulary into our docs.
- Treat SR's words as authoritative for the public site UI, dashboard frontend UX, and copy. NOT for backend architecture, data schema, or stack choice.
