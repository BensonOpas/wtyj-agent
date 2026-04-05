# OUTPUT 142 — Docker Setup

## What was done

BlueMarlin is now running in a Docker container on the VPS. Both processes (email poller + webhook server) managed by supervisord inside a single container. systemd services disabled.

## Files created

- `Dockerfile` — python:3.12-slim, gws binary, pip packages, supervisord
- `.dockerignore` — excludes backups, tests, briefs, caches from image
- `supervisord.conf` — runs email-poller + webhook-server
- `requirements.txt` — 27 pinned packages
- `docker-compose.yml` — per-client template with volume mounts
- `deploy.sh` — build/start/stop/restart/logs/status commands
- `config/client.json.template` — skeleton for new clients

## VPS migration

- Docker installed (28.2.2)
- Image built from python:3.12-slim
- BlueFinn config + data mounted as volumes
- Container running on port 8001 (same as before — nginx unchanged)
- systemd services stopped and disabled (service files kept for rollback)

## Verification results

1. Container status: UP, stable (not restarting)
2. Internal health (localhost:8001): OK
3. External health (api.wetakeyourjob.com): OK
4. Dashboard API: responds with auth challenge
5. gws binary: v0.8.0 working inside container
6. SQLite DB: accessible via volume mount
7. Both supervisor processes: RUNNING state

## Unexpected issues

1. **setuptools v82+ removed pkg_resources** — supervisor requires `pkg_resources` which was removed from setuptools 82+. The slim image installed the latest setuptools. Fixed by pinning to `setuptools==75.8.0`.

2. **python-multipart missing** — FastAPI requires `python-multipart` for form data (file uploads). It was installed on the VPS system-wide but not in the pip requirements. Fixed by adding to requirements.txt.

3. **docker-compose volume paths** — The git repo root on VPS is `/root/`, not `/root/bluemarlin/`. Config/data paths needed `bluemarlin/` prefix. Fixed by updating volume mounts.

4. **Docker layer caching** — After changing requirements.txt, `docker compose build` used cached pip install layer. Required `--no-cache` to pick up changes.

## Rollback command (if needed)

```bash
docker compose down
systemctl start bluemarlin
systemctl start bluemarlin-social
```
