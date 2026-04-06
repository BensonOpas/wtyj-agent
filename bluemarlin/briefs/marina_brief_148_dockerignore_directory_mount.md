# BRIEF 148 — .dockerignore + Directory-Mount Refactor

**Status:** Draft
**Files:** `.dockerignore`, `docker-compose.yml`, `clients/adamus/docker-compose.yml`, `bluemarlin/tests/marina/test_148_dockerignore_directory_mount.py` (new)
**Depends on:** Brief 146 (Adamus deployment), Brief 147 (gws hardcoded path fix — essential prerequisite)
**Blocks:** None. This is the final piece of the multi-client architecture proof.

---

## Context

Brief 146 deployed Restaurant Adamus as a second container on the same VPS as BlueMarlin. During verification, we found that Adamus's `/app/config/` directory contained BlueMarlin's entire runtime config — `azure_refresh_token.txt`, `email_thread_state.json`, `platform.env`, `archived_threads.jsonl`, `heartbeat.txt`, plus stale files. None were mounted by Adamus's docker-compose. They were baked into the Docker image at build time because the `Dockerfile` does `COPY bluemarlin/ /app/` and on the VPS `/root/bluemarlin/config/` contains live runtime files that are gitignored on disk but present at build time. `docker build` does not read `.gitignore`.

For Brief 146 the orchestrator proof still worked — Adamus's volume mounts correctly overrode `client.json` and `calendar-key.json` at the file level, and `env_file:` wins over any baked-in `platform.env`. But the baked-in secrets are still on disk in Adamus's container. If a future client ever sets `EMAIL_ADDRESS` without explicitly mounting their own refresh token, they'd read BlueMarlin's inbox. That's a data leak waiting to happen.

An earlier Brief 147 attempt tried to solve this with `.dockerignore` + per-file mounts, but the reviewer flagged that the per-file approach was fragile (nonexistent host files silently become empty directories), that I had the `state_registry.db` location wrong (it's in `data/`, not `config/`), and crucially that three Python source files hardcoded the pre-Brief-145 filename `bluemarlin-calendar-key.json` and would break the moment we excluded `bluemarlin/config/*` from the image. The Python hardcoded-path bug was the critical blocker — any `.dockerignore` refactor landing before fixing it would have broken BlueMarlin's gws integration further.

**That blocker is now cleared.** Brief 147 landed this session and fixed the three source files to read `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` from the env var with a `calendar-key.json` default. Gws is verified working end-to-end (real row written to row 112 of the BlueMarlin spreadsheet during Brief 147's verification). The way is clear to land the architectural fix properly.

Brief 148 uses a **directory mount** approach instead of per-file mounts. Same concept — runtime config lives on the host and is overlaid into the container at runtime — but simpler, more robust, and doesn't require enumerating every file that might exist. One line per mount, no file-existence preconditions, automatically handles new runtime files added later without any config changes.

---

## Why This Approach

**Alternative considered: per-file bind mounts** (the old Brief 147 attempt).
- Rejected. Fragile — bind-mounting a host path that doesn't exist silently creates an empty directory at that location, which then fails when code tries to `open()` it as a file.
- Rejected. Doesn't scale — every new runtime file (heartbeat.txt, image_library.json, future .tmp files from interrupted writes) needs a new mount line.
- Rejected. The mount list is an enumeration of everything in the config dir — if you forget one, it gets baked into the image silently. No way to be confident the list is complete.

**Alternative considered: `.dockerignore` with `!` re-includes for static files (brand/, client.json.template, .gitkeep).**
- Rejected. Still leaves runtime files baked in unless every runtime filename is explicitly listed. Same enumeration problem as per-file mounts.
- Rejected. Complicated syntax — `.dockerignore` negation rules are subtle and error-prone.

**Chosen: directory mount `./bluemarlin/config:/app/config:rw` + `.dockerignore` exclusion of `bluemarlin/config/`.**
- One line in docker-compose replaces the host dir over the container's `/app/config/` entirely.
- `.dockerignore` excludes the dir from the image build so no runtime files get baked in, regardless of what's in the host dir at build time.
- The image's `/app/config/` is empty (created by `RUN mkdir -p /app/config` in Dockerfile). The mount overlays it at runtime.
- Each client owns their own config dir. Mounts are per-client. No shared state.
- Adds zero enumeration — whatever is in the host dir at runtime is what the container sees. New runtime files just work.

**Tradeoff accepted:** The mount is read-write, meaning the container can modify the host's config dir. This is intentional — the email_poller writes to `email_thread_state.json`, `archived_threads.jsonl`, `heartbeat.txt`, and `azure_refresh_token.txt` (rotation). A read-only mount would break Brief 145's refresh token rotation. Read-write is what we already had via per-file `rw` mounts, just now applied at the directory level.

**Tradeoff accepted:** Adamus's config dir (`clients/adamus/config/`) does not contain a `brand/` subdirectory. After the directory mount, Adamus's container has no `/app/config/brand/Inter-Bold.ttf`. The graphics engine would fail if called — but graphics is currently deactivated per roadmap and Adamus is a restaurant with no Instagram integration. Acceptable. Per-client brand assets is a separate future brief.

**Tradeoff accepted:** BlueMarlin's container will have `/app/config/platform.env` visible inside the container (it's part of the mounted host dir). Nothing reads it — env vars come from docker-compose's `env_file:` directive at startup, not from a file at runtime. But the file exists in the container's filesystem. This is the same state we had before Brief 148 (platform.env was baked into the image). Brief 148 doesn't make it worse — it just moves it from "baked into image" to "mounted from host." The file is BlueMarlin's own secrets sitting inside BlueMarlin's own container. No cross-tenant leak.

---

## Source Material

### Current `.dockerignore` (10 lines)

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

Does NOT exclude `bluemarlin/config/` — the gap Brief 148 fills.

### Current BlueMarlin `docker-compose.yml`

```yaml
services:
  bluemarlin:
    build: .
    container_name: bluemarlin-${CLIENT_NAME:-default}
    restart: unless-stopped
    ports:
      - "${PORT:-8001}:8001"
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

Three per-file mounts that will be consolidated into one directory mount.

### Current Adamus `clients/adamus/docker-compose.yml`

```yaml
services:
  bluemarlin:
    image: root-bluemarlin
    container_name: bluemarlin-adamus
    restart: unless-stopped
    ports:
      - "8002:8001"
    env_file:
      - ./config/platform.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
    volumes:
      - ./config/client.json:/app/config/client.json:ro
      - ./config/calendar-key.json:/app/config/calendar-key.json:ro
      - ./data:/app/data
      - ./logs:/app/logs
```

Same pattern, two per-file mounts to consolidate.

### VPS `/root/bluemarlin/config/` contents (verified 2026-04-06 by `ssh ... ls -la`)

```
.gitkeep              (0 bytes, static)
archived_threads.jsonl (63344 bytes — runtime PII, must persist)
azure_refresh_token.txt (1776 bytes — secret, must persist, auto-rotates)
brand/                (static directory, contains Inter-Bold.ttf)
calendar-key.json     (2393 bytes — secret)
client.json           (16496 bytes — BlueMarlin's runtime data, tracked in git)
client.json.template  (1664 bytes — static template)
email_thread_state.json (292481 bytes — HUGE state file with all thread history, must persist)
heartbeat.txt         (10 bytes — runtime artifact)
platform.env          (1252 bytes — secrets, gitignored on VPS)
state_registry.db     (0 bytes — stale file, real DB lives in data/state_registry.db)
```

All of these will be mounted into the BlueMarlin container via `./bluemarlin/config:/app/config:rw`. The 0-byte stale state_registry.db stays in the host dir but it's a no-op (the real DB is in `/root/bluemarlin/data/state_registry.db` which is mounted separately via the existing `./bluemarlin/data:/app/data` mount).

### VPS `/root/clients/adamus/config/` contents (verified 2026-04-06)

```
calendar-key.json     (2393 bytes — copied from BlueMarlin's file during Brief 146 setup)
client.json           (3884 bytes — Adamus's real data, tracked in git)
platform.env          (967 bytes — secrets, gitignored on VPS)
platform.env.example  (859 bytes — template, tracked in git)
```

All mounted into the Adamus container via `./config:/app/config:rw`. No brand/, no client.json.template, no state files — and that's correct, Adamus doesn't need them.

### Why directory mount + dockerignore together

The `.dockerignore` exclusion is defense in depth. The directory mount ALONE would work (mount overlays whatever's in the image, so baked-in files become invisible at runtime). But the `.dockerignore` adds two benefits:

1. **Smaller image.** Without the exclusion, every `docker build` copies 290+ KB of `email_thread_state.json` and 63 KB of `archived_threads.jsonl` into the image layers. These grow over time. Excluding them keeps the image small.

2. **Defense against mount removal.** If someone accidentally removes the volume mount (or a future docker-compose template omits it), the container would fall back to the baked-in image files. With `.dockerignore` excluding them, the fallback is an empty `/app/config/` directory — noisy failure, but no data leak.

### Brief 147 regression guard

Brief 147 fixed the hardcoded calendar key path. Brief 148 must not break this. The verification in Brief 147 passed because `calendar-key.json` was reachable at `/app/config/calendar-key.json` inside the container (via the per-file mount). After Brief 148, the same file is reachable at the same path, but via the directory mount. The Python code (`_KEY_PATH = os.environ.get('GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE', _DEFAULT_KEY_PATH)`) is agnostic to mount strategy — it just reads the env var, which compose sets to `/app/config/calendar-key.json`. So gws continues working as long as the file is at that path, which it is via the new mount.

This brief will re-run Brief 147's in-container subprocess trace after the rebuild to confirm gws still works end-to-end.

---

## Instructions

### Step 1 — Update `.dockerignore`

Replace the current `.dockerignore` content with:

```
# === Source-tree exclusions (build context size) ===
bluemarlin/backups/
bluemarlin/tests/
bluemarlin/briefs/
bluemarlin/src/

# === Runtime config — provided at runtime via volume mount, never in the image ===
bluemarlin/config/

# === Runtime data + logs — never in the image ===
bluemarlin/data/
bluemarlin/logs/

# === Per-client trees — each client mounts its own config via their own compose ===
clients/

# === Mac/macOS junk ===
**/.DS_Store

# === Python build artifacts ===
**/__pycache__/
**/.pytest_cache/
*.pyc

# === Repo metadata + docs ===
.git/
.gitignore
*.md
```

Notes on what's new vs the current file:
- **NEW**: `bluemarlin/config/` — the fix. Excludes the entire config dir (no re-includes, no exceptions).
- **NEW**: `bluemarlin/data/` — runtime database, graphics, photos, training data. Never in the image.
- **NEW**: `bluemarlin/logs/` — runtime log files.
- **NEW**: `clients/` — per-client trees (like `clients/adamus/`). They have their own docker-compose configs and should never be copied into BlueMarlin's image.
- **NEW**: `**/.DS_Store` — Mac junk.
- **KEPT**: all existing entries (`bluemarlin/backups/`, `bluemarlin/tests/`, `bluemarlin/briefs/`, `bluemarlin/src/`, `**/__pycache__/`, `**/.pytest_cache/`, `*.pyc`, `.git/`, `.gitignore`, `*.md`). These are pre-existing exclusions from Brief 142.

### Step 2 — Update BlueMarlin `docker-compose.yml`

Replace the current content with:

```yaml
services:
  bluemarlin:
    build: .
    container_name: bluemarlin-${CLIENT_NAME:-default}
    restart: unless-stopped
    ports:
      - "${PORT:-8001}:8001"
    env_file:
      - ./bluemarlin/config/platform.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
    volumes:
      - ./bluemarlin/config:/app/config:rw
      - ./bluemarlin/data:/app/data
      - ./bluemarlin/logs:/app/logs
```

Changes:
- Removed three per-file volume mounts for `client.json`, `calendar-key.json`, `azure_refresh_token.txt`.
- Added one directory mount `./bluemarlin/config:/app/config:rw`.
- Everything else unchanged (`build:`, `container_name:`, `restart:`, `ports:`, `env_file:`, `environment:`, data/logs mounts).

The `env_file:` directive still points at `./bluemarlin/config/platform.env` — this tells docker-compose to read the env vars from that file at container start. It is independent of the volume mount; docker-compose parses the env file on the host, before the container starts. The volume mount is for runtime file access inside the container.

### Step 3 — Update Adamus `clients/adamus/docker-compose.yml`

Replace the current content with:

```yaml
services:
  bluemarlin:
    image: root-bluemarlin
    container_name: bluemarlin-adamus
    restart: unless-stopped
    ports:
      - "8002:8001"
    env_file:
      - ./config/platform.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
    volumes:
      - ./config:/app/config:rw
      - ./data:/app/data
      - ./logs:/app/logs
```

Changes:
- Removed two per-file volume mounts for `client.json` and `calendar-key.json`.
- Added one directory mount `./config:/app/config:rw`.
- Still uses `image: root-bluemarlin` (Adamus doesn't rebuild, it uses the image BlueMarlin produces).
- Port 8002, container name `bluemarlin-adamus`, data/logs mounts unchanged.

### Step 4 — Write the tests

Create `bluemarlin/tests/marina/test_148_dockerignore_directory_mount.py`. All tests read files from the repo and assert string content. No Docker daemon required. Fast.

1. `test_dockerignore_excludes_bluemarlin_config` — read `.dockerignore`, assert `bluemarlin/config/` line is present (as a full line, not as a substring of something else).
2. `test_dockerignore_excludes_bluemarlin_data` — assert `bluemarlin/data/` line is present.
3. `test_dockerignore_excludes_bluemarlin_logs` — assert `bluemarlin/logs/` line is present.
4. `test_dockerignore_excludes_clients_dir` — assert `clients/` line is present (defensive).
5. `test_dockerignore_excludes_ds_store` — assert `**/.DS_Store` line is present.
6. `test_dockerignore_preserves_brief_142_exclusions` — regression guard: all of `bluemarlin/backups/`, `bluemarlin/tests/`, `bluemarlin/briefs/`, `bluemarlin/src/`, `**/__pycache__/`, `**/.pytest_cache/`, `*.pyc`, `.git/` still present.
7. `test_bluemarlin_docker_compose_has_config_directory_mount` — read `docker-compose.yml`, assert `./bluemarlin/config:/app/config:rw` is present.
8. `test_bluemarlin_docker_compose_no_per_file_mounts` — read `docker-compose.yml`, assert `./bluemarlin/config/client.json:/app/config/client.json` is NOT present (regression guard — old per-file mounts must be gone).
9. `test_bluemarlin_docker_compose_preserves_data_and_logs_mounts` — assert `./bluemarlin/data:/app/data` and `./bluemarlin/logs:/app/logs` are still present.
10. `test_bluemarlin_docker_compose_preserves_env_file` — assert `env_file:` still points at `./bluemarlin/config/platform.env`.
11. `test_bluemarlin_docker_compose_preserves_credentials_env_var` — assert `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json` still present in the `environment:` block.
12. `test_adamus_docker_compose_has_config_directory_mount` — read `clients/adamus/docker-compose.yml`, assert `./config:/app/config:rw` is present.
13. `test_adamus_docker_compose_no_per_file_mounts` — assert `./config/client.json:/app/config/client.json` is NOT present.
14. `test_adamus_docker_compose_preserves_data_and_logs_mounts` — assert `./data:/app/data` and `./logs:/app/logs` present.
15. `test_adamus_docker_compose_preserves_image_ref` — assert `image: root-bluemarlin` present (regression guard — Adamus must not start rebuilding its own image).
16. `test_adamus_docker_compose_preserves_port_mapping` — assert `"8002:8001"` present.

Tests must read files from the repo root at runtime, NOT recreate their content as string literals. Use `os.path` to locate them relative to the test file.

### Step 5 — Run tests locally

```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin
python3 -m pytest tests/marina/test_148_dockerignore_directory_mount.py -v
```

All 16 new tests must pass. Then run the full suite:

```bash
python3 -m pytest tests/ -q --tb=no
```

Expected: 665 + 16 = 681 total passed. Same 7 pre-existing failures unchanged. Zero new failures.

### Step 6 — Commit and push

```bash
git add -A
git commit -m "Brief 148 — .dockerignore + directory-mount refactor"
# Push manually due to security hook
```

### Step 7 — Deploy BlueMarlin rebuild to VPS

```bash
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build && docker compose up -d"
```

Critical: `docker compose down` then `build` then `up -d` ensures the container is stopped before the build, so there's no race between the old container touching files and the new build reading them.

Then verify health:

```bash
ssh root@108.61.192.52 "sleep 10 && docker compose ps && curl -s http://localhost:8001/health"
```

Expected: container `bluemarlin-default` running, `{"status":"ok"}`.

### Step 8 — Verify BlueMarlin's `/app/config/` has all the runtime files via the mount

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-default ls -la /app/config/"
```

Expected output — ALL of the following should be present (this is BlueMarlin's host dir mounted into the container):

- `.gitkeep`
- `archived_threads.jsonl` (~63 KB)
- `azure_refresh_token.txt` (~1.8 KB)
- `brand/` (directory)
- `calendar-key.json` (~2.4 KB)
- `client.json` (~16 KB)
- `client.json.template` (~1.7 KB)
- `email_thread_state.json` (~290 KB — THIS IS THE CRITICAL ONE; if it's missing or 0 bytes, BlueMarlin's thread state is lost)
- `heartbeat.txt`
- `platform.env`
- `state_registry.db` (0 bytes, stale, expected)

If `email_thread_state.json` is missing or empty, STOP and investigate — the mount didn't work correctly and BlueMarlin's conversation history is gone.

### Step 9 — Re-verify Brief 147 (gws still works)

Re-run the exact in-container subprocess trace from Brief 147's Step 10 to confirm gws still writes to the spreadsheet:

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-default python3 -c '
import sys, os, subprocess, json
sys.path.insert(0, \"/app\")
from agents.marina import sheets_writer

print(\"KEY_PATH:\", sheets_writer.KEY_PATH)
print(\"env var:\", os.environ.get(\"GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE\"))

original_run = subprocess.run
def trace_run(cmd, **kwargs):
    print(\"SUBPROCESS env CREDENTIALS:\", kwargs.get(\"env\", {}).get(\"GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE\", \"<unset>\"))
    result = original_run(cmd, **kwargs)
    print(\"SUBPROCESS returncode:\", result.returncode)
    print(\"SUBPROCESS stdout:\", (result.stdout or \"\")[:200])
    return result
sheets_writer.subprocess.run = trace_run

sheets_writer._append(\"All Events\", [\"2026-04-06\", \"Brief 148 verification\", \"directory mount\", \"\", \"\"])
'"
```

Expected: `KEY_PATH` and both env var references equal `/app/config/calendar-key.json`. `SUBPROCESS returncode: 0`. stdout contains a `tableRange` showing a successful append at some row (`'All Events'!A1:E113` or similar).

If gws fails here, Brief 148 broke Brief 147. Roll back immediately.

### Step 10 — Restart Adamus container (it uses the new image automatically)

```bash
ssh root@108.61.192.52 "cd /root/clients/adamus && docker compose down && docker compose up -d"
ssh root@108.61.192.52 "sleep 8 && docker compose -f /root/clients/adamus/docker-compose.yml ps && curl -s http://localhost:8002/health"
```

Expected: `bluemarlin-adamus` running, `{"status":"ok"}`.

### Step 11 — Verify Adamus's `/app/config/` has ONLY Adamus files

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-adamus ls -la /app/config/"
```

Expected output — ONLY the following should be present:

- `calendar-key.json` (~2.4 KB, copied from BlueMarlin's file earlier)
- `client.json` (~3.9 KB, Adamus's data)
- `platform.env` (~1 KB, Adamus's secrets)
- `platform.env.example` (~0.9 KB, template)

EXPLICITLY ABSENT (this is the security-critical verification):
- NO `azure_refresh_token.txt` (BlueMarlin's Microsoft OAuth token)
- NO `email_thread_state.json` (BlueMarlin's thread history)
- NO `archived_threads.jsonl` (BlueMarlin's archived conversations)
- NO `heartbeat.txt` (BlueMarlin's runtime artifact)
- NO `brand/` directory (BlueMarlin's font — Adamus doesn't need it)
- NO `client.json.template` (static template, not mounted from Adamus's dir)
- NO `state_registry.db` (stale file, not in Adamus's dir)
- NO `.gitkeep` from the image (the image's `/app/config/` is now empty, so even the `.gitkeep` from BlueMarlin is gone from Adamus)

If ANY of the "explicitly absent" files appear in Adamus's container, STOP — the .dockerignore didn't take effect or the mount didn't override properly. Investigate before declaring success.

### Step 12 — Verify Adamus's config_loader still returns Sofia

Brief 146's orchestrator proof must still work:

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-adamus python3 -c '
import sys
sys.path.insert(0, \"/app\")
from shared import config_loader
b = config_loader.get_business()
t = config_loader.get_raw().get(\"terminology\", {})
print(\"name:\", b.get(\"name\"))
print(\"agent_name:\", b.get(\"agent_name\"))
print(\"service_label:\", t.get(\"service_label\"))
'"
```

Expected:
```
name: Restaurant Adamus
agent_name: Sofia
service_label: reservation
```

### Step 13 — Final sanity check

```bash
ssh root@108.61.192.52 "curl -s http://localhost:8001/health && echo && curl -s http://localhost:8002/health && echo && docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep bluemarlin"
```

Both containers must return `{"status":"ok"}` and both must be in `Up` state.

---

## Tests

See Step 4. Sixteen tests in `bluemarlin/tests/marina/test_148_dockerignore_directory_mount.py`:

- 6 `.dockerignore` tests (5 new exclusions + 1 regression guard for pre-existing)
- 5 BlueMarlin docker-compose tests (new directory mount, no old per-file mounts, data/logs preserved, env_file preserved, credentials env var preserved)
- 5 Adamus docker-compose tests (new directory mount, no old per-file mounts, data/logs preserved, image ref preserved, port mapping preserved)

All tests read files from disk and assert string content. Fast. No Docker daemon required.

---

## Success Condition

Both `bluemarlin-default` (port 8001) and `bluemarlin-adamus` (port 8002) running on VPS after rebuild. Both healthy. Brief 147's gws subprocess trace re-runs successfully showing `returncode: 0` and a real row write. BlueMarlin's `email_thread_state.json` is ~290 KB inside the container (preserved via mount, not lost). Adamus's `/app/config/` contains ONLY Adamus's four files — NO `azure_refresh_token.txt`, NO `email_thread_state.json`, NO `archived_threads.jsonl`, NO `brand/`. Adamus's `config_loader.get_business()` still returns `Restaurant Adamus` / `Sofia`. All 16 new tests pass.

---

## Rollback

**If the BlueMarlin rebuild breaks production (container won't start, gws auth fails, email poller crashes):**

```bash
ssh root@108.61.192.52 "cd /root && git revert HEAD && docker compose down && docker compose build && docker compose up -d"
```

This reverts `.dockerignore` AND `docker-compose.yml` AND `clients/adamus/docker-compose.yml` AND the test file all together. BlueMarlin returns to the per-file mount configuration. gws still works (Brief 147's fix is untouched by the revert because it was in different source files). Adamus reverts to per-file mounts via the same commit revert.

**If BlueMarlin is fine but Adamus is broken:**

```bash
ssh root@108.61.192.52 "cd /root/clients/adamus && docker compose down"
```

BlueMarlin keeps running. Debug Adamus separately.

**If `email_thread_state.json` is empty or missing inside BlueMarlin after rebuild:**

This is a disaster scenario. Check `/root/bluemarlin/config/email_thread_state.json` on the host:
- If it still exists and is ~290 KB on the host, the mount is misconfigured. Fix the compose file.
- If it's missing or 0 bytes on the host, something external truncated or deleted it. Investigate host filesystem. BlueMarlin's thread history may be lost.

**If tests fail locally before deployment:**

Don't deploy. Fix the tests or the configs, re-run until green.
