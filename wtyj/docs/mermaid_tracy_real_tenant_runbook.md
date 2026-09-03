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
- The response has exactly one `X-Unboks-Tenant: mermaid` header.
- `/api/not-a-real-tenant/health` returns HTTP 404 and has no
  `X-Unboks-Tenant` header.
- Nr3 connection status identifies Zernio and the exact normalized demo number.
- `channel_account_allowlist.mode` is `strict` and contains exactly the account
  selected for that number.
- No provider event for Ali, Roberto, or Unboks appears in Mermaid's data.
- No Mermaid event appears in another tenant's data.
- No secret, callback state, OTP, or raw provider token is captured in evidence.

Run `wtyj/scripts/smoke_unboks_domain.sh` for the public, read-only route
checks. To add authenticated profile and cross-tenant token checks, supply all
three environment variables named by that script from a protected operator
session. Never place their values in the command line, shell history, Git, or
demo evidence.

A legacy revision of the smoke script contained a dashboard credential. This
branch removes it, but Git history is not a secret store. Rotate that Unboks
dashboard credential through the normal protected operator workflow before the
demo; do not record the old or replacement value in this runbook or the PR.

## Canonical API routing

Every enabled tenant must have a literal Nginx location and a fixed loopback
upstream. The current production set used by this demo is:

| Public prefix | Fixed upstream |
|---|---|
| `/api/mermaid/` | `127.0.0.1:8102` |
| `/api/ali-car-rental/` | `127.0.0.1:8101` |
| `/api/consulta-despertares/` | `127.0.0.1:8103` |
| `/api/unboks/` | `127.0.0.1:8004` |

Add another tenant only by adding another explicit location after its runtime
exists. Never use a regex capture such as `/api/(?<tenant>...)/(.*)` with a
shared fallback upstream. That pattern makes nonexistent tenants look healthy
and lets the caller-selected slug be emitted as trusted identity. The server's
final `location /` must return 404 without proxying.

`ensure_dashboard_nginx.py` removes only the recognized legacy fallback to
port 8004, creates one explicit `/api/unboks/` route, rejects any unrecognized
API regex, and validates the final non-proxying 404. The dashboard deployment
then verifies authenticated Mermaid, Ali, and Unboks profiles, rejects tokens
used against a different tenant, and proves that an authenticated unknown slug
still returns 404.

## Live gluten-field drift and credential-preserving sync

The pre-merge live verification found that Mermaid's generated `client.json`
was missing the reviewed `faq.gluten_free` field and the corresponding bounded
gluten-free wording in `agent_persona.freeform_notes`. The live file also
contains generated dashboard credentials, a WhatsApp connection token, and
provider state that do not belong in Git and must not be replaced by the
tracked template.

After this commit is available in `/root/wtyj-agent-source`, first run the
narrow sync in dry-run mode:

```bash
python3 /root/wtyj-agent-source/wtyj/scripts/sync_mermaid_config_fields.py \
  --source /root/wtyj-agent-source/clients/mermaid/config/client.json \
  --target /root/clients/mermaid/config/client.json \
  --backup-dir /root/backups/mermaid-content-sync
```

It must report only `agent_persona.freeform_notes` and `faq.gluten_free` as
changed, or `none` if another reviewed process already synchronized them. To
apply the same two-field update, repeat the command with `--apply`. The tool:

- requires both documents to identify the `mermaid` tenant;
- requires the live target to be a real mode-0600 file;
- copies only those two reviewed content fields;
- preserves every other live field, including credentials, connection tokens,
  account allowlists, Facebook state, and provider identifiers;
- writes a mode-0600 backup under the mode-0700 backup directory; and
- aborts if the target changes during the operation.

The backup is credential-bearing. Keep it outside the repository and never
attach it to an issue, PR, log, or demo record. Do not use `cp` to replace the
live `client.json`, and do not export the live file for comparison. After an
approved apply, recreate only `wtyj-mermaid`, then repeat the health, paused
state, allowlist, dashboard profile, and isolation checks before enabling any
channel.

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
