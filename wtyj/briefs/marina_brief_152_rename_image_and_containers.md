# BRIEF 152 — Rename Docker Image + Container Names

**Status:** Draft
**Files:** `clients/bluemarlin/docker-compose.yml`, `clients/adamus/docker-compose.yml`, `wtyj/tests/marina/test_152_image_and_container_names.py` (new), pre-existing test files that hardcode the old image/container names
**Depends on:** Brief 151 (source rename wtyj/)
**Blocks:** Nothing. This is the final cleanup in the WTYJ naming sweep.

---

## Context

After Brief 151 the source directory is `wtyj/` but the Docker image is still tagged `root-bluemarlin` and BlueMarlin's container is still called `bluemarlin-default`. The image name comes from Docker Compose's default naming (project dir name + service name) which was tied to the old layout. Adamus's container is called `bluemarlin-adamus` which embeds the platform-not-client name.

Brief 152 finishes the WTYJ naming sweep:

- Docker image: `root-bluemarlin` → `wtyj-agent`
- BlueMarlin container: `bluemarlin-default` → `wtyj-bluemarlin`
- Adamus container: `bluemarlin-adamus` → `wtyj-adamus`

Both compose files explicitly declare `image:` and `container_name:` so the rename is fully under our control, not dependent on directory names.

---

## Why This Approach

**Alternative considered: leave the image tagged `root-bluemarlin`.** Rejected — the brief set is about removing the BlueMarlin identity from platform infrastructure. Image name is visible in `docker ps`, `docker images`, and deploy logs.

**Alternative considered: make image name `wtyj` without a suffix.** Rejected — `wtyj-agent` is clearer about what the image is (the agent platform binary). Leaves room for future images like `wtyj-dashboard-frontend` if we ever containerize that separately.

**Alternative considered: per-client image builds.** Rejected — the whole point of Brief 148 was to have ONE image for all clients. Each client gets their own container from the same image via volume mounts. `wtyj-agent` is the single shared platform image.

**Tradeoff accepted:** old image `root-bluemarlin` will remain on the VPS as a dangling tag until `docker image prune` runs. Not harmful, just extra disk. Cleanup on deploy verification.

---

## Source Material

### Current `clients/bluemarlin/docker-compose.yml`

```yaml
services:
  bluemarlin:
    build:
      context: ../..
    image: root-bluemarlin
    container_name: bluemarlin-default
    ...
```

### Current `clients/adamus/docker-compose.yml`

```yaml
services:
  bluemarlin:
    image: root-bluemarlin
    container_name: bluemarlin-adamus
    ...
```

### Tests that hardcode the old names

Brief 148's test file asserts `image: root-bluemarlin` in both compose files. Brief 146's Adamus tests assert `container_name: bluemarlin-adamus`. Brief 150's BlueMarlin tests assert `image: root-bluemarlin`. All need updating.

---

## Instructions

### Step 1 — Update BlueMarlin's docker-compose.yml

- `image: root-bluemarlin` → `image: wtyj-agent`
- `container_name: bluemarlin-default` → `container_name: wtyj-bluemarlin`
- Also rename the service key from `bluemarlin:` to `agent:` for consistency (service key is internal to compose)

### Step 2 — Update Adamus's docker-compose.yml

- `image: root-bluemarlin` → `image: wtyj-agent`
- `container_name: bluemarlin-adamus` → `container_name: wtyj-adamus`
- Service key `bluemarlin:` → `agent:`

### Step 3 — Update existing tests that hardcode the old names

- `test_146_adamus_second_client.py::test_adamus_docker_compose_container_name` — expects `bluemarlin-adamus`
- `test_148_dockerignore_directory_mount.py::test_adamus_docker_compose_preserves_image_ref` — expects `image: root-bluemarlin`
- `test_150_bluemarlin_deployment_layout.py::test_bluemarlin_docker_compose_image_name` — expects `image: root-bluemarlin`

All need updating to the new names.

### Step 4 — Write Brief 152 tests

- Test BlueMarlin compose has `image: wtyj-agent` and `container_name: wtyj-bluemarlin`
- Test Adamus compose has `image: wtyj-agent` and `container_name: wtyj-adamus`
- Test neither compose file still references `root-bluemarlin` or `bluemarlin-default` or `bluemarlin-adamus`

### Step 5 — Deploy

```bash
ssh root@108.61.192.52 "
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root && git pull
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
"
```

### Step 6 — Verify

```bash
ssh root@108.61.192.52 "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' | grep wtyj"
```

Expected output shows `wtyj-bluemarlin` + `wtyj-adamus` containers, both running `wtyj-agent` image.

---

## Success Condition

Both containers running under new names (`wtyj-bluemarlin` on 8001, `wtyj-adamus` on 8002). Both use the same `wtyj-agent` image. Both healthy. gws still works. Persona still works. No BlueMarlin references in docker ps.

---

## Rollback

```bash
ssh root@108.61.192.52 "
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root && git revert HEAD
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
"
```
