# BRIEF 142 — Docker Setup: Containerize BlueMarlin
**Status:** Draft | **Files:** `Dockerfile`, `.dockerignore`, `supervisord.conf`, `requirements.txt`, `docker-compose.yml`, `deploy.sh`, `config/client.json.template` (all new files) | **Depends on:** Brief 141 | **Blocks:** None

## Context

The code is client-agnostic (Briefs 133-141). Any business type works with a different client.json. But deployment is manual — SSH in, git pull, restart systemd. For a second client, you'd set up an entire VPS from scratch.

Docker packages the application into a container. Same image for every client, different config mounted from outside. New client = fill in config, run one command.

## Why This Approach

One container per client running both processes (email poller + webhook server) via supervisord. Not two containers — SQLite doesn't handle cross-container file sharing well with locking.

python:3.12-slim base image. gws CLI downloaded as standalone binary (no Node.js needed). All config and data mounted as volumes so nothing is lost when the container restarts.

BlueFinn migrates from systemd to Docker as the proof-of-concept. Systemd services kept as rollback.

## Source Material

### Current VPS layout:
```
/root/bluemarlin/
├── agents/          ← source code
├── shared/          ← source code
├── dashboard/       ← source code
├── config/          ← client.json, bluemarlin.env, calendar key, azure token
├── data/            ← state_registry.db, graphics
├── logs/            ← bluemarlin.log
└── tests/           ← test files
```

### Path resolution in code (all relative to module location):
- `state_registry.py:10` — DB at `../data/state_registry.db` relative to `shared/`
- `bm_logger.py:9` — log at `../logs/bluemarlin.log` relative to `shared/`
- `email_poller.py:32` — config at `../../config/` relative to `agents/marina/`
- `gws_calendar.py` — reads `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` env var

### Current systemd services:
- `bluemarlin` — `python3 -m agents.marina.email_poller`
- `bluemarlin-social` — `uvicorn agents.social.webhook_server:app --host 127.0.0.1 --port 8001`

### Key Python packages (from VPS):
anthropic==0.84.0, fastapi==0.135.1, uvicorn==0.41.0, late-sdk==1.3.35, pillow==12.1.1, dateparser==1.3.0, google-api-python-client==2.191.0, google-auth==2.48.0, httpx==0.28.1, pydantic==2.12.5

### gws CLI binary:
URL: `https://github.com/googleworkspace/cli/releases/download/v0.8.0/gws-x86_64-unknown-linux-gnu.tar.gz`
Extracts to a single `gws` binary. Needs `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` env var at runtime.

## Instructions

### Step 1: Create requirements.txt

File: `requirements.txt` (project root, same level as `bluemarlin/`)

```
anthropic==0.84.0
anyio==4.12.1
certifi==2023.11.17
click==8.1.6
dateparser==1.3.0
fastapi==0.135.1
google-api-python-client==2.191.0
google-auth==2.48.0
google-auth-httplib2==0.3.0
googleapis-common-protos==1.72.0
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.6
late-sdk==1.3.35
pillow==12.1.1
pydantic==2.12.5
pydantic_core==2.41.5
regex==2026.2.28
sniffio==1.3.1
starlette==0.52.1
supervisor==4.2.5
typing_extensions==4.15.0
uritemplate==4.2.0
uvicorn==0.41.0
```

### Step 2: Create supervisord.conf

File: `supervisord.conf` (project root)

```ini
[supervisord]
nodaemon=true
logfile=/app/logs/supervisord.log
logfile_maxbytes=10MB
pidfile=/tmp/supervisord.pid

[program:email-poller]
command=python3 -m agents.marina.email_poller
directory=/app
autostart=true
autorestart=true
startsecs=5
startretries=3
redirect_stderr=true
stdout_logfile=/app/logs/email_poller.log
stdout_logfile_maxbytes=10MB

[program:webhook-server]
command=uvicorn agents.social.webhook_server:app --host 0.0.0.0 --port 8001
directory=/app
autostart=true
autorestart=true
startsecs=5
startretries=3
redirect_stderr=true
stdout_logfile=/app/logs/webhook_server.log
stdout_logfile_maxbytes=10MB
```

Note: webhook server binds to `0.0.0.0` (not `127.0.0.1`) because Docker needs it accessible from outside the container.

### Step 2b: Create .dockerignore

File: `.dockerignore` (project root)

```
bluemarlin/backups/
bluemarlin/tests/
bluemarlin/briefs/
bluemarlin/src/
**/__pycache__/
**/.pytest_cache/
*.pyc
.git/
.gitignore
*.md
```

This keeps backups (with old customer data), tests, briefs, caches, and git history out of the image. Only source code (agents, shared, dashboard, config template) gets copied.

### Step 3: Create Dockerfile

File: `Dockerfile` (project root)

```dockerfile
FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Download gws CLI binary
RUN curl -L https://github.com/googleworkspace/cli/releases/download/v0.8.0/gws-x86_64-unknown-linux-gnu.tar.gz \
    | tar xz --strip-components=1 -C /usr/local/bin/ gws-x86_64-unknown-linux-gnu/gws && \
    chmod +x /usr/local/bin/gws

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY bluemarlin/ /app/

# Copy supervisord config
COPY supervisord.conf /etc/supervisord.conf

# Create directories for mounted volumes (defaults if not mounted)
RUN mkdir -p /app/config /app/data /app/logs

# Expose webhook server port
EXPOSE 8001

# Run supervisord
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
```

### Step 4: Create docker-compose.yml template

File: `docker-compose.yml` (project root — template, copied per client)

```yaml
services:
  bluemarlin:
    build: .
    container_name: bluemarlin-${CLIENT_NAME:-default}
    restart: unless-stopped
    ports:
      - "${PORT:-8001}:8001"
    env_file:
      - ./config/bluemarlin.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/bluemarlin-calendar-key.json
    volumes:
      - ./config/client.json:/app/config/client.json:ro
      - ./config/bluemarlin-calendar-key.json:/app/config/bluemarlin-calendar-key.json:ro
      - ./config/azure_refresh_token.txt:/app/config/azure_refresh_token.txt:rw
      - ./data:/app/data
      - ./logs:/app/logs
```

Note: `client.json` and calendar key are `:ro` (read-only). `azure_refresh_token.txt` is `:rw` because the email poller writes to it on token refresh. `data/` and `logs/` are read-write.

### Step 5: Create deploy.sh

File: `deploy.sh` (project root)

```bash
#!/bin/bash
set -e

# Usage: ./deploy.sh [build|start|stop|restart|logs|status]

ACTION="${1:-start}"

# Validate required config files
for f in config/client.json config/bluemarlin.env config/bluemarlin-calendar-key.json config/azure_refresh_token.txt; do
    if [ ! -f "$f" ]; then
        echo "ERROR: Missing $f"
        exit 1
    fi
done

# Create data and logs directories if they don't exist
mkdir -p data logs

case "$ACTION" in
    build)
        echo "Building Docker image..."
        docker compose build
        echo "Done."
        ;;
    start)
        echo "Starting container..."
        docker compose up -d
        sleep 3
        docker compose ps
        echo ""
        echo "Health check:"
        curl -s http://localhost:${PORT:-8001}/health || echo "Health check failed"
        ;;
    stop)
        echo "Stopping container..."
        docker compose down
        ;;
    restart)
        echo "Restarting container..."
        docker compose restart
        sleep 3
        docker compose ps
        ;;
    logs)
        docker compose logs -f --tail=50
        ;;
    status)
        docker compose ps
        echo ""
        echo "Health check:"
        curl -s http://localhost:${PORT:-8001}/health || echo "Not responding"
        ;;
    *)
        echo "Usage: ./deploy.sh [build|start|stop|restart|logs|status]"
        exit 1
        ;;
esac
```

### Step 6: Create client.json.template

File: `config/client.json.template` (in the config directory)

```json
{
  "business": {
    "name": "BUSINESS_NAME",
    "email": "owner@business.com",
    "booking_email": "bookings@yourdomain.com",
    "phone": "+1234567890",
    "whatsapp": "+1234567890",
    "location": "Business Address",
    "languages": ["English"],
    "operating_days": "Monday to Friday",
    "agent_name": "Marina",
    "agent_signature": "Marina\nBUSINESS_NAME",
    "support_email": "owner@business.com",
    "spreadsheet_id": "GOOGLE_SHEETS_ID"
  },
  "payment": {
    "timing": "none",
    "methods": [],
    "cancellation_policy": ""
  },
  "features": {
    "booking_flow": true
  },
  "terminology": {
    "service_label": "service",
    "party_size_label": "guests",
    "slot_label": "time slot"
  },
  "booking_rules": {
    "required_fields": ["service_name", "date", "guests"],
    "hold_duration_hours": 24,
    "group_threshold_requires_human": 15,
    "max_bookings_per_thread": 3
  },
  "services": {
    "example_service": {
      "display_name": "Example Service",
      "description": "Description of the service",
      "price": 50,
      "capacity": 20,
      "days_available": "daily",
      "duration_hours": 2,
      "included": ["item1", "item2"],
      "slots": [
        {
          "time": "09:00",
          "resource": "Resource Name",
          "location": "Departure Location",
          "calendar_id": "GOOGLE_CALENDAR_ID@group.calendar.google.com"
        }
      ]
    }
  },
  "service_aliases": {},
  "faq": {
    "hours": "We operate Monday to Friday, 9am to 5pm.",
    "parking": "Free parking available on site."
  },
  "common_sense_knowledge": {
    "marina_persona": "Friendly, professional, and helpful."
  }
}
```

### Step 7: Install Docker on VPS

Run on VPS:
```bash
curl -fsSL https://get.docker.com | sh
```

Verify:
```bash
docker --version
docker compose version
```

### Step 8: Build and test

On VPS, in the project directory:
```bash
# Build the image
docker compose build

# Stop BOTH systemd services first to avoid duplicate email polling
systemctl stop bluemarlin
systemctl stop bluemarlin-social

# Start Docker container on port 8001
docker compose up -d

# Verify health
curl http://localhost:8001/health

# Check logs — both processes should show as started
docker compose logs --tail=20
```

If health check returns `{"status": "ok"}`, the container works. If anything is wrong:
```bash
# Rollback — stop Docker, start systemd
docker compose down
systemctl start bluemarlin
systemctl start bluemarlin-social
```

### Step 9: Verify nginx still routes correctly

```bash
curl -s https://api.wetakeyourjob.com/health
```

Should return `{"status": "ok"}`. nginx config doesn't change — it still proxies to `127.0.0.1:8001`.

### Step 10: Disable systemd services (but don't delete)

```bash
systemctl disable bluemarlin
systemctl disable bluemarlin-social
```

This prevents them from starting on reboot. The service files stay in case we need to rollback.

## Tests

No new Python test files — this is infrastructure, not code. Verification is done on the VPS:

1. `docker compose build` succeeds without errors
2. `curl http://localhost:8001/health` returns `{"status": "ok"}`
3. `docker compose ps` shows container status as "Up" after 60 seconds (not restarting)
4. `docker compose logs --tail=20` shows both `email-poller` and `webhook-server` started without errors
5. `curl -s https://api.wetakeyourjob.com/health` returns `{"status": "ok"}` (nginx → container works)
6. `curl -s https://api.wetakeyourjob.com/dashboard/api/status` returns JSON with `pending`, `published` etc. (dashboard API works through container)
7. `docker compose exec bluemarlin gws --version` returns version string (gws binary works inside container)
8. `docker compose exec bluemarlin python3 -c "from shared import state_registry; print(state_registry.wa_get_booking_state('test'))"` returns empty state dict (DB accessible)
9. Run `python3 -m pytest tests/social/ tests/marina/ -q --tb=no` locally to confirm no source code was changed

## Success Condition

BlueMarlin runs in a Docker container on the VPS. Both processes (email poller + webhook server) managed by supervisord. All traffic flows through nginx → container. systemd services disabled. Rollback possible in 30 seconds.

## Rollback

```bash
docker compose down
systemctl start bluemarlin
systemctl start bluemarlin-social
```
