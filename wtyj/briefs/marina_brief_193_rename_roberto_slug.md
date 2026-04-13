# BRIEF 193 — Rename Roberto slug to consultadespertares
**Status:** Draft | **Files:** `.claude/commands/brief.md`, `wtyj/briefs/infra.md`, `tools/control-panel/data/clients.json`, `tools/control-panel/data/tasks.json`, `tools/control-panel/src/pages/SystemMap.tsx`, `memory/project_open_work.md` (doc/data updates only) | **Depends on:** — | **Blocks:** —

## Context

Roberto's business is called "Consulta Despertares" (psychology practice). The container slug is currently "roberto" — visible in the nginx URL prefix (`/roberto/`), the VPS directory (`/root/clients/roberto/`), the Docker container name (`wtyj-roberto`), and the dashboard workspace code operators type to log in. The slug should reflect the actual business for clarity and professionalism — operators typing "consultadespertares" as their workspace code is more meaningful than "roberto."

## Why This Approach

Pure infrastructure rename — no Python source code changes. Brief 191 already removed all hardcoded "roberto" from source. The rename touches only VPS files (directory, docker-compose, nginx, client.json) and local documentation (brief.md deploy commands, infra.md). Port 8003 stays the same.

### Rejected alternatives

1. **Keep "roberto" as the internal slug, only change client.json business.name.** Rejected: the user explicitly wants the full slug rename so the URL and workspace code match the business.

## Instructions

All VPS commands run via SSH. The Python regression suite runs locally on Mac (no source changes, just doc updates).

### Step 1 — Stop the Roberto container

```bash
ssh root@108.61.192.52 "cd /root/clients/roberto && docker compose down"
```

### Step 2 — Rename the directory

```bash
ssh root@108.61.192.52 "mv /root/clients/roberto /root/clients/consultadespertares"
```

### Step 3 — Update docker-compose.yml container name

SSH and edit `/root/clients/consultadespertares/docker-compose.yml`: change `container_name: wtyj-roberto` to `container_name: wtyj-consultadespertares`. The rest (image, ports, volumes) stays identical.

### Step 4 — Update client.json business name

SSH and update `/root/clients/consultadespertares/config/client.json`: change `"name": "Roberto"` to `"name": "Consulta Despertares"`.

### Step 5 — Update nginx

SSH and edit `/etc/nginx/sites-available/api-wetakeyourjob`: change `location /roberto/` to `location /consultadespertares/`. The `proxy_pass http://127.0.0.1:8003/` stays the same (port unchanged). Then `nginx -t && systemctl reload nginx`.

### Step 6 — Start the renamed container

```bash
ssh root@108.61.192.52 "cd /root/clients/consultadespertares && docker compose up -d"
```

### Step 7 — Verify

```bash
ssh root@108.61.192.52 "curl -s http://localhost:8003/health && echo"
curl -s https://api.wetakeyourjob.com/consultadespertares/health
```

Both should return `{"status":"ok"}`. Also verify the OLD path is gone: `curl -s https://api.wetakeyourjob.com/roberto/health` should return 404 or fall through to BlueMarlin's root path.

### Step 8 — Update local documentation

**A. `.claude/commands/brief.md`** — the deploy command references `/root/clients/roberto`. Replace with `/root/clients/consultadespertares`. Also update the container name in health check commands.

**B. `wtyj/briefs/infra.md`** — update the Services table row from "Roberto Psychology (demo #3) | wtyj-roberto | 8003 | /root/clients/roberto/" to "Consulta Despertares (demo #3) | wtyj-consultadespertares | 8003 | /root/clients/consultadespertares/". Also update the nginx routing table, deploy commands, and any other "roberto" references.

**C. `tools/control-panel/data/clients.json`** — update the client name from "Roberto (Psychology)" to "Consulta Despertares".

**D. `tools/control-panel/data/tasks.json`** — update "Roberto setup" task title/description and any subtask references to "Roberto" → "Consulta Despertares".

**E. `tools/control-panel/src/pages/SystemMap.tsx`** — update the roadmap card item that says "Roberto + HD Azure" → "Consulta Despertares + HD Azure".

**F. `memory/project_open_work.md`** — replace "roberto" references (directory paths, container names, setup instructions) with "consultadespertares".

**No frontend change needed.** The dashboard login page (post-Brief 190 login fix) uses a free-text workspace code input — there is no hardcoded tenant list. The operator types "consultadespertares" as their workspace code, the frontend sends it as the path prefix to `api.wetakeyourjob.com/consultadespertares/dashboard/api/login`, nginx routes it to port 8003. No code change in `wtyj-frontend` repo.

### Step 9 — Do NOT touch

- Python source code — zero "roberto" hardcodes remain after Brief 191
- BlueMarlin or Adamus containers/config — untouched
- Port 8003 — stays the same
- The `wtyj-agent` Docker image — shared, not renamed
- VPS platform.env — stays in the renamed directory, contents unchanged

## Tests

No new tests. Run the existing regression suite to confirm no source code references "roberto" in a way that breaks:

`python3 -m pytest wtyj/tests/ -q` should report **893 passed / 0 failed** (unchanged baseline).

## Success Condition

`curl -s https://api.wetakeyourjob.com/consultadespertares/health` returns `{"status":"ok"}`. Dashboard login at `wetakeyourjob.com/dashboard/login` with workspace code "consultadespertares" and the existing access key works. `docker ps` shows `wtyj-consultadespertares` running on port 8003.

## Rollback

Reverse the steps: `docker compose down`, `mv consultadespertares roberto`, revert nginx, `docker compose up -d`. Under 2 minutes.
