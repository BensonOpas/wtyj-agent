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

# Deploy paying clients + internal sandbox (image already built by canary).
# Runtime compose files may intentionally pin a tenant-specific tag. Refresh
# those local wtyj-agent tags from latest before forcing container recreation.
STATUS="success"
DEPLOY_CLIENTS="${WTYJ_DEPLOY_CLIENTS:-adamus consulta-despertares unboks wibrandt}"
HEALTH_PORTS=""
VERIFY_DESPERTARES=0
LATEST_IMAGE_ID=$(docker image inspect --format '{{.Id}}' wtyj-agent:latest)
for client in $DEPLOY_CLIENTS; do
  if [ ! -d "/root/clients/$client" ]; then
    echo "skip missing runtime client dir: /root/clients/$client"
    continue
  fi
  cd /root/clients/$client
  if ! (
    COMPOSE_IMAGES=$(docker compose config --images)
    for image in $COMPOSE_IMAGES; do
      case "$image" in
        wtyj-agent|wtyj-agent:*)
          docker tag wtyj-agent:latest "$image"
          ;;
      esac
    done
    docker compose down
    docker compose up -d --force-recreate

    # A green health endpoint is not sufficient if Compose recreated a stale
    # pinned image. Assert every application container is on the latest image.
    for container_id in $(docker compose ps -q); do
      configured_image=$(docker inspect --format '{{.Config.Image}}' "$container_id")
      case "$configured_image" in
        wtyj-agent|wtyj-agent:*)
          running_image_id=$(docker inspect --format '{{.Image}}' "$container_id")
          if [ "$running_image_id" != "$LATEST_IMAGE_ID" ]; then
            echo "stale application image for $client: $configured_image"
            exit 1
          fi
          ;;
      esac
    done
  ); then
    STATUS="failed"
    break
  fi
  case "$client" in
    bluemarlin) HEALTH_PORTS="$HEALTH_PORTS 8001" ;;
    adamus) HEALTH_PORTS="$HEALTH_PORTS 8002" ;;
    consulta-despertares)
      HEALTH_PORTS="$HEALTH_PORTS 8103"
      VERIFY_DESPERTARES=1
      ;;
    unboks) HEALTH_PORTS="$HEALTH_PORTS 8004" ;;
    wibrandt) HEALTH_PORTS="$HEALTH_PORTS 8100" ;;
  esac
done

# Health check with retry
if [ "$STATUS" = "success" ]; then
  for p in $HEALTH_PORTS; do
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

# Consulta Despertares needs the follow-up API for the persistent "Copiado"
# state. Authentication may return 401/403 here; 404 proves the route is absent.
if [ "$STATUS" = "success" ] && [ "$VERIFY_DESPERTARES" = "1" ]; then
  FOLLOW_UP_CODE=$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://localhost:8103/dashboard/api/follow-ups || true)
  if [ "$FOLLOW_UP_CODE" = "404" ] || [ "$FOLLOW_UP_CODE" = "000" ]; then
    echo "Consulta Despertares follow-up route verification failed: HTTP $FOLLOW_UP_CODE"
    STATUS="failed"
    bash "$SOURCE_ROOT/wtyj/scripts/rollback.sh" all || true
  fi

  # Probe the stable reply endpoint without credentials and with an invalid
  # body. A matched route returns auth/validation (401/403/422); 404/405 proves
  # the live container cannot accept the dashboard's POST request. No provider
  # send can occur from this probe.
  REPLY_CODE=$(curl -sS -m 5 -o /dev/null -w '%{http_code}' \
    -X POST -H 'Content-Type: application/json' -d '{}' \
    http://localhost:8103/dashboard/api/messages/whatsapp/reply || true)
  if [ "$REPLY_CODE" = "404" ] || [ "$REPLY_CODE" = "405" ] || [ "$REPLY_CODE" = "000" ]; then
    echo "Consulta Despertares reply route verification failed: HTTP $REPLY_CODE"
    STATUS="failed"
    bash "$SOURCE_ROOT/wtyj/scripts/rollback.sh" all || true
  else
    echo "Consulta Despertares reply route matched POST: HTTP $REPLY_CODE"
  fi
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
