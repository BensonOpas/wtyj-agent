#!/bin/bash
# Process deploy queue: deploy claimed SHAs to paying clients if off-hours.
# Idempotent: safe to run on cron every 30 min — no-ops when nothing to do.
# Honors $SKIP_OFF_HOURS_CHECK=1 (set by CI's deploy-production which already
# decided off-hours is OK and may be at the boundary).
set -e

SOURCE_ROOT="${WTYJ_SOURCE_ROOT:-/root/wtyj-agent-source}"
export DEPLOY_QUEUE_PATH="${DEPLOY_QUEUE_PATH:-/root/wtyj_deploy_queue.json}"
cd "$SOURCE_ROOT"

# Off-hours check (skip if CI already decided)
if [ "${SKIP_OFF_HOURS_CHECK:-0}" != "1" ]; then
  COMMIT_MSG=$(git log -1 --pretty=%B)
  if ! python3 "$SOURCE_ROOT/wtyj/scripts/off_hours_check.py" --commit-message "$COMMIT_MSG"; then
    echo "Currently business hours — skipping queue processing"
    exit 0
  fi
fi

# Atomically claim a deploy task (returns JSON or empty)
CLAIM=$(python3 -c "
import sys, json
sys.path.insert(0, '$SOURCE_ROOT/wtyj')
from shared import deploy_queue
c = deploy_queue.claim_for_deploy()
print(json.dumps(c) if c else '')
")

if [ -z "$CLAIM" ]; then
  echo "Nothing to deploy (queue empty or another deploy in progress)"
  exit 0
fi

SHA=$(echo "$CLAIM" | python3 -c "import sys,json; print(json.load(sys.stdin)['deploy_short_sha'])")
echo "Deploying claimed SHA: $SHA"
START=$(date +%s)

# Pre-deploy snapshot
bash "$SOURCE_ROOT/wtyj/scripts/pre_deploy_snapshot.sh" "$SHA"

# Deploy paying clients + internal sandbox (image already built by canary,
# just restart). unboks is the SR-facing test sandbox; deploys with the
# others so its container always runs the latest image.
STATUS="success"
for client in adamus consultadespertares unboks; do
  cd /root/clients/$client
  if ! (docker compose down && docker compose up -d); then
    STATUS="failed"
    break
  fi
done

# Health check with retry
if [ "$STATUS" = "success" ]; then
  for p in 8002 8003 8004; do
    OK=0
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
      if curl -sf -m 3 http://localhost:$p/health | grep -q '"ok"'; then
        OK=1; break
      fi
      sleep 5
    done
    if [ "$OK" = "0" ]; then
      STATUS="failed"
      bash "$SOURCE_ROOT/wtyj/scripts/rollback.sh" all || true
      break
    fi
  done
fi

DURATION=$(( $(date +%s) - START ))

# Mark complete in queue (writes per-brief history)
python3 -c "
import sys
sys.path.insert(0, '$SOURCE_ROOT/wtyj')
from shared import deploy_queue
deploy_queue.complete_deploy('$STATUS', $DURATION)
"

echo "Deploy $STATUS in ${DURATION}s"
[ "$STATUS" = "success" ] && exit 0 || exit 1
