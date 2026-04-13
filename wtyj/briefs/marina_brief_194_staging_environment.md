# BRIEF 194 — Staging environment: branch + container + CI/CD routing
**Status:** Draft | **Files:** `.github/workflows/ci-deploy.yml`, `wtyj/briefs/infra.md` | **Depends on:** CI/CD pipeline (this session) | **Blocks:** —

## Context

The CI/CD pipeline deploys main → production directly. Before HD Azure goes live, we need a staging lane: push to staging branch → tests → deploy to staging container → manual verification → merge to main → deploy to production.

## Why This Approach

**One staging container (port 9001), not three.** All clients run the same image — testing code on one config shape proves it works on all.

**Git worktree for branch isolation.** The VPS has one repo at `/root/` on the `main` branch. Staging needs a DIFFERENT branch checked out simultaneously. `git worktree add /root/staging-code staging` creates a separate checkout of the staging branch without disturbing the main checkout. Production deploys `cd /root && git pull` (main). Staging deploys `cd /root/staging-code && git pull` (staging branch).

**Separate Docker image tag.** Staging builds `wtyj-agent:staging`, production uses `wtyj-agent:latest`. The staging container's docker-compose references `wtyj-agent:staging`. Building staging never overwrites the production image.

**Dummy API keys in staging.** Staging's `platform.env` has empty `LATE_API_KEY`, `WHATSAPP_ACCESS_TOKEN`, and a different `ZERNIO_WEBHOOK_SECRET` to prevent staging from sending real messages to customers or accepting production webhooks. `ANTHROPIC_API_KEY` stays real (Claude calls are what we're testing). `EMAIL_ADDRESS` is empty (email poller exits cleanly — no refresh token file in staging config, so `os.path.exists(REFRESH_TOKEN_PATH)` fails at `email_poller.py:358`).

### Rejected alternatives

1. **Same image tag for staging and production.** Rejected: building staging overwrites the production image. Next production container restart would run staging code.
2. **Checkout staging branch in the same `/root/` directory.** Rejected: production's `git pull` would pull staging code, or vice versa. Git worktree gives two independent checkouts.
3. **Copy production platform.env to staging.** Rejected: staging with real API keys can send real Zernio messages, create real calendar holds, and reply to real customers. Dummy keys prevent all external side effects except Claude.

## Instructions

### Step 1 — Create staging directory + git worktree on VPS

```bash
ssh root@108.61.192.52 '
  # Create staging branch worktree
  cd /root && git worktree add /root/staging-code staging 2>/dev/null || \
    (git branch staging && git worktree add /root/staging-code staging)

  # Create staging runtime dirs
  mkdir -p /root/staging/{config,data,logs}

  # Copy BlueMarlin client.json (config shape for testing)
  cp /root/clients/bluemarlin/config/client.json /root/staging/config/
  cp /root/clients/bluemarlin/config/calendar-key.json /root/staging/config/ 2>/dev/null

  echo "Staging worktree + dirs created"
'
```

### Step 2 — Create staging platform.env with dummy keys

```bash
ssh root@108.61.192.52 'cat > /root/staging/config/platform.env << "ENV"
ANTHROPIC_API_KEY=<REAL KEY — copy from BlueMarlin>
DASHBOARD_PASSWORD=staging
EMAIL_ADDRESS=
LATE_API_KEY=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_VERIFY_TOKEN=
ZERNIO_WEBHOOK_SECRET=staging-dummy-secret
ENV
echo "Staging platform.env created (dummy keys)"
'
```

Note: the `ANTHROPIC_API_KEY` must be copied from BlueMarlin's real env (it's the shared Claude key). All other outbound keys are empty — staging can think but can't talk to the outside world.

### Step 3 — Create staging docker-compose.yml

```bash
ssh root@108.61.192.52 'cat > /root/staging/docker-compose.yml << "COMPOSE"
services:
  agent:
    image: wtyj-agent:staging
    container_name: wtyj-staging
    restart: unless-stopped
    ports:
      - "9001:8001"
    env_file:
      - ./config/platform.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
    volumes:
      - ./config:/app/config:rw
      - ./data:/app/data
      - ./logs:/app/logs
COMPOSE
echo "Staging docker-compose created (image: wtyj-agent:staging, port 9001)"
'
```

### Step 4 — Add nginx location for staging

```bash
ssh root@108.61.192.52 '
  grep -q "location /staging/" /etc/nginx/sites-available/api-wetakeyourjob
  if [ $? -ne 0 ]; then
    sed -i "/location \/bluemarlin\//i\\
    location /staging/ {\\
        proxy_pass http://127.0.0.1:9001/;\\
        proxy_set_header Host \$host;\\
        proxy_set_header X-Real-IP \$remote_addr;\\
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\\
        proxy_set_header X-Forwarded-Proto \$scheme;\\
    }\\
" /etc/nginx/sites-available/api-wetakeyourjob
  fi
  nginx -t && systemctl reload nginx
  echo "Nginx staging block added"
'
```

### Step 5 — Build staging image + start container

```bash
ssh root@108.61.192.52 '
  cd /root/staging-code
  docker build -t wtyj-agent:staging -f Dockerfile .
  cd /root/staging && docker compose up -d
  sleep 3
  curl -s http://localhost:9001/health
'
```

### Step 6 — Update CI/CD workflow

Replace `.github/workflows/ci-deploy.yml` with the new version that has two deploy jobs:

- `deploy-staging`: runs on `staging` branch push, SSHs to VPS, does `cd /root/staging-code && git pull`, rebuilds `wtyj-agent:staging`, restarts the staging container, health checks port 9001
- `deploy-production`: runs on `main` branch push (unchanged from current), rebuilds `wtyj-agent:latest`, restarts all 3 production containers, health checks ports 8001-8003

### Step 7 — Create the staging branch on GitHub

```bash
git checkout -b staging
git push origin staging
git checkout main
```

### Step 8 — Verify

- `curl -s https://api.wetakeyourjob.com/staging/health` returns `{"status":"ok"}`
- `docker ps` shows `wtyj-staging` on port 9001
- Dashboard login with workspace "staging" and password "staging" works at `wetakeyourjob.com/dashboard/login`

### Step 9 — Update infra.md

Add staging section documenting the container, port, image tag, worktree, dummy keys, and the branch workflow.

### Step 10 — Do NOT touch

- Production containers, configs, image tag — unchanged
- Python source code — zero changes
- Staging email poller — exits cleanly (no `EMAIL_ADDRESS` set, no refresh token file)

## Tests

No new tests, no Python changes. Existing regression confirms nothing broke: `python3 -m pytest wtyj/tests/ -q` should report **893 passed / 0 failed**.

## Success Condition

- Staging container running on port 9001 with `wtyj-agent:staging` image
- `https://api.wetakeyourjob.com/staging/health` returns OK
- Pushing to `staging` branch triggers CI → tests → deploys ONLY to staging container
- Pushing to `main` triggers CI → tests → deploys ONLY to production containers
- Staging cannot send Zernio messages, WhatsApp messages, or poll email (dummy keys)

## Rollback

```bash
ssh root@108.61.192.52 "cd /root/staging && docker compose down && cd /root && git worktree remove staging-code && rm -rf /root/staging"
```
Remove nginx staging block, reload nginx. Delete staging branch: `git push origin --delete staging && git branch -d staging`. Revert workflow file.
