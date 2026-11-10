#!/bin/bash
# BMAD Temp Cleanup: Automated cleanup of temporary files
# Version: 1.2.0
#
# DESCRIPTION:
#   Cleans old temporary files from temp/ directory while preserving
#   critical state files. Implements retention policies for snapshots,
#   archives, and trigger files.
#
# USAGE:
#   cleanup-temp.sh [--dry-run] [--force]
#
# OPTIONS:
#   --dry-run    Show what would be deleted without deleting
#   --force      Skip confirmation prompts
#   --verbose    Show detailed output
#
# RETENTION POLICIES:
#   - Snapshots: Keep last 7 days
#   - Archive: Keep last 30 days
#   - Trigger files: Keep last 1 day
#   - Critical files: NEVER deleted (bmad-state.json, current-context.md, etc.)
#
# EXAMPLES:
#   # Preview what will be deleted
#   cleanup-temp.sh --dry-run
#
#   # Clean with confirmation
#   cleanup-temp.sh
#
#   # Clean without prompts
#   cleanup-temp.sh --force
#
# EXIT CODES:
#   0 - Success
#   1 - Error occurred
#
# FILES NEVER DELETED:
#   - temp/bmad-state.json
#   - temp/current-context.md
#   - temp/user-messages-history.md
#   - temp/plans/* (active files)
#   - temp/reports/* (recent reports)
#
# INTEGRATION:
#   Can be run:
#   - Manually when needed
#   - Via cron for scheduled cleanup
#   - As pre-commit hook (optional)

set -euo pipefail

# ============================================================================
# DYNAMIC PATH DETECTION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ============================================================================
# CONFIGURATION
# ============================================================================

TEMP_DIR="${PROJECT_ROOT}/temp"
SNAPSHOTS_DIR="${TEMP_DIR}/snapshots"
ARCHIVE_DIR="${TEMP_DIR}/archive"

# Retention periods (in days)
SNAPSHOT_RETENTION=7
ARCHIVE_RETENTION=30
TRIGGER_RETENTION=1

# Flags
DRY_RUN=false
FORCE=false
VERBOSE=false

# Counters
DELETED_COUNT=0
BYTES_FREED=0

# ============================================================================
# PARSE ARGUMENTS
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--dry-run] [--force] [--verbose]"
            exit 1
            ;;
    esac
done

# ============================================================================
# FUNCTIONS
# ============================================================================

log_verbose() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo "$@"
    fi
}

format_bytes() {
    local bytes=$1
    if [[ $bytes -lt 1024 ]]; then
        echo "${bytes}B"
    elif [[ $bytes -lt 1048576 ]]; then
        echo "$((bytes / 1024))KB"
    else
        echo "$((bytes / 1048576))MB"
    fi
}

delete_file() {
    local file="$1"
    local size

    if [[ ! -f "$file" ]]; then
        return
    fi

    size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo "0")

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "  [DRY RUN] Would delete: $file ($(format_bytes "$size"))"
    else
        rm -f "$file"
        log_verbose "  Deleted: $file ($(format_bytes "$size"))"
    fi

    DELETED_COUNT=$((DELETED_COUNT + 1))
    BYTES_FREED=$((BYTES_FREED + size))
}

# ============================================================================
# MAIN CLEANUP LOGIC
# ============================================================================

echo "🧹 BMAD Temp Cleanup"
echo "===================="
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo "⚠️  DRY RUN MODE - No files will be deleted"
    echo ""
fi

# ============================================================================
# 1. Clean old snapshots (>7 days)
# ============================================================================

echo "📸 Cleaning snapshots older than ${SNAPSHOT_RETENTION} days..."

if [[ -d "$SNAPSHOTS_DIR" ]]; then
    while IFS= read -r -d '' file; do
        delete_file "$file"
    done < <(find "$SNAPSHOTS_DIR" -name "context-snapshot-*.md" -type f -mtime +${SNAPSHOT_RETENTION} -print0 2>/dev/null)
else
    log_verbose "  Snapshots directory doesn't exist"
fi

# ============================================================================
# 2. Clean old archive files (>30 days)
# ============================================================================

echo "📦 Cleaning archive files older than ${ARCHIVE_RETENTION} days..."

if [[ -d "$ARCHIVE_DIR" ]]; then
    while IFS= read -r -d '' file; do
        delete_file "$file"
    done < <(find "$ARCHIVE_DIR" -type f -mtime +${ARCHIVE_RETENTION} -print0 2>/dev/null)
else
    log_verbose "  Archive directory doesn't exist"
fi

# ============================================================================
# 3. Clean old trigger files (>1 day)
# ============================================================================

echo "🔔 Cleaning trigger files older than ${TRIGGER_RETENTION} day..."

if [[ -d "$TEMP_DIR" ]]; then
    while IFS= read -r -d '' file; do
        delete_file "$file"
    done < <(find "$TEMP_DIR" -maxdepth 1 -name "*-trigger.*" -type f -mtime +${TRIGGER_RETENTION} -print0 2>/dev/null)
else
    log_verbose "  Temp directory doesn't exist"
fi

# ============================================================================
# 4. Summary
# ============================================================================

echo ""
echo "✅ Cleanup Summary"
echo "===================="

if [[ "$DRY_RUN" == "true" ]]; then
    echo "Files that would be deleted: $DELETED_COUNT"
    echo "Disk space that would be freed: $(format_bytes "$BYTES_FREED")"
    echo ""
    echo "Run without --dry-run to actually delete files"
else
    echo "Files deleted: $DELETED_COUNT"
    echo "Disk space freed: $(format_bytes "$BYTES_FREED")"
fi

echo ""
echo "📋 Protected files (never deleted):"
echo "  - temp/bmad-state.json"
echo "  - temp/current-context.md"
echo "  - temp/user-messages-history.md"
echo "  - temp/plans/* (active)"
echo "  - temp/reports/* (recent)"

exit 0
