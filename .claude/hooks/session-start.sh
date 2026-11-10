#!/bin/bash
# BMAD Session Start Hook - Production with LOGGING
# Version: 1.0.2
set -euo pipefail

# LOGGING SETUP
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/temp/logs/hooks"
LOG_FILE="${LOG_DIR}/session-start.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "${LOG_DIR}" 2>/dev/null || true

# Start logging
exec 2>> "${LOG_FILE}"
echo "==================== SESSION START HOOK ====================" >> "${LOG_FILE}"
echo "Timestamp: ${TIMESTAMP}" >> "${LOG_FILE}"
echo "PWD: $(pwd)" >> "${LOG_FILE}"
echo "User: ${USER:-unknown}" >> "${LOG_FILE}"
echo "-----------------------------------------------------------" >> "${LOG_FILE}"

# Auto-cleanup old temp/ files to manage context bloat
echo "Running temp/ auto-cleanup..." >> "${LOG_FILE}"
find "${PROJECT_ROOT}/temp" -type f -mtime +7 -not -path "*/logs/*" -delete 2>/dev/null || true
find "${PROJECT_ROOT}/temp" -type d -empty -delete 2>/dev/null || true
find "${PROJECT_ROOT}/temp/logs" -type f -mtime +14 -delete 2>/dev/null || true
echo "Cleanup complete" >> "${LOG_FILE}"

# Inject the agent orientation at session start (concise — points to persona/protocols/brain).
ORIENTATION="${PROJECT_ROOT}/.bmad/local/orientation.txt"
KIT_PY="${PROJECT_ROOT}/.venv/bin/python3"
SCANNER="${PROJECT_ROOT}/bin/scan_context.py"

if [[ ! -f "$ORIENTATION" ]]; then
    echo "ERROR: orientation.txt not found at ${ORIENTATION}" >> "${LOG_FILE}"
elif [[ -x "$KIT_PY" ]] && ! "$KIT_PY" "$SCANNER" --file "$ORIENTATION"; then
    echo "# orientation.txt was not loaded: it carries injection signals. Tell the human."
    echo "ERROR: orientation.txt carries injection signals, not injected" >> "${LOG_FILE}"
else
    cat "$ORIENTATION"
    echo "SUCCESS: agent orientation loaded" >> "${LOG_FILE}"
fi

# What this session remembers: the memory brief, once, at the start. It stays the same for the
# whole session, so it does not break the prompt cache, and the service never hands out a memory
# with injection signals. Best-effort: without the service the session starts without it.
MEMORY_CLI="${PROJECT_ROOT}/local/scripts/memory_index/memory.py"
if [[ -x "$KIT_PY" && -f "$MEMORY_CLI" ]]; then
    echo ""
    "$KIT_PY" "$MEMORY_CLI" brief 2>> "${LOG_FILE}" || echo "ERROR: memory brief failed" >> "${LOG_FILE}"
fi

# The instruction files the engine loads on its own (AGENTS.md, CLAUDE.md…) cannot be stopped from
# here: the session is told which ones carry injection signals before it reads them as orders.
SESSION_DIR="$(jq -r '.cwd // empty' 2>/dev/null || true)"
if [[ -x "$KIT_PY" ]]; then
    "$KIT_PY" "$SCANNER" "${SESSION_DIR:-$PWD}" || echo "ERROR: context scan failed" >> "${LOG_FILE}"
fi

# A snapshot of the session's repository, kept outside it, before the agent touches anything
# (bin/snapshot.py): what a script destroys can come back. In the background, so the session
# never waits for it; a folder that is not a git work tree is skipped.
SNAPSHOT="${PROJECT_ROOT}/bin/snapshot.py"
if command -v python3 >/dev/null 2>&1 && [[ -f "$SNAPSHOT" ]]; then
    nohup python3 "$SNAPSHOT" take "${SESSION_DIR:-$PWD}" --reason session-start \
        >> "${LOG_FILE}" 2>&1 < /dev/null &
fi

# Languages of the repo: ai18n.yaml at the root, the ai18n standard (helpers/ai18n submodule).
# The normalized policy from its resolver goes in, never the raw file: no comment of the file
# reaches the model.
AI18N_PY="${PROJECT_ROOT}/.venv/bin/python3"
AI18N_RESOLVER="${PROJECT_ROOT}/helpers/ai18n/src/ai18n.py"

if [[ -x "$AI18N_PY" && -f "$AI18N_RESOLVER" ]] &&
    AI18N_POLICY="$("$AI18N_PY" "$AI18N_RESOLVER" show --root "$PROJECT_ROOT")"; then
    echo ""
    echo "$AI18N_POLICY"
    echo "SUCCESS: ai18n policy loaded" >> "${LOG_FILE}"
else
    echo ""
    echo "# ai18n: the resolver failed; read ai18n.yaml at the repo root before writing anything."
    echo "ERROR: ai18n resolver unavailable or policy invalid (${AI18N_RESOLVER})" >> "${LOG_FILE}"
fi

echo "Hook completed successfully at $(date '+%Y-%m-%d %H:%M:%S')" >> "${LOG_FILE}"
echo "" >> "${LOG_FILE}"
exit 0
