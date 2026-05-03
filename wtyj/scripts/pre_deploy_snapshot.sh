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
    echo "snapshot: ${client} -> $SNAPSHOT_DIR/${client}.db"
  fi
done

# Cleanup snapshots older than 7 days
find /root/backups/pre_deploy -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
echo "pre-deploy snapshot complete: $SNAPSHOT_DIR"
