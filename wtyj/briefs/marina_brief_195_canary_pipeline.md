# BRIEF 195 — Canary deploy pipeline: staging → BlueMarlin → street, with E2E + rollback + off-hours + snapshot

**Status:** Draft | **Files:** `.github/workflows/ci-deploy.yml`, `wtyj/scripts/off_hours_check.py`, `wtyj/scripts/e2e_canary_test.sh`, `wtyj/scripts/pre_deploy_snapshot.sh`, `wtyj/scripts/rollback.sh`, `wtyj/tests/scripts/test_off_hours_check.py` | **Depends on:** Brief 194 (staging container), post-staging-branch-delete state | **Blocks:** —

## Context

`project_live_preparations.md` decided a canary deploy model (School → Playground → Street) with six concrete pipeline changes. Currently the workflow is "test → deploy to all three production containers at once" with no staging gate, no E2E validation, no rollback, no snapshot, no off-hours enforcement, no image versioning. A bad deploy hits all three clients simultaneously with no way back except git revert + redeploy (minutes of downtime).

This brief consolidates all six items into one workflow rewrite + four helper scripts. One brief because they all mutate the same deploy path — splitting would mean six partial-state deploys that partially break each other during rollout.

## Why This Approach

**Two jobs (deploy-canary, deploy-production) not one mega-job.** GitHub Actions surfaces them as separate steps. Off-hours-check gates both via `needs:` chain, and each deploy job has its own explicit `if:` branch+event guard (belt-and-suspenders; skip-cascade semantics should never be the only PR protection).

**Off-hours check in Python with `zoneinfo`, not inline bash.** Python is testable (unit tests at boundary times); bash in YAML is not. Using `zoneinfo.ZoneInfo("America/Curacao")` and `ZoneInfo("Europe/Madrid")` avoids manual DST math for Madrid (CET/CEST transitions) and naturally handles Curaçao's no-DST AST. Script lives at `wtyj/scripts/off_hours_check.py`; exits 0 (allowed) or 1 (blocked).

**Block on EITHER Curaçao OR Madrid business hours.** Per live-preps decision: Curaçao 5:30am-8pm local (no DST), Madrid 9am-6pm local (DST-aware). `[HOTFIX]` in commit message bypasses both. At 3 clients the deploy window is tight (~7-8 hours of overlap each night) but the protection is real.

**Image rollback via retag, not git revert.** Tag every build as `wtyj-agent:<short-sha>`. Before building, retag current `wtyj-agent:latest` → `wtyj-agent:previous`. On rollback: `docker tag wtyj-agent:previous wtyj-agent:latest` + restart containers. Seconds, not minutes. git stays clean. **Known gap:** the very first deploy with this workflow has no `:previous` image yet, so rollback.sh exits 1 and the failed canary stays broken until manual intervention. Documented in Rollback section — acceptable because the safety fixes shipped today mean the first deploy is low-risk (just scripts + workflow changes, no Python behavior change).

**Staging container gets rebuilt via retag.** Per Brief 194 + infra.md:135-146, staging's docker-compose uses `image: wtyj-agent:staging` (separate tag). The workflow builds `wtyj-agent:latest`, then retags `:latest → :staging` so staging picks up the new code on the next container restart. Without this retag, staging would perpetually run whatever was last manually built — a fake gate.

**E2E test as a bash script on the VPS, not in Python.** Runs against a live container with curl + docker exec. Python + subprocess orchestration would be messier. Bash + `python3 -c` inline for DB assertions reads clearest.

**Sentinel conversation_id for webhook test (checks 8–10) + sentinel phone for brain test (check 4).** Conversation IDs start with `e2etest` so the cleanup block can do `WHERE phone LIKE 'e2etest%'` and sweep all test data in one pass. For the webhook test, when Marina's reply hits Zernio's API with the sentinel ID, Zernio returns 404, `send_dm_reply` at `zernio_dm_client.py:112` catches the exception, returns False — no real customer gets messaged. Confirmed by code inspection.

**"Platform: instagram" in E2E webhook test, not whatsapp.** The Instagram/FB/X DM path processes the message inline (skipping the 5-second debounce buffer). WhatsApp via Zernio goes through the buffer, which means sleep + wait. Instagram path is deterministic and fast.

**E2E check 3 uses `/dashboard/api/config`, not `/status`.** `api.py:118-131` `/status` returns draft counts + `season`; no business name. `api.py:392-395` `/config` returns `{context: <non-empty client context string>}` built from `client.json` via `_build_client_context()`. Check 3 asserts `response["context"]` is non-empty — proves client.json loaded.

**E2E check 4 seeds whatsapp_threads first.** `api.py:1010-1018` `/messages/suggest-reply` requires `{phone, draft_text}` AND raises 404 if `wa_get_full_history(phone)` is empty. The E2E test inserts one seed row into `whatsapp_threads` for a sentinel phone before the suggest-reply call, then asserts `response["body"]` is non-empty (proves Claude was reached). Cleanup sweeps the seed row.

**Pre-deploy snapshot only before paying clients deploy, not before canary.** BlueMarlin is the canary — if a deploy corrupts its data, we learn before paying clients are affected. Snapshotting ALL clients before ALL stages would double disk writes for no additional safety.

### Rejected alternatives

1. **Blue-green deployment with separate container sets.** Clean but doubles VPS resource use. At 3-4 clients, canary-first is enough.
2. **Healthcheck directive in docker-compose.yml + `docker compose up -d --wait`.** Cleaner than our retry loop but requires adding `healthcheck:` blocks to every compose file. Deferred — retry loop works and is localized.
3. **Off-hours enforcement via GitHub Environment protection rules.** Native, UI-visible, but can't express "unless [HOTFIX] in commit message." Script gives us the bypass.
4. **DRY_RUN env var on Zernio sender to make E2E webhook test silent.** Requires Python code change, expands scope. Sentinel conversation_id achieves the same safety without a source change.
5. **E2E tests against staging container instead of BlueMarlin.** Staging has dummy keys — can't test real Zernio webhook flow or Claude with real config. Defeats the purpose of the canary.
6. **Block if BOTH timezones are in business hours (AND), not EITHER (OR).** Less restrictive but leaves Madrid exposed during Spanish morning hours before Curaçao wakes. Live-preps explicitly said "Madrid exception: also blocked" — OR semantics.

## Instructions

### Step 1 — Create `wtyj/scripts/off_hours_check.py`

New file. Uses `zoneinfo` for DST-correct Madrid, blocks on either timezone.

```python
#!/usr/bin/env python3
"""Off-hours enforcement for production deploys.
Blocks deploys during EITHER Curaçao business hours (05:30-20:00 AST, no DST)
OR Madrid business hours (09:00-18:00 local, DST-aware).
Bypass by including [HOTFIX] in the commit message.
Exits 0 when deploy is allowed, 1 when blocked (reason printed to stdout).
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


CURACAO = ZoneInfo("America/Curacao")
MADRID = ZoneInfo("Europe/Madrid")

# Minute-of-day boundaries
CURACAO_START = 5 * 60 + 30   # 05:30
CURACAO_END   = 20 * 60       # 20:00 (exclusive)
MADRID_START  = 9 * 60        # 09:00
MADRID_END    = 18 * 60       # 18:00 (exclusive)


def _in_business_hours(local_dt: datetime, start: int, end: int) -> bool:
    mod = local_dt.hour * 60 + local_dt.minute
    return start <= mod < end


def is_deploy_blocked(now_utc: datetime, commit_message: str) -> tuple[bool, str]:
    """Return (blocked, reason). blocked=True means refuse deploy."""
    if "[HOTFIX]" in commit_message:
        return (False, "HOTFIX bypass — proceeding during business hours")

    cura_local = now_utc.astimezone(CURACAO)
    madrid_local = now_utc.astimezone(MADRID)
    cura_blocked = _in_business_hours(cura_local, CURACAO_START, CURACAO_END)
    madrid_blocked = _in_business_hours(madrid_local, MADRID_START, MADRID_END)

    if cura_blocked and madrid_blocked:
        return (True,
                f"Blocked: both timezones in business hours "
                f"(Curaçao {cura_local.strftime('%H:%M')} AST, "
                f"Madrid {madrid_local.strftime('%H:%M')} local). "
                f"Emergency bypass: include [HOTFIX] in commit message.")
    if cura_blocked:
        return (True,
                f"Blocked: Curaçao business hours "
                f"({cura_local.strftime('%H:%M')} AST). "
                f"Bypass: [HOTFIX] in commit message.")
    if madrid_blocked:
        return (True,
                f"Blocked: Madrid business hours "
                f"({madrid_local.strftime('%H:%M')} local). "
                f"Bypass: [HOTFIX] in commit message.")
    return (False,
            f"Off-hours (Curaçao {cura_local.strftime('%H:%M')}, "
            f"Madrid {madrid_local.strftime('%H:%M')}) — proceeding")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--commit-message", required=True)
    args = p.parse_args()
    blocked, reason = is_deploy_blocked(datetime.now(timezone.utc),
                                        args.commit_message)
    print(reason)
    sys.exit(1 if blocked else 0)


if __name__ == "__main__":
    main()
```

### Step 2 — Create `wtyj/tests/scripts/test_off_hours_check.py`

New file. Six tests covering single/dual timezone blocks + hotfix bypass + boundary.

```python
from datetime import datetime, timezone
from scripts.off_hours_check import is_deploy_blocked


def _utc(hour: int, minute: int = 0) -> datetime:
    # April 14, 2026 — Madrid is CEST (UTC+2), Curaçao is AST (UTC-4)
    return datetime(2026, 4, 14, hour, minute, tzinfo=timezone.utc)


def test_blocked_when_both_timezones_in_business_hours():
    # 15:00 UTC = 17:00 Madrid (blocked), 11:00 Curaçao (blocked)
    blocked, reason = is_deploy_blocked(_utc(15, 0), "Brief 195: ship")
    assert blocked is True
    assert "both timezones" in reason


def test_blocked_curacao_only_late_afternoon():
    # 18:00 UTC = 20:00 Madrid (off, ≥ 18:00), 14:00 Curaçao (blocked)
    blocked, reason = is_deploy_blocked(_utc(18, 0), "Brief 195: ship")
    assert blocked is True
    assert "Curaçao business hours" in reason


def test_blocked_madrid_only_early_morning():
    # 07:00 UTC = 09:00 Madrid (blocked), 03:00 Curaçao (off, < 05:30)
    blocked, reason = is_deploy_blocked(_utc(7, 0), "Brief 195: ship")
    assert blocked is True
    assert "Madrid business hours" in reason


def test_not_blocked_when_both_off_hours():
    # 04:00 UTC = 06:00 Madrid (off), 00:00 Curaçao (off)
    blocked, reason = is_deploy_blocked(_utc(4, 0), "Brief 195: ship")
    assert blocked is False
    assert "Off-hours" in reason


def test_hotfix_bypasses_block():
    # Same as dual-block case but with [HOTFIX] → allowed
    blocked, reason = is_deploy_blocked(_utc(15, 0), "Brief 200: [HOTFIX] patch")
    assert blocked is False
    assert "HOTFIX bypass" in reason


def test_curacao_boundary_exit_allowed():
    # 00:00 UTC = 02:00 Madrid (off), 20:00 Curaçao (exclusive end — off)
    blocked, _ = is_deploy_blocked(_utc(0, 0), "Brief 195: ship")
    assert blocked is False
```

### Step 3 — Create `wtyj/scripts/e2e_canary_test.sh`

New file, executable. Runs against BlueMarlin on port 8001. Exit 0 on success, 1 on any failure. See "Final helper scripts" section.

### Step 4 — Create `wtyj/scripts/pre_deploy_snapshot.sh`

New file, executable. Snapshots all client state_registry.db files to `/root/backups/pre_deploy/<timestamp>_<sha>/`. 7-day retention (daily_backup.sh covers 30-day).

### Step 5 — Create `wtyj/scripts/rollback.sh`

New file, executable. Retags `wtyj-agent:previous` → `wtyj-agent:latest`, restarts specified client containers, logs the rollback event.

### Step 6 — Rewrite `.github/workflows/ci-deploy.yml`

Replace entire file with the canary pipeline. Both `deploy-canary` and `deploy-production` have explicit `if:` branch+event guards (not just `needs:` chaining).

```yaml
name: CI/CD — Test + Canary Deploy

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest
      - name: Run test suite
        env:
          ANTHROPIC_API_KEY: "test-key"
          DASHBOARD_PASSWORD: "testpass"
          WHATSAPP_VERIFY_TOKEN: "test"
          WHATSAPP_PHONE_NUMBER_ID: "test"
          META_ACCESS_TOKEN: "test"
          LATE_API_KEY: "test"
          ZERNIO_WEBHOOK_SECRET: "test"
          CLIENT_CONFIG_PATH: "clients/bluemarlin/config/client.json"
        run: python -m pytest wtyj/tests/ -q --tb=short

  off-hours-check:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Block production deploy during Curaçao/Madrid business hours
        run: |
          COMMIT_MSG=$(git log -1 --pretty=%B)
          python3 wtyj/scripts/off_hours_check.py --commit-message "$COMMIT_MSG"

  deploy-canary:
    needs: off-hours-check
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - name: Deploy to staging + BlueMarlin canary + E2E
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          command_timeout: 10m
          script: |
            set -e
            cd /root && git pull
            SHA=$(git rev-parse --short HEAD)
            chmod +x wtyj/scripts/*.sh

            # Save current image as :previous before rebuilding (graceful on first run)
            docker tag wtyj-agent:latest wtyj-agent:previous 2>/dev/null || \
              echo "No previous wtyj-agent:latest to tag (first run — rollback unavailable this deploy)"

            # Build new image + archive-tag with SHA
            cd /root/clients/bluemarlin && docker compose build
            docker tag wtyj-agent:latest wtyj-agent:$SHA

            # Retag :latest → :staging so staging container picks up new code on restart
            docker tag wtyj-agent:latest wtyj-agent:staging

            # Deploy staging (port 9001) with retry health check
            cd /root/staging && docker compose down && docker compose up -d
            for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
              if curl -sf -m 3 http://localhost:9001/health | grep -q '"ok"'; then
                echo "staging healthy (attempt $attempt)"; break
              fi
              [ "$attempt" = "12" ] && { echo "STAGING HEALTH FAILED"; exit 1; }
              sleep 5
            done

            # Deploy BlueMarlin canary (port 8001) with retry health check
            cd /root/clients/bluemarlin && docker compose down && docker compose up -d
            for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
              if curl -sf -m 3 http://localhost:8001/health | grep -q '"ok"'; then
                echo "bluemarlin healthy (attempt $attempt)"; break
              fi
              [ "$attempt" = "12" ] && {
                echo "BLUEMARLIN HEALTH FAILED — attempting rollback";
                bash /root/wtyj/scripts/rollback.sh bluemarlin || true; exit 1; }
              sleep 5
            done

            # System-wide E2E test (10 checks on BlueMarlin)
            if ! bash /root/wtyj/scripts/e2e_canary_test.sh; then
              echo "E2E FAILED — attempting rollback"
              bash /root/wtyj/scripts/rollback.sh bluemarlin || true
              exit 1
            fi

  deploy-production:
    needs: deploy-canary
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - name: Snapshot DBs + deploy paying clients
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          command_timeout: 10m
          script: |
            set -e
            SHA=$(cd /root && git rev-parse --short HEAD)
            chmod +x /root/wtyj/scripts/*.sh

            bash /root/wtyj/scripts/pre_deploy_snapshot.sh $SHA

            # Deploy paying clients (no rebuild — same image as canary)
            for client in adamus consultadespertares; do
              cd /root/clients/$client
              docker compose down && docker compose up -d
            done

            # Health check paying clients with retry
            for p in 8002 8003; do
              for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
                if curl -sf -m 3 http://localhost:$p/health | grep -q '"ok"'; then
                  echo "port $p healthy (attempt $attempt)"; break
                fi
                [ "$attempt" = "12" ] && {
                  echo "PORT $p HEALTH FAILED — attempting rollback all";
                  bash /root/wtyj/scripts/rollback.sh all || true; exit 1; }
                sleep 5
              done
            done
            echo "All production containers healthy"
```

### Step 7 — Commit source changes

The VPS runs `git pull` in the deploy script, so scripts must be committed BEFORE the new workflow's first run. All files go in one commit. The new workflow triggers on the push — runs tests, runs off-hours check, deploys canary, runs E2E, deploys production. Full pipeline validates itself on the very commit that introduces it.

## Final helper scripts

**`wtyj/scripts/e2e_canary_test.sh`:**

```bash
#!/bin/bash
# System-wide E2E test — runs on BlueMarlin after canary deploy
# 10 checks from project_live_preparations.md. Exit 0 on success, 1 on failure.
# Uses sentinel prefix "e2etest" so cleanup can LIKE-sweep all test data.
set -e

BASE="http://localhost:8001"
PASSWORD=$(docker exec wtyj-bluemarlin printenv DASHBOARD_PASSWORD)
SECRET=$(docker exec wtyj-bluemarlin printenv ZERNIO_WEBHOOK_SECRET)
RAND=$(head -c 6 /dev/urandom | xxd -p)
SENTINEL_BRAIN="e2etest_brain_${RAND}"     # for check 4 (suggest-reply)
SENTINEL_WEBHOOK="e2etest${RAND}00000000000000"   # 24+ chars, for checks 8-10
SENTINEL_MSG="e2etest_msg_${RAND}"

fail() { echo "E2E CHECK $1 FAILED: $2"; exit 1; }

# 1. Health
curl -sf -m 3 "$BASE/health" | grep -q '"ok"' || fail 1 "health endpoint"
echo "1/10 health ✓"

# 2. Login
TOKEN=$(curl -sf -m 5 -X POST "$BASE/dashboard/api/login" \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"$PASSWORD\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))')
[ -z "$TOKEN" ] && fail 2 "login returned no token"
echo "2/10 login ✓"

# 3. Config loads (/dashboard/api/config returns {context: <client context string>})
curl -sf -m 5 "$BASE/dashboard/api/config" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); c=d.get("context",""); assert c and len(c)>20, f"config context empty or too short: {c!r}"' \
  || fail 3 "config context empty"
echo "3/10 config ✓"

# 4. Claude brain (seed whatsapp_threads, then /messages/suggest-reply)
docker exec wtyj-bluemarlin python3 -c "
import sqlite3
from datetime import datetime, timezone
c = sqlite3.connect('/app/data/state_registry.db')
c.execute('INSERT INTO whatsapp_threads (phone, role, text, created_at) VALUES (?, ?, ?, ?)',
          ('${SENTINEL_BRAIN}', 'user', 'Hi, what services do you offer?',
           datetime.now(timezone.utc).isoformat()))
c.commit()
" || fail 4 "could not seed whatsapp_threads"
curl -sf -m 30 -X POST "$BASE/dashboard/api/messages/suggest-reply" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"${SENTINEL_BRAIN}\",\"draft_text\":\"\"}" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d.get("body"), d' \
  || fail 4 "suggest-reply returned no body"
echo "4/10 brain ✓"

# 5. DB writable (insert → read → delete in container)
docker exec wtyj-bluemarlin python3 -c "
import sqlite3
c = sqlite3.connect('/app/data/state_registry.db')
c.execute('CREATE TABLE IF NOT EXISTS _e2e_test (marker TEXT)')
c.execute('INSERT INTO _e2e_test VALUES (?)', ('${RAND}',))
assert c.execute('SELECT marker FROM _e2e_test WHERE marker=?', ('${RAND}',)).fetchone()
c.execute('DELETE FROM _e2e_test WHERE marker=?', ('${RAND}',))
c.commit()
" || fail 5 "db write-read-delete"
echo "5/10 db writable ✓"

# 6. Conversations endpoint
curl -sf -m 5 "$BASE/dashboard/api/messages/conversations" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); assert isinstance(d,(list,dict)), d' \
  || fail 6 "conversations endpoint"
echo "6/10 conversations ✓"

# 7. Escalations endpoint
curl -sf -m 5 "$BASE/dashboard/api/escalations" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); assert isinstance(d,(list,dict)), d' \
  || fail 7 "escalations endpoint"
echo "7/10 escalations ✓"

# 8. Webhook accepts a signed test payload (sentinel conv_id — Zernio returns 404 on reply)
PAYLOAD=$(python3 -c "
import json
print(json.dumps({'event':'message.received','data':{
  'text':'e2e test message','conversationId':'${SENTINEL_WEBHOOK}',
  'id':'${SENTINEL_MSG}','accountId':'e2etest_account',
  'sender':{'name':'E2E Test','id':'e2etest_sender'},
  'platform':'instagram','channel':'instagram_dm'},
  'account':{'id':'e2etest_account'}}))
")
SIG=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -sf -m 5 -X POST "$BASE/webhooks/zernio" \
  -H "Content-Type: application/json" \
  -H "X-Zernio-Signature: $SIG" \
  -d "$PAYLOAD" | grep -q "OK" || fail 8 "webhook accept"
echo "8/10 webhook ✓"

# Background task processes the webhook (Claude call + DB writes)
sleep 4

# 9. Conversation status was updated
docker exec wtyj-bluemarlin python3 -c "
import sqlite3
c = sqlite3.connect('/app/data/state_registry.db')
row = c.execute('SELECT status FROM conversation_status WHERE conversation_id=?',
                ('${SENTINEL_WEBHOOK}',)).fetchone()
assert row, 'no conversation_status row'
" || fail 9 "conversation_status not updated"
echo "9/10 conversation_status ✓"

# 10. Customer record created
docker exec wtyj-bluemarlin python3 -c "
import sqlite3
c = sqlite3.connect('/app/data/state_registry.db')
row = c.execute(
  'SELECT c.id FROM customers c JOIN customer_identifiers ci ON ci.customer_id=c.id '
  'WHERE ci.value=?', ('${SENTINEL_WEBHOOK}',)).fetchone()
assert row, 'no customer row'
" || fail 10 "customer record not created"
echo "10/10 customer record ✓"

# Cleanup — LIKE sweep by 'e2etest%' prefix covers both sentinel conversations
docker exec wtyj-bluemarlin python3 -c "
import sqlite3
c = sqlite3.connect('/app/data/state_registry.db')
# Customer rows keyed on customer_id (via identifiers)
ids = [r[0] for r in c.execute(
    \"SELECT customer_id FROM customer_identifiers WHERE value LIKE 'e2etest%'\").fetchall()]
for cid in set(ids):
    c.execute('DELETE FROM customer_identifiers WHERE customer_id=?', (cid,))
    c.execute('DELETE FROM customers WHERE id=?', (cid,))
# Phone-keyed tables
c.execute(\"DELETE FROM whatsapp_threads WHERE phone LIKE 'e2etest%'\")
c.execute(\"DELETE FROM whatsapp_booking_state WHERE phone LIKE 'e2etest%'\")
c.execute(\"DELETE FROM whatsapp_processed WHERE message_id LIKE 'e2etest%'\")
c.execute(\"DELETE FROM conversation_status WHERE conversation_id LIKE 'e2etest%'\")
c.commit()
"
echo ""
echo "All 10 E2E checks passed (sentinels: brain=${SENTINEL_BRAIN}, webhook=${SENTINEL_WEBHOOK})"
exit 0
```

**`wtyj/scripts/pre_deploy_snapshot.sh`:**

```bash
#!/bin/bash
# Pre-deploy DB snapshot — copy all client state_registry.db before paying-client deploy
# Short-term insurance: 7-day retention (daily_backup.sh handles 30-day)
set -e
SHA="${1:-unknown}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
SNAPSHOT_DIR="/root/backups/pre_deploy/${TS}_${SHA}"
mkdir -p "$SNAPSHOT_DIR"

for dir in /root/clients/*/data/; do
  client=$(basename $(dirname "$dir"))
  src="$dir/state_registry.db"
  if [ -f "$src" ]; then
    cp "$src" "$SNAPSHOT_DIR/${client}.db"
    echo "snapshot: ${client} → $SNAPSHOT_DIR/${client}.db"
  fi
done

# Cleanup snapshots older than 7 days
find /root/backups/pre_deploy -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
echo "pre-deploy snapshot complete: $SNAPSHOT_DIR"
```

**`wtyj/scripts/rollback.sh`:**

```bash
#!/bin/bash
# Rollback: retag wtyj-agent:previous → :latest, restart affected containers
# Exits 1 if no :previous image exists (first-run case — manual intervention required)
set -e
TARGET="${1:-all}"   # bluemarlin | staging | adamus | consultadespertares | all

if ! docker image inspect wtyj-agent:previous >/dev/null 2>&1; then
  echo "ROLLBACK ERROR: no wtyj-agent:previous image — cannot auto-roll back"
  echo "Manual recovery: git revert <bad-sha> && git push, or restore /root/backups/pre_deploy"
  exit 1
fi

docker tag wtyj-agent:previous wtyj-agent:latest
# Also retag :staging so staging container recovers if it was in the blast radius
docker tag wtyj-agent:previous wtyj-agent:staging
echo "=== ROLLBACK EXECUTED: $(date -Iseconds) target=$TARGET ==="

case "$TARGET" in
  all)      DIRS="/root/clients/bluemarlin /root/clients/adamus /root/clients/consultadespertares" ;;
  staging)  DIRS="/root/staging" ;;
  *)        DIRS="/root/clients/$TARGET" ;;
esac

for dir in $DIRS; do
  cd "$dir"
  docker compose down && docker compose up -d
  echo "restarted: $dir"
done

sleep 10
for p in 8001 8002 8003 9001; do
  if curl -sf -m 3 http://localhost:$p/health | grep -q '"ok"'; then
    echo "port $p: ok after rollback"
  else
    echo "port $p: STILL DOWN after rollback"
  fi
done
```

## Tests

6 Python unit tests on `wtyj/scripts/off_hours_check.py:is_deploy_blocked`:
1. Both timezones in business hours → blocked
2. Curaçao only in business hours (late UTC afternoon, Madrid past 18:00) → blocked with "Curaçao" in reason
3. Madrid only in business hours (early UTC morning, Curaçao before 05:30) → blocked with "Madrid" in reason
4. Both off-hours → allowed
5. `[HOTFIX]` bypass during dual-block → allowed
6. Curaçao boundary exit at 00:00 UTC (= 20:00 AST exact, end exclusive) → allowed

The E2E script, pre-deploy snapshot, and rollback script are validated operationally by the pipeline itself — the first deploy with the new workflow IS the integration test. If any of the 10 E2E checks, the snapshot dir creation, or the rollback retag fails, the pipeline exits 1 and we see it in the Actions UI. Unit-testing bash orchestrating docker exec + curl has low ROI.

**Regression baseline:** 893 passing / 0 failures. (system_state.md's latest entry is Brief 190 at 891; briefs 191/192/193/194 shipped without state-log entries — actual `python3 -m pytest wtyj/tests/ -q` right now returns 893.) After this brief: **899 passing / 0 failures (baseline 893 + 6 new).**

## Success Condition

- `python3 wtyj/scripts/off_hours_check.py --commit-message "[HOTFIX] test"` exits 0 regardless of time; without `[HOTFIX]` it exits 1 whenever either timezone is in business hours.
- First CI run on main after this brief ships passes all jobs: test → off-hours-check → deploy-canary → deploy-production.
- BlueMarlin canary step logs 10 green E2E checks (`1/10 health ✓` through `10/10 customer record ✓`) and leaves no rows matching `e2etest%` in `whatsapp_threads`, `whatsapp_booking_state`, `whatsapp_processed`, `conversation_status`, `customer_identifiers`, or `customers`.
- Pre-deploy snapshot creates `/root/backups/pre_deploy/<ts>_<sha>/{bluemarlin,adamus,consultadespertares}.db`.
- `docker images wtyj-agent` shows `latest`, `previous`, `staging`, and a SHA-tagged entry after deploy.
- All 4 containers healthy (ports 8001, 8002, 8003, 9001) post-deploy.

## Rollback

If this brief itself breaks the pipeline:

```bash
# Revert the workflow + scripts commit
git revert <commit-sha>
git push origin main
```

The revert commit triggers the NEW workflow (since the revert is still on main) but with the OLD workflow contents. If the OLD workflow is what gets restored, it runs fine. If the NEW workflow structure is incompatible with what's on VPS, manually SSH and revert scripts: `rm -f /root/wtyj/scripts/{e2e_canary_test,pre_deploy_snapshot,rollback,off_hours_check}*`.

If a deployed image is bad and `:previous` exists:

```bash
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Containers restart with the previous commit's image in seconds.

**First-run gap (explicit limitation):** the very first deploy using this workflow has no `wtyj-agent:previous` image yet (nothing to tag as previous on the initial build). If that first canary fails E2E, `rollback.sh` exits 1 and BlueMarlin stays on the failing image. Manual recovery: `git revert` + push. Acceptable because this brief only changes workflow + helper scripts (no Python behavior change) — probability of first canary failing for code reasons is near zero; failures would be workflow typos that a second push fixes.
