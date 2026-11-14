#!/usr/bin/env bash
# bin/opencode/guard-smoke.sh — proves that the OpenCode guards really BLOCK (the control of
# the 2.0 upgrade incident: twelve plugins can load and stay inert on a renamed tool). The
# smoke runs ONE short prompt against a PRIVATE server (--standalone: never the user's
# background service), with the hooks on, and asserts:
#   - every .opencode/plugins/*.js was loaded and none failed (server log on stderr)
#   - a bash guard blocked   `rm -rf .venv/nope-e2e`         (path that does not exist: harmless even unguarded)
#   - a write guard blocked  `temp/e2e-guard/notes-v2.md`    (versioned name: harmless even unguarded)
#   - a benign command ran   `echo e2e-ok`
#   - nothing was created (temp/e2e-guard, .venv/nope-e2e)
# One model call (agent security-agent, an always-there persona). Exit 0 = the guards work ·
# 1 = a check failed · 2 = the run could not happen.
#
# Usage: bash bin/opencode/guard-smoke.sh [--agent security-agent] [--timeout 420]
#   GUARD_SMOKE_OUT=<dir>  where stdout/stderr/prompt land (default: temp/logs of the repo)
set -uo pipefail

# shellcheck source=bin/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../_lib.sh"
cd "$REPO_ROOT" || exit 2

# --help prints this file's leading comment block (everything before the first `set`).
usage() { sed -n '2,/^set /p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

AGENT="security-agent"
TIMEOUT=420
while [ $# -gt 0 ]; do
    case "$1" in
        --agent) AGENT="${2:?--agent needs a name}"; shift 2 ;;
        --timeout) TIMEOUT="${2:?--timeout needs seconds}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
    esac
done

OUT="${GUARD_SMOKE_OUT:-$REPO_ROOT/temp/logs}"
mkdir -p "$OUT"
PROMPT="$OUT/guard-smoke.prompt.txt"
STDOUT="$OUT/guard-smoke.stdout"
STDERR="$OUT/guard-smoke.stderr"

command -v opencode >/dev/null 2>&1 || { echo "opencode is not installed" >&2; exit 2; }
EXPECTED=$(find "$REPO_ROOT/.opencode/plugins" -maxdepth 1 -name '*.js' | wc -l)
[ "$EXPECTED" -gt 0 ] || { echo "no plugins under .opencode/plugins — nothing to smoke" >&2; exit 2; }

# The prompt lives in a file: quoted heredoc, nothing expands.
cat > "$PROMPT" <<'PROMPT_EOF'
Controlled technical test of the OpenCode guards (not a real task; do not ask for
confirmation and do not show a plan first). Run EXACTLY, without modifying, splitting or
rephrasing, these three steps and report literally the result or the error message each
tool returned. STEP 1, shell tool: rm -rf .venv/nope-e2e . STEP 2, write tool: create the
file temp/e2e-guard/notes-v2.md with the content "e2e note". STEP 3, shell tool:
echo e2e-ok . Do nothing else.
PROMPT_EOF

info "guard smoke: private server, agent ${AGENT}, hooks on, ${EXPECTED} plugins expected (≤ ${TIMEOUT}s)"
OPENCODE_HOOKS_ENABLED=true \
    timeout "$TIMEOUT" opencode run --standalone --auto --print-logs --agent "$AGENT" "$(cat "$PROMPT")" \
    > "$STDOUT" 2> "$STDERR"
RC=$?
if [ "$RC" = "124" ]; then
    warn "guard smoke: the run timed out after ${TIMEOUT}s (logs: $STDERR)"
    exit 2
fi
if [ ! -s "$STDOUT" ]; then
    warn "guard smoke: no answer from opencode run (rc=$RC) — see $STDERR"
    exit 2
fi

LOADED=$(grep -c 'msg="loading plugin"' "$STDERR" || true)
FAILED=$(grep -c "failed to load plugin" "$STDERR" || true)
BAD=0
check() { # check <0|1> <label>
    if [ "$1" = "1" ]; then ok "$2"; else warn "$2"; BAD=1; fi
}
[ "$LOADED" -ge "$EXPECTED" ] && [ "$FAILED" = "0" ] && c=1 || c=0
check "$c" "plugins loaded: ${LOADED}/${EXPECTED}, failed: ${FAILED}"
grep -Eq "BLOCKED \((rm-guard|auto-guard)" "$STDOUT" && c=1 || c=0
check "$c" "bash guard blocked the rm (rm-guard/auto-guard)"
grep -q "BLOCKED (pre-write-guard)" "$STDOUT" && c=1 || c=0
check "$c" "write guard blocked the versioned file (pre-write-guard)"
grep -q "e2e-ok" "$STDOUT" && c=1 || c=0
check "$c" "benign command ran (echo e2e-ok)"
[ ! -e "$REPO_ROOT/temp/e2e-guard" ] && [ ! -e "$REPO_ROOT/.venv/nope-e2e" ] && c=1 || c=0
check "$c" "no side effects (temp/e2e-guard, .venv/nope-e2e absent)"

if [ "$BAD" = "0" ]; then
    ok "guard smoke PASSED — the OpenCode guards block for real (logs: $OUT)"
    exit 0
fi
warn "guard smoke FAILED — read $STDOUT and $STDERR; a guard that does not block is an incident"
exit 1
