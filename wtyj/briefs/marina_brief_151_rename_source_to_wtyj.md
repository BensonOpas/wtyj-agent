# BRIEF 151 — Rename Source Directory `bluemarlin/` → `wtyj/`

**Status:** Draft
**Files:** `Dockerfile`, `.dockerignore`, entire `bluemarlin/` tree renamed via `git mv`, `bluemarlin/tests/marina/test_151_source_rename.py` (new)
**Depends on:** Brief 150 (BlueMarlin deployment moved out of bluemarlin/ into clients/bluemarlin/)
**Blocks:** Brief 152 (Docker image/container rename)

---

## Context

After Brief 150, `bluemarlin/` at the repo root contains only source code (agents/, shared/, dashboard/, tests/, briefs/, backups/, src/). BlueMarlin's client deployment lives at `clients/bluemarlin/`. The `bluemarlin/` directory name is a leftover from when BlueMarlin was the only client and the source tree was named after it. Brief 151 renames the source directory to `wtyj/` (wetakeyourjob) — the platform's actual short identifier.

This is a low-risk mechanical rename because:
- Python imports are relative to the directory CONTENTS (e.g., `from agents.marina import ...`), not the directory NAME. The content inside `bluemarlin/` — `agents/`, `shared/`, `dashboard/` — stays identical.
- Inside the Docker container, the working directory is `/app/` regardless. The Dockerfile does `COPY bluemarlin/ /app/` today and will do `COPY wtyj/ /app/` after Brief 151. The container never sees the source directory name.
- `conftest.py` computes `_BM_ROOT = os.path.dirname(os.path.dirname(...))` relative to `__file__`, which yields whatever the parent of `tests/` is called. Works for both names.
- Tests that walk up from their file location to find `_REPO_ROOT` use `os.path.dirname` chains that are name-independent.

---

## Why This Approach

**Alternative considered: add `wtyj/` as a symlink to `bluemarlin/` for backward compat.** Rejected. Symlinks inside a git repo are fragile (Windows checkouts break them). A clean rename is simpler.

**Alternative considered: rename only the Dockerfile COPY source but keep the directory as `bluemarlin/`.** Rejected. Doesn't address the user's actual request — they want the source directory name to reflect the platform (WTYJ) not a client (BlueMarlin).

**Alternative considered: also rename file header comments (`# bluemarlin/agents/...`) to `# wtyj/agents/...`.** Out of scope for Brief 151. These comments are cosmetic and don't affect functionality. Sweep them later if desired.

**Alternative considered: rename demo payment URLs `https://demo.pay/bluemarlin/` → `https://demo.pay/wtyj/`.** Out of scope. Those are placeholder stub URLs, never hit, and renaming them has test-cascade implications (tests assert on the URL format).

**Tradeoff accepted:** several cosmetic `# bluemarlin/...` header comments in source files will still mention `bluemarlin/` after Brief 151. They're informational and don't affect runtime behavior. Clean sweep is a separate future cleanup.

---

## Source Material

### Current `Dockerfile` line 21

```dockerfile
# Copy application source
COPY bluemarlin/ /app/
```

### Current `.dockerignore` (post-Brief-148)

```
bluemarlin/backups/
bluemarlin/tests/
bluemarlin/briefs/
bluemarlin/src/
bluemarlin/config/
bluemarlin/data/
bluemarlin/logs/
clients/
**/.DS_Store
**/__pycache__/
**/.pytest_cache/
*.pyc
.git/
.gitignore
*.md
```

### Current `bluemarlin/` directory contents

```
agents/          (core Python source — marina, social)
backups/         (legacy snapshots, excluded from image)
briefs/          (brief files, excluded from image)
config/          (empty after Brief 150 on Mac; empty on VPS after the move)
dashboard/       (FastAPI backend)
data/            (empty on Mac; empty on VPS after Brief 150)
logs/            (empty/gitignored)
payment_state.json  (legacy runtime file at repo level — investigate if still needed)
shared/          (config_loader, state_registry, bm_logger)
snapshot.sh      (backup script)
src/             (legacy JS/node? excluded from image)
tests/           (Python tests, excluded from image)
```

---

## Instructions

### Step 1 — Rename the directory

```bash
cd /Users/benson/Projects/bluemarlin-agent
git mv bluemarlin wtyj
```

### Step 2 — Update `Dockerfile`

Change line 21 from `COPY bluemarlin/ /app/` to `COPY wtyj/ /app/`.

### Step 3 — Update `.dockerignore`

Change every `bluemarlin/*` entry to `wtyj/*`:

```
wtyj/backups/
wtyj/tests/
wtyj/briefs/
wtyj/src/
wtyj/config/
wtyj/data/
wtyj/logs/
clients/
**/.DS_Store
**/__pycache__/
**/.pytest_cache/
*.pyc
.git/
.gitignore
*.md
```

### Step 4 — Write a test

`wtyj/tests/marina/test_151_source_rename.py`:

1. `test_wtyj_directory_exists` — assert `wtyj/` exists at repo root
2. `test_bluemarlin_directory_gone` — assert `bluemarlin/` does NOT exist at repo root
3. `test_dockerfile_copies_wtyj` — assert Dockerfile contains `COPY wtyj/ /app/`
4. `test_dockerfile_no_bluemarlin_copy` — assert Dockerfile does NOT contain `COPY bluemarlin/`
5. `test_dockerignore_uses_wtyj_paths` — assert `.dockerignore` contains `wtyj/backups/`, `wtyj/tests/`, etc.
6. `test_dockerignore_no_bluemarlin_paths` — assert `.dockerignore` does not contain any `bluemarlin/` path patterns

### Step 5 — Run tests + full regression

Expected: 717 + 6 = 723 total. No new failures.

### Step 6 — Commit, push, deploy

Deploy is more involved because the VPS has `/root/bluemarlin/` that needs renaming too. The container must be stopped, rename done, then built from the new path.

```bash
ssh root@108.61.192.52 "
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root && git pull
  mv /root/bluemarlin /root/wtyj
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
"
```

Both containers rebuild because the image SHA changes when the COPY source changes.

### Step 7 — Verify

Both containers healthy on 8001 and 8002, gws still works, email_thread_state preserved (it's in `clients/bluemarlin/config/`, unaffected by the source rename).

---

## Success Condition

`wtyj/` exists at the repo root containing the source tree. `bluemarlin/` is gone. Dockerfile and .dockerignore updated. Both containers running, both healthy, both serving their respective clients. `email_thread_state.json` preserved (105 threads, 292481 bytes). All 6 new tests pass.

---

## Rollback

```bash
ssh root@108.61.192.52 "
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root && git revert HEAD
  mv /root/wtyj /root/bluemarlin
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
"
```
