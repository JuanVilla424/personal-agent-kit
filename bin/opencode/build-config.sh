#!/usr/bin/env bash
# bin/opencode/build-config.sh — Builds ~/.config/opencode/opencode.json from the repo (source of truth).
# Combines opencode.base.json (mcp + providers + lsp + agents with model/description) with each
# agent's prompt — read directly from its real BMAD persona for the ones that have one
# (.bmad/local/*.txt, .bmad/bmm/agents/*.md, .bmad/core/agents/*.md) and from agents/*.prompt only
# for the ones that don't (wrappers of a single script, if there ever are any) — resolves
# the LSP servers' paths to this machine's absolute paths, validates, and deploys.
# Replaces the old sync-agents.sh (which only patched prompts into a pre-existing config).
# Usage: bash bin/opencode/build-config.sh
set -uo pipefail

# shellcheck source=bin/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../_lib.sh"

BASE="$REPO_ROOT/bin/opencode/opencode.base.json"
AGENTS_DIR="$REPO_ROOT/bin/opencode/agents"
CONFIG_DIR="$HOME/.config/opencode"
CONFIG_FILE="$CONFIG_DIR/opencode.json"

command -v jq &>/dev/null || fail "jq is not installed (run bin/install-opencode.sh)"
[ -f "$BASE" ] || fail "Base template not found: $BASE"

mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_FILE" ]; then
    BK="$CONFIG_FILE.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$CONFIG_FILE" "$BK" && ok "Backed up previous config: $BK"
fi

TMP=$(mktemp); cp "$BASE" "$TMP"

# ── 0. BMAD is opt-in: without it, only the kit's own personas stay ──
if ! bmad_active; then
    jq '.agent |= with_entries(select(.key | IN("infra-agent", "security-agent", "reports-agent", "database")))
        | del(.default_agent)' "$TMP" > "$TMP.n" \
        && mv "$TMP.n" "$TMP" || fail "jq failed removing the BMAD agents"
    info "BMAD not active — building the kit's own agents only"
fi

# ── 0b. The kit's instructions by absolute path: the config is global, the session may be anywhere ──
jq --arg root "$REPO_ROOT" '.instructions |= map(if startswith("/") then . else "\($root)/\(.)" end)' \
    "$TMP" > "$TMP.n" && mv "$TMP.n" "$TMP" || fail "jq failed resolving the instructions"

# ── 1. Resolve the LSP servers to this machine's absolute path ──
# (they're "bare" in the repo because nvm's path changes between machines/node versions)
for key in $(jq -r '.lsp | keys[]' "$TMP"); do
    bin=$(jq -r --arg k "$key" '.lsp[$k].command[0]' "$TMP")
    abs="$(command -v "$bin" 2>/dev/null || true)"
    if [ -n "$abs" ]; then
        jq --arg k "$key" --arg abs "$abs" '.lsp[$k].command[0] = $abs' "$TMP" > "$TMP.n" \
            && mv "$TMP.n" "$TMP" || fail "jq failed resolving LSP $key"
        ok "LSP $key → $abs"
    else
        warn "LSP $key: '$bin' not on PATH — left bare (install it with bin/install-opencode.sh)"
    fi
done

# ── 2. Inject each prompt ──
# Most agents ARE a full BMAD persona — their prompt is read DIRECTLY from the
# real source (.bmad/local/*.txt, .bmad/bmm/agents/*.md, .bmad/core/agents/*.md), never from a
# copy in agents/*.prompt: two copies means someone edits one and the other silently
# goes stale (this really happened with kubernetes.prompt — see memory
# project_opencode_agent_prompt_build_pipeline). Agents with NO persona behind them (they're
# wrappers of a single script) would use their own agents/<key>.prompt — there's no
# BMAD source to "go out of sync" with. Today all 14 agents below DO have a real
# BMAD persona, none falls into this fallback — it stays as a generic mechanism for the
# next agent that doesn't have one.
declare -A BMAD_SOURCE=(
    [infra-agent]="$REPO_ROOT/.bmad/local/infra.txt"
    [security-agent]="$REPO_ROOT/.bmad/local/cybersecurity.txt"
    [reports-agent]="$REPO_ROOT/.bmad/local/reports.txt"
    [database]="$REPO_ROOT/.bmad/local/database.txt"
    [bmad-master]="$REPO_ROOT/.bmad/core/agents/bmad-master.md"
    [analyst]="$REPO_ROOT/.bmad/bmm/agents/analyst.md"
    [architect]="$REPO_ROOT/.bmad/bmm/agents/architect.md"
    [dev]="$REPO_ROOT/.bmad/bmm/agents/dev.md"
    [pm]="$REPO_ROOT/.bmad/bmm/agents/pm.md"
    [sm]="$REPO_ROOT/.bmad/bmm/agents/sm.md"
    [tea]="$REPO_ROOT/.bmad/bmm/agents/tea.md"
    [tech-writer]="$REPO_ROOT/.bmad/bmm/agents/tech-writer.md"
    [ux-designer]="$REPO_ROOT/.bmad/bmm/agents/ux-designer.md"
    [quick-flow]="$REPO_ROOT/.bmad/bmm/agents/quick-flow-solo-dev.md"
)

missing=0
for key in $(jq -r '.agent | keys[]' "$TMP"); do
    f="${BMAD_SOURCE[$key]:-$AGENTS_DIR/$key.prompt}"
    if [ ! -f "$f" ]; then
        warn "Agent '$key' has no prompt source ($f) — its prompt is left empty"; missing=$((missing + 1)); continue
    fi
    jq --rawfile prompt "$f" --arg key "$key" '.agent[$key].prompt = $prompt' "$TMP" > "$TMP.n" \
        && mv "$TMP.n" "$TMP" || fail "jq failed injecting $key's prompt"
done

# ── 2.5 Agent model: if OPENCODE_MODEL is set, apply it to all of them ──
# (install-opencode.sh asks for it; run standalone with no env var, base.json's model is kept)
if [ -n "${OPENCODE_MODEL:-}" ]; then
    jq --arg m "$OPENCODE_MODEL" '.agent |= map_values(.model = $m)' "$TMP" > "$TMP.n" \
        && mv "$TMP.n" "$TMP" || fail "jq failed applying model $OPENCODE_MODEL"
    ok "Model applied to all agents: $OPENCODE_MODEL"
fi

# ── 2.7 Inject the memory MCP (agent_memory via memory_service, on-demand) ──
# Can't be hardcoded in opencode.base.json: the interpreter path belongs to THIS
# REPO_ROOT's .venv, machine-specific just like the LSP paths. Requires the
# `mcp` package installed in .venv (see requirements.txt) — if missing, opencode still
# starts, just without this MCP available.
PY="$REPO_ROOT/.venv/bin/python3"
MCP_MEMORY_SERVER="$REPO_ROOT/bin/opencode/mcp_memory_server.py"
if [ -x "$PY" ] && [ -f "$MCP_MEMORY_SERVER" ]; then
    jq --arg py "$PY" --arg srv "$MCP_MEMORY_SERVER" \
        '.mcp.memory = {"type": "local", "command": [$py, $srv], "enabled": true}' "$TMP" > "$TMP.n" \
        && mv "$TMP.n" "$TMP" && ok "MCP memory → $PY $MCP_MEMORY_SERVER" \
        || fail "jq failed injecting the memory MCP"
else
    warn "Memory MCP skipped (missing .venv or $MCP_MEMORY_SERVER)"
fi

# ── 2.7b The guard and decision MCP (guard_mutation, decide, route_agent) ──
MCP_DECISION_SERVER="$REPO_ROOT/bin/decision_mcp.py"
if [ -x "$PY" ] && [ -f "$MCP_DECISION_SERVER" ]; then
    jq --arg py "$PY" --arg srv "$MCP_DECISION_SERVER" \
        '.mcp.decision = {"type": "local", "command": [$py, $srv], "enabled": true}' "$TMP" > "$TMP.n" \
        && mv "$TMP.n" "$TMP" && ok "MCP decision → $PY $MCP_DECISION_SERVER" \
        || fail "jq failed injecting the decision MCP"
else
    warn "Decision MCP skipped (missing .venv or $MCP_DECISION_SERVER)"
fi

# ── 2.7c The kit's plugins in every project, not only inside this repo ──
# OpenCode finds .opencode/plugins/ by itself only when it runs in this repo; Claude Code's hooks
# are global (local/hooks/install-hooks.py), so the guards are global here too.
PLUGINS_JSON=$(find "$REPO_ROOT/.opencode/plugins" -maxdepth 1 -name '*.js' | sort \
    | jq -R 'select(length > 0) | "file://" + .' | jq -s .)
jq --argjson p "$PLUGINS_JSON" '.plugin = $p' "$TMP" > "$TMP.n" \
    && mv "$TMP.n" "$TMP" && ok "Plugins → $(jq length <<< "$PLUGINS_JSON") guards and hooks, in every project" \
    || fail "jq failed injecting the plugins"

# ── 2.8 Inject the language policy: the resolver's normalized rendering, never the raw file ──
# Machine-specific like the paths above, and it follows ai18n.yaml: re-run this after changing it.
AI18N_RESOLVER="$REPO_ROOT/helpers/ai18n/src/ai18n.py"
AI18N_POLICY="$CONFIG_DIR/ai18n-policy.md"
if [ -x "$PY" ] && [ -f "$AI18N_RESOLVER" ] && "$PY" "$AI18N_RESOLVER" show --root "$REPO_ROOT" > "$AI18N_POLICY"; then
    jq --arg p "$AI18N_POLICY" '.instructions = ((.instructions // []) + [$p])' "$TMP" > "$TMP.n" \
        && mv "$TMP.n" "$TMP" && ok "Language policy → instructions: $AI18N_POLICY" \
        || fail "jq failed injecting the language policy"
else
    warn "Language policy skipped (missing .venv or $AI18N_RESOLVER, or the policy is invalid)"
fi

# ── 2.9 The memory brief: what every session starts with, as in Claude Code's session start ──
# session-lifecycle.js refreshes this file at each session start; written empty when the memory
# service does not answer.
MEMORY_CLI="$REPO_ROOT/local/scripts/memory_index/memory.py"
MEMORY_BRIEF="$CONFIG_DIR/memory-brief.md"
if [ -x "$PY" ] && [ -f "$MEMORY_CLI" ]; then
    "$PY" "$MEMORY_CLI" brief > "$MEMORY_BRIEF" 2>/dev/null || : > "$MEMORY_BRIEF"
    jq --arg p "$MEMORY_BRIEF" '.instructions = ((.instructions // []) + [$p])' "$TMP" > "$TMP.n" \
        && mv "$TMP.n" "$TMP" && ok "Memory brief → instructions: $MEMORY_BRIEF" \
        || fail "jq failed injecting the memory brief"
else
    warn "Memory brief skipped (missing .venv or $MEMORY_CLI)"
fi

# ── 3. Validate and deploy ──
jq empty "$TMP" 2>/dev/null || fail "The built config isn't valid JSON — not deploying it"
mv "$TMP" "$CONFIG_FILE"
n_agents=$(jq '.agent | keys | length' "$CONFIG_FILE")
provs=$(jq -r '.provider | keys | join(", ")' "$CONFIG_FILE")
lsps=$(jq -r '.lsp | keys | join(", ")' "$CONFIG_FILE")
ok "opencode.json built → $CONFIG_FILE"
ok "  $n_agents agents · providers: $provs · lsp: $lsps · default: $(jq -r '.default_agent' "$CONFIG_FILE")"
[ "$missing" -gt 0 ] && warn "$missing agent(s) with no .prompt — check $AGENTS_DIR"
exit 0
