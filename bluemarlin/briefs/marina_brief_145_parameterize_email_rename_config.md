# BRIEF 145 — Parameterize Email Poller + Rename Config Files
**Status:** Draft | **Files:** `agents/marina/email_poller.py`, `docker-compose.yml`, `deploy.sh` | **Depends on:** Brief 142 | **Blocks:** Adamus deployment

## Context

Deploying a second client (Restaurant Adamus) alongside BlueFinn on the same VPS. Two blockers:

1. Email poller hardcodes CLIENT_ID, TENANT_ID, EMAIL_ADDR — a second client with a different inbox can't use the same code without different values.
2. Config file names contain "bluemarlin" (bluemarlin.env, bluemarlin-calendar-key.json) — should be generic (platform.env, calendar-key.json) so every client uses the same file names.

## Why This Approach

Read email config from env vars with BlueFinn defaults. Backwards compatible — BlueFinn's .env doesn't need to set them (defaults kick in). New clients set different values in their .env.

Rename config files to generic names. Only docker-compose.yml and deploy.sh reference the file names. The actual code reads from env vars, not file names.

## Source Material

### email_poller.py lines 27-29:
```python
CLIENT_ID = "28e94343-2f77-444c-ac32-58b7bed33b65"
TENANT_ID = "caac06b5-1420-4223-9dcc-ba4a670ec26a"
EMAIL_ADDR = "hello@wetakeyourjob.com"
```

### docker-compose.yml:
```yaml
env_file:
  - ./bluemarlin/config/bluemarlin.env
environment:
  - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/bluemarlin-calendar-key.json
volumes:
  - ./bluemarlin/config/bluemarlin-calendar-key.json:/app/config/bluemarlin-calendar-key.json:ro
```

### deploy.sh line 9:
```bash
for f in config/client.json config/bluemarlin.env config/bluemarlin-calendar-key.json config/azure_refresh_token.txt; do
```

## Instructions

### Step 1: Parameterize email poller

In `agents/marina/email_poller.py`, change lines 27-29 from:
```python
CLIENT_ID = "28e94343-2f77-444c-ac32-58b7bed33b65"
TENANT_ID = "caac06b5-1420-4223-9dcc-ba4a670ec26a"
EMAIL_ADDR = "hello@wetakeyourjob.com"
```
to:
```python
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "28e94343-2f77-444c-ac32-58b7bed33b65")
TENANT_ID = os.environ.get("AZURE_TENANT_ID", "caac06b5-1420-4223-9dcc-ba4a670ec26a")
EMAIL_ADDR = os.environ.get("EMAIL_ADDRESS", "hello@wetakeyourjob.com")
```

### Step 2: Rename config refs in docker-compose.yml

Change from:
```yaml
    env_file:
      - ./bluemarlin/config/bluemarlin.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/bluemarlin-calendar-key.json
    volumes:
      - ./bluemarlin/config/client.json:/app/config/client.json:ro
      - ./bluemarlin/config/bluemarlin-calendar-key.json:/app/config/bluemarlin-calendar-key.json:ro
      - ./bluemarlin/config/azure_refresh_token.txt:/app/config/azure_refresh_token.txt:rw
      - ./bluemarlin/data:/app/data
      - ./bluemarlin/logs:/app/logs
```
to:
```yaml
    env_file:
      - ./bluemarlin/config/platform.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
    volumes:
      - ./bluemarlin/config/client.json:/app/config/client.json:ro
      - ./bluemarlin/config/calendar-key.json:/app/config/calendar-key.json:ro
      - ./bluemarlin/config/azure_refresh_token.txt:/app/config/azure_refresh_token.txt:rw
      - ./bluemarlin/data:/app/data
      - ./bluemarlin/logs:/app/logs
```

### Step 3: Rename config refs in deploy.sh

Change line 9 from:
```bash
for f in config/client.json config/bluemarlin.env config/bluemarlin-calendar-key.json config/azure_refresh_token.txt; do
```
to:
```bash
for f in config/client.json config/platform.env config/calendar-key.json config/azure_refresh_token.txt; do
```

### Step 4: Rename actual files on VPS

After deploying the code changes:
```bash
ssh root@108.61.192.52 "mv /root/bluemarlin/config/bluemarlin.env /root/bluemarlin/config/platform.env"
ssh root@108.61.192.52 "mv /root/bluemarlin/config/bluemarlin-calendar-key.json /root/bluemarlin/config/calendar-key.json"
```

## Tests

No new test file — these are config/infrastructure changes. Verification:

1. Existing tests pass (email_poller reads from env vars with defaults — no behavior change)
2. Docker container starts and health check passes after rename
3. BlueFinn still works end-to-end

## Success Condition

Email poller reads CLIENT_ID, TENANT_ID, EMAIL_ADDR from env vars. Config files have generic names. BlueFinn still works. Ready for second client deployment.

## Rollback

Revert code changes. Rename files back on VPS:
```bash
mv /root/bluemarlin/config/platform.env /root/bluemarlin/config/bluemarlin.env
mv /root/bluemarlin/config/calendar-key.json /root/bluemarlin/config/bluemarlin-calendar-key.json
```
