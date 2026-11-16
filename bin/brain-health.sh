#!/usr/bin/env bash
# bin/brain-health.sh — per-task health check of the kit's brain.
# The memory is the only state that exists nowhere else, so this verifies every layer it
# depends on (Qdrant, memory_service, the nightly consolidation, the local backups) plus
# the host drift the installers own (systemd units, OpenCode pin, containers), and reports
# what is degraded, so the agent warns the user instead of assuming full context.
# Exit 0 = all critical layers healthy; non-zero = N critical layers degraded.
#
# Usage: bash bin/brain-health.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO_ROOT="$(pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
fails=0
ok() { echo -e "  ${GREEN}✔${NC}  $1"; }
bad() {
    echo -e "  ${RED}✘${NC}  $1"
    fails=$((fails + 1))
}
warn() { echo -e "  ${YELLOW}–${NC}  $1"; }

# get_env KEY → the value from the root .env, unquoted (the .env quotes values with spaces
# so `bash source` can read them; curl must receive them bare).
get_env() {
    local v
    v="$(grep -m1 "^$1=" "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2-)"
    v="${v%\"}" v="${v#\"}" v="${v%\'}" v="${v#\'}"
    echo "${v}"
}
QPORT="$(get_env QDRANT_PORT)"
QPORT="${QPORT:-7633}"
# The local Qdrant may require an API key. The key reaches curl on stdin (printf is a
# builtin), never in argv: other users of a shared host can read every process's arguments.
QKEY="$(get_env QDRANT_API_KEY)"
qcurl() {
    if [ -n "${QKEY}" ]; then
        printf 'api-key: %s\n' "${QKEY}" | curl -s -m3 -H @- "$@"
    else
        curl -s -m3 "$@"
    fi
}

echo "🧠 Brain health:"

# 1. Qdrant responds
if qcurl "localhost:${QPORT}/collections" >/dev/null 2>&1; then
    ok "Qdrant responds (:${QPORT})"
else
    bad "Qdrant DOWN (:${QPORT}) — no semantic memory"
fi

# 2. The memory collections exist and hold points (0 points is a warning: runbooks may not
#    be indexed yet, but a memory collection with 0 points is a brain that finds nothing).
c_memory="$(get_env MEMORY_COLLECTION)"
c_user="$(get_env MEMORY_USER_COLLECTION)"
c_docs="$(get_env QDRANT_COLLECTION)"
COLLS="${MEMORY_BACKUP_COLLECTIONS:-${c_memory:-agent_memory} ${c_user:-agent_memory_user} ${c_docs:-runbooks}}"
COLLS="${COLLS//,/ }"
for coll in ${COLLS}; do
    pts="$(qcurl "localhost:${QPORT}/collections/${coll}" 2>/dev/null |
        grep -o '"points_count":[0-9]*' | head -1 | cut -d: -f2)"
    if [ -n "${pts}" ] && [ "${pts}" -gt 0 ] 2>/dev/null; then
        ok "${coll} holds ${pts} points"
    elif [ "${pts}" = "0" ] && [ "${coll}" = "${c_docs}" ]; then
        warn "${coll} is empty (0 points) — index the docs"
    elif [ "${pts}" = "0" ]; then
        warn "${coll} is empty (0 points) — nothing saved there yet"
    else
        warn "${coll} missing or unreadable (points=${pts:-?})"
    fi
done

# 3. memory_service answers, accepts this kit's token, and reports its layers. /memory/health
#    answers anyone: on a machine with two kits the service on this address may be the other
#    one's, and its memories are not this kit's. The token is the proof, and it reaches curl on
#    stdin like the Qdrant key.
svc_url="$(get_env MEMORY_SERVICE_URL)"
svc_url="${svc_url:-http://localhost:7700}"
health="$(curl -s -m3 "${svc_url}/memory/health" 2>/dev/null)"
if echo "${health}" | grep -q '"status": *"ok"'; then
    shared="$(echo "${health}" | grep -o '"entries": *[0-9]*' | grep -o '[0-9]*')"
    user="$(echo "${health}" | grep -o '"user_entries": *[0-9]*' | grep -o '[0-9]*')"
    whoami="$(printf 'x-memory-token: %s\n' "$(get_env MEMORY_SERVICE_TOKEN)" |
        curl -s -m3 -o /dev/null -w '%{http_code}' -H @- "${svc_url}/memory/whoami" 2>/dev/null)"
    case "${whoami}" in
        200) ok "memory_service answers and accepts this kit's token (${shared:-?} shared / ${user:-?} personal memories)" ;;
        401) bad "memory_service at ${svc_url} REFUSES this kit's token — it is another kit's service, or MEMORY_SERVICE_TOKEN is not one of its MEMORY_USER_TOKENS" ;;
        *) bad "memory_service at ${svc_url} cannot confirm this kit's token (HTTP ${whoami:-none}) — restart it on the current code; if it still cannot, another kit owns that address" ;;
    esac
else
    bad "memory_service does NOT answer at ${svc_url} — no memory over MCP"
fi

# unit_installed NAME → 0 when systemd knows that exact unit. A unit whose name only contains
# it, such as another kit's, does not count; and nothing is piped, so a long listing cut short
# by the reader cannot turn an installed unit into a missing one.
unit_installed() { [ -n "$(systemctl list-unit-files --no-legend "$1" 2>/dev/null)" ]; }

# 4. The nightly consolidation: unit installed → must be active; timer too
if systemctl is-active --quiet agent-memory.service 2>/dev/null; then
    ok "unit agent-memory.service active"
elif unit_installed agent-memory.service; then
    bad "unit agent-memory.service INSTALLED but INACTIVE"
else
    warn "unit agent-memory.service not installed on this box"
fi
if systemctl is-active --quiet agent-memory-consolidate.timer 2>/dev/null; then
    ok "nightly consolidation timer active"
elif unit_installed agent-memory-consolidate.timer; then
    bad "consolidation timer INSTALLED but INACTIVE — the memory never consolidates"
else
    warn "consolidation timer not installed (pak memory consolidate by hand)"
fi

# 5. Brain backups: freshness of the newest generation (the memory survives nowhere else —
#    stale backups mean a dead machine loses recent memories)
newest=0
if [ -d "${HOME}/.pak/backups/brain" ]; then
    for gen in "${HOME}/.pak/backups/brain"/latest.*.generation; do
        [ -e "${gen}" ] || continue
        coll="$(basename "${gen}")"
        coll="${coll#latest.}"
        coll="${coll%.generation}"
        file="$(dirname "${gen}")/${coll}/$(cat "${gen}" 2>/dev/null)"
        [ -e "${file}" ] || continue
        mtime="$(stat -c %Y "${file}" 2>/dev/null || echo 0)"
        [ "${mtime}" -gt "${newest}" ] && newest="${mtime}"
    done
fi
now="$(date +%s)"
age_days=$(( (now - newest) / 86400 ))
if [ "${newest}" -eq 0 ]; then
    warn "no brain backups yet — pak brain backup (the memory survives nowhere else)"
elif [ "${age_days}" -gt 7 ]; then
    warn "brain backups STALE (${age_days}d old) — pak brain backup"
else
    ok "brain backups fresh (${age_days}d old)"
fi

# 6. Drift de versión de OpenCode: binario instalado vs pin del repo. warn (no bad): no
#    tumba nada, pero el próximo update.sh cambia la versión y mejor alinearlo a propósito.
oc_pin="$(cat "${REPO_ROOT}/configs/opencode.version" 2>/dev/null)"
if command -v opencode &>/dev/null && [ -n "${oc_pin}" ]; then
    oc_ver="$(opencode --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if [ -z "${oc_ver}" ]; then
        warn "no pude leer la versión del binario opencode"
    elif [ "${oc_ver}" = "${oc_pin}" ]; then
        ok "opencode ${oc_ver} aligned with the repo pin"
    else
        warn "opencode DRIFT: binary ${oc_ver} ≠ pin ${oc_pin} — align pin or binary"
    fi
else
    warn "opencode not installed or configs/opencode.version missing — no drift check"
fi

# 7. OpenCode server unit: installed → active
if systemctl is-active --quiet opencode-server.service 2>/dev/null; then
    ok "opencode-server active (127.0.0.1:4096)"
elif unit_installed opencode-server.service; then
    bad "opencode-server INSTALLED but INACTIVE"
else
    warn "opencode-server not installed (bash bin/install-opencode.sh)"
fi

# 8. Containers: none unhealthy
if command -v docker &>/dev/null; then
    unhealthy="$(docker ps --filter health=unhealthy --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
    if [ -z "${unhealthy% }" ]; then
        ok "no unhealthy containers"
    else
        warn "unhealthy containers: ${unhealthy}"
    fi
fi

echo ""
if [ "${fails}" -eq 0 ]; then
    echo -e "${GREEN}Brain healthy — full context available.${NC}"
else
    echo -e "${RED}${fails} critical layer(s) degraded — warn the user; context may be partial.${NC}"
fi
exit "${fails}"
