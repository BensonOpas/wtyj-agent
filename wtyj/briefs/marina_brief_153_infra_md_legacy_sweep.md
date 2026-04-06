# BRIEF 153 — Sweep Stale Legacy References Out of `infra.md`

**Status:** Draft
**Files:** `wtyj/briefs/infra.md`, `~/.claude/projects/.../memory/reference_email_accounts.md` (memory, not git)
**Depends on:** Briefs 150-152 (the WTYJ rename sweep). Brief 152 already partially updated infra.md but only the top + the project layout section. Brief 153 finishes the job in the rest of the document.
**Blocks:** Nothing. Pure documentation cleanup.

---

## Context

After Briefs 150-152, the platform layout looks like this on the VPS:
- Source tree: `/root/wtyj/`
- BlueMarlin runtime: `/root/clients/bluemarlin/`
- Adamus runtime: `/root/clients/adamus/`
- Image: `wtyj-agent`
- Containers: `wtyj-bluemarlin`, `wtyj-adamus`

Brief 152 updated the top of `infra.md` (canonical naming hierarchy + the legacy disambiguation note + the project-on-VPS table + the services table + the deploy commands at the top of the deploy section), but **did not** update:

- The Environment Variables intro paragraph (`All secrets live in /root/bluemarlin/config/bluemarlin.env` — wrong path AND wrong filename)
- The AZURE/EMAIL env var rows in the inventory table (descriptions reference "BlueFinn's app/tenant")
- The Credential files table (all rows use `/root/bluemarlin/config/...` paths)
- The Hardcoded constants table (mentions "BlueFinn's")
- The Email mailboxes table contains a wrong row claiming `marina@wetakeyourjob.com` is the polled BlueFinn Charters mailbox. Per Benson the actual polled mailbox is `hello@wetakeyourjob.com`. The `marina@` row was added based on a memory file I wrote earlier in the session that turned out to be wrong.
- The Email section's `Marina's inbox = hello@wetakeyourjob.com` row is **correct**, must NOT be touched.
- The Email section's `Production support = info@bluefinncharters.com (from client.json)` row is wrong — Brief 150 scrubbed BlueFinn's email out of client.json and replaced with butlerbensonagent@gmail.com
- The Services section heading (`## Services (Docker — as of Brief 142)`) is stale, AND the next sentence (`Single Docker container running both services via supervisord.`) directly contradicts the sentence after it which says "Two containers."
- The "Old services (systemd — disabled, kept for rollback)" subsection inside Services has dead unit names (`bluemarlin`, `bluemarlin-social`) referring to systemd units that were disabled in Brief 142 and don't reference the new file paths anymore.
- The gws section credentials file path uses the old name `bluemarlin-calendar-key.json` and old location `/root/bluemarlin/config/`.
- The `## Deploy Flow (Docker — as of Brief 142)` section is a stale duplicate of the post-Brief-152 deploy block already present higher in the document under `### Deploy commands (post-Brief-152)`. Brief 152 added the new block but didn't delete the old one.
- The "Old deploy flow (systemd — disabled, kept for rollback)" subsection references `/root/bluemarlin/` source path.

The doc is currently internally inconsistent — the top of the file says one layout, the bottom says another. The disambiguation note covers brief HISTORY but doesn't excuse infra.md itself being wrong.

There is also a memory file `~/.claude/projects/.../memory/reference_email_accounts.md` that incorrectly says "marina@wetakeyourjob.com" is BlueMarlin's actual polled inbox. The actual polled inbox is `hello@wetakeyourjob.com`. This memory file mislead me into making the wrong infra.md edit during the systemwide check. **Brief 153 must also fix the memory file** so the same mistake can't recur.

---

## Why This Approach

**Alternative considered: do the sweep inline as quick edits during the systemwide check.** Tried it. The user caught me changing `hello@wetakeyourjob.com` → `marina@wetakeyourjob.com` based on the bad memory file. The inline approach didn't catch the upstream wrongness in memory, propagated the mistake into infra.md, and the user had to revert. Lesson: doc sweeps with cross-references are NOT quick fixes — they need a brief so the source-of-truth questions get resolved before any edit lands.

**Alternative considered: leave the doc internally inconsistent with the disambiguation note as the only authoritative source.** Rejected. The disambiguation note is for the brief HISTORY (old briefs that legitimately predate the WTYJ rename). It's not an excuse to leave the LIVE infrastructure doc wrong. If someone reads infra.md to figure out where secrets live, they should get the right answer.

**Alternative considered: rewrite infra.md from scratch.** Rejected — too risky. There's a lot of correct content I'd potentially break or lose. Surgical sweep is safer.

**Tradeoff accepted:** the memory file `reference_email_accounts.md` has stale content beyond just the marina@ vs hello@ confusion. This brief only fixes that one wrong claim, not a full memory file rewrite. Other memory cleanup happens separately if needed.

---

## Source Material

### Authoritative facts (verified live in this session, do not change)

These are the values that infra.md must reflect after the sweep. Any line in infra.md that contradicts these is wrong and gets updated:

| Item | Truth |
|---|---|
| Source tree on VPS | `/root/wtyj/` |
| BlueMarlin runtime root | `/root/clients/bluemarlin/` |
| Adamus runtime root | `/root/clients/adamus/` |
| Docker image (single, shared) | `wtyj-agent:latest` |
| BlueMarlin container | `wtyj-bluemarlin` (port 8001:8001) |
| Adamus container | `wtyj-adamus` (port 8002:8001) |
| BlueMarlin platform.env | `/root/clients/bluemarlin/config/platform.env` |
| BlueMarlin calendar-key.json | `/root/clients/bluemarlin/config/calendar-key.json` |
| BlueMarlin azure_refresh_token.txt | `/root/clients/bluemarlin/config/azure_refresh_token.txt` |
| BlueMarlin email_thread_state.json | `/root/clients/bluemarlin/config/email_thread_state.json` |
| Adamus platform.env | `/root/clients/adamus/config/platform.env` |
| Adamus calendar-key.json | `/root/clients/adamus/config/calendar-key.json` |
| **Polled email address (BlueMarlin)** | **`hello@wetakeyourjob.com`** — this is the value of the EMAIL_ADDRESS env var in BlueMarlin's platform.env, AND the default in `email_poller.py` line 29 (`os.environ.get("EMAIL_ADDRESS", "hello@wetakeyourjob.com")`). NOT marina@. |
| Polled email address (Adamus) | Currently empty in Adamus's platform.env, which triggers the Brief 146 graceful-exit path (no email polling for Adamus until OAuth bootstrap is done). |
| Microsoft Azure CLIENT_ID | `28e94343-2f77-444c-ac32-58b7bed33b65` (the WTYJ Azure app — shared across all clients on the wetakeyourjob.com Microsoft 365 tenant) |
| Microsoft Azure TENANT_ID | `caac06b5-1420-4223-9dcc-ba4a670ec26a` |
| Google service account | `bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com` (rename to wtyj-* on roadmap, deferred) |
| Google service account key file (host) | `/root/clients/bluemarlin/config/calendar-key.json` and `/root/clients/adamus/config/calendar-key.json` (currently the same key, copied to both) |
| Google service account key file (container) | `/app/config/calendar-key.json` (mounted) |
| BlueMarlin spreadsheet ID | `1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I` |
| Adamus spreadsheet ID | `1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc` |
| Demo support email (escalations) | `butlerbensonagent@gmail.com` (Benson's personal — used as `business.support_email` in both client.json files) |

### What is NOT in scope to verify

- The DMARC TXT record (`v=DMARC1; p=none; rua=mailto:hello@wetakeyourjob.com; ...`) — the brief leaves this exactly as-is. The `hello@` in the DMARC record is the canonical address and is correct.
- The DKIM CNAME records — leave as-is.
- The SPF record — leave as-is.

### The memory file bug

`~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/memory/reference_email_accounts.md` currently has this entry:

```markdown
### marina@wetakeyourjob.com
- **Used by:** BlueFinn Charters (client #1)
- **Purpose:** Customer-facing inbox. Marina (the agent) reads emails here and replies as the BlueFinn team.
- **Provider:** Microsoft 365 / Outlook
- **Note:** Display name was "hello@wetakeyourjob.com" originally but the actual mailbox is now marina@. Code defaults to `EMAIL_ADDRESS` env var.
```

**This is wrong.** The actual polled mailbox is `hello@wetakeyourjob.com`. There may or may not also be a `marina@wetakeyourjob.com` mailbox in the GoDaddy account, but the platform doesn't poll it. The memory file got this backwards. Brief 153 must replace this entry with the correct facts:

```markdown
### hello@wetakeyourjob.com
- **Used by:** BlueMarlin Charters (deployed demo client #1)
- **Purpose:** Customer-facing inbox. Marina (the agent name in BlueMarlin's client.json) reads emails here and replies.
- **Provider:** Microsoft 365 via GoDaddy (one of 2 GoDaddy seats)
- **Note:** This is the literal address polled by email_poller. The platform's `business.agent_name` is "Marina" but the email address is `hello@`, not `marina@`.
- **Refresh token location:** `/root/clients/bluemarlin/config/azure_refresh_token.txt`
```

---

## Instructions

### Step 1 — Update infra.md "Environment Variables" intro paragraph

Replace:

```
All secrets live in `/root/bluemarlin/config/bluemarlin.env`.
**NOT in `.bashrc`, `.zshrc`, or `.profile`** — never look there.
The systemd units source this file at startup.
```

With:

```
Each client has its own secrets file:
- BlueMarlin: `/root/clients/bluemarlin/config/platform.env`
- Adamus: `/root/clients/adamus/config/platform.env`

Loaded by docker-compose's `env_file:` directive at container start.
**NOT in `.bashrc`, `.zshrc`, or `.profile`** — never look there.
(Brief 145 renamed the file from `bluemarlin.env` → `platform.env`. Brief 150 moved it from `/root/bluemarlin/config/` to `/root/clients/<client>/config/`.)
```

### Step 2 — Update the AZURE/EMAIL rows in the env var inventory table

Replace:

```
| `AZURE_CLIENT_ID` | Email poller | Microsoft Azure app client ID. Default: BlueFinn's app. |
| `AZURE_TENANT_ID` | Email poller | Microsoft Azure tenant ID. Default: BlueFinn's tenant. |
| `EMAIL_ADDRESS` | Email poller | Inbox email address to poll. Default: hello@wetakeyourjob.com |
```

With:

```
| `AZURE_CLIENT_ID` | Email poller | Microsoft Azure app client ID. Default in source: `28e94343-2f77-444c-ac32-58b7bed33b65` (the WTYJ Azure app, shared across all clients on the wetakeyourjob.com Microsoft 365 tenant). |
| `AZURE_TENANT_ID` | Email poller | Microsoft Azure tenant ID. Default in source: `caac06b5-1420-4223-9dcc-ba4a670ec26a`. |
| `EMAIL_ADDRESS` | Email poller | Inbox email address to poll. BlueMarlin: `hello@wetakeyourjob.com` (also the source default). Adamus: empty (triggers Brief 146 graceful exit until OAuth bootstrap is done). |
```

### Step 3 — Update Credential files table

Replace the table:

```
### Credential files

| File | VPS Path | Purpose |
|------|----------|---------|
| `platform.env` | `/root/bluemarlin/config/platform.env` | All env vars above (renamed from bluemarlin.env in Brief 145) |
| `calendar-key.json` | `/root/bluemarlin/config/calendar-key.json` | Google service account key (renamed from bluemarlin-calendar-key.json) |
| `azure_refresh_token.txt` | `/root/bluemarlin/config/azure_refresh_token.txt` | Microsoft OAuth2 refresh token (persisted, auto-rotated) |
| `client.json` | `/root/bluemarlin/config/client.json` | Business config (not credentials — safe in git) |
```

With:

```
### Credential files (per-client, post-Brief-150)

| File | BlueMarlin path | Adamus path | Purpose |
|------|-----------------|-------------|---------|
| `platform.env` | `/root/clients/bluemarlin/config/platform.env` | `/root/clients/adamus/config/platform.env` | All env vars above |
| `calendar-key.json` | `/root/clients/bluemarlin/config/calendar-key.json` | `/root/clients/adamus/config/calendar-key.json` | Google service account key (currently the same physical key, copied to both during Brief 146 setup — see GCP roadmap note for the rename) |
| `azure_refresh_token.txt` | `/root/clients/bluemarlin/config/azure_refresh_token.txt` | (not yet — needs OAuth bootstrap for `sophia@wetakeyourjob.com`, see open work memory) | Microsoft OAuth2 refresh token (persisted, auto-rotated) |
| `client.json` | `/root/clients/bluemarlin/config/client.json` | `/root/clients/adamus/config/client.json` | Business config (not credentials — safe in git) |
```

### Step 4 — Update Email mailboxes table

Replace:

```
| Mailbox | Client | Password | Notes |
|---------|--------|----------|-------|
| `marina@wetakeyourjob.com` | BlueFinn Charters | (not recorded — uses stored OAuth refresh token) | Primary BlueFinn inbox. Polled by email_poller via Microsoft Graph OAuth. |
| `sophia@wetakeyourjob.com` | Restaurant Adamus (demo) | `Cur@ao2026` | Repurposed from a previously unused seat. Needs interactive OAuth login to generate initial refresh token. |
```

With:

```
| Mailbox | Client | Password | Notes |
|---------|--------|----------|-------|
| `hello@wetakeyourjob.com` | BlueMarlin Charters (deployed demo) | (not recorded — uses stored OAuth refresh token) | Primary BlueMarlin inbox. Polled by email_poller via Microsoft Graph OAuth. Refresh token at `/root/clients/bluemarlin/config/azure_refresh_token.txt`. |
| `sophia@wetakeyourjob.com` | Restaurant Adamus (deployed demo) | `Cur@ao2026` | Created in GoDaddy. Needs interactive OAuth login to generate initial refresh token before email polling can start. See `memory/project_open_work.md` IMMEDIATE section. |
```

### Step 5 — Update Hardcoded constants table

Replace:

```
| ~~Microsoft `CLIENT_ID`~~ | ~~email_poller.py:27~~ | Now env var `AZURE_CLIENT_ID` (default: BlueFinn's) | Azure app registration |
| ~~Microsoft `TENANT_ID`~~ | ~~email_poller.py:28~~ | Now env var `AZURE_TENANT_ID` (default: BlueFinn's) | Azure tenant |
| ~~`EMAIL_ADDR`~~ | ~~email_poller.py:29~~ | Now env var `EMAIL_ADDRESS` (default: hello@wetakeyourjob.com) | Inbox to poll |
```

With:

```
| ~~Microsoft `CLIENT_ID`~~ | ~~email_poller.py:27~~ | Now env var `AZURE_CLIENT_ID` (default: WTYJ Azure app `28e94343-...`) | Azure app registration |
| ~~Microsoft `TENANT_ID`~~ | ~~email_poller.py:28~~ | Now env var `AZURE_TENANT_ID` (default: `caac06b5-...`) | Azure tenant |
| ~~`EMAIL_ADDR`~~ | ~~email_poller.py:29~~ | Now env var `EMAIL_ADDRESS` (default: `hello@wetakeyourjob.com` for BlueMarlin; empty for Adamus triggers graceful exit) | Inbox to poll |
```

Also update the file reference:
```
| WhatsApp API version | whatsapp_client.py:14 | `v22.0` | Meta Cloud API version |
```
→
```
| WhatsApp API version | wtyj/agents/social/whatsapp_client.py:14 | `v22.0` | Meta Cloud API version |
```

### Step 5b — Fix the Services section header + intro

The Services section currently has a stale heading and an internally contradictory intro:

```
## Services (Docker — as of Brief 142)

Single Docker container running both services via supervisord.

Two containers, one shared image. Multi-client architecture proven and isolated as of Brief 152.
```

The line "Single Docker container running both services via supervisord" was true as of Brief 142 but is now contradicted by the very next sentence saying "Two containers." Replace the entire 4-line block with:

```
## Services (Docker — post Brief 152)

Two containers, one shared image. Multi-client architecture proven and isolated as of Brief 152.
```

(Just delete the stale heading qualifier and the contradictory "Single Docker container" sentence. Keep the "Two containers" sentence as the new intro.)

### Step 5c — Delete the "Old services (systemd — disabled, kept for rollback)" subsection

Inside the Services section, there's a stale subsection listing systemd unit names that no longer apply:

```
### Old services (systemd — disabled, kept for rollback)

| Service | Command to re-enable |
|---------|---------------------|
| `bluemarlin` (email poller) | `systemctl enable --now bluemarlin` |
| `bluemarlin-social` (webhook server) | `systemctl enable --now bluemarlin-social` |
```

Delete this entire subsection (heading + table). systemd has been disabled since Brief 142 and the unit files don't reference the new file paths anymore — the rollback is dead. The Docker compose path is the only deploy mechanism.

### Step 6 — Update Email section (preserve the "Marina's inbox" row verbatim, only fix the wrong "Production support" row and add Adamus)

The `Marina's inbox | hello@wetakeyourjob.com (Microsoft Outlook, OAuth2)` row must be preserved EXACTLY AS-IS — don't change the label, don't change the value, don't change the note in parentheses. The user explicitly corrected an earlier edit that touched this row.

Two surgical changes only:

**Change 6a:** Remove the wrong "Production support = info@bluefinncharters.com (from client.json)" row. Brief 150 scrubbed BlueFinn's email out of client.json, so this row no longer reflects reality. Find:

```
| Production support | `info@bluefinncharters.com` (from client.json) |
```

Delete that single row. The "Demo support/relay = butlerbensonagent@gmail.com" row above it stays.

**Change 6b:** Add a new row for Adamus's inbox. Find:

```
| Marina's inbox | `hello@wetakeyourjob.com` (Microsoft Outlook, OAuth2) |
```

Add a new row IMMEDIATELY BELOW it (do not modify the Marina's inbox row itself):

```
| Marina's inbox | `hello@wetakeyourjob.com` (Microsoft Outlook, OAuth2) |
| Adamus inbox (created, not yet polled) | `sophia@wetakeyourjob.com` (Microsoft Outlook via GoDaddy — needs OAuth bootstrap) |
```

After both changes, the Email table reads:
```
| Marina's inbox | `hello@wetakeyourjob.com` (Microsoft Outlook, OAuth2) |
| Adamus inbox (created, not yet polled) | `sophia@wetakeyourjob.com` (Microsoft Outlook via GoDaddy — needs OAuth bootstrap) |
| IMAP host | `outlook.office365.com:993` |
| SMTP host | `smtp.office365.com:587` |
| Demo support/relay | `butlerbensonagent@gmail.com` |
```

The "Marina's inbox" row text is byte-for-byte unchanged.

### Step 7 — Update gws (Google Workspace CLI) section

Replace:

```
| Binary path | `/usr/bin/gws` |
| Auth env var | `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` |
| Credentials file | `/root/bluemarlin/config/bluemarlin-calendar-key.json` |
| Spreadsheet ID | `1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I` |
| Service account | `bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com` |
```

With:

```
| Binary path | `/usr/local/bin/gws` (downloaded in Dockerfile from googleworkspace/cli releases) |
| Auth env var | `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` (set in each client's docker-compose `environment:` block) |
| Credentials file (BlueMarlin host) | `/root/clients/bluemarlin/config/calendar-key.json` |
| Credentials file (Adamus host) | `/root/clients/adamus/config/calendar-key.json` |
| Credentials file (inside container) | `/app/config/calendar-key.json` (mounted from host) |
| BlueMarlin spreadsheet ID | `1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I` |
| Adamus spreadsheet ID | `1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc` |
| Service account | `bluemarlin-calendar@bluemarlin-ops.iam.gserviceaccount.com` (rename to wtyj-* deferred — see roadmap) |
```

### Step 8 — Delete the old Deploy Flow section entirely (no replacement needed)

infra.md ALREADY has a correct post-Brief-152 deploy block earlier in the document, inside the Services section under `### Deploy commands (post-Brief-152)`. That block was added during Brief 152's post-execution sweep and contains the right commands.

The old `## Deploy Flow (Docker — as of Brief 142)` section further down the file is a stale duplicate. Delete it completely — no replacement needed.

**What to delete:** find the line `## Deploy Flow (Docker — as of Brief 142)` and delete everything from that line through the end of the next subsection `### Old deploy flow (systemd — disabled, kept for rollback)` (which contains a code block ending with `systemctl restart bluemarlin-social`). The next thing in the file should be `---` followed by `## Console Convention`.

Concretely, delete this entire block (text-anchored, not line-numbered):

```
## Deploy Flow (Docker — as of Brief 142)

```bash
# Code-only deploy (no new packages)
ssh root@108.61.192.52 "cd /root && git pull && docker compose build && docker compose up -d"

# Full rebuild (new packages or Dockerfile changes)
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build --no-cache && docker compose up -d"

# Check status
ssh root@108.61.192.52 "docker compose ps && curl -s http://localhost:8001/health"

# View logs
ssh root@108.61.192.52 "docker compose logs --tail=50"
```

Key auth configured — no password needed.

**Rollback to systemd (if Docker fails):**
```bash
ssh root@108.61.192.52 "docker compose down && systemctl start bluemarlin && systemctl start bluemarlin-social"
```

### Old deploy flow (systemd — disabled, kept for rollback)
```bash
ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin && systemctl restart bluemarlin-social"
```
```

After deletion, the `---` separator and `## Console Convention` heading should be the next thing in the file. The post-Brief-152 deploy block at the top of the Services section becomes the single source of truth.

### Step 9 — Update "Things Claude Code Keeps Getting Wrong" list

Replace the existing 7-item list with this 9-item list:

```
1. **API key location** — in each client's `platform.env` at `/root/clients/<client>/config/platform.env`. NOT in `.bashrc` or shell profile. NOT in source code.
2. **Poller is always running** — do not start it. Just restart the container after deploys (`docker compose down && up -d`).
3. **VPS source path** — `/root/wtyj/`, NOT `/root/bluemarlin/` (legacy, removed in Brief 151).
4. **VPS client deployment paths** — `/root/clients/bluemarlin/`, `/root/clients/adamus/`. Each client has its own `docker-compose.yml`.
5. **SSH from Claude Code** — works. Key auth set up. No password needed.
6. **bm_logger.log() first arg** — the parameter is named `event`. Never pass `event=` as a kwarg.
7. **Config caching** — `config_loader.get_raw()` returns a mutable dict. Modifying it in tests leaks between tests.
8. **CLIENT_CONFIG_PATH env var** — set in conftest.py for Mac dev tests so config_loader finds the moved client.json. Inside the container, the legacy default still resolves correctly.
9. **Use `trash` not `rm`** — macOS has `/usr/bin/trash`. Always use it for file deletions.
```

### Step 10 — Fix the memory file `reference_email_accounts.md`

This is a memory file (not git-tracked). Replace the wrong `marina@wetakeyourjob.com` entry with a correct `hello@wetakeyourjob.com` entry. See "The memory file bug" section above for the exact replacement.

This step is critical because the bad memory entry is what misled me into making the wrong infra.md edit during the systemwide check. If we don't fix the memory, the same mistake will happen again next session.

### Step 11 — Verify and grep for any remaining stale references

After the edits, run a broader grep that catches paths, filenames, the legacy systemd unit names, the "as of Brief 142" stale heading, and the "Single Docker container" contradiction:

```bash
grep -nE "/root/bluemarlin/|root-bluemarlin|bluemarlin-default|bluefinncharters|info@bluefinn|bluemarlin\.env|bluemarlin-calendar-key\.json|Single Docker container|as of Brief 142|systemctl.*bluemarlin|Old services.*systemd|Old deploy flow.*systemd" wtyj/briefs/infra.md
```

Expected matches:
- Inside the disambiguation note at the TOP of the file (lines 13-30 region), where these strings are listed as examples of what to ignore. These are intentional and stay.

Anything else is a miss — re-edit until the grep returns only the disambiguation-note matches.

Also do a manual visual scan: open the file in your editor and read the Services section, the Email section, the Credentials section, and make sure the layout matches the post-Brief-152 state.

### Step 12 — Commit and push

```
git add -A
git commit -m "Brief 153 — Sweep stale legacy references out of infra.md"
git push
```

No VPS deploy needed — this is doc-only.

---

## Tests

Doc-only brief, no test code. The verification step (Step 11 grep) is the test.

---

## Success Condition

`infra.md` no longer has any references to legacy paths/names from before the WTYJ rename (except the disambiguation note at the top which legitimately mentions them as examples). The Email section, Credentials table, Email mailboxes table, gws section, and Deploy Flow section all reflect the post-Brief-152 layout. The `marina@wetakeyourjob.com` entry in the memory file is replaced with the correct `hello@wetakeyourjob.com` entry. The `Marina's inbox = hello@wetakeyourjob.com` line is preserved verbatim per the user's correction.

---

## Rollback

Single git revert restores all of infra.md. Memory file change is non-git but trivially reversible by re-reading the old version from any backup or from the brief itself (the old text is quoted in "The memory file bug" section).
