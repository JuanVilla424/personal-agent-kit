#!/usr/bin/env bash
# bin/update.sh — unattended self-update of an installed kit.
#
# Difference from install.sh: install sets up a new machine and asks questions; update.sh
# assumes an ALREADY-installed kit and brings it to the repo's version without asking —
# meant to run by hand or from a cron.
#
# What it updates, in order:
#   1. git: fetch + pull --ff-only of the defined branch (dev) — never switches branch,
#      never stashes, never forces; a dirty tree or another branch skips the step and says so
#   2. submodules (helpers/ai18n)
#   3. .venv: requirements.txt + requirements.dev.txt + the services' requirements
#   4. pre-commit hooks (install if missing; NEVER runs run --all-files — rewriting files
#      unattended is unacceptable)
#   5. ~/.config/opencode/opencode.json (bin/opencode/build-config.sh) — only if configured
#   6. Claude Code hooks (local/hooks/install-hooks.py) and TASKS.md if missing
#   7. services that run from this repo (agent-memory, opencode-server): try-restart ONLY
#      if step 1 moved HEAD (no code change, no restart — running it hourly is harmless)
#   8. verification: bin/brain-health.sh (informative — brain health is not an update failure)
#
# What it does NOT touch on purpose: systemd enablement (install.sh's job), the .env
# (secrets, human), crons, the user's branch, anything with --force.
#
# Usage: bash bin/update.sh     → 0 all fine · 1 some step soft-failed
set -o pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# shellcheck source=bin/_lib.sh
source "$REPO_ROOT/bin/_lib.sh"

BRANCH="dev"
LOCK_FILE="${TMPDIR:-/tmp}/pak-update.lock"
TOTAL_STEPS=8
FAILS=0
STEP=0
CODE_CHANGED=0

step() { STEP=$((STEP + 1)); sep; info "[${STEP}/${TOTAL_STEPS}] $*"; }
soft_fail() { warn "$*"; FAILS=$((FAILS + 1)); }
PY="${REPO_ROOT}/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"

# ── 0. single instance + preconditions ─────────────────────────────
step "Preflight"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    fail "another update.sh is running ($LOCK_FILE) — leaving everything untouched"
fi
[ "$(id -u)" -eq 0 ] && fail "run it as your own user, never as root (it breaks git/venv/permissions)"
command -v git >/dev/null 2>&1 || fail "git is not in PATH"
ok "preflight OK ($(date '+%F %T'), user $(id -un))"

# ── 1. Git: pull --ff-only of the defined branch ───────────────────
step "Git (branch $BRANCH, ff-only, no stash, no switch)"
OLD_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    soft_fail "dirty work tree — NOT pulling (never a stash). Commit or clean and re-run"
elif [ "$(git branch --show-current 2>/dev/null)" != "$BRANCH" ]; then
    soft_fail "not on $BRANCH — no branch switching; pull skipped"
elif ! git fetch origin "$BRANCH" 2>&1; then
    soft_fail "git fetch failed (network?) — pull skipped"
elif ! git pull --ff-only origin "$BRANCH" 2>&1; then
    soft_fail "pull --ff-only failed (diverged?) — resolve by hand; never force"
else
    NEW_HEAD="$(git rev-parse --short HEAD)"
    if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
        ok "already up to date ($NEW_HEAD)"
    else
        ok "updated $OLD_HEAD → $NEW_HEAD"
        CODE_CHANGED=1
        git log --oneline "${OLD_HEAD}..${NEW_HEAD}" 2>/dev/null | head -10 | sed 's/^/    /'
    fi
fi

# ── 2. Submodules ──────────────────────────────────────────────────
step "Submodules (helpers/ai18n)"
if [ -f .gitmodules ]; then
    # Unattended: sync to the SHA the repo records. NEVER --remote here: it moves the
    # submodule past the recorded pin and the tree turns dirty for the next run.
    git submodule update --init 2>&1 \
        && ok "submodules at the recorded pin" \
        || soft_fail "submodule update failed — check by hand"
else
    ok "no .gitmodules — nothing to do"
fi

# ── 3. .venv: dependencies ─────────────────────────────────────────
step "Python (.venv)"
if [ ! -d .venv ]; then
    soft_fail ".venv missing — run install.sh first; update.sh never installs from zero"
else
    .venv/bin/pip install --upgrade pip --quiet 2>/dev/null
    if .venv/bin/pip install -r requirements.txt -r requirements.dev.txt \
        -r local/scripts/memory_index/requirements.txt --quiet 2>&1 \
        && { [ ! -f local/scripts/notify/requirements.txt ] \
            || .venv/bin/pip install -r local/scripts/notify/requirements.txt --quiet 2>&1; }; then
        ok "requirements installed ($(.venv/bin/python3 --version 2>&1))"
    else
        soft_fail "pip install failed — requirements possibly broken in the repo"
    fi
fi

# ── 4. pre-commit hooks: install, NEVER run ────────────────────────
step "pre-commit hooks"
if [ ! -x .venv/bin/pre-commit ]; then
    soft_fail "pre-commit missing from .venv — requirements.dev.txt incomplete"
elif grep -q "pre-commit" .git/hooks/pre-commit 2>/dev/null \
    && grep -q "pre-commit" .git/hooks/pre-push 2>/dev/null; then
    ok "hooks already installed (pre-commit + pre-push)"
elif .venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push >/dev/null 2>&1; then
    ok "hooks installed (pre-commit + pre-push)"
else
    soft_fail "pre-commit install failed"
fi

# ── 5. OpenCode: rebuild the config ────────────────────────────────
step "OpenCode (build-config)"
if [ ! -f "$HOME/.config/opencode/opencode.json" ]; then
    ok "OpenCode client not configured on this box — skipped (bash bin/install-opencode.sh)"
elif bash "$REPO_ROOT/bin/opencode/build-config.sh" >/dev/null 2>&1; then
    ok "opencode.json rebuilt from the repo"
else
    soft_fail "build-config.sh failed"
fi

# ── 6. Claude Code hooks + TASKS.md ────────────────────────────────
step "Claude Code hooks and TASKS.md"
if "$PY" "$REPO_ROOT/local/hooks/install-hooks.py" >/dev/null 2>&1; then
    ok "hooks registered in ~/.claude/settings.json"
else
    soft_fail "install-hooks.py failed"
fi
if [ ! -f TASKS.md ]; then
    cp bin/tasks.template.md TASKS.md && ok "TASKS.md created from the template"
else
    ok "TASKS.md left as is"
fi

# ── 7. Services: restart only if code moved ────────────────────────
step "Services (restart only if HEAD moved)"
if [ "$CODE_CHANGED" = "1" ]; then
    for unit in agent-memory.service opencode-server.service; do
        if systemctl is-active --quiet "$unit" 2>/dev/null; then
            systemctl try-restart "$unit" 2>/dev/null \
                && ok "$unit restarted" \
                || soft_fail "$unit restart failed"
        else
            ok "$unit not running — nothing to restart"
        fi
    done
else
    ok "no code change — services untouched"
fi

# ── 8. Verification (informative) ──────────────────────────────────
step "Verification (brain health, informative)"
bash "$REPO_ROOT/bin/brain-health.sh" || true

echo ""
if [ "$FAILS" -eq 0 ]; then
    ok "update finished clean"
    exit 0
fi
warn "update finished with ${FAILS} soft failure(s)"
exit 1
