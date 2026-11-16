#!/bin/bash
# Checks if this checkout's Qdrant container is running: memory-qdrant, or memory-qdrant-<port>
# when QDRANT_PORT in the root .env is not the default 7633 (the names bin/_lib.sh gives it).
# Posts DOWN alert to Slack on failure; posts RECOVERED when it comes back.
# Cron: 0 */6 * * * (set -a; . <repo>/local/scripts/notify/.env; <repo>/local/scripts/qdrant_health_check.sh) >> <repo>/local/scripts/qdrant_health_check.log 2>&1

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="$(grep -m1 '^QDRANT_PORT=' "${REPO}/.env" 2>/dev/null | cut -d= -f2- | tr -d "\"' ")"
SUFFIX=""
[[ -n "${PORT}" && "${PORT}" != "7633" ]] && SUFFIX="-${PORT}"
CONTAINER="memory-qdrant${SUFFIX}"
STATE_FILE="${TMPDIR:-/tmp}/qdrant_health_check${SUFFIX}.down"

if [[ -z "${SLACK_WEBHOOK_URL}" ]]; then
    echo "ERROR: SLACK_WEBHOOK_URL not set" >&2
    exit 1
fi

if docker ps --filter "name=^${CONTAINER}$" --filter "status=running" --format "{{.Names}}" | grep -q "^${CONTAINER}$"; then
    if [[ -f "${STATE_FILE}" ]]; then
        rm -f "${STATE_FILE}"
        curl -s -X POST "${SLACK_WEBHOOK_URL}" \
            -H "Content-Type: application/json" \
            -d "{\"text\":\"✅ *personal-agent-kit health check* — Qdrant container \`${CONTAINER}\` is back UP.\"}"
    fi
    exit 0
fi

# An existing container is started again; a missing one is created by the installer, which is
# what gives it this checkout's name and ports.
STATUS=$(docker ps -a --filter "name=^${CONTAINER}$" --format "{{.Status}}" 2>/dev/null)
RESTART="docker start ${CONTAINER}"
if [[ -z "${STATUS}" ]]; then
    STATUS="container not found"
    RESTART="bash ${REPO}/bin/install.sh"
fi

touch "${STATE_FILE}"
curl -s -X POST "${SLACK_WEBHOOK_URL}" \
    -H "Content-Type: application/json" \
    -d "{\"text\":\"⚠️ *personal-agent-kit health check* — Qdrant container \`${CONTAINER}\` is NOT running.\n*Status:* \`${STATUS}\`\n*Restart:* \`${RESTART}\`\"}"
