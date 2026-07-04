#!/bin/bash
# Database backup script for Highlight Helper
# Creates consistent SQLite backups with integrity verification
#
# Usage: ./scripts/backup_db.sh [database_path] [backup_dir]
#
# Features:
# - Uses SQLite's online backup API (via Python) for consistent snapshots,
#   safe to run while the app is writing (WAL contents are included)
# - Verifies backup integrity
# - Rotates old backups (keeps last N highlight_helper_*.db backups;
#   other filenames, e.g. milestone backups, are never rotated)
# - Sets secure file permissions on backups
#
# Requires: uv (the backup itself runs through `uv run python` so no
# sqlite3 CLI is needed on the host).

set -euo pipefail

# Configuration
DEFAULT_DB_PATH="./data/highlight_helper.db"
DEFAULT_BACKUP_DIR="./backups"
KEEP_BACKUPS="${KEEP_BACKUPS:-7}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Parse arguments
DB_PATH="${1:-$DEFAULT_DB_PATH}"
BACKUP_DIR="${2:-$DEFAULT_BACKUP_DIR}"

# Normalize paths (also rejects paths that cannot resolve)
DB_PATH=$(realpath -m "$DB_PATH") || {
    echo "Error: cannot normalize database path" >&2
    exit 1
}
BACKUP_DIR=$(realpath -m "$BACKUP_DIR") || {
    echo "Error: cannot normalize backup directory" >&2
    exit 1
}

BACKUP_FILE="$BACKUP_DIR/highlight_helper_$TIMESTAMP.db"

echo "=== Database Backup ==="
echo "Source: $DB_PATH"
echo "Destination: $BACKUP_FILE"
echo ""

# Check if source database exists
if [[ ! -f "$DB_PATH" ]]; then
    echo "Error: Database not found at $DB_PATH" >&2
    exit 1
fi

# Create backup directory with secure permissions
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Create and verify the backup using SQLite's online backup API.
# The backup API takes a consistent snapshot including WAL contents,
# without blocking or modifying the running application.
echo "Creating backup..."
SRC="$DB_PATH" DEST="$BACKUP_FILE" uv run python - <<'PYEOF'
import os
import sqlite3
import sys

src_path = os.environ["SRC"]
dest_path = os.environ["DEST"]

src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
dest = sqlite3.connect(dest_path)
try:
    src.backup(dest)
finally:
    dest.close()
    src.close()

check = sqlite3.connect(dest_path)
try:
    result = check.execute("PRAGMA integrity_check").fetchone()[0]
finally:
    check.close()

if result != "ok":
    print(f"Error: backup integrity check failed: {result}", file=sys.stderr)
    os.unlink(dest_path)
    sys.exit(1)

print("Backup verified successfully.")
PYEOF

# Set secure permissions on backup file (readable only by owner)
chmod 600 "$BACKUP_FILE"

# Get backup size
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup size: $BACKUP_SIZE"

# Rotate old backups
echo ""
echo "Rotating old backups (keeping last $KEEP_BACKUPS)..."
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "highlight_helper_*.db" -type f | wc -l)
if [[ $BACKUP_COUNT -gt $KEEP_BACKUPS ]]; then
    # Sort by name (which includes timestamp) and remove oldest
    DELETE_COUNT=$((BACKUP_COUNT - KEEP_BACKUPS))
    find "$BACKUP_DIR" -name "highlight_helper_*.db" -type f | sort | head -n "$DELETE_COUNT" | while read -r old_backup; do
        echo "  Removing: $(basename "$old_backup")"
        rm -f "$old_backup"
    done
fi

echo ""
echo "=== Backup Complete ==="
echo "Backup saved to: $BACKUP_FILE"

# List all backups
echo ""
echo "Available backups:"
find "$BACKUP_DIR" -name "*.db" -type f | sort | while read -r backup; do
    size=$(du -h "$backup" | cut -f1)
    perms=$(stat -c "%a" "$backup")
    echo "  $(basename "$backup") ($size, mode $perms)"
done
