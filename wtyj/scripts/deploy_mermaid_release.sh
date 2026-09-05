#!/bin/bash
# Deploy one reviewed Mermaid/Tracy image without touching another tenant.
# The image must already exist under an immutable revision tag. This script
# prepares protected rollback material, stops and recreates only Compose's
# Mermaid `agent` service, and proves all six peer container identities stayed
# byte-for-byte stable across the operation.
set -Eeuo pipefail
umask 077

SOURCE_ROOT="${WTYJ_SOURCE_ROOT:-/root/wtyj-agent-source}"
LIVE_DIR="${WTYJ_MERMAID_LIVE_DIR:-/root/clients/mermaid}"
DEPLOY_LOCK_PATH="${WTYJ_DEPLOY_LOCK_PATH:-/root/wtyj-production-deploy.lock}"
HEALTH_URL="${WTYJ_MERMAID_HEALTH_URL:-http://127.0.0.1:8102/health}"
STOP_TIMEOUT="${WTYJ_MERMAID_STOP_TIMEOUT:-30}"
IMAGE=""
RELEASE=""

usage() {
  echo "Usage: $0 --image wtyj-agent:tracy-<name>-<revision> --release /root/backups/mermaid-reservations/<release> [--source <repo>]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --image)
      IMAGE="${2:-}"
      shift 2
      ;;
    --release)
      RELEASE="${2:-}"
      shift 2
      ;;
    --source)
      SOURCE_ROOT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$IMAGE" ] || [ -z "$RELEASE" ]; then
  usage >&2
  exit 2
fi
case "$RELEASE" in
  /root/backups/mermaid-reservations/*) ;;
  *)
    echo "Release must be below /root/backups/mermaid-reservations" >&2
    exit 2
    ;;
esac

PREPARE_SCRIPT="$SOURCE_ROOT/wtyj/scripts/prepare_mermaid_reservation_release.py"
test -f "$PREPARE_SCRIPT"
test -d "$LIVE_DIR"
export WTYJ_MERMAID_LIVE_DIR="$LIVE_DIR"

snapshot_peers() {
  # Discover the live peer set at the start of the release. Tenant names can
  # change over time, so a stale allowlist must never disable the safety gate.
  # Sorting makes the before/after byte comparison deterministic.
  containers=$(docker ps --format '{{.Names}}' | LC_ALL=C sort)
  for container in $containers; do
    [ "$container" = "wtyj-mermaid" ] && continue
    snapshot=$(docker inspect --format '{{.Name}}|{{.Id}}|{{.Image}}|{{.State.StartedAt}}|{{.State.Running}}' "$container")
    case "$snapshot" in
      *'|true') ;;
      *)
        echo "Peer container is not running: $container" >&2
        return 1
        ;;
    esac
    printf '%s\n' "$snapshot"
  done
}

wait_for_health() {
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if curl -fsS -m 3 "$HEALTH_URL" | grep -q '"ok"'; then
      return 0
    fi
    sleep 5
  done
  return 1
}

mkdir -p "$(dirname "$DEPLOY_LOCK_PATH")"
exec 9>"$DEPLOY_LOCK_PATH"
if ! flock -n 9; then
  echo "Another production deployment holds $DEPLOY_LOCK_PATH" >&2
  exit 1
fi

if [ "$(docker inspect --format '{{.State.Running}}' wtyj-mermaid)" != "true" ]; then
  echo "Mermaid must be running before a release is prepared" >&2
  exit 1
fi
CANDIDATE_IMAGE_ID=$(docker image inspect --format '{{.Id}}' "$IMAGE")
PEERS_BEFORE=$(snapshot_peers)
PEER_COUNT=$(printf '%s\n' "$PEERS_BEFORE" | sed '/^$/d' | wc -l | tr -d ' ')

python3 "$PREPARE_SCRIPT" \
  --source "$SOURCE_ROOT" \
  --release "$RELEASE" \
  --image "$IMAGE"
printf '%s\n' "$PEERS_BEFORE" > "$RELEASE/peers-before.tsv"
PREVIOUS_IMAGE_ID=$(python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["previous_image_id"])' \
  "$RELEASE/manifest.json")
ROLLBACK_IMAGE=$(python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["rollback_image"])' \
  "$RELEASE/manifest.json")

ROLLBACK_ARMED=0
restore_on_failure() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ] && [ "$ROLLBACK_ARMED" = "1" ]; then
    echo "Mermaid release failed; restoring its protected files and previous image" >&2
    set +e
    cd "$LIVE_DIR"
    docker compose stop --timeout "$STOP_TIMEOUT" agent
    RESTORE_OK=1
    if ! python3 "$PREPARE_SCRIPT" \
        --source "$SOURCE_ROOT" \
        --release "$RELEASE" \
        --image "$IMAGE" \
        --rollback \
        --service-stopped; then
      RESTORE_OK=0
      echo "ROLLBACK ERROR: protected files did not match a complete release state; Mermaid remains stopped" >&2
    fi
    if [ "$RESTORE_OK" = "1" ]; then
      if ! docker compose up -d --no-deps --force-recreate agent; then
        RESTORE_OK=0
        echo "ROLLBACK ERROR: previous Mermaid image could not be recreated" >&2
      fi
    fi
    if [ "$RESTORE_OK" = "1" ]; then
      RESTORED_IMAGE_ID=$(docker inspect --format '{{.Image}}' wtyj-mermaid)
      RESTORED_IMAGE_TAG=$(docker inspect --format '{{.Config.Image}}' wtyj-mermaid)
      if [ "$RESTORED_IMAGE_ID" != "$PREVIOUS_IMAGE_ID" ] || [ "$RESTORED_IMAGE_TAG" != "$ROLLBACK_IMAGE" ]; then
        RESTORE_OK=0
        echo "ROLLBACK ERROR: Mermaid did not restore the exact pre-release image" >&2
        docker compose stop --timeout "$STOP_TIMEOUT" agent
      elif ! wait_for_health; then
        RESTORE_OK=0
        echo "ROLLBACK ERROR: Mermaid health did not recover" >&2
      fi
    fi
    PEERS_AFTER_FAILURE=$(snapshot_peers) || true
    if [ -n "${PEERS_AFTER_FAILURE:-}" ] && [ "$PEERS_AFTER_FAILURE" != "$PEERS_BEFORE" ]; then
      echo "ROLLBACK ERROR: a peer container identity changed" >&2
    fi
    set -e
  fi
  exit "$status"
}
trap restore_on_failure EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

ROLLBACK_ARMED=1
cd "$LIVE_DIR"
docker compose stop --timeout "$STOP_TIMEOUT" agent
if [ "$(docker inspect --format '{{.State.Running}}' wtyj-mermaid)" != "false" ]; then
  echo "Mermaid did not stop cleanly" >&2
  exit 1
fi

# Apply uses compare-and-swap hashes and creates the consistent SQLite backup
# now that only Mermaid is stopped. No peer service is addressed here.
python3 "$PREPARE_SCRIPT" \
  --source "$SOURCE_ROOT" \
  --release "$RELEASE" \
  --image "$IMAGE" \
  --apply \
  --service-stopped

docker compose up -d --no-deps --force-recreate agent
if ! wait_for_health; then
  echo "Mermaid health check failed after candidate recreation" >&2
  exit 1
fi

RUNNING_IMAGE_ID=$(docker inspect --format '{{.Image}}' wtyj-mermaid)
RUNNING_IMAGE_TAG=$(docker inspect --format '{{.Config.Image}}' wtyj-mermaid)
RESTART_POLICY=$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' wtyj-mermaid)
if [ "$RUNNING_IMAGE_ID" != "$CANDIDATE_IMAGE_ID" ] || [ "$RUNNING_IMAGE_TAG" != "$IMAGE" ]; then
  echo "Mermaid is not running the exact candidate image" >&2
  exit 1
fi
if [ "$RESTART_POLICY" != "unless-stopped" ]; then
  echo "Mermaid restart policy changed: $RESTART_POLICY" >&2
  exit 1
fi

PEERS_AFTER=$(snapshot_peers)
printf '%s\n' "$PEERS_AFTER" > "$RELEASE/peers-after.tsv"
if [ "$PEERS_AFTER" != "$PEERS_BEFORE" ]; then
  echo "A peer container identity changed during the Mermaid release" >&2
  exit 1
fi

ROLLBACK_ARMED=0
trap - EXIT HUP INT TERM
printf '{"deployed":true,"tenant":"mermaid","image":"%s","backup":"%s","peers_preserved":%s}\n' \
  "$IMAGE" "$RELEASE" "$PEER_COUNT"
