---
name: Open work tracker — read this every session
description: Single source of truth for unfinished work, parked items, and next steps. Check this before starting any new work.
type: project
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
## Status as of 2026-04-11

**867 tests pass / 0 failures.** Three containers running on VPS:
- `wtyj-bluemarlin` (port 8001) — BlueMarlin Charters demo
- `wtyj-adamus` (port 8002) — Restaurant Adamus demo
- `wtyj-roberto` (port 8003) — Roberto psychology practice (empty shell, booking_flow=false)

All healthy. E2E tested across WhatsApp, Instagram, Facebook, Email, and Dashboard.

## Session 2026-04-09 to 2026-04-11 — Briefs shipped

- Brief 174: Marina tool use migration (root fix for parse failures)
- Brief 175: Date disambiguation ("next Saturday" = nearest upcoming)
- Brief 176: Context-aware fallback reply
- Brief 177: Phase 2 multi-client dashboard routing + Roberto container shell
- Brief 178: Email normalization + strengthened cross-channel rule
- Brief 179: Poller resilience (backoff, cleanup, forced exit)
- Brief 180: Prompt hardening (date verification, language matching, cancellation ref echo)
- Brief 181: Escalation contact_type + customer display_name update
- Brief 182: Persistent IMAP connection for email poller
- Brief 183: Escalation contact enrichment (real email/phone from customer file)
- Brief 184: Allow semi-escalation from fully-escalated conversations
- CORS fix for *.wetakeyourjob.com origins
- API contract for SR (wtyj/docs/dashboard_api_contract.md)
- Mobile API spec answers for SR (wtyj/docs/mobile_api_spec_answers.md)
- Dashboard frontend: Phone → Contact rename, escalation card total count fix

## IMMEDIATE — Going live infrastructure

Before HD Azure Realty goes live, the dev workflow needs to be production-grade:

1. **CI/CD pipeline** — GitHub Actions: push to main → run tests → deploy to VPS automatically. No more manual SSH deploy commands. ~20 lines of YAML. Eliminates the entire `ssh root@... && git pull && docker compose build` dance.

2. **Staging environment** — second set of containers on the VPS (ports 9001/9002/9003) with `staging-api.wetakeyourjob.com` nginx routes. Test changes before they hit a paying client's live WhatsApp. Push to `staging` branch → deploys to staging. Push to `main` → deploys to production.

3. **Client configs in git** — `client.json` and `platform.env` files currently float on the VPS filesystem, not version-controlled. If the VPS dies, all client configs are gone. Move to a private repo or encrypted config (secrets excluded via `.gitignore` + stored in GitHub Secrets or a vault).

4. **Automated backups** — Vultr VPS snapshot ($1/mo) + nightly SQLite database backup to Google Drive or S3. Non-negotiable once HD Azure's real customer data is flowing.

5. **Uptime monitoring** — UptimeRobot (free tier) pinging health endpoints every 60 seconds. Know the server is down before the client calls.

## IMMEDIATE — HD Azure Realty onboarding

First REAL paying client. Real estate in Curaçao. Website: hdazurerealty.com. Package: WhatsApp only + dashboard.

What's needed:
- Write `client.json` (real estate terminology, booking_flow TBD, agent persona TBD)
- Create Zernio profile for HD Azure, connect their WhatsApp Business
- Create `/root/clients/hdazure/` on VPS (same pattern as Adamus/Roberto)
- nginx location block `/hdazure/` → port 8004
- Dashboard access (workspace code + access key)
- Onboarding playbook: `docs/onboarding_playbook.md` — document the process this time

## IMMEDIATE — Roberto setup

Roberto has a psychology practice. WhatsApp-only, filter/buffer mode (booking_flow=false).
- Support contact: +34 653445607 (Roberto's personal — for the owner-ping feature)
- Customer-facing WhatsApp: Zernio US number (TBD, same Zernio account as BlueMarlin, different profile)
- Owner-ping feature: Brief deferred — add `business.owner_whatsapp` + extend notification dispatcher to send WhatsApp alert to Roberto when escalation is created

## Domain restructuring (decided, SR executing)

Target state — one domain, one project:
```
wetakeyourjob.com                     → WTYJ marketing site
wetakeyourjob.com/demo/bluemarlin     → BlueMarlin demo (hidden page)
wetakeyourjob.com/dashboard/login     → operator dashboard login
wetakeyourjob.com/dashboard/*         → operator console
api.wetakeyourjob.com                 → backend API (VPS)
```

SR is merging the 3 Replit projects into 1. BlueMarlin demo becomes a route. Dashboard becomes `/dashboard/*` routes. One GitHub repo: `wetakeyourjob-website`.

## SR's mobile app — API gaps

SR needs new backend endpoints for the mobile app:
- Mark read / mark unread for conversations (new endpoint + DB column)
- Push token registration + push notification payload (new endpoints)
- Unread count (depends on mark-read)
Everything else answered in `wtyj/docs/mobile_api_spec_answers.md`.

## Channel platform field

SR's bug report: IG/FB/X DMs are all stored as `channel: "whatsapp"`. Need to store the actual Zernio platform. The webhook already sends `platform: "whatsapp" | "instagram" | "facebook" | "twitter"` — just not stored. Small brief needed.

## Email poller — persistent connection deployed

Brief 182 shipped. Poller now keeps ONE IMAP connection alive across iterations with NOOP keepalive. Reconnects on error or every 45 min for token refresh. Zero "Command Error. 12" since deploy. Email poller also has the same fully-escalated guard bug as social_agent (Brief 184 fixed WhatsApp path only — email path deferred).

## Parked / longer-term

- Rename Google Cloud project (`bluemarlin-ops` → `wtyj-platform`) — DEFERRED
- Mailgun migration — DEFERRED, only needed at scale
- Email signature phone extraction for automatic cross-channel pre-linking (Brief 179 candidate)
- Username + password login (replace tenant dropdown) — discussed but deferred
- Owner-ping WhatsApp notification for Roberto — deferred until his number is provisioned
