---
name: Email account inventory
description: All email accounts used by the WTYJ platform and what each one is for. Polled inboxes, escalation targets, test senders.
type: reference
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
## Preferred contact email (2026-05-05)

### hello@unboks.org
- **Status:** New polled mailbox for the unboks tenant going forward, per Benson 2026-05-05. Domain is `.org` not `.com` (`unboks.com` doesn't exist).
- **Purpose:** Public contact email — when prospects email the company, calvin-csa picks it up via the email_poller path on the unboks container and replies through the `dm_agent`/Q&A-only flow (booking_flow:false in the unboks `client.json`).
- **Provider:** Google Workspace (NOT Microsoft 365 like BlueMarlin's `hello@wetakeyourjob.com` and Adamus's `sophia@wetakeyourjob.com`).
- **Implication for code:** `wtyj/agents/marina/email_poller.py` currently only knows Microsoft Azure OAuth → Outlook IMAP. Adding Google needs Google OAuth + `imap.gmail.com:993` support. Recommended: env-var provider switch (`EMAIL_PROVIDER=google` vs `microsoft`) so future Google Workspace clients reuse the same path. Awaiting brief.
- **Mailbox status:** created in Google Workspace by SR. OAuth bootstrap + refresh token to `/root/clients/unboks/config/google_refresh_token.txt` (or similar — naming per the new code path) NOT done yet.

## Polled customer-facing inboxes

### hello@wetakeyourjob.com
- **Used by:** BlueMarlin Charters (deployed demo client #1)
- **Purpose:** Customer-facing inbox. The platform's email_poller polls this address. Replies are sent FROM this address. The agent's persona name in client.json is "Marina" but the email address itself is `hello@`, NOT `marina@`.
- **Provider:** Microsoft 365 via GoDaddy (one of 2 GoDaddy seats on the wetakeyourjob.com tenant)
- **Default in source:** `wtyj/agents/marina/email_poller.py:29` defaults `EMAIL_ADDRESS` to `hello@wetakeyourjob.com` if no env var is set
- **Refresh token location (VPS):** `/root/clients/bluemarlin/config/azure_refresh_token.txt`
- **CRITICAL:** Do not confuse with `marina@`. There may or may not be a `marina@wetakeyourjob.com` mailbox in GoDaddy, but the platform DOES NOT poll it. Earlier in this session I (Claude) wrote a memory file claiming `marina@` was the polled mailbox — that was wrong, and I made the wrong infra.md edit because of it. Always trust this file: the polled BlueMarlin mailbox is `hello@wetakeyourjob.com`.

### sophia@wetakeyourjob.com
- **Used by:** Restaurant Adamus (deployed demo client #2)
- **Purpose:** Customer-facing inbox for Adamus. Created in GoDaddy but **not yet polled** — needs interactive Microsoft OAuth bootstrap to generate the initial refresh token. Until that's done, Adamus's email_poller exits cleanly via the Brief 146 graceful-exit guard.
- **Provider:** Microsoft 365 via GoDaddy (the second of 2 GoDaddy seats)
- **Password:** `Cur@ao2026` (only used for the one-time browser-based OAuth bootstrap)
- **TODO:** see `memory/project_open_work.md` IMMEDIATE section — bootstrap script + token save to `/root/clients/adamus/config/azure_refresh_token.txt`

## Escalation / support email

### butlerbensonagent@gmail.com
- **Used by:** Both BlueMarlin and Adamus as `business.support_email` in their respective client.json files
- **Purpose:** Where escalations go when Marina/Sofia can't handle a customer message and need human review. Also where the platform sends operator notifications.
- **Provider:** Gmail (Benson's personal account)
- **Note:** This is the demo escalation target. For real clients, this should be replaced with the client's own operations email (e.g., the restaurant's owner's inbox).

## Test senders (not polled, never receive customer mail)

### ops.bluemarlindemo@gmail.com
- **Used by:** Test infrastructure only
- **Purpose:** Test sender for `wtyj/tests/marina/live_test_harness.py` — sends test emails TO Marina (the polled `hello@wetakeyourjob.com` address) to verify the email pipeline end-to-end. Not a real operations email.
- **Provider:** Gmail
- **Code reference:** `wtyj/tests/marina/live_test_harness.py:25` — `TEST_SENDER`

## Per-client mailbox naming convention (current state)

Currently both deployed clients use `wetakeyourjob.com` mailboxes:
- BlueMarlin → `hello@wetakeyourjob.com`
- Adamus → `sophia@wetakeyourjob.com`

The mailbox name does not have to match the agent name. BlueMarlin's agent is "Marina" but the mailbox is `hello@`. Adamus's agent is "Sofia" and the mailbox is `sophia@` (matches). The platform reads `EMAIL_ADDRESS` from each client's `platform.env` independently — agent name and mailbox address are decoupled.

## Future: Mailgun migration (Roadmap Milestone E)

Long-term plan: replace per-client Microsoft mailboxes with Mailgun routing.
- One Mailgun account
- Per-client subdomains or aliases (each client uses their own domain, e.g. `bookings@restaurantadamus.com`)
- Eliminates manual Outlook/Azure OAuth setup per client
- Currently deferred — Microsoft via GoDaddy works for first few clients
