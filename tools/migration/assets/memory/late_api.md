---
name: Late API
description: Late (getlate.dev) is the publishing gateway for Instagram. API key, account ID, SDK details.
type: reference
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
Late API (getlate.dev) — social media publishing service.
- Python SDK: `late-sdk` (pip install late-sdk)
- API key env var: `LATE_API_KEY`
- Instagram account ID: `69b8689d6cb7b8cf4c7846ff` (discovered at runtime via SDK)
- Instagram username: `@bluemarlincharters`
- Free tier: 20 posts/month, 60 requests/min
- Analytics: paid add-on ($10/mo on Build plan $19/mo = $29/mo total). Not active.
- Supports 14 platforms. Only Instagram connected currently. Facebook needs SR to connect.
- SDK key methods: `client.accounts.list()`, `client.media.upload(path)`, `client.posts.create(...)`, `client.posts.delete(id)`
- Account field name is `field_id` (not `id` or `_id`) due to Pydantic mapping

## Zernio webhook (Brief 199 era — 2026-05-03)

Late was rebranded as Zernio at some point. Zernio is now the source-of-truth name for the inbox/DM side; Late refers more to the legacy publishing SDK.

**Webhooks are profile-level**, not channel-level. The unboks Zernio profile (id `69ed4453b2337d1a9cb1c79c`) has webhook `unboks-dms` pointing at `https://api.wetakeyourjob.com/unboks/webhooks/zernio`, signed with HMAC-SHA256.

**Webhook secret rotation log:**
- 2026-05-03: rotated. Value lives in `/root/clients/unboks/config/platform.env` (`ZERNIO_WEBHOOK_SECRET=`) AND `/root/clients/bluemarlin/config/platform.env` (kept here for the canary E2E test which reads the secret from bluemarlin to sign synthetic test payloads). The old `bluemarlin-dms` Zernio webhook is still registered with its original secret; pending deletion once cutover is verified. The two webhooks fire in parallel during the transition; only the unboks one verifies and processes.

**Events enabled** on `unboks-dms`: `message.received` (required for inbound), plus eventually `message.failed`, `message.sent`, `account.disconnected` for production-grade ops.

**Conversation IDs in Zernio webhooks** are 24-char hex strings (e.g. `69f7cea6e99a2574e014abec`), NOT raw phone numbers. Means we can't match against a contact phone allowlist directly — would need an `ignored_conversations` list of these IDs instead.
