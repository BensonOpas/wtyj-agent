# BRIEF 150 — Move BlueMarlin Deployment to `clients/bluemarlin/` + Rebrand client.json

**Status:** Draft
**Files:** `clients/bluemarlin/` (new dir tree with config/, docker-compose.yml), `docker-compose.yml` (delete at repo root), `deploy.sh` (delete at repo root), `bluemarlin/config/` (git-move contents to clients/bluemarlin/config/), `bluemarlin/data/.gitkeep` (git-move), `bluemarlin/logs/` (git-move if present), `bluemarlin/tests/marina/test_150_bluemarlin_deployment_layout.py` (new)
**Depends on:** Brief 148 (directory-mount refactor — both compose files use dir mounts)
**Blocks:** Brief 151 (source tree rename `bluemarlin/` → `wtyj/`)

---

## Context

Today BlueMarlin's deployment lives at `/root/bluemarlin/` on the VPS with config, data, and logs intermingled with the source code tree. Restaurant Adamus's deployment lives at `/root/clients/adamus/` with its own docker-compose and config directory. The layout is asymmetric — BlueMarlin is structurally elevated above Adamus even though both are supposed to be equal clients.

Brief 150 fixes the asymmetry. BlueMarlin's deployment moves to `/root/clients/bluemarlin/`, matching Adamus. After this brief:

```
/root/                                  (repo root on VPS)
├── bluemarlin/                         (SOURCE CODE only — agents/, shared/, dashboard/, tests/, briefs/, backups/)
├── clients/
│   ├── bluemarlin/                     (BlueMarlin's deployment — docker-compose, config, data, logs)
│   │   ├── docker-compose.yml
│   │   ├── config/
│   │   │   ├── client.json             (git-tracked, now rebranded to BlueMarlin Charters)
│   │   │   ├── client.json.template    (git-tracked)
│   │   │   ├── brand/                  (git-tracked, Inter-Bold.ttf)
│   │   │   ├── .gitkeep                (git-tracked)
│   │   │   ├── platform.env            (gitignored, VPS-only, secrets)
│   │   │   ├── calendar-key.json       (gitignored, VPS-only)
│   │   │   ├── azure_refresh_token.txt (gitignored, VPS-only, auto-rotates)
│   │   │   ├── email_thread_state.json (gitignored, VPS-only, runtime state)
│   │   │   ├── archived_threads.jsonl  (gitignored, VPS-only)
│   │   │   ├── heartbeat.txt           (gitignored, VPS-only)
│   │   │   └── state_registry.db       (gitignored, VPS-only, 0 bytes stale)
│   │   ├── data/                       (gitkeep + runtime)
│   │   └── logs/                       (gitignored runtime)
│   └── adamus/                         (Restaurant Adamus's deployment — already here)
├── Dockerfile                          (shared, still COPYs bluemarlin/ source)
└── requirements.txt
```

The `/root/docker-compose.yml` and `/root/deploy.sh` at the repo root are deleted — BlueMarlin now uses its own compose at `clients/bluemarlin/docker-compose.yml`, same as Adamus. The deploy command changes from `cd /root && docker compose ...` to `cd /root/clients/bluemarlin && docker compose ...` (exactly mirroring Adamus's deploy).

### The rebrand portion

BlueMarlin's `client.json` currently has BlueFinn's real company name, email, and phone number because the demo was loaded with BlueFinn's public website data for realism. This is an unauthorized live impersonation if the container ever becomes publicly reachable. Brief 150 scrubs the real-company identity from BlueMarlin's config while keeping the trip data (Klein Curaçao, sunset cruise, etc.) since the trip data is structure, not identity.

Specific field changes confirmed by Benson 2026-04-06:

| Field | Old | New |
|---|---|---|
| `business.name` | `BlueFinn Charters Curaçao` | `BlueMarlin Charters` |
| `business.email` | `info@bluefinncharters.com` (BlueFinn's real email) | `butlerbensonagent@gmail.com` (same as support_email) |
| `business.booking_email` | `hello@wetakeyourjob.com` | unchanged (already WTYJ's) |
| `business.phone` | `+599 9690 3717` (BlueFinn's real number) | `+15155005577` (Benson's Twilio line) |
| `business.whatsapp` | `+599 9690 3717` (same as above) | `+15155005577` |
| `business.agent_signature` | `Marina\nBlueFinn Charters Curaçao` | `Marina\nBlueMarlin Charters` |

Fields NOT touched (either already WTYJ's or business-structural, not identity):
- `support_email` (`butlerbensonagent@gmail.com`) — kept
- `demo_support_email` — kept
- `languages`, `operating_days`, `agent_name` — kept
- `services` (5 trip definitions) — kept, the structure is generic charter content
- `service_aliases` — kept, words like "klein curaçao" are geographical, not identity
- `resources` — has strings like "BlueFinn 1 (B&W)" and "BlueFinn 2 (Apache)" as boat display names. **These will also be renamed** to "BlueMarlin 1" and "BlueMarlin 2" for consistency. Actual boat model/length/capacity unchanged.

---

## Why This Approach

**Alternative considered: keep BlueMarlin at `/root/bluemarlin/` and just add a `clients/bluemarlin/` symlink.** Rejected. Symlinks inside a git repo add ambiguity and break on Windows checkouts. Move the files cleanly.

**Alternative considered: do the rebrand as a separate brief after the move.** Rejected. The brief is already modifying `client.json`'s location in git; rebranding it in the same commit means the git-move is captured with the new content. Two separate briefs would double the test cycle for no benefit.

**Alternative considered: rename the boat resources to be fully generic ("Boat 1", "Boat 2").** Rejected. "BlueMarlin 1" is consistent with the new business name and keeps the mental model "named boats belonging to a sailing company." Generic "Boat 1" loses the vibe. Benson can override if preferred.

**Tradeoff accepted:** the source tree stays at `bluemarlin/` for this brief. Brief 151 renames it to `wtyj/`. Mixing the two renames in one brief would be a bigger blast radius — deploy tools, docker-compose paths, test imports, sys.path, all in one commit. Brief 150 moves the DEPLOYMENT only; Brief 151 renames the SOURCE directory.

**Tradeoff accepted:** the `/root/docker-compose.yml` and `/root/deploy.sh` at the repo root get deleted. The BlueMarlin deploy command changes. Any muscle memory or automation that does `cd /root && docker compose up -d` will break and need updating to `cd /root/clients/bluemarlin && docker compose up -d`.

---

## Source Material

### Current `bluemarlin/config/client.json` business section (lines 1-22)

```json
"business": {
  "name": "BlueFinn Charters Curaçao",
  "email": "info@bluefinncharters.com",
  "booking_email": "hello@wetakeyourjob.com",
  "phone": "+599 9690 3717",
  "whatsapp": "+599 9690 3717",
  "location": "Jan Thiel Beach, z/n, Willemstad, Curaçao",
  "languages": ["English", "Dutch", "German", "Spanish", "Portuguese"],
  "operating_days": "7 days a week",
  "agent_name": "Marina",
  "agent_signature": "Marina\nBlueFinn Charters Curaçao",
  "spreadsheet_id": "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I",
  "support_email": "butlerbensonagent@gmail.com",
  "demo_support_email": "butlerbensonagent@gmail.com",
  "operating_mode": "full_booking"
}
```

### Current `resources` section (client.json lines 423-455)

```json
"resources": {
  "bluefinn1": {
    "display_name": "BlueFinn 1 (B&W)",
    "type": "sailing catamaran",
    "length_ft": 75,
    "max_guests": 65
  },
  "bluefinn2": {
    "display_name": "BlueFinn 2 (Apache)",
    "type": "sailing catamaran",
    "length_ft": 80,
    "max_guests": 95
  },
  "kailani": { ... unchanged ... },
  "red_dragon": { ... unchanged ... },
  "topcat": { ... unchanged ... }
}
```

The resource keys `bluefinn1` and `bluefinn2` are internal identifiers referenced by `services.klein_curacao.slots[*].resource` as the string `"BlueFinn1"` and `"BlueFinn2"`. The brief will rename both the JSON keys and the referenced strings in the services section together to keep them consistent. `kailani`, `red_dragon`, and `topcat` are unchanged — they're not BlueFinn-branded.

### Service slot resource references (client.json lines 236-246)

```json
"slots": [
  {
    "time": "08:00",
    "calendar_id": "...",
    "resource": "BlueFinn2",
    "location": "Jan Thiel Beach"
  },
  {
    "time": "08:30",
    "calendar_id": "...",
    "resource": "BlueFinn1",
    "location": "Jan Thiel Beach"
  }
]
```

Both `"resource": "BlueFinn2"` and `"resource": "BlueFinn1"` strings need to become `"BlueMarlin2"` and `"BlueMarlin1"` to match the renamed resource keys.

### Current VPS `/root/bluemarlin/config/` contents (verified 2026-04-06)

```
.gitkeep             0 bytes
archived_threads.jsonl  63344 bytes  (gitignored — runtime PII, must persist through the move)
azure_refresh_token.txt 1776 bytes   (gitignored — MS OAuth token, auto-rotates, must persist)
brand/                               (git-tracked — contains Inter-Bold.ttf)
calendar-key.json    2393 bytes      (gitignored — GCP service account key, must persist)
client.json          18853 bytes     (git-tracked — BlueMarlin business data, being rebranded)
client.json.template 1664 bytes      (git-tracked — static template)
email_thread_state.json  292481 bytes (gitignored — 290 KB of thread state, MUST persist)
heartbeat.txt        10 bytes        (gitignored — runtime)
platform.env         1252 bytes      (gitignored — secrets, must persist)
state_registry.db    0 bytes         (gitignored — stale file)
```

### Current VPS `/root/bluemarlin/data/` contents

```
.gitkeep             (tracked)
bluemarlin.db        (gitignored, 0 bytes)
graphics/            (gitignored runtime output)
photos/              (gitignored, Drive sync target)
state.db             (gitignored, 0 bytes)
state_registry.db    (gitignored, 303104 bytes — REAL DB, must persist)
training/            (gitignored LLM training data)
```

### Current `/root/docker-compose.yml` (repo root)

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

### Target `/root/clients/bluemarlin/docker-compose.yml` (to be created)

```yaml
services:
  bluemarlin:
    build:
      context: ../..
    image: root-bluemarlin
    container_name: bluemarlin-default
    restart: unless-stopped
    ports:
      - "8001:8001"
    env_file:
      - ./config/platform.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
    volumes:
      - ./config:/app/config:rw
      - ./data:/app/data
      - ./logs:/app/logs
```

Key differences from the current root compose:
- `build:` uses a `context: ../..` so the build context is still the repo root (where the Dockerfile lives). Without this, docker-compose would try to build in the `clients/bluemarlin/` directory and fail.
- `image: root-bluemarlin` added explicitly so the built image is tagged with the same name. Without this, the image would be auto-named `bluemarlin-bluemarlin` based on the directory + service. Keeping `root-bluemarlin` preserves consistency with the existing image that Adamus references (`image: root-bluemarlin` in Adamus's compose).
- `container_name: bluemarlin-default` is hardcoded — the old compose used `${CLIENT_NAME:-default}` which was a holdover from when there was no separate client tree. Simpler to hardcode now.
- Volume paths change from `./bluemarlin/config` to `./config` (relative to the new compose file's location).
- The `${PORT:-8001}` variable substitution is replaced with literal `"8001:8001"` for clarity.

### Dockerfile — no changes needed

The Dockerfile stays at `/root/Dockerfile` (repo root) and still does `COPY bluemarlin/ /app/`. The source tree is unchanged by Brief 150 — only the config/data/logs move. The Dockerfile doesn't care where the deployment lives; it only cares about the source tree being at `bluemarlin/` at the build context root.

---

## Instructions

### Step 1 — Rebrand `bluemarlin/config/client.json` (still at old path)

Edit `bluemarlin/config/client.json` BEFORE moving it. Change the `business` section and the `resources` section:

```json
"business": {
  "name": "BlueMarlin Charters",
  "email": "butlerbensonagent@gmail.com",
  "booking_email": "hello@wetakeyourjob.com",
  "phone": "+15155005577",
  "whatsapp": "+15155005577",
  "location": "Jan Thiel Beach, z/n, Willemstad, Curaçao",
  "languages": ["English", "Dutch", "German", "Spanish", "Portuguese"],
  "operating_days": "7 days a week",
  "agent_name": "Marina",
  "agent_signature": "Marina\nBlueMarlin Charters",
  "spreadsheet_id": "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I",
  "support_email": "butlerbensonagent@gmail.com",
  "demo_support_email": "butlerbensonagent@gmail.com",
  "operating_mode": "full_booking"
}
```

And in `resources`:

```json
"resources": {
  "bluemarlin1": {
    "display_name": "BlueMarlin 1",
    "type": "sailing catamaran",
    "length_ft": 75,
    "max_guests": 65
  },
  "bluemarlin2": {
    "display_name": "BlueMarlin 2",
    "type": "sailing catamaran",
    "length_ft": 80,
    "max_guests": 95
  },
  "kailani": {...unchanged},
  "red_dragon": {...unchanged},
  "topcat": {...unchanged}
}
```

And in `services.klein_curacao.slots`, update the two resource string references:

```json
{
  "time": "08:00",
  "calendar_id": "4ce23ea0...",
  "resource": "BlueMarlin2",
  "location": "Jan Thiel Beach"
},
{
  "time": "08:30",
  "calendar_id": "9f25610...",
  "resource": "BlueMarlin1",
  "location": "Jan Thiel Beach"
}
```

Leave everything else in client.json unchanged — agent_persona, social_content, seasonal_calendar, faq, common_sense_knowledge, and all other services. The client.json is being rebranded, not restructured.

**Also update agent_persona.freeform_notes** if it mentions BlueFinn by name. Check the current value and if it contains "BlueFinn", change to "BlueMarlin".

### Step 2 — Create `clients/bluemarlin/` directory tree in the repo

Using `git mv` to preserve history:

```bash
cd /Users/benson/Projects/bluemarlin-agent
mkdir -p clients/bluemarlin/config clients/bluemarlin/data clients/bluemarlin/logs
git mv bluemarlin/config/client.json clients/bluemarlin/config/client.json
git mv bluemarlin/config/client.json.template clients/bluemarlin/config/client.json.template
git mv bluemarlin/config/brand clients/bluemarlin/config/brand
git mv bluemarlin/config/.gitkeep clients/bluemarlin/config/.gitkeep
git mv bluemarlin/data/.gitkeep clients/bluemarlin/data/.gitkeep
```

After these moves, `bluemarlin/config/` and `bluemarlin/data/` should be empty on the Mac (no tracked files). Any gitignored runtime files on the Mac (shouldn't exist in dev, but check with `ls bluemarlin/config/ bluemarlin/data/`) stay where they are — they're the Mac's local copy and don't affect the VPS.

Create a `.gitkeep` in `clients/bluemarlin/logs/` so the directory is preserved in git even when empty:

```bash
touch clients/bluemarlin/logs/.gitkeep
git add clients/bluemarlin/logs/.gitkeep
```

### Step 3 — Create `clients/bluemarlin/docker-compose.yml`

Create the file with the content from the Source Material section above (the "Target" compose block). This includes `build.context: ../..`, `image: root-bluemarlin`, the hardcoded container name, the 8001 port, and the three directory mounts with `./config`, `./data`, `./logs` paths relative to the new compose file's location.

### Step 4 — Delete `/docker-compose.yml` and `/deploy.sh` at repo root

```bash
git rm docker-compose.yml
git rm deploy.sh
```

Both files are superseded. BlueMarlin now uses `clients/bluemarlin/docker-compose.yml` the same way Adamus uses `clients/adamus/docker-compose.yml`. There's no more special "repo root compose" that's only for BlueMarlin.

### Step 5 — Update `.dockerignore`

In `.dockerignore`, the existing `bluemarlin/config/`, `bluemarlin/data/`, `bluemarlin/logs/` entries still apply to whatever remains in those paths on the Mac (gitignored runtime artifacts that never existed in the first place since dev doesn't use Docker). Leave those lines unchanged — they're defensive.

Add new lines to exclude `clients/bluemarlin/` runtime state from the Docker build context (the build context is the repo root per Dockerfile, so `clients/` needs to be excluded):

Verify the current `.dockerignore` already has `clients/` (it was added in Brief 148). If yes, no change needed — `clients/` exclusion covers `clients/bluemarlin/` automatically.

### Step 6 — Update `.gitignore`

In `.gitignore`, the existing `clients/*/config/platform.env`, `clients/*/config/calendar-key.json`, `clients/*/config/azure_refresh_token.txt`, `clients/*/data/`, `clients/*/logs/` patterns already cover BlueMarlin's new location. Verify they're there (they were added in Brief 146/148 for Adamus). No changes needed if they're present.

Also add these specific patterns for BlueMarlin's runtime state files that don't exist for Adamus:

```
clients/*/config/email_thread_state.json
clients/*/config/archived_threads.jsonl
clients/*/config/heartbeat.txt
clients/*/config/state_registry.db
```

These are gitignored because they're runtime state written by the running container. The VPS's copy of them persists via the volume mount, but they should never be committed to git.

Also remove the now-obsolete legacy lines:
```
bluemarlin/config/azure_refresh_token.txt
bluemarlin/config/bluemarlin-calendar-key.json
bluemarlin/config/email_thread_state.json
bluemarlin/data/*
!bluemarlin/data/.gitkeep
```

These referenced the old location. The `**/` catch-all patterns from Brief 148 already cover these cases. The legacy specific-path lines are redundant and misleading.

### Step 7 — Write the tests

Create `bluemarlin/tests/marina/test_150_bluemarlin_deployment_layout.py` with:

1. `test_bluemarlin_config_lives_in_clients_bluemarlin` — assert `clients/bluemarlin/config/client.json` exists.
2. `test_bluemarlin_config_not_at_legacy_location` — assert `bluemarlin/config/client.json` does NOT exist (file was moved).
3. `test_bluemarlin_docker_compose_exists` — assert `clients/bluemarlin/docker-compose.yml` exists.
4. `test_root_docker_compose_deleted` — assert repo-root `docker-compose.yml` does NOT exist.
5. `test_root_deploy_sh_deleted` — assert repo-root `deploy.sh` does NOT exist.
6. `test_bluemarlin_docker_compose_has_directory_mount` — assert it contains `./config:/app/config:rw`.
7. `test_bluemarlin_docker_compose_has_build_context` — assert it contains `context: ../..` so the build works from a different directory.
8. `test_bluemarlin_docker_compose_uses_port_8001` — assert `"8001:8001"`.
9. `test_bluemarlin_docker_compose_image_name` — assert `image: root-bluemarlin` present (keeps consistency with Adamus's reference).
10. `test_bluemarlin_client_json_name_rebranded` — load `clients/bluemarlin/config/client.json`, assert `business.name == "BlueMarlin Charters"` AND `business.name != "BlueFinn Charters Curaçao"`.
11. `test_bluemarlin_client_json_email_rebranded` — assert `business.email == "butlerbensonagent@gmail.com"` AND does NOT contain `bluefinncharters.com`.
12. `test_bluemarlin_client_json_phone_rebranded` — assert `business.phone == "+15155005577"` AND `business.whatsapp == "+15155005577"`. Assert neither contains `9690 3717`.
13. `test_bluemarlin_client_json_agent_signature_rebranded` — assert `business.agent_signature` ends with `BlueMarlin Charters` and does NOT contain `BlueFinn`.
14. `test_bluemarlin_resources_rebranded` — assert `resources.bluemarlin1` and `resources.bluemarlin2` exist, and `resources.bluefinn1` does NOT exist.
15. `test_bluemarlin_klein_curacao_slots_reference_renamed_resources` — load the klein_curacao service, iterate its slots, assert any resource string starting with "BlueMarlin" and none starting with "BlueFinn".
16. `test_bluemarlin_client_json_no_bluefinn_references_in_business` — load `clients/bluemarlin/config/client.json`, dump the `business` section + `resources` section as text, assert substrings `BlueFinn`, `bluefinn`, `bluefinncharters`, `9690 3717` do NOT appear in either section. Guards against partial rebrands.
17. `test_bluemarlin_persona_no_bluefinn_references` — load `agent_persona.freeform_notes`, assert it does NOT contain `BlueFinn` (case-sensitive). The persona text can mention "charter" or "Caribbean" but not the real company name.

### Step 8 — Run tests locally

```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin
python3 -m pytest tests/marina/test_150_bluemarlin_deployment_layout.py -v
```

All 17 new tests must pass.

Then run the full suite:

```bash
python3 -m pytest tests/ -q --tb=no
```

Expected: 700 + 17 = 717 total passed. Same 7 pre-existing failures unchanged. **IMPORTANT: watch for any test that hardcoded the old `bluemarlin/config/client.json` path** — those will fail once the file is moved. Most tests use `config_loader.get_business()` which reads via the package's import-relative path, but any test that did `open("bluemarlin/config/client.json")` directly will break. Fix those by updating to the new path.

### Step 9 — Commit (locally)

```bash
git add -A
git commit -m "Brief 150 — Move BlueMarlin deployment to clients/bluemarlin/ + rebrand"
# Push manually due to security hook
```

### Step 10 — Deploy to VPS

This is the risky step because BlueMarlin's 290 KB `email_thread_state.json` and azure_refresh_token.txt live on the VPS in gitignored files that git-pull won't move. They have to be moved with a `mv` command while the container is stopped.

Execution order:

```bash
# 1. Stop BlueMarlin (downtime begins here)
ssh root@108.61.192.52 "cd /root && docker compose down"

# 2. Pull the new git state
ssh root@108.61.192.52 "cd /root && git pull"

# 3. At this point, the git-tracked files (client.json, client.json.template, brand/, .gitkeep)
#    have moved into /root/clients/bluemarlin/config/ via git-pull. The gitignored runtime files
#    are still at the old location /root/bluemarlin/config/. Move them manually:
ssh root@108.61.192.52 "
  mkdir -p /root/clients/bluemarlin/data /root/clients/bluemarlin/logs
  mv /root/bluemarlin/config/platform.env /root/clients/bluemarlin/config/platform.env
  mv /root/bluemarlin/config/calendar-key.json /root/clients/bluemarlin/config/calendar-key.json
  mv /root/bluemarlin/config/azure_refresh_token.txt /root/clients/bluemarlin/config/azure_refresh_token.txt
  mv /root/bluemarlin/config/email_thread_state.json /root/clients/bluemarlin/config/email_thread_state.json
  mv /root/bluemarlin/config/archived_threads.jsonl /root/clients/bluemarlin/config/archived_threads.jsonl
  mv /root/bluemarlin/config/heartbeat.txt /root/clients/bluemarlin/config/heartbeat.txt
  mv /root/bluemarlin/config/state_registry.db /root/clients/bluemarlin/config/state_registry.db 2>/dev/null || true
  mv /root/bluemarlin/data/state_registry.db /root/clients/bluemarlin/data/state_registry.db
  mv /root/bluemarlin/data/bluemarlin.db /root/clients/bluemarlin/data/bluemarlin.db 2>/dev/null || true
  mv /root/bluemarlin/data/state.db /root/clients/bluemarlin/data/state.db 2>/dev/null || true
  mv /root/bluemarlin/data/graphics /root/clients/bluemarlin/data/graphics 2>/dev/null || true
  mv /root/bluemarlin/data/photos /root/clients/bluemarlin/data/photos 2>/dev/null || true
  mv /root/bluemarlin/data/training /root/clients/bluemarlin/data/training 2>/dev/null || true
  mv /root/bluemarlin/logs/* /root/clients/bluemarlin/logs/ 2>/dev/null || true
  echo '=== New config dir ===' && ls -la /root/clients/bluemarlin/config/
  echo '=== New data dir ===' && ls -la /root/clients/bluemarlin/data/
"

# 4. Verify the critical state file made it
ssh root@108.61.192.52 "ls -la /root/clients/bluemarlin/config/email_thread_state.json"
# Expected: ~290 KB

# 5. Build and start from the new location
ssh root@108.61.192.52 "cd /root/clients/bluemarlin && docker compose build && docker compose up -d"

# 6. Health check
ssh root@108.61.192.52 "sleep 10 && curl -s http://localhost:8001/health"
```

### Step 11 — Verify BlueMarlin running with new deployment location

```bash
ssh root@108.61.192.52 "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep bluemarlin && echo && curl -s http://localhost:8001/health && echo && curl -s http://localhost:8002/health"
```

Expected: `bluemarlin-default` container running from `/root/clients/bluemarlin/`, health OK. Adamus untouched on 8002, also health OK.

### Step 12 — Verify BlueMarlin's config was preserved through the move

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-default python3 -c '
import sys
sys.path.insert(0, \"/app\")
from shared import config_loader
b = config_loader.get_business()
print(\"name:\", b.get(\"name\"))
print(\"phone:\", b.get(\"phone\"))
print(\"email:\", b.get(\"email\"))
print(\"agent_signature:\", b.get(\"agent_signature\"))
'"
```

Expected output:
```
name: BlueMarlin Charters
phone: +15155005577
email: butlerbensonagent@gmail.com
agent_signature: Marina
BlueMarlin Charters
```

### Step 13 — Verify gws still writes (Brief 147 regression)

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-default python3 -c '
import sys, subprocess
sys.path.insert(0, \"/app\")
from agents.marina import sheets_writer
original_run = subprocess.run
def trace_run(cmd, **kwargs):
    result = original_run(cmd, **kwargs)
    print(\"returncode:\", result.returncode)
    print(\"stdout[:150]:\", (result.stdout or \"\")[:150])
    return result
sheets_writer.subprocess.run = trace_run
sheets_writer._append(\"All Events\", [\"2026-04-06\", \"Brief 150 verification\", \"deployment moved\", \"\", \"\"])
'"
```

Expected: `returncode: 0` and stdout showing a successful row append. Another row is written to BlueMarlin's All Events spreadsheet (row 114 or higher).

### Step 14 — Clean up empty `/root/bluemarlin/config/` and `/root/bluemarlin/data/` directories

After the moves, the old directories are empty but still exist. Leave them — they're just empty directories, not harmful, and git-tracking may still expect the path to exist for other files in the source tree. Verify with:

```bash
ssh root@108.61.192.52 "ls -la /root/bluemarlin/config/ /root/bluemarlin/data/"
```

Expected: mostly empty (maybe `.gitkeep` if git recreated it from a different path, but that shouldn't happen since we git-moved `.gitkeep`).

If `/root/bluemarlin/config/` is entirely empty after the move, that's fine. It's going to be deleted in Brief 151 when the source tree rename happens anyway.

### Step 15 — Final health check for both containers

```bash
ssh root@108.61.192.52 "
  curl -s http://localhost:8001/health && echo
  curl -s http://localhost:8002/health && echo
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep bluemarlin
"
```

---

## Success Condition

BlueMarlin container running from `/root/clients/bluemarlin/`, port 8001, health OK. `client.json` rebranded in place showing name=BlueMarlin Charters, phone=+15155005577, email=butlerbensonagent@gmail.com, agent signature=Marina BlueMarlin Charters. Resources renamed from bluefinn1/bluefinn2 to bluemarlin1/bluemarlin2, and klein_curacao slots reference the new names. The 290 KB `email_thread_state.json` preserved through the move (visible inside the container at /app/config/email_thread_state.json). Brief 147's gws integration still works post-move (real row written to the spreadsheet). Adamus on port 8002 unchanged and still healthy. All 17 new tests pass. Full regression clean, 717 total passed.

---

## Rollback

**If the deployment at the new location fails to start:**

```bash
# Undo the file moves on VPS (reverse direction)
ssh root@108.61.192.52 "
  mv /root/clients/bluemarlin/config/platform.env /root/bluemarlin/config/ 2>/dev/null || true
  mv /root/clients/bluemarlin/config/calendar-key.json /root/bluemarlin/config/ 2>/dev/null || true
  mv /root/clients/bluemarlin/config/azure_refresh_token.txt /root/bluemarlin/config/ 2>/dev/null || true
  mv /root/clients/bluemarlin/config/email_thread_state.json /root/bluemarlin/config/ 2>/dev/null || true
  mv /root/clients/bluemarlin/config/archived_threads.jsonl /root/bluemarlin/config/ 2>/dev/null || true
  mv /root/clients/bluemarlin/config/heartbeat.txt /root/bluemarlin/config/ 2>/dev/null || true
  mv /root/clients/bluemarlin/data/state_registry.db /root/bluemarlin/data/ 2>/dev/null || true
  cd /root && git revert HEAD && docker compose build && docker compose up -d
"
```

**If tests fail locally before deployment:**

```bash
cd /Users/benson/Projects/bluemarlin-agent
git reset --hard HEAD  # If not yet committed
# OR
git revert HEAD  # If committed
```

**If `email_thread_state.json` is missing or 0 bytes after the move:**

Disaster. Check `/root/bluemarlin/config/email_thread_state.json` — if still present there, the move failed silently. Move it manually. If not, check for backups in `/root/bluemarlin/backups/` or restore from a previous Docker volume snapshot (if Docker Desktop has one). BlueMarlin's email thread history is hard to rebuild without this file.
