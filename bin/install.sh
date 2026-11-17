#!/usr/bin/env bash
# bin/install.sh — setup for personal-agent-kit, for the user who runs it and from wherever the
# repo was cloned: it creates no Linux user. Installs the guards and hooks, a local Qdrant
# (personal collection) and the local memory_service via systemd (writer + single search
# endpoint). Everything local — no central server, no fleet. See --help for the optional parts.
# Usage: bash bin/install.sh [options]
set -uo pipefail

# shellcheck source=bin/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
cd "$REPO_ROOT"

parse_install_args "$@"
settle_install_options
print_install_plan
if [ "$PAK_DRY_RUN" = "1" ]; then
    info "Dry run: nothing was changed."
    exit 0
fi

# ── 1. Base ───────────────────────────────────────────────────────
sep; echo -e "${CYAN}[1/9] Base (tools, Claude Code, submodules, venv, .env, hooks)${NC}"
setup_system_tools
[ "$PAK_WITH_DEV_TOOLS" = "1" ] && setup_dev_tools
setup_claude_code
setup_submodules
setup_venv
setup_env_file
setup_language
setup_precommit
setup_metrics_hook
setup_hooks
setup_cli
setup_tasks_scaffold

# ── 2. Local brain (Qdrant: personal collection) ──────────────────
sep; echo -e "${CYAN}[2/9] Local brain (Qdrant — personal memory)${NC}"
setup_local_qdrant

# ── 3. Local memory_service (systemd, writer for personal memory) ──
# The service is fail-closed: it won't start without auth. Auth is GUARANTEED here: if
# missing, the key is generated and set COMPLETELY (coherent MEMORY_SERVICE_TOKEN +
# MEMORY_USER_TOKENS) — the service ALWAYS ends up configured and running, with startup
# retried here and self-repair during verification.
sep; echo -e "${CYAN}[3/9] Local memory_service (systemd — personal + search)${NC}"
setup_memory_service_local

# ── 4. BMAD (optional) ────────────────────────────────────────────
# Runs before OpenCode: build-config.sh adds the BMAD agents only when BMAD is active.
sep; echo -e "${CYAN}[4/9] BMAD (optional)${NC}"
if [ "$PAK_WITH_BMAD" = "1" ]; then
    setup_bmad
else
    info "BMAD not activated — activate it later with: bash bin/install.sh --with-bmad"
fi

# ── 5. OpenCode (additional client, optional) ─────────────────────
# setup_opencode_client does NOT repeat the local brain/memory_service above, only what's
# OpenCode-specific: Node/CLI/config/keys/timeout/server.
sep; echo -e "${CYAN}[5/9] OpenCode (additional client, optional)${NC}"
if [ "$PAK_WITH_OPENCODE" = "1" ]; then
    setup_opencode_client
    OPENCODE_INSTALLED=1
else
    info "OpenCode skipped — run it later with: bash bin/install-opencode.sh"
    OPENCODE_INSTALLED=0
fi

# ── 6. Voice (optional): playback tools + local Chatterbox fallback ──
# Chatterbox is only used if TTS_ENGINE (edge-tts) fails at runtime — see
# .claude/hooks/tts_speak_worker.py::_synthesize(). Best-effort: unlike Qdrant/
# memory_service, this never fails the installer if Docker isn't available — it's a
# fallback, not a requirement. Reuses the image and model if the container already ran before.
sep; echo -e "${CYAN}[6/9] Voice and Slack (optional)${NC}"
v_slack=skip
if [ "$PAK_WITH_SLACK" = "1" ]; then
    setup_slack && v_slack=1 || v_slack=0
else
    info "Slack bot skipped — run it later with: bash bin/install.sh --with-slack"
fi
v_chatterbox=skip
if [ "$PAK_WITH_TTS" = "1" ]; then
    for tool in ffmpeg pulseaudio-utils; do install_apt "$tool"; done
    if docker_host_ready; then
        if container_running chatterbox-tts-server-chatterbox-tts-server-1; then
            ok "Local Chatterbox TTS already running (:8004)"
            v_chatterbox=1
        else
            CMP="$(docker_compose_cmd)" \
                && $CMP -f local/scripts/chatterbox-tts-server/docker-compose-cpu.yml up -d \
                && ok "Local Chatterbox TTS up (:8004, first start downloads the model — may take a few minutes)" \
                && v_chatterbox=1 \
                || { warn "Could not start Chatterbox TTS — the hook keeps working without a fallback"; v_chatterbox=0; }
        fi
    else
        warn "Docker not available — fallback TTS (Chatterbox) skipped, edge-tts remains the only engine"
    fi
else
    info "Voice skipped — run it later with: bash bin/install.sh --with-tts"
fi

# ── 7. Skill seed (global Claude Code Skills) ──────────────────────
# bin/skills-seed/ carries copies (via build-skills-seed.py) of Skills that apply to any repo
# (debugging, TDD, code review, planning, worktrees, authoring meta-skills) -- these are
# user-global, they don't travel with the git clone. helpers/ai18n brings the ai18n skill. Never
# overwrites one the user already has (no-clobber per folder). See bin/skills-seed/MANIFEST.md for
# what was included/excluded and why.
sep; echo -e "${CYAN}[7/9] Skill seed (global Claude Code Skills)${NC}"
SKILLS_DIR="$HOME/.claude/skills"
mkdir -p "$SKILLS_DIR"
skills_seeded=0
for d in "$REPO_ROOT"/bin/skills-seed/*/ "$REPO_ROOT"/helpers/ai18n/skills/*/; do
    name=$(basename "$d")
    [[ -d "$SKILLS_DIR/$name" ]] && continue
    cp -r "$d" "$SKILLS_DIR/$name"
    skills_seeded=$((skills_seeded + 1))
done
if [[ "$skills_seeded" -gt 0 ]]; then
    ok "skill seed: ${skills_seeded} new ones installed in ${SKILLS_DIR}"
else
    ok "skill seed already complete — no changes"
fi

# ── 8. Claude Code plugins (LSP + functionality) ──────────────────
# Live in ~/.claude/settings.json (per-machine). The 5 LSP ones are zero-cost config pointing at
# the binaries setup_lsp_toolchains installs with --with-dev-tools; the other 6 plus
# frontend-design (project scope) are pure functionality.
sep; echo -e "${CYAN}[8/9] Claude Code plugins (LSP + functionality)${NC}"
setup_claude_plugins
v_plugin=1
plugin_list_after="$(claude plugin list 2>/dev/null)"
for p in claude-code-setup code-simplifier feature-dev hookify pr-review-toolkit security-guidance \
         clangd-lsp gopls-lsp pyright-lsp rust-analyzer-lsp typescript-lsp frontend-design; do
    echo "$plugin_list_after" | grep -A3 "${p}@claude-plugins-official" | grep -q "✔ enabled" || v_plugin=0
done

# ── 9. Verification + summary: reflects REAL state, not hardcoded checkmarks ──
# OpenCode (if requested) already self-verified inside setup_opencode_client — nothing to
# repeat here, its variables (v_node/v_oc/v_build/v_cfg/v_brief/v_custom/v_zai/v_timeout/v_unit)
# are already set for the summary below.
sep; echo -e "${CYAN}[9/9] Verification and summary${NC}"
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
        seed_brain_evidence
    else
        warn "Local memory_service not responding (:$MEMSVC_PORT)"
        v_svc=0
    fi
else
    info "Local memory_service skipped — skipping its verification"; v_svc=skip
fi
if [ "$v_chatterbox" = "1" ]; then
    curl -s -m5 http://localhost:8004/api/model-info >/dev/null 2>&1 && ok "Chatterbox TTS responds (:8004)" \
        || { warn "Chatterbox TTS not responding yet (:8004) — may still be loading the model (~2min on first start)"; v_chatterbox=0; }
fi

echo ""
mark() { [ "$1" = "1" ] && echo -e "  ${GREEN}✔${NC}  $2" || { [ "$1" = "skip" ] && echo -e "  ${YELLOW}–${NC}  $2" || echo -e "  ${RED}✘${NC}  $2"; }; }
mark 1            "Base:           tools, Claude Code, .venv, submodules, .env, hooks"
mark "$v_local"   "Local brain:    Qdrant (personal memory)"
mark "$v_svc"     "Local service:  memory_service via systemd (:$MEMSVC_PORT — personal + search)"
if bmad_active; then
    mark 1        "BMAD:           active (commands, subagents, OpenCode agents)"
else
    mark skip     "BMAD:           not activated (bash bin/install.sh --with-bmad)"
fi
OPENCODE_WARN=0
if [ "${OPENCODE_INSTALLED:-0}" = "1" ]; then
    mark "$v_node"    "OpenCode Node:  $(command -v node &>/dev/null && node --version || echo missing)"
    mark "$v_oc"      "OpenCode CLI:   $(command -v opencode &>/dev/null && opencode --version 2>/dev/null | head -1 || echo missing)"
    mark "$v_build"   "OpenCode cfg:   build-config.sh (opencode.base.json + personas → opencode.json)"
    mark "$v_cfg"     "OpenCode cfg:   providers custom/zai + agents + lsp"
    mark "$v_brief"   "OpenCode brief: memory brief injected into instructions"
    mark "$v_custom"  "OpenCode key:   CUSTOM_API_KEY (custom provider)"
    mark "$v_zai"     "OpenCode key:   ZAI_API_KEY (provider zai / GLM-5.2)"
    mark "$v_timeout" "OpenCode bash:  timeout OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS (diag)"
    mark "$v_unit"    "OpenCode server: opencode-server via systemd (127.0.0.1:4096)"
    for v in "$v_node" "$v_oc" "$v_build" "$v_cfg" "$v_brief" "$v_custom" "$v_zai" "$v_timeout" "$v_unit"; do
        [ "$v" = "0" ] && OPENCODE_WARN=1
    done
else
    mark skip         "OpenCode:       not requested (bash bin/install-opencode.sh whenever you want)"
fi
mark 1            "Skills:         ${skills_seeded} new in ${SKILLS_DIR}"
mark "$v_plugin"  "Plugins:        12 Claude Code plugins (LSP + functionality) + frontend-design"
TTS_ENGINE_CUR=$(.venv/bin/python3 -c "from dotenv import dotenv_values; print(dotenv_values('.env').get('TTS_ENGINE','edge-tts'))" 2>/dev/null)
TTS_PERSONA_CUR=$(.venv/bin/python3 -c "from dotenv import dotenv_values; print(dotenv_values('.env').get('TTS_PERSONA','') or '(none)')" 2>/dev/null)
mark 1            "TTS:            Stop/Notification hooks registered — engine=${TTS_ENGINE_CUR}, persona=${TTS_PERSONA_CUR}"
mark "$v_chatterbox" "TTS fallback:   local Chatterbox (:8004 — only if edge-tts fails at runtime)"
mark "$v_slack"   "Slack bot:      units installed, closed until SLACK_CHANNEL_IDS and SLACK_ALLOWED_USERS list who"
echo ""
warn "Reload the shell to apply Claude Code's env vars:  source ~/.bashrc"
info "When you open the project in Claude Code it will ask you to approve the MCP servers from .mcp.json (context7, sequential-thinking, memory) — say yes once. chrome-devtools is added separately, at the agent level (claude mcp add), it doesn't travel in .mcp.json."
echo ""
# Hard failure ONLY if something local that was requested didn't come up; OpenCode (opt-in,
# best-effort — never fails the installer, same policy as Chatterbox TTS) is just a warning.
if [ "$v_local" = "0" ] || [ "$v_svc" = "0" ]; then
    warn "Setup FINISHED WITH FAILURES — you asked for the local brain but it didn't come up."
    exit 1
elif [ "$OPENCODE_WARN" = "1" ]; then
    warn "Setup complete, but OpenCode has warnings — check above."
else
    ok "Setup complete."
fi
