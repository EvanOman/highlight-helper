#!/bin/bash
# Database backup script for Highlight Helper
# Creates consistent SQLite backups with integrity verification
#
# Usage: ./scripts/backup_db.sh [database_path] [backup_dir]
#
# Features:
# - Uses SQLite .backup command for consistent snapshots
# - Checkpoints WAL before backup
# - Verifies backup integrity
# - Rotates old backups (keeps last N backups)
# - Sets secure file permissions on backups

set -euo pipefail

# Configuration
DEFAULT_DB_PATH="./data/highlight_helper.db"
DEFAULT_BACKUP_DIR="./backups"
KEEP_BACKUPS="${KEEP_BACKUPS:-7}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Parse arguments
DB_PATH="${1:-$DEFAULT_DB_PATH}"
BACKUP_DIR="${2:-$DEFAULT_BACKUP_DIR}"

# Security: Validate paths to prevent directory traversal
validate_path() {
    local path="$1"
    local description="$2"

    # Check for null bytes
    if [[ "$path" == *$'\0'* ]]; then
        echo "Error: $description contains null bytes" >&2
        exit 1
    fi

    # Check for directory traversal attempts
    # Normalize the path and check it doesn't escape
    local normalized
    normalized=$(realpath -m "$path" 2>/dev/null) || {
        echo "Error: Cannot normalize $description: $path" >&2
        exit 1
    }

    # For backup directory, ensure it's under the project or an absolute path we trust
    if [[ "$description" == "backup directory" ]]; then
        # Allow absolute paths or paths relative to current directory
        if [[ ! "$normalized" =~ ^/ ]] && [[ "$normalized" == *".."* ]]; then
            echo "Error: $description appears to escape current directory" >&2
            exit 1
        fi
    fi

    echo "$normalized"
}

# Validate paths
DB_PATH=$(validate_path "$DB_PATH" "database path")
BACKUP_DIR=$(validate_path "$BACKUP_DIR" "backup directory")

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

# Checkpoint WAL to ensure all changes are in main database
# Use readonly mode to avoid modifying the source
echo "Checkpointing WAL..."
sqlite3 "file:${DB_PATH}?mode=ro" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || {
    echo "Note: WAL checkpoint skipped (database may not be in WAL mode or is locked)"
}

# Create backup using SQLite's backup command with readonly mode
echo "Creating backup..."
sqlite3 "file:${DB_PATH}?mode=ro" ".backup '$BACKUP_FILE'"

# Set secure permissions on backup file (readable only by owner)
chmod 600 "$BACKUP_FILE"

# Verify backup integrity
echo "Verifying backup integrity..."
INTEGRITY=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;")
if [[ "$INTEGRITY" != "ok" ]]; then
    echo "Error: Backup integrity check failed!" >&2
    echo "$INTEGRITY" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi

echo "Backup verified successfully."

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
find "$BACKUP_DIR" -name "highlight_helper_*.db" -type f | sort | while read -r backup; do
    size=$(du -h "$backup" | cut -f1)
    perms=$(stat -c "%a" "$backup")
    echo "  $(basename "$backup") ($size, mode $perms)"
done
