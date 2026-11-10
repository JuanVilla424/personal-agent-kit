#!/usr/bin/env bash
# bin/_lib.sh — shared helpers and base setup for the personal-agent-kit installers.
# Sourced by install.sh and install-opencode.sh.
# Not meant to be run directly.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✔${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
info() { echo -e "${CYAN}→${NC}  $*"; }
fail() { echo -e "${RED}✘${NC}  $*"; exit 1; }
sep()  { echo -e "\n${CYAN}──────────────────────────────────────────${NC}"; }

# ── Run as the invoking user, never as root ────────────────────────
# install.sh / install-opencode.sh do sudo INTERNALLY where root is needed.
# Running the WHOLE thing under `sudo` breaks git (dubious ownership over the user's
# repo) and leaves .venv, ~/.bashrc, ~/.claude and the crontab owned by root. Worse:
# as root, the user's nvm node, aws CLI, and .venv are NOT on PATH → tools report "not
# found" and get reinstalled for nothing. If we were sudo'd from a real user, re-exec
# as that user (no password needed: root can become anyone).
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    warn "Running as root (sudo) — re-executing as '$SUDO_USER'; the installer sudos internally where needed."
    exec sudo -u "$SUDO_USER" -H bash "$0" "$@"
fi

# Plain root (containers, minimal systems) has nothing to elevate and may not ship sudo.
if [ "$(id -u)" -eq 0 ] && ! command -v sudo &>/dev/null; then
    sudo() { "$@"; }
fi

# ── Installer options ───────────────────────────────────────────────
# A core install is the guards, the hooks and the local brain. Everything else is opt-in: by flag,
# or by answering the prompt when there is a terminal and no --yes. Empty means "not decided yet".
PAK_ASSUME_YES=0
PAK_DRY_RUN=0
PAK_WITH_BRAIN=""
PAK_WITH_BMAD=""
PAK_WITH_OPENCODE=""
PAK_WITH_TTS=""
PAK_WITH_SLACK=""
PAK_WITH_DEV_TOOLS=""
PAK_LANGUAGE=""
PAK_OPENCODE_MODEL=""
DEFAULT_OPENCODE_MODEL="custom/extended"
OPENCODE_NPM_PACKAGE="@opencode/cli"
OPENCODE_SERVER_URL="http://127.0.0.1:4096/"
OPENCODE_SERVER_WAIT_TRIES=20
NODE_MAJOR_VERSION=24
MEMORY_SERVICE_WAIT_TRIES=60
BMAD_CLAUDE_DIR=".bmad/integrations/claude"
# Language tags the ai18n standard accepts (helpers/ai18n/SPEC.md, section 4).
LANGUAGE_TAG_RE='^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$'

install_usage() {
    cat <<EOF
Usage: bash bin/$(basename "$0") [options]

Installs the core kit: Claude Code, the guards and hooks, and the local memory brain. Each optional
part is asked about when there is a terminal; with --yes or without one, the defaults apply.

Options:
  -y, --yes               never prompt: take the defaults and the flags below
      --dry-run           print the resolved plan and exit without changing anything
      --with-brain        local Qdrant and memory_service (default)
      --no-brain          skip them
      --with-bmad         activate the BMAD commands, subagents and OpenCode agents
      --no-bmad           leave BMAD inactive (default)
      --with-opencode     install the OpenCode client
      --no-opencode       skip it (default)
      --with-tts          voice tools and the local Chatterbox fallback
      --no-tts            skip them (default)
      --with-slack        the Slack bot and its timers (it answers nobody until you list who)
      --no-slack          skip it (default)
      --with-dev-tools    LSP servers and language toolchains (Rust, Go, Bun, nvm, rbenv, gh)
      --no-dev-tools      skip them (default)
      --language TAG      language for replies and voice, such as es or pt-BR (default: en)
      --opencode-model M  provider/model for the OpenCode agents (default: $DEFAULT_OPENCODE_MODEL)
  -h, --help              show this help
EOF
}

# feature_var NAME → prints the option variable of a --with-NAME / --no-NAME flag.
feature_var() {
    case "$1" in
        brain) echo PAK_WITH_BRAIN ;;
        bmad) echo PAK_WITH_BMAD ;;
        opencode) echo PAK_WITH_OPENCODE ;;
        tts) echo PAK_WITH_TTS ;;
        slack) echo PAK_WITH_SLACK ;;
        dev-tools) echo PAK_WITH_DEV_TOOLS ;;
        *) return 1 ;;
    esac
}

install_option_error() {
    echo -e "${RED}✘${NC}  $1 — see --help" >&2
    exit 2
}

parse_install_args() {
    local feature var
    while [ $# -gt 0 ]; do
        case "$1" in
            -h | --help) install_usage; exit 0 ;;
            -y | --yes) PAK_ASSUME_YES=1 ;;
            --dry-run) PAK_DRY_RUN=1 ;;
            --with-* | --no-*)
                feature="${1#--with-}"
                feature="${feature#--no-}"
                var="$(feature_var "$feature")" || install_option_error "Unknown option: $1"
                if [[ "$1" == --with-* ]]; then printf -v "$var" '1'; else printf -v "$var" '0'; fi
                ;;
            --language)
                [ $# -ge 2 ] || install_option_error "--language needs a language tag"
                [[ "$2" =~ $LANGUAGE_TAG_RE ]] || install_option_error "Invalid language tag: $2"
                PAK_LANGUAGE="$2"
                shift
                ;;
            --opencode-model)
                [ $# -ge 2 ] || install_option_error "--opencode-model needs provider/model"
                PAK_OPENCODE_MODEL="$2"
                shift
                ;;
            *) install_option_error "Unknown option: $1" ;;
        esac
        shift
    done
}

# choose VAR PROMPT DEFAULT → settles an option into VAR as 1 or 0: a flag already decided it, or
# --yes and a missing terminal take the default, or the prompt does.
choose() {
    local var=$1 prompt=$2 default=$3 answer hint="[y/N]"
    [ -n "${!var}" ] && return
    [ "$default" = "1" ] && hint="[Y/n]"
    if [ "$PAK_ASSUME_YES" = "1" ] || ! (: </dev/tty) 2>/dev/null; then
        printf -v "$var" '%s' "$default"
        return
    fi
    read -rp "  $prompt $hint: " answer </dev/tty || answer=""
    case "$answer" in
        [Yy]*) printf -v "$var" '1' ;;
        [Nn]*) printf -v "$var" '0' ;;
        *) printf -v "$var" '%s' "$default" ;;
    esac
}

settle_install_options() {
    [ "$PAK_DRY_RUN" = "1" ] && PAK_ASSUME_YES=1
    choose PAK_WITH_BRAIN "Install the local brain (Qdrant + memory_service)?" 1
    choose PAK_WITH_BMAD "Activate BMAD (commands, subagents, OpenCode agents)?" 0
    choose PAK_WITH_OPENCODE "Also install the OpenCode client?" 0
    choose PAK_WITH_TTS "Install the voice tools and the local Chatterbox fallback?" 0
    choose PAK_WITH_SLACK "Install the Slack bot?" 0
    choose PAK_WITH_DEV_TOOLS "Install the LSP servers and language toolchains?" 0
}

print_install_plan() {
    local line
    info "Install plan:"
    for line in "Local brain:$PAK_WITH_BRAIN" "BMAD:$PAK_WITH_BMAD" "OpenCode:$PAK_WITH_OPENCODE" \
        "Voice:$PAK_WITH_TTS" "Slack:$PAK_WITH_SLACK" "Dev tools:$PAK_WITH_DEV_TOOLS"; do
        if [ "${line##*:}" = "1" ]; then
            echo "  - ${line%%:*}: yes"
        else
            echo "  - ${line%%:*}: no"
        fi
    done
    echo "  - Language: ${PAK_LANGUAGE:-from ai18n.yaml}"
}

# ── Base setup ──────────────────────────────────────────────────────

install_apt() {
    local pkg=$1
    if ! command -v "$pkg" &>/dev/null; then
        info "Installing $pkg..."
        sudo apt-get install -y "$pkg" &>/dev/null && ok "$pkg installed" || warn "Could not install $pkg — install manually"
    else
        ok "$pkg already installed ($(command -v "$pkg"))"
    fi
}

# npm global (-g) installs by default into /usr/lib/node_modules + a symlink in /usr/bin —
# both root-owned with NodeSource's Node.js. Instead of sudo on every install, or touching
# shared system folders (/usr/bin has thousands of unrelated binaries), we redirect npm's
# global prefix to a folder the user owns, which is never root-owned. Idempotent. Its own
# function (not just part of setup_system_tools) because install-opencode.sh also installs
# global npm packages (@opencode/cli) and may run without install.sh having run first in this
# same shell — one script's PATH export doesn't reach the other.
setup_npm_global_prefix() {
    if [ "$(npm config get prefix 2>/dev/null)" != "$HOME/.npm-global" ]; then
        mkdir -p "$HOME/.npm-global"
        npm config set prefix "$HOME/.npm-global"
        ok "npm global prefix → $HOME/.npm-global (no sudo on -g installs)"
    else
        ok "npm global prefix already points to $HOME/.npm-global"
    fi
    export PATH="$HOME/.npm-global/bin:$PATH"
    grep -q '.npm-global/bin' "$HOME/.bashrc" 2>/dev/null \
        || { echo ''; echo '# npm global (-g) without sudo, without touching system folders'; echo 'export PATH="$HOME/.npm-global/bin:$PATH"'; } >> "$HOME/.bashrc"
}

setup_system_tools() {
    info "Updating package index (apt-get update)..."
    sudo apt-get update -qq &>/dev/null || warn "apt-get update failed — package installs below may fail"

    for tool in git curl python3 python3-venv python-is-python3 jq; do install_apt "$tool"; done

    if ! command -v yq &>/dev/null; then
        info "Installing yq..."
        local YQ_VERSION="v4.44.3" YQ_BINARY="yq_linux_amd64"
        curl -sL "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/${YQ_BINARY}" \
            -o /tmp/yq && chmod +x /tmp/yq && sudo mv /tmp/yq /usr/local/bin/yq \
            && ok "yq ${YQ_VERSION} installed" || warn "Could not install yq — install manually"
    else
        ok "yq already installed ($(yq --version 2>/dev/null | head -1))"
    fi

    # Docker and Node come from signed apt repositories: the core install runs no downloaded script.
    if command -v docker &>/dev/null; then
        ok "docker $(docker --version | cut -d' ' -f3 | tr -d ',')"
    elif [ "$PAK_WITH_BRAIN" = "1" ] || [ "$PAK_WITH_TTS" = "1" ]; then
        info "Docker not found — installing from the distribution's packages..."
        # Without recommends: they only add a network fan and a dnsmasq system account.
        if sudo apt-get install -y --no-install-recommends docker.io &>/dev/null; then
            sudo apt-get install -y --no-install-recommends docker-compose-v2 &>/dev/null \
                || sudo apt-get install -y --no-install-recommends docker-compose &>/dev/null \
                || warn "Could not install Docker Compose — install manually"
            sudo systemctl enable --now docker &>/dev/null || warn "Could not start the docker service"
            sudo usermod -aG docker "${SUDO_USER:-$(whoami)}" 2>/dev/null || true
            ok "docker $(docker --version | cut -d' ' -f3 | tr -d ',') installed (re-login for the docker group)"
        else
            warn "Could not install Docker — https://docs.docker.com/engine/install/"
        fi
    fi

    if ! command -v node &>/dev/null; then
        info "Node.js not found — installing from the NodeSource apt repository..."
        sudo mkdir -p -m 755 /etc/apt/keyrings
        curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo tee /etc/apt/keyrings/nodesource.asc >/dev/null
        echo "deb [signed-by=/etc/apt/keyrings/nodesource.asc] https://deb.nodesource.com/node_${NODE_MAJOR_VERSION}.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list >/dev/null
        sudo apt-get update -qq &>/dev/null
        sudo apt-get install -y nodejs &>/dev/null && ok "Node.js $(node --version) installed" || warn "Could not install Node.js — install manually"
    else
        ok "node $(node --version)"
    fi

    setup_npm_global_prefix
}

# Language toolchains for the LSP servers and day-to-day development. Opt-in: the kit itself does
# not need them, and they are the slowest part of an install.
setup_dev_tools() {
    install_apt rbenv
    if [ -d "$HOME/.nvm" ] || command -v nvm &>/dev/null; then
        ok "nvm already installed"
    else
        info "Installing nvm..."
        curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash &>/dev/null \
            && ok "nvm installed (reload shell to use)" || warn "Could not install nvm — install manually"
    fi
    if command -v cargo &>/dev/null || [ -d "$HOME/.cargo" ]; then
        ok "Rust already installed"
    else
        info "Installing Rust (rustup)..."
        curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs | sh -s -- -y &>/dev/null \
            && ok "Rust installed (~/.cargo/bin)" || warn "Could not install Rust — install manually"
    fi
    export PATH="$HOME/.cargo/bin:$PATH"
    if command -v bun &>/dev/null || [ -d "$HOME/.bun" ]; then
        ok "Bun already installed"
    else
        info "Installing Bun..."
        curl -fsSL https://bun.sh/install | bash &>/dev/null \
            && ok "Bun installed (~/.bun/bin)" || warn "Could not install Bun — install manually"
    fi

    # GitHub CLI (gh) — not in Ubuntu's apt; add GitHub's apt repo.
    if command -v gh &>/dev/null; then
        ok "gh already installed"
    else
        info "Installing GitHub CLI (gh)..."
        sudo mkdir -p -m 755 /etc/apt/keyrings
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
        sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
        sudo apt-get update -qq &>/dev/null
        sudo apt-get install -y gh &>/dev/null && ok "gh installed" || warn "Could not install gh — install manually"
    fi

    setup_lsp_toolchains
}

setup_claude_code() {
    if ! command -v claude &>/dev/null; then
        info "Installing Claude Code CLI..."
        npm install -g @anthropic-ai/claude-code &>/dev/null \
            && ok "Claude Code installed ($(claude --version 2>/dev/null | head -1))" \
            || fail "Could not install Claude Code — check npm permissions"
    else
        ok "Claude Code already installed ($(claude --version 2>/dev/null | head -1))"
    fi

    local bashrc="$HOME/.bashrc"
    if ! grep -q "CLAUDE_CODE_EFFORT_LEVEL" "$bashrc" 2>/dev/null; then
        info "Adding Claude Code env vars to ~/.bashrc..."
        local sub_model
        sub_model="$(model_for_role claude_code_subagent)"
        {
            echo ""
            echo "# Claude Code configuration"
            echo "export CLAUDE_CODE_EFFORT_LEVEL=max"
            [ -n "$sub_model" ] && echo "export CLAUDE_CODE_SUBAGENT_MODEL=$sub_model"
        } >> "$bashrc"
        [ -n "$sub_model" ] || warn "roles.claude_code_subagent not resolved (model map) — CLAUDE_CODE_SUBAGENT_MODEL not set"
        ok "Claude Code env vars added to ~/.bashrc (reload shell or run: source ~/.bashrc)"
    else
        ok "Claude Code env vars already in ~/.bashrc"
    fi

    # Claude never appears as a (co-)author of commits/PRs — a project rule, not the tool's
    # default. includeGitInstructions=false turns off the git/PR system-reminder the harness
    # injects into the session (the source); the empty attribution/includeCoAuthoredBy fields
    # are belt-and-suspenders in case some flow still checks them. Idempotent merge: preserves
    # the rest of the file.
    local claude_settings="$HOME/.claude/settings.json"
    mkdir -p "$(dirname "$claude_settings")"
    [ -f "$claude_settings" ] || echo '{}' > "$claude_settings"
    # System python3 (not .venv): setup_venv runs AFTER setup_claude_code in install.sh's
    # sequence, so .venv doesn't exist yet here — this block only uses stdlib (json), the
    # repo's venv isn't needed.
    python3 -c "
import json
path = '$claude_settings'
with open(path) as f:
    cfg = json.load(f)
cfg.setdefault('model', 'opusplan')
cfg['includeGitInstructions'] = False
cfg['includeCoAuthoredBy'] = False
cfg['attribution'] = {'commit': '', 'pr': '', 'sessionUrl': False}
with open(path, 'w') as f:
    json.dump(cfg, f, indent=2)
    f.write('\n')
" && ok "Claude Code defaults set: model and no attribution (~/.claude/settings.json)" \
    || warn "Could not set the Claude Code defaults in ~/.claude/settings.json"
}

# LSP servers shared by Claude Code's 5 zero-cost LSP plugins (clangd-lsp/gopls-lsp/pyright-lsp/
# rust-analyzer-lsp/typescript-lsp — each just points Claude Code at an out-of-process binary,
# never installs it) AND OpenCode's bin/opencode/opencode.base.json "lsp" section. One function,
# called from both install.sh and install-opencode.sh — no duplicated install logic.
setup_lsp_toolchains() {
    ensure_npm_lsp() {  # $1 = npm package(s), $2 = binary it provides
        if command -v "$2" &>/dev/null; then
            ok "$2 already installed"
        else
            info "Installing $1 (LSP)..."
            npm install -g $1 &>/dev/null && ok "$1 installed" || warn "Could not install $1 — $2 LSP will not work"
        fi
    }
    ensure_npm_lsp "pyright" "pyright-langserver"
    ensure_npm_lsp "typescript typescript-language-server" "typescript-language-server"

    if command -v rust-analyzer &>/dev/null; then
        ok "rust-analyzer already installed"
    elif command -v rustup &>/dev/null; then
        info "Installing rust-analyzer component..."
        rustup component add rust-analyzer &>/dev/null \
            && ok "rust-analyzer installed" || warn "Could not install rust-analyzer"
    else
        warn "rustup not found — rust-analyzer skipped (it comes with --with-dev-tools)"
    fi

    # Go — not installed by setup_system_tools (gopls is its only consumer here); official
    # tarball, same pattern as yq/Rust/Bun above (pinned version, PATH via ~/.bashrc).
    if ! command -v go &>/dev/null; then
        info "Installing Go..."
        local GO_VERSION="1.26.3" GOARCH
        GOARCH="$(dpkg --print-architecture)"
        if curl -sL "https://go.dev/dl/go${GO_VERSION}.linux-${GOARCH}.tar.gz" -o /tmp/go.tar.gz \
            && sudo tar -C /usr/local -xzf /tmp/go.tar.gz; then
            ok "Go ${GO_VERSION} installed (/usr/local/go)"
        else
            warn "Could not install Go — https://go.dev/doc/install"
        fi
        rm -f /tmp/go.tar.gz
        grep -q '/usr/local/go/bin' "$HOME/.bashrc" 2>/dev/null \
            || { echo ''; echo '# Go (gopls LSP)'; echo 'export PATH=$PATH:/usr/local/go/bin:$HOME/go/bin'; } >> "$HOME/.bashrc"
        export PATH="$PATH:/usr/local/go/bin:$HOME/go/bin"
    else
        ok "go already installed ($(go version | awk '{print $3}'))"
        export PATH="$PATH:$HOME/go/bin"
    fi
    if command -v gopls &>/dev/null; then
        ok "gopls already installed"
    elif command -v go &>/dev/null; then
        info "Installing gopls..."
        go install golang.org/x/tools/gopls@latest &>/dev/null \
            && ok "gopls installed (~/go/bin)" || warn "Could not install gopls"
    else
        warn "go not available — cannot install gopls"
    fi

    if command -v clangd &>/dev/null; then
        ok "clangd already installed"
    else
        info "Installing clangd..."
        sudo apt-get install -y clangd &>/dev/null \
            && ok "clangd installed" || warn "Could not install clangd — sudo apt-get install clangd"
    fi
}

# Claude Code plugins this project uses — LSP plugins (clangd-lsp/gopls-lsp/pyright-lsp/
# rust-analyzer-lsp/typescript-lsp) are zero-cost config pointing at setup_lsp_toolchains'
# binaries; the rest are pure feature plugins with no LSP/binary dependency. All user-scope
# except frontend-design (project-scope, applies only to this repo).
setup_claude_plugins() {
    command -v claude &>/dev/null || { warn "claude not installed — skipping plugins"; return; }
    # A fresh Claude Code only knows its built-in directory.
    claude plugin marketplace list 2>/dev/null | grep -q claude-plugins-official \
        || claude plugin marketplace add anthropics/claude-plugins-official &>/dev/null \
        || warn "could not add the claude-plugins-official marketplace"
    local user_plugins=(
        claude-code-setup code-simplifier feature-dev hookify pr-review-toolkit security-guidance
        clangd-lsp gopls-lsp pyright-lsp rust-analyzer-lsp typescript-lsp
    )
    local p list
    list="$(claude plugin list 2>/dev/null)"
    for p in "${user_plugins[@]}"; do
        if echo "$list" | grep -A2 "${p}@claude-plugins-official" | grep -q "Scope: user"; then
            ok "plugin $p already installed (user)"
        else
            claude plugin install "${p}@claude-plugins-official" --scope user -y &>/dev/null \
                && ok "plugin $p installed (user)" \
                || warn "could not install plugin $p"
        fi
    done
    if echo "$list" | grep -A2 "frontend-design@claude-plugins-official" | grep -q "Scope: project"; then
        ok "plugin frontend-design already at project scope — no changes"
    else
        claude plugin install frontend-design@claude-plugins-official --scope project -y &>/dev/null \
            && ok "plugin frontend-design installed at project scope" \
            || warn "could not install plugin frontend-design"
    fi
}

setup_submodules() {
    # Belt and suspenders: if this still runs as root (pure root, no SUDO_USER), git
    # rejects the user's repo as 'dubious ownership' — allow it (idempotent).
    if [ "$(id -u)" -eq 0 ]; then
        git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$REPO_ROOT" \
            || git config --global --add safe.directory "$REPO_ROOT"
    fi
    git -C "$REPO_ROOT" submodule update --init --recursive \
        && ok "Submodules initialized" || fail "Submodule init failed"
}

setup_venv() {
    cd "$REPO_ROOT"
    if [ ! -d ".venv" ]; then
        info "Creating .venv..."
        python3 -m venv .venv && ok ".venv created"
    else
        ok ".venv already exists"
    fi
    info "Installing base dependencies..."
    .venv/bin/pip install --upgrade pip --quiet
    .venv/bin/pip install -r requirements.txt --quiet && ok "requirements.txt installed"
    [ -f requirements.dev.txt ] && .venv/bin/pip install -r requirements.dev.txt --quiet && ok "requirements.dev.txt installed"
}

# Installs a tool's requirements.txt into the root .venv. $1 = path relative to the requirements file.
install_tool_deps() {
    local req="$REPO_ROOT/$1"
    [ -f "$req" ] || { warn "$1 does not exist — skipping"; return; }
    "$REPO_ROOT/.venv/bin/pip" install -r "$req" --quiet && ok "$1 deps installed" || warn "failed installing $1"
}

setup_precommit() {
    cd "$REPO_ROOT"
    .venv/bin/pre-commit --version &>/dev/null || fail "pre-commit not found in .venv — check requirements.dev.txt"
    # The hooks are only installed: running them here would rewrite the user's files.
    if [ -f "$REPO_ROOT/.git/hooks/pre-commit" ] && grep -q pre-commit "$REPO_ROOT/.git/hooks/pre-commit" 2>/dev/null; then
        ok "pre-commit hooks already installed"
    else
        .venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push \
            && ok "pre-commit hooks installed (pre-commit + pre-push)"
    fi
}

setup_metrics_hook() {
    # Stop hook → pushes each Claude Code turn's metrics to the Pushgateway (PUSHGATEWAY_URL from .env).
    chmod +x "$REPO_ROOT/local/monitoring/hooks/push-claude-code-metric.sh" 2>/dev/null || true
    "$REPO_ROOT/.venv/bin/python3" "$REPO_ROOT/local/monitoring/hooks/install-claude-code-hook.py" \
        && ok "Session metrics hook registered (~/.claude/settings.json)" \
        || warn "Could not register metrics hook — run: .venv/bin/python3 local/monitoring/hooks/install-claude-code-hook.py"
}

# The kit's command line for whoever installs it: ~/.local/bin/pak links to this clone's bin/pak. A
# different file already called pak is left alone.
setup_cli() {
    local link="$HOME/.local/bin/pak"
    mkdir -p "$HOME/.local/bin"
    if [ -e "$link" ] && [ "$(readlink -f "$link")" != "$REPO_ROOT/bin/pak" ]; then
        warn "$link exists and is not this kit's: left alone (run $REPO_ROOT/bin/pak instead)"
        return 0
    fi
    ln -sfn "$REPO_ROOT/bin/pak" "$link" && ok "pak → $link (try: pak doctor)"
}

setup_hooks() {
    # Registers ALL the hooks from local/hooks/install-hooks.py: PreToolUse (write-guard,
    # rm-guard), PostToolUse (post-write-judge, post-plan-approval),
    # PreCompact, UserPromptSubmit (token-check), SessionStart, and Stop/Notification (TTS).
    # See local/hooks/README.md for the full list and what each one does.
    chmod +x "$REPO_ROOT"/local/hooks/pre-write-guard.sh "$REPO_ROOT"/local/hooks/post-write-judge.sh \
        "$REPO_ROOT"/local/hooks/judge_against_agents.py 2>/dev/null || true
    "$REPO_ROOT/.venv/bin/python3" "$REPO_ROOT/local/hooks/install-hooks.py" \
        && ok "Hooks registered (see local/hooks/README.md — guards, TTS, memory, etc.)" \
        || warn "Could not register hooks — run: python3 local/hooks/install-hooks.py"
}

# render_placeholders FILE → prints FILE for this user and this checkout. The repo's templates
# (.env.template, *.service) carry <user>, /home/<user> and <opencode-bin> placeholders.
render_placeholders() {
    local claude_bin
    claude_bin="$(command -v claude 2>/dev/null || true)"
    sed -e "s#/home/<user>/personal-agent-kit#$REPO_ROOT#g" \
        -e "s#/home/<user>#$HOME#g" \
        -e "s#<user>#$(id -un)#g" \
        -e "s#<opencode-bin>#$(command -v opencode 2>/dev/null)#g" \
        -e "s#<claude-bin>#$claude_bin#g" \
        -e "s#<claude-dir>#${claude_bin%/*}#g" "$1"
}

# The Slack bot (local/scripts/notify): its own venv, its .env and its units. Closed by default:
# with SLACK_CHANNEL_IDS or SLACK_ALLOWED_USERS empty it answers nobody, and without its tokens
# the units are installed but not started.
SLACK_DIR_REL="local/scripts/notify"
setup_slack() {
    local dir="$REPO_ROOT/$SLACK_DIR_REL" unit
    if [ ! -x "$dir/venv/bin/python3" ]; then
        python3 -m venv "$dir/venv" && ok "Slack bot venv created" || { warn "Could not create the Slack bot venv"; return 1; }
    fi
    "$dir/venv/bin/pip" install -q -r "$dir/requirements.txt" && ok "Slack bot dependencies installed" \
        || { warn "Could not install the Slack bot dependencies"; return 1; }
    if [ -f "$dir/.env" ]; then
        ok "$SLACK_DIR_REL/.env already exists — no changes"
    else
        (umask 077 && render_placeholders "$dir/.env.template" > "$dir/.env") && ok "$SLACK_DIR_REL/.env created (private)"
    fi
    for unit in "$dir"/agent-bot*.service "$dir"/agent-bot*.timer; do
        install_unit "$unit"
    done
    sudo systemctl daemon-reload
    if "$dir/venv/bin/python3" -c "import sys; from dotenv import dotenv_values; v = dotenv_values(sys.argv[1]); sys.exit(0 if v.get('SLACK_BOT_TOKEN') and v.get('SLACK_APP_TOKEN') else 1)" "$dir/.env" 2>/dev/null; then
        sudo systemctl enable --now agent-bot.service agent-bot-watchdog.timer agent-bot-backup.timer \
            agent-bot-rotate.timer && ok "Slack bot running"
    else
        info "Slack bot installed, not started: fill SLACK_* in $SLACK_DIR_REL/.env, then"
        info "  sudo systemctl enable --now agent-bot.service agent-bot-watchdog.timer agent-bot-backup.timer agent-bot-rotate.timer"
    fi
}

# .env — the single config file (see .env.template). Created once and never overwritten; owner-only
# because it holds the local tokens.
setup_env_file() {
    local env_file="$REPO_ROOT/.env"
    if [ -f "$env_file" ]; then
        ok ".env already exists — no changes"
    else
        render_placeholders "$REPO_ROOT/.env.template" > "$env_file" && ok ".env created from .env.template"
    fi
    chmod 600 "$env_file"
}

# ai18n.yaml is the one place for languages, so --language edits it. The repo surfaces (document,
# code, instruct) stay in English; only the conversation changes, and with it the voice.
setup_language() {
    [ -n "$PAK_LANGUAGE" ] || return 0
    local policy="$REPO_ROOT/ai18n.yaml" tag="$PAK_LANGUAGE"
    [ "$tag" = "no" ] && tag='"no"' # YAML 1.1 reads a bare no as false
    sed -i -E "s/^(respond|speak): .*/\1: $tag/" "$policy"
    if [ -f "$REPO_ROOT/.env" ]; then
        sed -i -E "s/^TTS_LANGUAGE=.*/TTS_LANGUAGE=$PAK_LANGUAGE/" "$REPO_ROOT/.env"
    fi
    ok "Replies and voice set to $PAK_LANGUAGE (ai18n.yaml)"
}

bmad_active() { [ -d "$REPO_ROOT/.claude/commands/bmad" ]; }

# BMAD is opt-in. .bmad/ always ships with the repo; activating it copies its slash commands and
# subagents into .claude/, where the engines look for them, and build-config.sh adds its OpenCode
# agents. Copies, not links, so no engine depends on following symlinks; re-running refreshes them.
setup_bmad() {
    local src="$REPO_ROOT/$BMAD_CLAUDE_DIR" agent
    mkdir -p "$REPO_ROOT/.claude/commands" "$REPO_ROOT/.claude/agents"
    cp -r "$src/commands/bmad" "$REPO_ROOT/.claude/commands/" || fail "Could not copy the BMAD commands"
    for agent in "$src"/agents/*/; do
        cp -r "${agent%/}" "$REPO_ROOT/.claude/agents/" || fail "Could not copy BMAD agent $agent"
    done
    ok "BMAD active ($(find "$REPO_ROOT/.claude/commands/bmad" -type f | wc -l) commands)"
}

# TASKS.md — TodoWrite substitute on surfaces without that tool (see AGENTS.md's "Task
# Tracking" section). post-plan-approval.sh only APPENDS to History; if the file doesn't
# exist yet, this gives the first approved plan a real template to land in. Idempotent:
# does not touch an existing TASKS.md (never overwrites in-progress work).
setup_tasks_scaffold() {
    local tasks_file="$REPO_ROOT/TASKS.md"
    if [ -f "$tasks_file" ]; then
        ok "TASKS.md already exists — no changes"
        return
    fi
    cp "$REPO_ROOT/bin/tasks.template.md" "$tasks_file"
    ok "TASKS.md created (tracking template)"
}

# Adds a line to the crontab if it isn't there already (idempotent). $1 = full cron line, $2 = unique pattern.
cron_add() {
    local line=$1 pattern=$2
    if crontab -l 2>/dev/null | grep -qF "$pattern"; then
        ok "cron already present: $pattern"
    else
        (crontab -l 2>/dev/null; echo "$line") | crontab - && ok "cron added: $pattern"
    fi
}

# ── Local brain (Qdrant + memory_service) — shared by install.sh / install-opencode.sh ──
# Factored out so both clients leave the same local memory running, without duplicating logic.
# Follows PAK_WITH_BRAIN; sets LOCAL_BRAIN=1|0 so setup_memory_service_local knows whether to
# proceed.
setup_local_qdrant() {
    LOCAL_BRAIN=0
    if [ "$PAK_WITH_BRAIN" != "1" ]; then
        warn "Local brain skipped"
        return
    fi
    if ! docker_host_ready; then
        warn "Docker not available — local brain skipped"
        return
    fi
    LOCAL_BRAIN=1
    if container_running memory-qdrant; then
        ok "Local Qdrant already running (memory-qdrant:7633)"
    else
        CMP="$(docker_compose_cmd)" \
            && $CMP -f "$REPO_ROOT/local/scripts/memory_index/docker-compose.yml" up -d \
            && ok "Local Qdrant up (memory-qdrant:7633)" \
            || warn "Could not start Qdrant"
    fi
    install_tool_deps "local/scripts/memory_index/requirements.txt"
}

# Local memory_service (systemd, writer for personal memory). Requires LOCAL_BRAIN set by
# setup_local_qdrant. The service is fail-closed: it won't start without auth — auth is
# GUARANTEED here (generated and set if missing). Sets LOCAL_MEMSVC=1|skip.
setup_memory_service_local() {
    if [ "${LOCAL_BRAIN:-0}" = "1" ]; then
        if ! has_env MEMORY_USER_TOKENS && ! has_env MEMORY_ADMIN_TOKEN && ! env_is_true MEMORY_ALLOW_NO_AUTH; then
            if ! has_env MEMORY_SERVICE_TOKEN; then
                info "No client key — generating and setting one..."
                NEW_TOK="tok_$(head -c24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
                NEW_TOK="$NEW_TOK" "$REPO_ROOT/.venv/bin/python3" -c "
import os
from dotenv import set_key
set_key('$REPO_ROOT/.env', 'MEMORY_SERVICE_TOKEN', os.environ['NEW_TOK'], quote_mode='never')
"
            fi
            "$REPO_ROOT/.venv/bin/python3" -c "
import getpass
from dotenv import dotenv_values, set_key
tok = dotenv_values('$REPO_ROOT/.env').get('MEMORY_SERVICE_TOKEN', '')
set_key('$REPO_ROOT/.env', 'MEMORY_USER_TOKENS', f'{tok}:{getpass.getuser()}', quote_mode='never')
"
            ok "local auth set (key in MEMORY_SERVICE_TOKEN + MEMORY_USER_TOKENS, identity $(whoami))"
        fi
        install_unit "$REPO_ROOT/local/scripts/memory_index/agent-memory.service"
        install_unit "$REPO_ROOT/local/scripts/memory_index/agent-memory-consolidate.service"
        install_unit "$REPO_ROOT/local/scripts/memory_index/agent-memory-consolidate.timer"
        sudo systemctl daemon-reload
        sudo systemctl enable --now agent-memory-consolidate.timer 2>/dev/null \
            && ok "nightly memory consolidation scheduled (03:30, agent-memory-consolidate.timer)" \
            || warn "could not schedule the nightly memory consolidation"
        if unit_active agent-memory.service; then
            # a re-install brings new code: the running service has to load it
            sudo systemctl restart agent-memory.service 2>/dev/null || true
            ok "local memory_service restarted on the current code (systemd)"
        else
            fuser -k 7700/tcp 2>/dev/null || true   # free the port if a stray process held it
            sudo systemctl enable --now agent-memory.service 2>/dev/null || true
            if ! unit_active agent-memory.service; then
                sleep 2
                sudo systemctl restart agent-memory.service 2>/dev/null || true
                sleep 3
            fi
            unit_active agent-memory.service && ok "local memory_service configured and running (:7700)" \
                || info "starting up — verification will confirm and repair"
        fi
        LOCAL_MEMSVC=1
    else
        info "Local brain skipped — skipping local memory_service"
        LOCAL_MEMSVC=skip
    fi
}

# Full OpenCode client: Node/nvm, CLI, LSP toolchains, build-config.sh (builds opencode.json
# with the memory brief + asks for the model), provider API keys, bash tool timeout, systemd
# opencode-server. Shared between install.sh (optional step, after the local brain/
# memory_service already ran) and install-opencode.sh (its own main flow) — does NOT include
# Qdrant/memory_service/cron: those stay the caller's responsibility, so setup_local_qdrant's
# interactive prompt isn't asked twice if install.sh already did it. setup_lsp_toolchains IS
# repeated here (not interactive, repeating it doesn't cause a double prompt). Includes its
# own verification (avoids checking command -v opencode in setup AND again in a separate
# Verification step) — leaves set: v_node v_oc v_build v_cfg v_brief v_custom v_zai v_timeout
# v_unit, plus exported OPENCODE_MODEL/CONFIG_FILE for whoever needs them.
setup_opencode_client() {
    local BASHRC="$HOME/.bashrc"
    local BUILD_SCRIPT="$REPO_ROOT/bin/opencode/build-config.sh"
    local BASH_TIMEOUT_MS=300000
    CONFIG_FILE="$HOME/.config/opencode/opencode.json"

    # Node.js / nvm
    if [ -f "$HOME/.nvm/nvm.sh" ]; then
        # shellcheck source=/dev/null
        . "$HOME/.nvm/nvm.sh"
    fi
    v_node=1
    if ! command -v node &>/dev/null; then
        if command -v nvm &>/dev/null; then
            info "Node.js not found — installing 20 via nvm..."
            nvm install 20 &>/dev/null && nvm use 20 &>/dev/null || { warn "nvm install 20 failed"; v_node=0; }
        else
            warn "Node.js not found and no nvm — install nvm (https://github.com/nvm-sh/nvm) and retry"
            v_node=0
        fi
    fi
    if [ "$v_node" = "1" ]; then
        NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
        if [ "$NODE_MAJOR" -lt 20 ]; then
            warn "Node.js $(node --version 2>/dev/null) is too old (needs ≥20)"
            v_node=0
        else
            ok "node $(node --version)"
        fi
    fi

    # OpenCode CLI — the version the guards were proven against (configs/opencode.version): a new
    # major once ignored every plugin of this kit without an error. OpenCode 2 is published as
    # @opencode/cli; the old opencode-ai package stays on the 1.x line.
    v_oc=1
    setup_npm_global_prefix
    local oc_pin
    oc_pin="$(tr -d '[:space:]' < "$REPO_ROOT/configs/opencode.version")"
    if ! command -v opencode &>/dev/null; then
        info "Installing $OPENCODE_NPM_PACKAGE@$oc_pin..."
        npm install -g "$OPENCODE_NPM_PACKAGE@$oc_pin" &>/dev/null && ok "OpenCode installed ($(opencode --version 2>/dev/null | head -1))" \
            || { warn "Could not install $OPENCODE_NPM_PACKAGE@$oc_pin — check npm permissions"; v_oc=0; }
    else
        ok "OpenCode already installed ($(opencode --version 2>/dev/null | head -1))"
        opencode --version 2>/dev/null | grep -q "$oc_pin" \
            || warn "OpenCode is not $oc_pin, the version the guards were proven against: bash bin/tests/guard-e2e/run.sh opencode"
    fi

    # jq — normally already brought in by setup_system_tools; safety net if this function runs alone.
    command -v jq &>/dev/null || { sudo apt-get install -y jq &>/dev/null && ok "jq installed" || warn "Could not install jq"; }

    # LSP — idempotent and non-interactive, repeating it if install.sh already ran it bothers no one.
    setup_lsp_toolchains

    # Model + build-config.sh
    local OC_MODEL="$PAK_OPENCODE_MODEL"
    if [ -z "$OC_MODEL" ] && [ "$PAK_ASSUME_YES" != "1" ] && (: </dev/tty) 2>/dev/null; then
        read -rp "  OpenCode model for the agents (provider/model) [${DEFAULT_OPENCODE_MODEL}]: " OC_MODEL </dev/tty || OC_MODEL=""
    fi
    export OPENCODE_MODEL="${OC_MODEL:-$DEFAULT_OPENCODE_MODEL}"

    v_build=1
    if [ -f "$BUILD_SCRIPT" ]; then
        bash "$BUILD_SCRIPT" && ok "config built from the repo (providers + lsp + agents, model=${OPENCODE_MODEL})" \
            || { warn "build-config.sh failed"; v_build=0; }
    else
        warn "Could not find build-config.sh at: $BUILD_SCRIPT"
        v_build=0
    fi

    # Provider API keys (custom + ZAI/GLM) — never print the value, only whether it's present.
    _check_opencode_key() {
        local k=$1
        if [ -n "${!k:-}" ]; then
            ok "$k present in the environment"
        elif grep -q "$k" "$BASHRC" 2>/dev/null; then
            ok "$k in ~/.bashrc (reload: source ~/.bashrc)"
        else
            warn "$k is missing — add it to ~/.bashrc:  export $k=your_key_here"
            return 1
        fi
    }
    v_custom=1; _check_opencode_key CUSTOM_API_KEY || v_custom=0
    v_zai=1;    _check_opencode_key ZAI_API_KEY    || v_zai=0

    # OpenCode's bash tool timeout (diag and long commands)
    v_timeout=1
    if grep -q "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS" "$BASHRC" 2>/dev/null; then
        ok "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS already in ~/.bashrc"
    else
        {
            echo ""
            echo "# OpenCode — raises the bash tool timeout (default 120s) for diag and long commands"
            echo "export OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=${BASH_TIMEOUT_MS}"
        } >> "$BASHRC" && ok "bash timeout → $((BASH_TIMEOUT_MS / 1000))s"
    fi

    # opencode-server (systemd, headless 127.0.0.1:4096). A started unit is not a running server:
    # a bad flag makes it restart in a loop, so the port has to answer.
    v_unit=1
    if [ -f "$REPO_ROOT/bin/opencode/opencode-server.service" ]; then
        install_unit "$REPO_ROOT/bin/opencode/opencode-server.service"
        sudo systemctl daemon-reload
        sudo systemctl enable opencode-server.service 2>/dev/null
        sudo systemctl restart opencode-server.service 2>/dev/null
        if wait_http "$OPENCODE_SERVER_URL" "$OPENCODE_SERVER_WAIT_TRIES"; then
            ok "opencode-server running via systemd ($OPENCODE_SERVER_URL)"
        else
            warn "opencode-server does not answer on $OPENCODE_SERVER_URL — check: journalctl -u opencode-server"
            v_unit=0
        fi
    else
        warn "Missing bin/opencode/opencode-server.service in the repo — headless server not installed"
        v_unit=0
    fi

    # Final verification: valid config + memory brief injected + timeout/unit persisted.
    v_cfg=1
    if [ -f "$CONFIG_FILE" ] && jq empty "$CONFIG_FILE" 2>/dev/null; then
        if jq -e '.provider.zai and .provider.custom and ((.agent | keys | length) > 0)' "$CONFIG_FILE" >/dev/null 2>&1; then
            ok "valid config: providers custom/zai + $(jq '.agent | keys | length' "$CONFIG_FILE") agents + lsp $(jq -r '.lsp | keys | join("/")' "$CONFIG_FILE")"
        else
            warn "config built but incomplete (providers/agents)"
            v_cfg=0
        fi
    else
        warn "opencode.json does not exist or isn't valid JSON"
        v_cfg=0
    fi
    v_brief=1
    if [ -f "$CONFIG_FILE" ] && jq -e '(.instructions // []) | map(endswith("/memory-brief.md")) | any' "$CONFIG_FILE" >/dev/null 2>&1; then
        ok "memory brief injected into instructions (refreshed at each session start)"
    else
        warn "the memory brief did not end up in instructions"
        v_brief=0
    fi
    grep -q "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS" "$BASHRC" 2>/dev/null || v_timeout=0
    unit_active opencode-server.service || v_unit=0
}

# ── Validations: idempotency (already done?) + prerequisites (env present?) ──

# has_env KEY → 0 if the var exists and is NOT empty in the root .env. Never prints the value (safe for secrets).
has_env() {
    [ -f "$REPO_ROOT/.env" ] || return 1
    [ -x "$REPO_ROOT/.venv/bin/python3" ] || return 1
    KEY="$1" "$REPO_ROOT/.venv/bin/python3" -c "import os,sys; from dotenv import dotenv_values; sys.exit(0 if dotenv_values(os.path.join('$REPO_ROOT','.env')).get(os.environ['KEY'],'') else 1)" 2>/dev/null
}

# env_is_true KEY → 0 if the var in the root .env is true, the way memory_service reads it.
env_is_true() {
    [ -f "$REPO_ROOT/.env" ] || return 1
    [ -x "$REPO_ROOT/.venv/bin/python3" ] || return 1
    KEY="$1" "$REPO_ROOT/.venv/bin/python3" -c "import os,sys; from dotenv import dotenv_values; sys.exit(0 if (dotenv_values(os.path.join('$REPO_ROOT','.env')).get(os.environ['KEY']) or '').lower() in ('1','true','yes') else 1)" 2>/dev/null
}

# require_env VAR... → 0 if ALL are present in .env; if any is missing, warns and returns 1 (to skip the step).
require_env() {
    local rc=0 v
    for v in "$@"; do has_env "$v" || { warn "  missing \$$v in .env"; rc=1; }; done
    return $rc
}

# Set to "sudo" by docker_host_ready when this shell can't reach the daemon on its own: the docker
# group of a fresh install only applies after the next login.
DOCKER_SUDO=""

# container_running NAME → 0 if the Docker container is already running.
container_running() { $DOCKER_SUDO docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$1"; }

# docker_host_ready → 0 if docker reaches a live daemon. If the current DOCKER_HOST/context
# doesn't connect but a rootless socket exists for this user, adopt it (exports DOCKER_HOST).
docker_host_ready() {
    command -v docker &>/dev/null || return 1
    docker info &>/dev/null && return 0
    local sock="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/docker.sock"
    if [ -S "$sock" ]; then
        export DOCKER_HOST="unix://$sock"
        docker info &>/dev/null && return 0
        unset DOCKER_HOST
    fi
    sudo -n docker info &>/dev/null && DOCKER_SUDO="sudo"
}

# docker_compose_cmd → prints the available compose: "docker compose" (v2 plugin) or
# "docker-compose" (standalone v1). Returns 1 if neither is available.
docker_compose_cmd() {
    if $DOCKER_SUDO docker compose version &>/dev/null; then echo "$DOCKER_SUDO docker compose"
    elif command -v docker-compose &>/dev/null; then echo "$DOCKER_SUDO docker-compose"
    else return 1; fi
}

# wait_memory_service → 0 once :7700 reports healthy. The first start downloads the embedding
# model, which can take a few minutes.
wait_memory_service() {
    local _
    for _ in $(seq 1 "$MEMORY_SERVICE_WAIT_TRIES"); do
        curl -s -m5 "http://localhost:7700/memory/health" 2>/dev/null | grep -q '"status":"ok"' && return 0
        sleep 5
    done
    return 1
}

# wait_http URL TRIES → 0 as soon as anything answers on URL (any HTTP status), one try a second.
wait_http() {
    local _
    for _ in $(seq 1 "$2"); do
        curl -s -o /dev/null -m2 "$1" 2>/dev/null && return 0
        sleep 1
    done
    return 1
}

# unit_active NAME → 0 if the systemd unit is already active.
unit_active() { systemctl is-active --quiet "$1" 2>/dev/null; }

# unit_installed NAME → 0 if the unit is already installed in /etc/systemd/system.
unit_installed() { [ -f "/etc/systemd/system/$1" ]; }

# model_for_role ROLE → prints the role's model from configs/model-protocol-map.yaml (single
# source of truth for models — see MODELS.md §3). Empty if the role doesn't exist or yq is
# missing: the caller decides (warn + skip); no default is invented here to avoid
# reintroducing hardcodes.
model_for_role() {
    command -v yq &>/dev/null || return 1
    local m
    m="$(yq -r ".roles.$1 // \"\"" "$REPO_ROOT/configs/model-protocol-map.yaml" 2>/dev/null)"
    [ -n "$m" ] && [ "$m" != "null" ] && echo "$m"
}

# install_unit PATH → installs/refreshes a systemd unit only if it's missing or changed
# (idempotent), rendered for this user and checkout. $1 = path to the .service in the repo.
install_unit() {
    local s=$1 name rendered; name="$(basename "$s")"
    rendered="$(mktemp)"
    render_placeholders "$s" > "$rendered"
    if [ -f "/etc/systemd/system/$name" ] && cmp -s "$rendered" "/etc/systemd/system/$name"; then
        ok "unit $name already installed (no changes)"
    else
        sudo install -m 644 "$rendered" "/etc/systemd/system/$name" && ok "unit $name installed" || warn "could not install $name"
    fi
    rm -f "$rendered"
}
