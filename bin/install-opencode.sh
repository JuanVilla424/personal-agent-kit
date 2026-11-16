#!/usr/bin/env bash
# bin/install-opencode.sh — OpenCode client setup for personal-agent-kit.
# Installs the OpenCode CLI + dependencies (jq, LSP servers), BUILDS ~/.config/opencode/opencode.json
# from the repo (source of truth: bin/opencode/opencode.base.json + prompts read directly from
# .bmad/{local,bmm/agents,core/agents}/* for each persona, agents/*.prompt only for the 3
# wrappers with no persona) via build-config.sh,
# ensures the provider API keys (custom + ZAI/GLM), sets the bash tool timeout for diag,
# and installs the headless server's systemd unit (bin/opencode/opencode-server.service → :4096).
# Aligned with install.sh: uses bin/_lib.sh, numbered phases, Verification + Summary
# with REAL state (no hardcoded checkmarks) and an honest exit 1.
# Usage: bash bin/install-opencode.sh [options]
set -uo pipefail

# shellcheck source=bin/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
cd "$REPO_ROOT"

parse_install_args "$@"
PAK_WITH_OPENCODE=1
settle_install_options
print_install_plan
if [ "$PAK_DRY_RUN" = "1" ]; then
    info "Dry run: nothing was changed."
    exit 0
fi

# ── 1. OpenCode (Node/CLI/LSP/config/keys/timeout/server) ─────────
# Everything OpenCode-specific lives in setup_opencode_client (bin/_lib.sh) — shared with
# install.sh's optional step, so this logic isn't duplicated across two files. Leaves set
# v_node/v_oc/v_build/v_cfg/v_brief/v_custom/v_zai/v_timeout/v_unit for the Verification/Summary
# below, plus exported CONFIG_FILE.
sep; echo -e "${CYAN}[1/5] OpenCode (Node/CLI/LSP/config/keys/timeout/server)${NC}"
setup_opencode_client
warn "Caveat: an upstream AI SDK bug (stepMs 120s, opencode#25509) may still cap it at 120s depending on version."

# ── 2. Local brain (Qdrant: personal collection) ──────────────────
# Same local brain as install.sh (see bin/_lib.sh) — without this, OpenCode starts without
# memory brief if nobody ran install.sh before on this box.
sep; echo -e "${CYAN}[2/5] Local brain (Qdrant — personal memory)${NC}"
setup_local_qdrant

# ── 3. Local memory_service (systemd, writer for personal memory) ──
sep; echo -e "${CYAN}[3/5] Local memory_service (systemd — personal + search)${NC}"
setup_memory_service_local

# ── 4. Verification ────────────────────────────────────────────────
# OpenCode already self-verified inside setup_opencode_client — this only covers what's
# missing: the local brain (Qdrant/memory_service), same as install.sh does.
sep; echo -e "${CYAN}[4/5] Verification${NC}"
v_local=1 v_svc=1
brain_ports
if [ "${LOCAL_BRAIN:-0}" = "1" ]; then
    curl -s -m3 "http://localhost:$QDRANT_PORT/collections" >/dev/null 2>&1 && ok "Local Qdrant responds (:$QDRANT_PORT)" || { warn "Local Qdrant not responding (:$QDRANT_PORT)"; v_local=0; }
else
    info "Local brain skipped — skipping its verification"; v_local=skip
fi
if [ "${LOCAL_MEMSVC:-0}" = "1" ]; then
    if [ "$v_local" = "1" ] && wait_memory_service; then
        ok "Local memory_service responds (:$MEMSVC_PORT)"
        info "Embedding model: a first install downloads it (a few hundred MB)..."
        warm_memory_model && ok "Embedding model ready" \
            || warn "Embedding model not fetched yet — the first save or search will wait for it"
    else
        warn "Local memory_service not responding (:$MEMSVC_PORT)"
        v_svc=0
    fi
else
    info "Local memory_service skipped — skipping its verification"; v_svc=skip
fi

# ── 5. Summary: reflects REAL state, not hardcoded checkmarks ─────
sep; echo -e "${CYAN}[5/5] Summary${NC}\n"
mark() { [ "$1" = "1" ] && echo -e "  ${GREEN}✔${NC}  $2" || { [ "$1" = "skip" ] && echo -e "  ${YELLOW}–${NC}  $2" || echo -e "  ${RED}✘${NC}  $2"; }; }
mark "$v_node"    "Node.js:        $(command -v node &>/dev/null && node --version || echo missing)"
mark "$v_oc"      "OpenCode:       $(command -v opencode &>/dev/null && opencode --version 2>/dev/null | head -1 || echo missing)"
mark "$v_local"   "Local brain:    Qdrant (personal memory)"
mark "$v_svc"     "Local service:  memory_service via systemd (:$MEMSVC_PORT — personal + search)"
mark "$v_build"   "Config built:   build-config.sh (.bmad/* + agents/*.prompt → opencode.json)"
mark "$v_cfg"     "Config valid:   providers custom/zai + agents + lsp"
mark "$v_brief"   "Memory brief:   injected into instructions"
mark "$v_custom"  "CUSTOM_API_KEY  (custom provider)"
mark "$v_zai"     "ZAI_API_KEY     (provider zai / GLM-5.2)"
mark "$v_timeout" "Bash timeout:   OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=300000 (diag)"
mark "$v_unit"    "Server:         opencode-server via systemd (127.0.0.1:4096)"
echo ""
warn "Reload the shell and restart the opencode server to apply:  source ~/.bashrc && sudo systemctl restart opencode-server"
echo ""
# Hard failure if node/opencode/config didn't come up; keys/timeout/unit are just warnings (they depend on the user's environment).
if [ "$v_node" = "0" ] || [ "$v_oc" = "0" ] || [ "$v_build" = "0" ]; then
    fail "OpenCode setup FINISHED WITH FAILURES — node/opencode/config didn't come up."
elif [ "$v_cfg" = "0" ] || [ "$v_brief" = "0" ] || [ "$v_custom" = "0" ] || [ "$v_zai" = "0" ] || [ "$v_timeout" = "0" ] || [ "$v_unit" = "0" ] || [ "$v_local" = "0" ] || [ "$v_svc" = "0" ]; then
    warn "OpenCode setup complete with warnings — check the ✘/⚠ above (config/keys/timeout/local memory)."
else
    ok "OpenCode setup complete."
fi
