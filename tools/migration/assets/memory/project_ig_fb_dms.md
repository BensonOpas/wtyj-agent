---
name: IG/FB DMs — using Zernio, not direct Meta API
description: Decision April 2026: use Zernio Inbox API for IG/FB DMs instead of direct Meta Graph API. Bypasses App Review.
type: project
---

**Decision changed:** Originally planned direct Meta Graph API for IG/FB DMs. Now using Zernio Inbox API instead.

**Why:** Zernio gives us 7 DM platforms for $10/mo add-on, bypasses Meta App Review entirely, and we already use their publishing API. Building direct Meta integrations for each platform would take weeks and cost more (Twitter API alone is $100/mo).

**Current Meta app permissions (unchanged):**
- whatsapp_business_management: granted
- whatsapp_business_messaging: granted
- public_profile: granted
- Pages connected: 0

**These Meta permissions are NO LONGER NEEDED since Zernio handles it:**
- pages_messaging (Facebook Messenger) — Zernio covers this
- instagram_manage_messages (IG DMs) — Zernio covers this

**WhatsApp:** Keep on Meta direct API for now (already built and working). Could migrate to Zernio WhatsApp later if consolidation is needed.

**How to apply:** When building DM integration, use Zernio `/v1/inbox/` endpoints. Connect IG/FB accounts in Zernio dashboard. Set up `message.received` webhook. Route incoming DMs through Marina's conversation handler.
