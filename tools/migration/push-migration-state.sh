#!/bin/bash
# Re-pushable script to rebuild the migration-state branch with current Mac state.
# Use this to refresh the branch (e.g., if memory files have updated since the
# initial push) before re-running migration on Windows.
#
# Run from repo root.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

ASSETS_DIR="$REPO_ROOT/tools/migration/assets"
MAC_MEMORY="$HOME/.claude/projects/-Users-benson-Projects-bluemarlin-agent/memory"
MAC_SOUNDS="$HOME/.claude/hooks/sounds"

if [ ! -d "$MAC_MEMORY" ]; then
    echo "ERROR: Mac memory dir not found at $MAC_MEMORY"
    echo "(This script is meant to run on Benson's Mac during migration prep.)"
    exit 1
fi

# Refresh memory files
mkdir -p "$ASSETS_DIR/memory"
rm -f "$ASSETS_DIR/memory/"*.md
cp "$MAC_MEMORY"/*.md "$ASSETS_DIR/memory/"
echo "Refreshed $(ls "$ASSETS_DIR/memory/" | wc -l) memory files."

# Refresh sound files
mkdir -p "$ASSETS_DIR/hooks/sounds"
rm -f "$ASSETS_DIR/hooks/sounds/"*.mp3
cp "$MAC_SOUNDS"/*.mp3 "$ASSETS_DIR/hooks/sounds/"
echo "Refreshed $(ls "$ASSETS_DIR/hooks/sounds/" | wc -l) sound files."

# Note: settings.json, security-gate.ps1, notify-done.ps1 are static (committed
# verbatim from MIGRATION_PLAN.md appendices). If they need updating, edit the
# files in tools/migration/assets/ directly and commit.

echo
echo "Assets refreshed. To push the branch:"
echo "  git checkout migration-state"
echo "  git add tools/migration/assets/"
echo '  git commit -m "Refresh migration-state assets"'
echo "  git push origin migration-state"
