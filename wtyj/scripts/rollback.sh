#!/bin/bash
# Rollback: retag wtyj-agent:previous and recreate affected containers.
# Exits 1 if no :previous image exists (first-run case - manual intervention required).
set -euo pipefail
umask 077
TARGET="${1:-all}"   # staging | shared tenant name | all
DEPLOY_LOCK_PATH="${WTYJ_DEPLOY_LOCK_PATH:-/root/wtyj-production-deploy.lock}"

case "$TARGET" in
  mermaid)
    echo "ROLLBACK ERROR: Mermaid uses a tenant-scoped immutable image and release backup"
    echo "Use deploy_mermaid_release.sh with the protected Mermaid release manifest"
    exit 1
    ;;
  all|staging|bluemarlin|adamus|ali-car-rental|consulta-despertares|unboks|wibrandt) ;;
  *)
    echo "ROLLBACK ERROR: unknown shared deployment target: $TARGET"
    exit 1
    ;;
esac

# process_deploy_queue.sh already owns descriptor 9 while invoking rollback.
# Direct operator rollbacks take the same lock as generic and Mermaid deploys.
if [ "${WTYJ_DEPLOY_LOCK_HELD:-0}" != "1" ]; then
  mkdir -p "$(dirname "$DEPLOY_LOCK_PATH")"
  exec 9>"$DEPLOY_LOCK_PATH"
  if ! flock -n 9; then
    echo "ROLLBACK ERROR: another production deployment holds $DEPLOY_LOCK_PATH"
    exit 1
  fi
fi

if ! docker image inspect wtyj-agent:previous >/dev/null 2>&1; then
  echo "ROLLBACK ERROR: no wtyj-agent:previous image - cannot auto-roll back"
  echo "Manual recovery: git revert <bad-sha> && git push, or restore /root/backups/pre_deploy"
  exit 1
fi

docker tag wtyj-agent:previous wtyj-agent:latest
docker tag wtyj-agent:previous wtyj-agent:staging
echo "=== ROLLBACK EXECUTED: $(date -Iseconds) target=$TARGET ==="

case "$TARGET" in
  all)
    DIRS="/root/clients/bluemarlin /root/clients/adamus /root/clients/ali-car-rental /root/clients/consulta-despertares /root/clients/unboks /root/clients/wibrandt"
    ;;
  staging) DIRS="/root/staging" ;;
  *)       DIRS="/root/clients/$TARGET" ;;
esac

for dir in $DIRS; do
  if [ -L "$dir" ]; then
    echo "ROLLBACK ERROR: refusing symlinked runtime dir: $dir"
    exit 1
  fi
  if [ ! -d "$dir" ]; then
    echo "skip missing runtime dir: $dir"
    continue
  fi
  cd "$dir"

  COMPOSE_CONFIG=$(docker compose config)
  if grep -Eq '^[[:space:]]*container_name:[[:space:]]*wtyj-mermaid[[:space:]]*$' <<< "$COMPOSE_CONFIG"; then
    echo "ROLLBACK ERROR: protected Mermaid container found in shared target $dir"
    exit 1
  fi

  # Tenant Compose files can pin a local wtyj-agent tag. Move every such tag
  # to the previous image before recreation, otherwise rollback restarts the
  # same broken image while appearing successful.
  COMPOSE_IMAGES=$(docker compose config --images)
  for image in $COMPOSE_IMAGES; do
    case "$image" in
      sha256:*)
        echo "ROLLBACK ERROR: raw image digest cannot be retagged for $dir"
        exit 1
        ;;
      wtyj-agent:tracy-*|wtyj-agent:mermaid-*)
        echo "ROLLBACK ERROR: protected tenant-scoped image cannot be retagged for $dir"
        exit 1
        ;;
      wtyj-agent|wtyj-agent:*)
        docker tag wtyj-agent:previous "$image"
        ;;
    esac
  done

  docker compose down
  docker compose up -d --force-recreate
  echo "restarted: $dir"
done

sleep 10
for p in 8001 8002 8101 8103 8004 8100 9001; do
  if curl -sf -m 3 http://localhost:$p/health | grep -q '"ok"'; then
    echo "port $p: ok after rollback"
  else
    echo "port $p: unavailable after rollback"
  fi
done
