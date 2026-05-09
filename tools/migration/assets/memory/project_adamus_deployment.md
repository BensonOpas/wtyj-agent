---
name: Restaurant Adamus — second client deployment (IN PROGRESS)
description: Phase 2 proof deployment. Beach club restaurant in Curaçao. Deploying as second container on same VPS alongside BlueFinn.
type: project
---

## Status (2026-04-06): PAUSED — waiting on email decision

Started deploying Restaurant Adamus as client #2 to prove Phase 2 multi-client architecture works. Hit a blocker on email (GoDaddy only has 2 seats, can't create sophia@wetakeyourjob.com without buying more). Decision made to migrate to Mailgun instead.

## What's been done

- **Brief 145 deployed:** `email_poller.py` parameterized (CLIENT_ID, TENANT_ID, EMAIL_ADDR now env vars). Config files renamed: `bluemarlin.env` → `platform.env`, `bluemarlin-calendar-key.json` → `calendar-key.json`. BlueFinn still working.
- **Quick fix:** `business.support_email` in client.json now drives escalation routing. Default fallback is butlerbensonagent@gmail.com.
- **Google Calendars created** for Adamus (by Benson, in butlerbensonagent@gmail.com Google account):
  - Lunch: `c3058824908775658a72e60877f8cea295b54b2b0d5c1c5a33c295e0ec2f8094@group.calendar.google.com`
  - Dinner: `5b51d6514c5576577fd39e8cb385c0fbcbfc285d283b8ca27095d322b9af50a1@group.calendar.google.com`
  - Both shared with service account `bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com`
- **Google Sheet created** for Adamus:
  - Spreadsheet ID: `1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc`
  - Shared with same service account

## What's blocked

- **Email inbox for Adamus** — was going to be sophia@wetakeyourjob.com but GoDaddy email plan has only 2 seats (marina@ is one, second one is something else). Would need to buy more seats, which doesn't scale. Decision: migrate to Mailgun.

## Adamus client.json (ready to create)

```json
{
  "business": {
    "name": "Restaurant Adamus",
    "email": "adamus@wetakeyourjob.com",
    "booking_email": "adamus@wetakeyourjob.com",
    "phone": "+599 9 XXX XXXX",
    "whatsapp": "+599 9 XXX XXXX",
    "location": "Jan Thiel Beach, Curaçao",
    "languages": ["English", "Dutch", "Spanish", "Papiamentu"],
    "operating_days": "Wednesday to Sunday",
    "agent_name": "Sofia",
    "agent_signature": "Sofia\nRestaurant Adamus",
    "support_email": "butlerbensonagent@gmail.com",
    "spreadsheet_id": "1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc"
  },
  "terminology": {
    "service_label": "reservation",
    "party_size_label": "diners",
    "slot_label": "seating"
  },
  "services": {
    "lunch": { "slots": [{"calendar_id": "c3058824...@group.calendar.google.com"}] },
    "dinner": { "slots": [{"calendar_id": "5b51d651...@group.calendar.google.com"}] }
  }
}
```

Full structure in `/Users/benson/.claude/plans/enumerated-coalescing-neumann.md` (approved plan).

## Decisions made

- Same VPS, second container on port 8002
- Generic file names (client.json, platform.env, calendar-key.json) ✅ DONE
- Parameterize email poller ✅ DONE
- Beach club restaurant, agent name: **Sofia**
- Orchestrator direct testing (no real WhatsApp/Zernio for Adamus)
- Google account for calendar ownership: **butlerbensonagent@gmail.com** (Benson's personal)
  - Note: bluemarlin-ops GCP project ID is permanent, will rename to agnostic name later (noted in roadmap 2026-04-06)
- Escalations for demo clients default to butlerbensonagent@gmail.com

## Next steps (when we resume)

1. **Decide email path:**
   - Path A: Mailgun migration (3 briefs) — replaces GoDaddy email entirely, unlimited addresses on any domain
   - Path B: Skip email for Adamus test, deploy without it, use orchestrator tests only

2. **If Path A (Mailgun):**
   - Benson creates Mailgun account (free tier)
   - Add wetakeyourjob.com sending domain
   - Update DNS at GoDaddy (SPF, DKIM, MX records)
   - WARNING: changing MX breaks marina@wetakeyourjob.com GoDaddy mailbox
   - Build Mailgun connector to replace IMAP polling in email_poller.py
   - Migrate BlueFinn to Mailgun, verify it works
   - Create adamus@wetakeyourjob.com as a Mailgun route
   - Deploy Adamus container

3. **If Path B (skip email):**
   - Create Adamus client.json (data above)
   - Create Adamus platform.env (only ANTHROPIC_API_KEY + EMAIL_ADDRESS left empty)
   - Create /root/clients/adamus/ on VPS with docker-compose.yml
   - Deploy second container on port 8002
   - Test orchestrator directly with Adamus config

## Files to reference

- **Plan file:** `/Users/benson/.claude/plans/enumerated-coalescing-neumann.md` (approved Adamus deployment plan)
- **Brief 145:** `bluemarlin/briefs/marina_brief_145_parameterize_email_rename_config.md`
- **Adamus docker-compose template:** Not yet created on VPS — needs `image: root-bluemarlin`, port 8002:8001
