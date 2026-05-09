---
name: Zernio (Late) — full platform reference
description: Complete Zernio API reference. Account on SR's email (calvin@gaimin.io). API key in bluemarlin.env as LATE_API_KEY. Free tier, upgrading to Build + DMs ($29/mo).
type: reference
---

## Account Details
- **Zernio login:** calvin@gaimin.io (SR's email — move to BlueMarlin business email later)
- **API key env var:** `LATE_API_KEY` in `/root/bluemarlin/config/bluemarlin.env`
- **SDK:** `late-sdk` v1.3.35 on VPS. Import as `from late import Late` or `from zernio import Zernio` (same thing)
- **Current plan:** Free (upgrading to Build $19/mo + Comments & DMs $10/mo = $29/mo)
- **Billing anchor:** 16th of each month

## Connected Accounts (BlueMarlin's)
- **Profile:** "Default Profile" (ID: `69b868672cde65a782026248`)
- **Instagram:** `bluemarlincharters` / "BlueMarlin Tours Curaçao" (ID: `69b8689d6cb7b8cf4c7846ff`)
- **Facebook:** "BlueMarlin Tours Curacao" (ID: `69bb24a66cb7b8cf4c8074aa`)

## Plan Limits

| Plan | Price | Social Sets | Posts/mo | Req/min | Analytics | DMs |
|------|-------|-------------|----------|---------|-----------|-----|
| Free | $0 | 2 | 20 | 60 | No | No |
| Build | $19 | 10 | 120 | 120 | +$10 | +$10 |
| Accelerate | $49 | 50 | Unlimited | 600 | +$50 | +$50 |
| Unlimited | $999 | Unlimited | Unlimited | 1,200 | +$1,000 | +$1,000 |

- Posts/mo is TOTAL across all social sets, not per set
- Media uploads don't count separately
- Cross-post counting (1 call to 3 platforms = 1 or 3?) — unknown, test empirically
- Exceeding post limit: posting paused, no overage charges

## Publishing — 14 Platforms
Instagram, Facebook, X/Twitter, LinkedIn, TikTok, YouTube, Threads, Reddit, Pinterest, Bluesky, Telegram, Snapchat, Google Business, WhatsApp

## DMs — 7 Platforms (requires add-on)
- **Real-time webhook:** Instagram, Facebook, WhatsApp, Telegram
- **Polling:** X/Twitter, Bluesky, Reddit
- **NOT supported:** LinkedIn DMs (LinkedIn blocks third-party access)

## Comments — 8 Platforms (requires add-on)
Facebook, Instagram, YouTube, LinkedIn, Threads, X/Twitter, Reddit, Bluesky
- Instagram: can only REPLY to comments, not post new top-level ones
- Includes hide/unhide on FB, IG, Threads, X
- Reviews: Facebook + Google Business

## Webhook Events
`post.scheduled`, `post.published`, `post.failed`, `post.partial`, `post.cancelled`, `post.recycled`, `account.connected`, `account.disconnected`, `message.received`, `comment.received`, `webhook.test`
- Signed via `X-Zernio-Signature` (HMAC-SHA256)
- Max 3 retries, auto-disables after 10 consecutive failures
- Log retention: 7 days

## Hidden Features Worth Knowing
1. **Scoped API keys** — restricted keys per client (read-only or specific profiles). Important for multi-tenant.
2. **Post recycling** — auto-repost evergreen content on schedule
3. **Content validation** — `POST /v1/tools/validate/post-length` checks platform limits before publishing
4. **Duplicate detection** — 409 Conflict if identical content within 24 hours
5. **White-label** — API responses don't mention Zernio. Can resell.
6. **Bulk CSV upload** — schedule hundreds of posts via CSV
7. **MCP server** — official Claude Desktop integration
8. **Error classification** — failed posts get `errorCategory` (8 types) + `errorSource` (user/platform/system)
9. **Best-time analytics** — optimal posting times per day/hour (requires analytics add-on)
10. **Comment-to-DM automation** — auto-respond via DM when users comment specific keywords
11. **Chat SDK adapter** — `@zernio/chat-sdk-adapter` unified messaging adapter
12. **n8n integration** — official community node

## Architecture Decision
- Zernio = delivery layer (publishing + DMs for IG/FB/X)
- Our stack = intelligence layer (Claude/Marina for conversation handling, booking, escalations, content generation)
- WhatsApp stays on Meta direct API (booking flow built there, free, proven)
- If Zernio goes down: queue posts locally, retry. DMs delayed not lost.

## SDK Resources Available
`profiles`, `accounts`, `posts`, `media`, `inbox`, `connect`, `webhooks`, `messages`, `analytics`, `comments`, `reviews`, `tools`, `queue`, `logs`, `usage`
