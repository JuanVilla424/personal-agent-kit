#!/usr/bin/env bash
# bin/opencode/opencode-run-wrapped.sh — wraps `opencode run` with memory before/after,
# approximating what a real hook would do — OpenCode has no hooks (see
# bin/opencode/mcp_memory_server.py, same limitation documented there). This ONLY covers
# headless/scripted invocations through this wrapper; it doesn't cover opencode's interactive
# TUI (there's no way to intercept that without opencode adding plugin support).
#
# BEFORE: searches agent_memory (memory_service) for anything relevant to the prompt and adds
#        it as context. Best-effort — if memory_service doesn't respond, it proceeds without memory.
# AFTER: if opencode's response ends with a line "REMEMBER: <text>" (personal)
#        or "REMEMBER-SHARED: <text>" (for the whole team), it saves it. The model decides
#        whether there's anything worth keeping — the wrapper only obeys the marker, never invents it.
#
# Usage: bash bin/opencode/opencode-run-wrapped.sh "your prompt" [-- extra opencode run flags]
set -uo pipefail

# shellcheck source=bin/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../_lib.sh"

[ $# -ge 1 ] || fail 'usage: bash bin/opencode/opencode-run-wrapped.sh "prompt" [extra flags]'
PROMPT="$1"; shift

command -v opencode &>/dev/null || fail "opencode is not installed (run bin/install-opencode.sh)"
command -v jq &>/dev/null || fail "jq is not installed"

# .env only to read MEMORY_SERVICE_URL/TOKEN in this process — never printed or logged.
set -a; [ -f "$REPO_ROOT/.env" ] && . "$REPO_ROOT/.env"; set +a
MEMORY_URL="${MEMORY_SERVICE_URL:-http://localhost:7700}"

# ── 1. Look up relevant memory (best-effort, never blocks the run) ──
CONTEXT=""
HITS=$(curl -s -m5 -H "x-memory-token: ${MEMORY_SERVICE_TOKEN:-}" \
    --get --data-urlencode "q=$PROMPT" "$MEMORY_URL/memory/search" --data-urlencode "k=5" 2>/dev/null)
if [ -n "$HITS" ]; then
    TEXTS=$(echo "$HITS" | jq -r '.results[]?.text // empty' 2>/dev/null)
    [ -n "$TEXTS" ] && CONTEXT="Relevant memory (shared/personal):
$TEXTS

"
fi

ENRICHED="${CONTEXT}${PROMPT}

If you learned something worth remembering for the future, end your response with a new,
exact line: \"REMEMBER: <the lesson, one sentence>\" — or \"REMEMBER-SHARED: <...>\"
if it's something useful to the whole team, not just you. If there's nothing worth
remembering, don't add that line."

# ── 2. Actually run opencode — JSON format to extract the text without ANSI noise ──
RAW=$(opencode run --format json "$ENRICHED" "$@" 2>/dev/null)
OUT=$(echo "$RAW" | jq -rs '[.[] | select(.type=="text") | .part.text] | join("")' 2>/dev/null)
if [ -z "$OUT" ]; then
    fail "opencode run returned no text — check with: opencode run \"$PROMPT\""
fi

# ── 3. Extract the memory marker (if any) and show the response without that internal line ──
LESSON_SHARED=$(echo "$OUT" | sed -n 's/^REMEMBER-SHARED: //p')
LESSON_USER=$(echo "$OUT" | sed -n 's/^REMEMBER: //p')
echo "$OUT" | grep -v '^REMEMBER\(-SHARED\)\?: '

save_memory() {
    local scope=$1 text=$2
    [ -z "$text" ] && return
    curl -s -m5 -o /dev/null -w '%{http_code}' -X POST \
        -H "x-memory-token: ${MEMORY_SERVICE_TOKEN:-}" -H "Content-Type: application/json" \
        -d "$(jq -n --arg t "$text" --arg s "$scope" '{text:$t, scope:$s}')" \
        "$MEMORY_URL/memory/add" 2>/dev/null | grep -q '^200$' \
        && ok "memory saved (scope=$scope): $text" \
        || warn "could not save memory to $MEMORY_URL (scope=$scope)"
}

save_memory shared "$LESSON_SHARED"
save_memory user "$LESSON_USER"
