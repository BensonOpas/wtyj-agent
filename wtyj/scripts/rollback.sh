#!/bin/bash
# Rollback: retag wtyj-agent:previous and recreate affected containers.
# Exits 1 if no :previous image exists (first-run case - manual intervention required).
set -e
TARGET="${1:-all}"   # bluemarlin | staging | adamus | ali-car-rental | mermaid | consulta-despertares | all

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
    DIRS="/root/clients/bluemarlin /root/clients/adamus /root/clients/ali-car-rental /root/clients/mermaid /root/clients/consulta-despertares /root/clients/unboks /root/clients/wibrandt"
    ;;
  staging) DIRS="/root/staging" ;;
  *)       DIRS="/root/clients/$TARGET" ;;
esac

for dir in $DIRS; do
  if [ ! -d "$dir" ]; then
    echo "skip missing runtime dir: $dir"
    continue
  fi
  cd "$dir"

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
for p in 8001 8002 8101 8102 8103 8004 8100 9001; do
  if curl -sf -m 3 http://localhost:$p/health | grep -q '"ok"'; then
    echo "port $p: ok after rollback"
  else
    echo "port $p: unavailable after rollback"
  fi
done
