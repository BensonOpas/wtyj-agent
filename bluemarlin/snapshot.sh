#!/usr/bin/env bash
# bluemarlin/snapshot.sh
# Purpose: Pull a timestamped backup of all VPS runtime state to local machine
# Usage: ./snapshot.sh [optional-tag]
#   Example: ./snapshot.sh pre-deploy
#            ./snapshot.sh
#
# What it backs up:
#   - SQLite database (bookings, holds, manifests, dedup hashes)
#   - Thread state JSON (all active conversations)
#   - Config files (client.json, env, oauth token, calendar key)
#   - Poller logs (last 500 lines)
#   - Git state on VPS (current commit, dirty files)
#
# What it does NOT back up:
#   - Source code (already in git)
#   - Google Sheets/Calendar data (external services)

set -euo pipefail

VPS="root@108.61.192.52"
VPS_DIR="/root/bluemarlin"
LOCAL_BACKUP_DIR="$(dirname "$0")/backups"
TAG="${1:-}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SNAPSHOT_NAME="snapshot_${TIMESTAMP}${TAG:+_${TAG}}"
DEST="${LOCAL_BACKUP_DIR}/${SNAPSHOT_NAME}"

echo "=== BlueMarlin VPS Snapshot ==="
echo "Target: ${DEST}"
echo ""

mkdir -p "${DEST}"

# 1. SQLite database (the real one is in src/)
echo "[1/6] Pulling SQLite database..."
scp "${VPS}:${VPS_DIR}/src/state_registry.db" "${DEST}/state_registry.db"
scp "${VPS}:${VPS_DIR}/src/state_registry.db-wal" "${DEST}/state_registry.db-wal" 2>/dev/null || true
scp "${VPS}:${VPS_DIR}/src/state_registry.db-shm" "${DEST}/state_registry.db-shm" 2>/dev/null || true

# 2. Thread state JSON
echo "[2/6] Pulling thread state..."
scp "${VPS}:${VPS_DIR}/config/email_thread_state.json" "${DEST}/email_thread_state.json"

# 3. Config files (excluding secrets by default — uncomment to include)
echo "[3/6] Pulling config files..."
scp "${VPS}:${VPS_DIR}/config/client.json" "${DEST}/client.json"
# Uncomment these to include secrets in backup:
# scp "${VPS}:${VPS_DIR}/config/bluemarlin.env" "${DEST}/bluemarlin.env"
# scp "${VPS}:${VPS_DIR}/config/azure_refresh_token.txt" "${DEST}/azure_refresh_token.txt"
# scp "${VPS}:${VPS_DIR}/config/bluemarlin-calendar-key.json" "${DEST}/bluemarlin-calendar-key.json"

# 4. Poller logs (last 500 lines from journalctl + log file)
echo "[4/6] Pulling logs..."
ssh "${VPS}" "journalctl -u bluemarlin -n 500 --no-pager" > "${DEST}/journalctl_last500.log" 2>/dev/null || true
scp "${VPS}:${VPS_DIR}/logs/bluemarlin.log" "${DEST}/bluemarlin.log" 2>/dev/null || true

# 5. VPS git state
echo "[5/6] Capturing VPS git state..."
ssh "${VPS}" "cd ${VPS_DIR} && echo 'commit:' && git log --oneline -1 && echo 'status:' && git status --short" > "${DEST}/vps_git_state.txt"

# 6. DB summary (human-readable)
echo "[6/6] Generating DB summary..."
ssh "${VPS}" "cd ${VPS_DIR} && python3 << 'PYEOF'
import sqlite3
c = sqlite3.connect('src/state_registry.db')
print('=== DATABASE SUMMARY ===')
for t in ['bookings','trip_bookings','manifest_events','processed_hashes']:
    count = c.execute('SELECT count(*) FROM ' + t).fetchone()[0]
    print(t + ': ' + str(count) + ' rows')
print()
print('=== BOOKINGS ===')
for r in c.execute('SELECT booking_ref, trip_key, customer_name, customer_email, date, status FROM bookings ORDER BY created_at DESC').fetchall():
    print('  ' + ' | '.join(str(x) for x in r))
print()
print('=== ACTIVE HOLDS ===')
for r in c.execute(\"SELECT trip_key, date, departure_time, guests, status, customer_name FROM trip_bookings WHERE status='soft_hold'\").fetchall():
    print('  ' + ' | '.join(str(x) for x in r))
PYEOF" > "${DEST}/db_summary.txt"

# Done
echo ""
echo "=== Snapshot complete ==="
SNAPSHOT_SIZE=$(du -sh "${DEST}" | cut -f1)
echo "Location: ${DEST}"
echo "Size: ${SNAPSHOT_SIZE}"
echo "Files:"
ls -la "${DEST}/"
