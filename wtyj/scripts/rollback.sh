#!/bin/bash
# Rollback: retag wtyj-agent:previous -> :latest, restart affected containers
# Exits 1 if no :previous image exists (first-run case - manual intervention required)
set -e
TARGET="${1:-all}"   # bluemarlin | staging | adamus | consultadespertares | all

if ! docker image inspect wtyj-agent:previous >/dev/null 2>&1; then
  echo "ROLLBACK ERROR: no wtyj-agent:previous image - cannot auto-roll back"
  echo "Manual recovery: git revert <bad-sha> && git push, or restore /root/backups/pre_deploy"
  exit 1
fi

docker tag wtyj-agent:previous wtyj-agent:latest
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
