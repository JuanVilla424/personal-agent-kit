#!/bin/bash
# BMAD Anti-Versioning Validator: Prevent creation of versioned files
# Version: 1.2.0
#
# DESCRIPTION:
#   Validates that file operations do not create versioned files like
#   filename-v2.md, proposal-v3.txt, etc. Enforces single file updates
#   instead of creating multiple versions.
#
# USAGE:
#   validate-no-versioning.sh [file_path]
#   validate-no-versioning.sh  # Validates from stdin (for hooks)
#
# VALIDATION RULES:
#   - Rejects: *-v2.*, *-v3.*, *-version-2.*, etc.
#   - Rejects: *-20251102-v2.*, *_v2.*, etc.
#   - Allows: semantic-versioning.md (legitimate uses)
#
# EXIT CODES:
#   0 - Validation passed (no versioned files)
#   1 - Validation failed (versioned file detected)
#
# EXAMPLES:
#   # Check a specific file
#   validate-no-versioning.sh temp/plans/proposal-v2.md
#   # Returns: exit 1 (blocked)
#
#   # Check from Write tool in hook
#   echo '{"file_path": "proposal-v2.md"}' | validate-no-versioning.sh
#   # Returns: exit 1 (blocked)
#
# INTEGRATION:
#   Can be used as:
#   - Pre-write hook in Claude Code
#   - Manual validation before commits
#   - Part of CI/CD pipeline

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

# Patterns that indicate versioned files (BLOCKED)
VERSIONED_PATTERNS=(
    '\-v[0-9]'          # -v2, -v3, etc.
    '\-version\-[0-9]'  # -version-2, etc.
    '_v[0-9]'           # _v2, _v3, etc.
    '\-rev[0-9]'        # -rev2, -rev3, etc.
    '\.v[0-9]\.'        # .v2., .v3., etc.
)

# Legitimate files that contain version-like patterns (ALLOWED)
ALLOWED_FILES=(
    'semantic-versioning.md'
    'version-compliance-report.md'
    '.bmadrc.yaml'
    'CHANGELOG.md'
)

# ============================================================================
# FUNCTIONS
# ============================================================================

is_allowed_file() {
    local filepath="$1"
    local basename=$(basename "$filepath")

    for allowed in "${ALLOWED_FILES[@]}"; do
        if [[ "$basename" == "$allowed" ]]; then
            return 0  # Allowed
        fi
    done

    return 1  # Not in allowed list
}

validate_file_path() {
    local filepath="$1"

    # Check if it's an allowed file first
    if is_allowed_file "$filepath"; then
        return 0  # Pass validation
    fi

    # Check against versioned patterns
    for pattern in "${VERSIONED_PATTERNS[@]}"; do
        if echo "$filepath" | grep -qE "$pattern"; then
            echo "❌ BLOCKED: Versioned file detected: $filepath"
            echo ""
            echo "📋 BMAD Protocol: Single File Updates"
            echo "   Instead of creating: $(basename "$filepath")"
            echo "   Update the existing file using Edit or Write tool"
            echo ""
            echo "   Example: Edit the existing file instead of creating -v2"
            echo ""
            return 1  # Fail validation
        fi
    done

    return 0  # Pass validation
}

# ============================================================================
# MAIN
# ============================================================================

if [[ $# -eq 0 ]]; then
    # Read from stdin (for hook integration)
    if [[ -t 0 ]]; then
        echo "Usage: $0 [file_path]"
        echo "   or: cat tool_input.json | $0"
        exit 1
    fi

    # Try to parse JSON from stdin
    INPUT=$(cat)

    # Extract file_path from JSON (multiple possible fields)
    FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .file_path // empty' 2>/dev/null || echo "")

    if [[ -z "$FILE_PATH" || "$FILE_PATH" == "null" ]]; then
        # No file_path found, allow operation (not a file write)
        exit 0
    fi
else
    # File path provided as argument
    FILE_PATH="$1"
fi

# Validate the file path
if validate_file_path "$FILE_PATH"; then
    exit 0  # Validation passed
else
    exit 1  # Validation failed (blocked)
fi
