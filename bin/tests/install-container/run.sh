#!/usr/bin/env bash
# Installs the kit in a clean container, from a fresh clone, as an ordinary account and in a path
# that is not the default one, then checks that it really works.
#
# The clone comes from the working tree as it is. The tree is committed to a throwaway repository
# under temp/, so this test never adds a commit to the real history. The container holds its own
# Docker daemon, so nothing starts on the host.
#
# Usage: bash bin/tests/install-container/run.sh [--keep]
#   --keep leaves the container running to look inside it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
IMAGE="pak-install-test:local"
CONTAINER="pak-install-test"
ACCOUNT="someone"
CHECKOUT="/home/${ACCOUNT}/work/tools/pak"
RUN_DIR="$REPO_ROOT/temp/install-test/$(date +%Y%m%dT%H%M%S)"
HEALTH_URL="http://localhost:7800/memory/health"

mkdir -p "$RUN_DIR"
KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

cleanup() {
    [ "$KEEP" = "1" ] || docker rm -fv "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

in_container() { docker exec -i -u "$ACCOUNT" -w "$CHECKOUT" "$CONTAINER" bash -lc "$1"; }

failures=0
check() {
    local name=$1 command=$2
    if in_container "$command" >>"$RUN_DIR/checks.log" 2>&1; then
        echo "PASS $name" | tee -a "$RUN_DIR/summary.txt"
    else
        echo "FAIL $name" | tee -a "$RUN_DIR/summary.txt"
        failures=$((failures + 1))
    fi
}

echo "== Snapshot of the working tree"
SNAPSHOT="$RUN_DIR/snapshot.git"
git init -q --bare -b dev "$SNAPSHOT"
snapshot_git() { GIT_DIR="$SNAPSHOT" GIT_WORK_TREE="$REPO_ROOT" git "$@"; }
snapshot_git add -A 2>/dev/null # git warns about the submodules; they are added as gitlinks
snapshot_git -c user.name=install-test -c user.email=install-test@localhost \
    commit -q -m "install test snapshot"
echo "tracked files: $(snapshot_git ls-files | wc -l)" | tee -a "$RUN_DIR/summary.txt"

echo "== Clean machine"
docker build -q -t "$IMAGE" "$REPO_ROOT/bin/tests/install-container" >/dev/null
docker rm -fv "$CONTAINER" >/dev/null 2>&1 || true
# The anonymous volumes keep the inner Docker off the container's own overlay filesystem.
docker run -d --name "$CONTAINER" --privileged --tmpfs /run --tmpfs /run/lock \
    -v /var/lib/docker -v /var/lib/containerd -v "$SNAPSHOT:/src/pak.git:ro" "$IMAGE" >/dev/null
for _ in $(seq 1 30); do
    state="$(docker exec "$CONTAINER" systemctl is-system-running 2>/dev/null || true)"
    case "$state" in running | degraded) break ;; esac
    sleep 1
done
docker exec -u "$ACCOUNT" "$CONTAINER" bash -lc "
    git config --global --add safe.directory /src/pak.git
    mkdir -p \"\$(dirname $CHECKOUT)\" && git clone -q /src/pak.git $CHECKOUT"
docker exec "$CONTAINER" getent passwd | sort >"$RUN_DIR/accounts-before.txt"

echo "== Install: bin/install.sh --yes"
set +e
in_container "bash bin/install.sh --yes" >"$RUN_DIR/install.log" 2>&1
install_exit=$?
set -e
echo "install exit: $install_exit" | tee -a "$RUN_DIR/summary.txt"
[ "$install_exit" = "0" ] || failures=$((failures + 1))

echo "== Checks"
docker exec "$CONTAINER" getent passwd | sort >"$RUN_DIR/accounts-after.txt"
new_accounts="$(comm -13 "$RUN_DIR/accounts-before.txt" "$RUN_DIR/accounts-after.txt" | wc -l)"
if [ "$new_accounts" = "0" ]; then
    echo "PASS the install created no account" | tee -a "$RUN_DIR/summary.txt"
else
    echo "FAIL the install created $new_accounts account(s)" | tee -a "$RUN_DIR/summary.txt"
    failures=$((failures + 1))
fi

check "memory_service unit runs as the installing user" \
    "[ \"\$(systemctl show -p User --value agent-memory.service)\" = \"$ACCOUNT\" ] && systemctl is-active agent-memory.service"
check "the unit points at this checkout" \
    "grep -q 'WorkingDirectory=$CHECKOUT' /etc/systemd/system/agent-memory.service"
check "no placeholder reached the machine" \
    "! grep -q '<user>' /etc/systemd/system/agent-memory.service && ! grep -q '/home/<user>' .env"
check ".env is private" "[ \"\$(stat -c %a .env)\" = 600 ]"
check "qdrant answers" "curl -sf -m5 http://localhost:7733/collections"
check "memory_service answers" "curl -sf -m5 $HEALTH_URL | grep -q '\"status\":\"ok\"'"
check "memory_service refuses a call without a token" \
    "[ \"\$(curl -s -m5 -o /dev/null -w '%{http_code}' 'http://localhost:7800/memory/search?q=x')\" = 401 ]"
check "a memory can be written and found again" "
    source <(grep -E '^MEMORY_SERVICE_TOKEN=' .env)
    curl -sf -m30 -X POST http://localhost:7800/memory/add \
        -H \"x-memory-token: \$MEMORY_SERVICE_TOKEN\" -H 'content-type: application/json' \
        -d '{\"text\": \"the install test wrote this sentence about purple elephants\"}' >/dev/null
    curl -sf -m30 -G http://localhost:7800/memory/search --data-urlencode 'q=purple elephants' \
        -H \"x-memory-token: \$MEMORY_SERVICE_TOKEN\" | grep -q 'purple elephants'"
check "the guards are registered" \
    "grep -q 'rm-guard.sh' ~/.claude/settings.json && grep -q 'pre-write-guard.sh' ~/.claude/settings.json \
        && grep -q '$CHECKOUT/local/hooks/auto-guard.py' ~/.claude/settings.json \
        && grep -q '$CHECKOUT/local/hooks/url-guard.py' ~/.claude/settings.json"
check "the guard runs with its human-approval default" \
    "python3 bin/auto_guard.py --status | jq -e '.stage1.state == \"on\" and .stage2.state == \"off\" and .auto_approve == false'"
check "the guard blocks in claude code (real engine, scripted model)" \
    "PATH=~/.npm-global/bin:\$PATH bash bin/tests/guard-e2e/run.sh claude"
check "the worker runs a task in its container: guard inside, refused egress, cost cap, host mode (real engine)" \
    "PATH=~/.npm-global/bin:\$PATH bash bin/tests/guard-e2e/worker.sh"
check "the worker image is built at its pinned version" \
    "docker image inspect \"\$(.venv/bin/python -c 'import sys; sys.path.insert(0, \"bin\"); import pak_worker; print(pak_worker.image_tag())')\" >/dev/null"
check "pak is on the PATH and doctor finds every core layer" "~/.local/bin/pak doctor"
check "doctor reports the snapshots and the worker" \
    "~/.local/bin/pak doctor > /tmp/doctor.txt; grep -q ' Snapshots ' /tmp/doctor.txt && grep -q ' Worker ' /tmp/doctor.txt"
check "the nightly memory consolidation is scheduled and runs" \
    "systemctl is-active --quiet agent-memory-consolidate.timer && ~/.local/bin/pak memory consolidate"
check "the session hook prints the language policy" \
    "bash .claude/hooks/session-start.sh | grep -q 'the languages of this repository'"
check "the session start took a snapshot of the repository" \
    "for _ in \$(seq 1 30); do ~/.local/bin/pak snapshot list | grep -q session-start && exit 0; sleep 1; done; exit 1"
check "claude code is installed" "~/.npm-global/bin/claude --version"
check "claude code defaults are set" "jq -e '.model == \"opusplan\"' ~/.claude/settings.json"
check "the plugins are installed" "~/.npm-global/bin/claude plugin list | grep -q hookify"
check "bmad stays inactive by default" "[ ! -e .claude/commands/bmad ]"
check "submodules stayed at their pins" "! git submodule status | grep -q '^+'"

echo "== Re-run with options: --with-bmad --language es"
set +e
in_container "bash bin/install.sh --yes --with-bmad --language es" >"$RUN_DIR/reinstall.log" 2>&1
reinstall_exit=$?
set -e
echo "re-install exit: $reinstall_exit" | tee -a "$RUN_DIR/summary.txt"
[ "$reinstall_exit" = "0" ] || failures=$((failures + 1))
check "bmad activates on request" "[ -d .claude/commands/bmad/core ] && [ -d .claude/agents/bmad-review ]"
check "the conversation language changed" "grep -q '^respond: es' ai18n.yaml && grep -q '^document: en' ai18n.yaml"
check "the memory survived the re-install" "
    source <(grep -E '^MEMORY_SERVICE_TOKEN=' .env)
    curl -sf -m30 -G http://localhost:7800/memory/search --data-urlencode 'q=purple elephants' \
        -H \"x-memory-token: \$MEMORY_SERVICE_TOKEN\" | grep -q 'purple elephants'"

echo "== Re-run with OpenCode: --with-opencode"
set +e
in_container "bash bin/install.sh --yes --with-opencode" >"$RUN_DIR/opencode.log" 2>&1
opencode_exit=$?
set -e
echo "opencode install exit: $opencode_exit" | tee -a "$RUN_DIR/summary.txt"
[ "$opencode_exit" = "0" ] || failures=$((failures + 1))
check "opencode is installed" "~/.npm-global/bin/opencode --version"
check "opencode gets the whole team with bmad active" \
    "[ \"\$(jq '.agent | keys | length' ~/.config/opencode/opencode.json)\" = 14 ]"
check "opencode gets the language policy" \
    "grep -q 'respond: es' ~/.config/opencode/ai18n-policy.md"
check "opencode-server runs as the installing user" \
    "[ \"\$(systemctl show -p User --value opencode-server.service)\" = \"$ACCOUNT\" ] && systemctl is-active opencode-server.service"
check "opencode is the version the guards were proven against" \
    "~/.npm-global/bin/opencode --version | grep -q \"\$(cat configs/opencode.version)\""
check "opencode loads the guards in every project" \
    "[ \"\$(jq '.plugin | length' ~/.config/opencode/opencode.json)\" = \"\$(find .opencode/plugins -maxdepth 1 -name '*.js' | wc -l)\" ]"
# The OpenCode engine check starts OpenCode with the scripted model. Where a host guard forbids any
# model outside its own allowlist, PAK_SKIP_OPENCODE_ENGINE=1 skips it, and the summary says so.
if [ "${PAK_SKIP_OPENCODE_ENGINE:-0}" = "1" ]; then
    echo "SKIP the guard blocks in opencode (real engine): PAK_SKIP_OPENCODE_ENGINE=1" | tee -a "$RUN_DIR/summary.txt"
else
    check "the guard blocks in opencode (real engine, scripted model)" \
        "PATH=~/.npm-global/bin:\$PATH bash bin/tests/guard-e2e/run.sh opencode"
fi

echo "== Re-run with the Slack bot: --with-slack"
set +e
in_container "bash bin/install.sh --yes --with-slack" >"$RUN_DIR/slack.log" 2>&1
slack_exit=$?
set -e
echo "slack install exit: $slack_exit" | tee -a "$RUN_DIR/summary.txt"
[ "$slack_exit" = "0" ] || failures=$((failures + 1))
check "the slack units are rendered for the installing user and this checkout" \
    "for u in /etc/systemd/system/agent-bot*.service; do grep -q '^User=$ACCOUNT' \$u \
        && grep -q 'WorkingDirectory=$CHECKOUT/local/scripts/notify' \$u && ! grep -qE '<user>|<claude-dir>|\\.nvm/versions' \$u \
        || exit 1; done"
check "the slack bot is closed and not started without its tokens" \
    "[ \"\$(stat -c %a local/scripts/notify/.env)\" = 600 ] && grep -q '^SLACK_ALLOWED_USERS=$' local/scripts/notify/.env \
        && ! systemctl is-active agent-bot.service"

echo "failures: $failures" | tee -a "$RUN_DIR/summary.txt"
echo "evidence: $RUN_DIR"
[ "$failures" = "0" ]
