# Mermaid TRACY real-tenant runbook

This runbook covers the real Unboks demo tenant. It does not create or serve a
Mermaid website.

## Asset map

| Asset | Required value |
|---|---|
| Tenant slug | `mermaid` |
| Internal display name | `Mermaid Boat Trips Demo` |
| Assistant | `TRACY` |
| Container | `wtyj-mermaid` |
| Loopback port | `8102` |
| Public API prefix | `https://api.unboks.org/api/mermaid/` |
| Dashboard | `https://dashboard.unboks.org/login?workspace=mermaid` |
| Zernio channel | WhatsApp |
| Demo number | `+599 9 686 5665` / `+59996865665` |
| Demo Facebook Page | `Klein Curaçao Trip Desk Demo` |

The existing Mermaid public number `+599 9 560 1530` and existing public Meta
profiles are out of scope for connection or mutation.

## Safe state progression

1. **Provisioned, disconnected:** container and routes are healthy; the strict
   Zernio allowlist is present and empty; `ai_auto_reply`, `whatsapp_inbox`, and
   `facebook_dms` are explicitly false in Nr3.
2. **Authorization pending:** a tenant-bound Zernio profile and stateful Meta
   link exist; the strict allowlist stays empty and every toggle stays false.
3. **Connected, quarantined:** the callback/phone-selection flow records the
   provider account and writes it into the strict allowlist. Verify that the
   displayed number normalizes to `+59996865665`, then verify the account has no
   ownership collision. Keep AI and channel toggles false throughout.
4. **Inbox-only canary:** enable only `whatsapp_inbox`; keep `ai_auto_reply`
   false. One tester message through the allowlisted provider account must be
   stored as paused in Mermaid and must not appear in Ali, Roberto, or Unboks.
5. **Controlled reply canary:** deliberately enable `ai_auto_reply`, send one
   published-fact question, and verify exactly one stored TRACY reply. Pause
   immediately again if identity, isolation, or reply-count checks fail.
6. **Demo ready:** factual reply, escalation, takeover, hand-back, and isolation
   checks are recorded. `facebook_dms` stays false unless Facebook messaging is
   separately connected and canaried.

Do not skip directly from provisioning to enabled traffic. An absent allowlist
is legacy-permissive; an empty strict allowlist is the required pre-connection
control.

## Acceptance conversation

Use a tester number that is not any tenant's own business number.

1. Ask: `What is the price for two adults and a seven-year-old?`
   TRACY must use only the approved USD/EUR/XCG bands and make no availability
   claim.
2. Ask: `Do you have four seats this Sunday?`
   TRACY must say it cannot see live seats and provide the official Mermaid
   reservation URL.
3. Ask: `Can I cancel tomorrow and get a refund?`
   TRACY must avoid promising a policy or refund and route the case to a human.
   The customer must not see `[ESCALATE]`.
4. In the Unboks inbox, take over the conversation and send one operator reply.
   Confirm the AI remains muted until hand-back.
5. Hand the conversation back and ask one published-fact question. Confirm AI
   resumes for only that conversation.

## Operational checks

- `wtyj-mermaid` is healthy on `127.0.0.1:8102`.
- `/api/mermaid/health` returns HTTP 200 through Nginx.
- Nr3 connection status identifies Zernio and the exact normalized demo number.
- `channel_account_allowlist.mode` is `strict` and contains exactly the account
  selected for that number.
- No provider event for Ali, Roberto, or Unboks appears in Mermaid's data.
- No Mermaid event appears in another tenant's data.
- No secret, callback state, OTP, or raw provider token is captured in evidence.

## Rollback checkpoints

The Mermaid installation has an explicit pre-TRACY configuration snapshot at
`/root/backups/mermaid-pre-tracy-20260902T182854Z/client.json`. The provisioner
does not create a general `/root/backups` configuration snapshot, and the normal
pre-deploy script snapshots tenant databases only.

Before every cutover, create a protected timestamped backup of Mermaid's
`client.json`, `platform.env`, `docker-compose.yml`, state database, Nginx site,
and currently running image ID. Do not copy a live secret into Git or demo
evidence.

For an application-only rollback, restore Mermaid's saved compose/image target
and recreate only `wtyj-mermaid`; the normal rollback script also includes
Mermaid and checks port 8102 once this branch reaches `main`. For a channel
rollback, disable AI and the Mermaid channel first, restore strict-empty account
isolation, then disconnect only the dedicated demo account/profile. Do not
remove the audit trail during a demo-day rollback.
