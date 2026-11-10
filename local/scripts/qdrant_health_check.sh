#!/bin/bash
# Checks if the memory-qdrant Docker container is running.
# Posts DOWN alert to Slack on failure; posts RECOVERED when it comes back.
# Cron: 0 */6 * * * (set -a; . <repo>/local/scripts/notify/.env; <repo>/local/scripts/qdrant_health_check.sh) >> <repo>/local/scripts/qdrant_health_check.log 2>&1

CONTAINER="memory-qdrant"
COMPOSE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/memory_index/docker-compose.yml"
STATE_FILE="/tmp/qdrant_health_check.down"

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

STATUS=$(docker ps -a --filter "name=^${CONTAINER}$" --format "{{.Status}}" 2>/dev/null)
[[ -z "${STATUS}" ]] && STATUS="container not found"

touch "${STATE_FILE}"
curl -s -X POST "${SLACK_WEBHOOK_URL}" \
    -H "Content-Type: application/json" \
    -d "{\"text\":\"⚠️ *personal-agent-kit health check* — Qdrant container \`${CONTAINER}\` is NOT running.\n*Status:* \`${STATUS}\`\n*Restart:* \`docker compose -f ${COMPOSE_FILE} up -d\`\"}"
