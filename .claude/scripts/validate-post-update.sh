#!/bin/bash
# ==============================================================================
# BMAD MANDATORY Post-Update Validation
# ==============================================================================
# **CRITICAL**: Claude MUST execute this script AFTER updating files
# **Purpose**: Enforce ALL BMAD protocols
# **Exit Code**: 0 = all OK, 1 = BLOCKED (fix errors immediately)
# ==============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "🔍 BMAD Protocol Validation (MANDATORY)"
echo "========================================"
echo ""

ERRORS=0

# ==============================================================================
# VALIDATION 1: Anti-Versioning
# ==============================================================================
echo -n "1. Anti-Versioning Check... "

# Basename anchored to the end (same proven pattern as local/hooks/pre-write-guard.sh) —
# a bare "*-v[0-9]*" substring match would flag content-derived slugs like
# memories/mirror-...-batch-v1-job-...md, where "v1" is Kubernetes' batch/v1 apiVersion inside
# an auto-generated name, not a sequential file version. Excludes cover generated/vendored
# trees anywhere in the repo (not just top-level), plus temp/ (gitignored scratch).
VERSIONED_FILES=""
while IFS= read -r -d '' f; do
    if basename "$f" | grep -qE '\-v[0-9]+(\.[A-Za-z0-9]+)?$'; then
        VERSIONED_FILES="${VERSIONED_FILES}${f}
"
    fi
done < <(find . -type f \
  ! -path "./.git/*" \
  ! -path "*/node_modules/*" \
  ! -path "*/venv/*" \
  ! -path "*/.venv/*" \
  ! -path "./temp/*" \
  ! -path "*/docs/*upgrade*.md" \
  ! -path "*/docs/*migration*.md" \
  -print0 2>/dev/null)
VERSIONED_FILES=$(printf '%s' "$VERSIONED_FILES" | sed '/^$/d')

if [ -n "$VERSIONED_FILES" ]; then
    echo -e "${RED}FAILED${NC}"
    echo ""
    echo -e "${RED}❌ BLOCKED: Versioned files detected${NC}"
    echo "$VERSIONED_FILES" | sed 's/^/  - /'
    echo ""
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}PASSED${NC}"
fi

# ==============================================================================
# VALIDATION 2: Version Fields (ALL .md files)
# ==============================================================================
echo -n "2. Version Fields Check... "

INVALID_VERSIONS=""

# Check ALL .md files (protocols/, docs/, root)
for mdfile in protocols/*.md docs/*.md *.md; do
    if [ -f "$mdfile" ]; then
        # Check **Version**: 1.0.0 or version: 1.0.0
        if grep -qE "^(\*\*Version\*\*:|version:) 1\.0\.0" "$mdfile" 2>/dev/null; then
            INVALID_VERSIONS="${INVALID_VERSIONS}${mdfile} (version: 1.0.0 forbidden)\n"
        fi

        # Check version: 0.x.x
        if grep -qE "^(\*\*Version\*\*:|version:) 0\.[0-9]" "$mdfile" 2>/dev/null; then
            VERSION=$(grep -E "^(\*\*Version\*\*:|version:)" "$mdfile" | head -1 | sed -E 's/.*: ([0-9.]+).*/\1/')
            INVALID_VERSIONS="${INVALID_VERSIONS}${mdfile} (version: ${VERSION} forbidden)\n"
        fi
    fi
done

if [ -n "$INVALID_VERSIONS" ]; then
    echo -e "${RED}FAILED${NC}"
    echo ""
    echo -e "${RED}❌ BLOCKED: Invalid versions (1.0.0 or 0.x.x forbidden)${NC}"
    echo -e "$INVALID_VERSIONS" | sed 's/^/  - /'
    echo ""
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}PASSED${NC}"
fi

# ==============================================================================
# VALIDATION 3: .bmadrc.yaml Version
# ==============================================================================
echo -n "3. .bmadrc.yaml Version Check... "

if [ -f ".bmadrc.yaml" ]; then
    VERSION=$(grep "^version:" .bmadrc.yaml | sed 's/version: //' | tr -d ' ')

    if [ "$VERSION" = "1.0.0" ] || [[ "$VERSION" =~ ^0\. ]]; then
        echo -e "${RED}FAILED${NC}"
        echo ""
        echo -e "${RED}❌ BLOCKED: Invalid version in .bmadrc.yaml: $VERSION${NC}"
        echo "   Forbidden: 1.0.0 and 0.x.x"
        echo ""
        ERRORS=$((ERRORS + 1))
    else
        echo -e "${GREEN}PASSED${NC}"
    fi
else
    echo -e "${YELLOW}SKIPPED${NC} (file not found)"
fi

# ==============================================================================
# VALIDATION 4: Agent Protocol Loading (Agent-Specific)
# ==============================================================================
echo -n "4. Agent Protocol Loading... "

# Local BMAD personas are the "local"-module rows of agent-manifest.csv (the same
# source of truth party-mode itself reads — see .claude/skills/bmad-component/SKILL.md:
# "party-mode arma el roster leyendo ese CSV, no escaneando .bmad/local/"). Not every
# .txt file under .bmad/local/ is a party-mode persona (e.g. orientation.txt is a plain
# instructions doc, not a persona) — globbing the directory would false-positive on it.
# agent-protocol-map.yaml
# was retired (orphaned, described a pre-v6 roster) — this is now the only validation branch.
INVALID_AGENTS=""

LOCAL_AGENT_PATHS=$("${PROJECT_ROOT}/.venv/bin/python3" -c "
import csv
with open('.bmad/_cfg/agent-manifest.csv') as f:
    for row in csv.DictReader(f):
        if row.get('module') == 'local':
            print(row['path'])
" 2>/dev/null)

for agent in $LOCAL_AGENT_PATHS; do
    if [ -f "$agent" ]; then
        BASENAME=$(basename "$agent" .txt)

        # Must have PROTOCOL-ENFORCEMENT-ABSOLUTE (COMPACT or ULTRA)
        if ! grep -qE "PROTOCOL-ENFORCEMENT-ABSOLUTE-(COMPACT|ULTRA)" "$agent" 2>/dev/null; then
            INVALID_AGENTS="${INVALID_AGENTS}${BASENAME} (missing ABSOLUTE enforcement)\n"
        fi
    fi
done

if [ -n "$INVALID_AGENTS" ]; then
    echo -e "${RED}FAILED${NC}"
    echo ""
    echo -e "${RED}❌ BLOCKED: Agents missing ABSOLUTE enforcement:${NC}"
    echo -e "$INVALID_AGENTS" | sed 's/^/  - /'
    echo ""
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}PASSED${NC}"
fi

# ==============================================================================
# VALIDATION 5: Staged Files Check (if git repo)
# ==============================================================================
if [ -d ".git" ]; then
    echo -n "5. Git Staged Files... "

    STAGED_COUNT=$(git diff --cached --name-only 2>/dev/null | wc -l || echo "0")

    if [ "$STAGED_COUNT" -eq 0 ]; then
        echo -e "${YELLOW}WARNING${NC}"
        echo ""
        echo -e "${YELLOW}⚠️  No files staged for commit${NC}"
        echo "   Did you forget 'git add'?"
        echo ""
    else
        echo -e "${GREEN}PASSED${NC} ($STAGED_COUNT files)"
    fi
fi

# ==============================================================================
# RESULT
# ==============================================================================
echo ""
echo "========================================"

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}❌ VALIDATION FAILED${NC}"
    echo ""
    echo -e "${RED}CRITICAL: DO NOT PROCEED WITH COMMIT${NC}"
    echo "Fix the errors above before committing."
    echo ""
    exit 1
else
    echo -e "${GREEN}✅ ALL VALIDATIONS PASSED${NC}"
    echo ""
    echo "Safe to commit."
    echo ""
    exit 0
fi
