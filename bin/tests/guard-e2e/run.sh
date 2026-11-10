#!/usr/bin/env bash
# bin/tests/guard-e2e/run.sh — the guards inside the REAL engines, with no key and no spend.
#
# A unit test proves a plugin's code; it does not prove the engine loads it: OpenCode 2 ignored
# every plugin of this kit until they gained a V2 definition, and nothing failed. This runs Claude
# Code and OpenCode for real against a scripted model (fake_model.py) that asks for the tool calls
# of steps.json, and checks what each engine answered:
#   - rm -rf of a path that does not exist        → blocked (auto-guard / rm-guard)
#   - writing <project>/.env                       → blocked (pre-write-guard)
#   - git push --force                             → blocked (auto-guard)
#   - fetching http://127.0.0.1:9/                 → blocked (url-guard)
#   - echo e2e-ok                                  → runs
# and that nothing was created, and that the session started with the memory brief (the scripted
# model's server hands one out as memory_service would). Each step is harmless even unguarded, and everything runs in a
# throwaway HOME and project under temp/guard-e2e/<timestamp>/: the real ~/.claude and
# ~/.config/opencode are never touched.
#
# Usage: bash bin/tests/guard-e2e/run.sh [claude|opencode|all]
# Exit 0 = every check passed · 1 = a check failed · 2 = an engine could not run.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
ENGINES="${1:-all}"
STEP_COUNT=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$HERE/steps.json")
RUN_TIMEOUT=300
START_TIMEOUT=120  # an OpenCode run of these 5 steps takes about 15 s

WORK="$REPO_ROOT/temp/guard-e2e/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$WORK"
SERVER_PID=""
trap '[ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null' EXIT

FAILED=0
check() { # check <0|1> <label>
    if [ "$1" = "1" ]; then echo "  ✔ $2"; else echo "  ✘ $2"; FAILED=1; fi
}

start_model() { # start_model <dir>: a fresh fake model for one engine
    : > "$1/results.jsonl"
    # not empty: the kit's session start hook prunes empty folders under temp/
    echo "# e2e project" > "$1/project/README.md"
    python3 "$HERE/fake_model.py" --script "$HERE/steps.json" --log "$1/results.jsonl" \
        --port-file "$1/port" --project "$1/project" --seen "$1/seen.txt" &
    SERVER_PID=$!
    for _ in $(seq 1 50); do [ -s "$1/port" ] && return 0; sleep 0.1; done
    echo "the fake model did not start" >&2
    return 1
}

stop_model() {
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
    SERVER_PID=""
}

# The answer to step N, as the engine sent it back to the model.
result_of() { python3 -c '
import json, sys
for line in open(sys.argv[1]):
    entry = json.loads(line)
    if entry["step"] == int(sys.argv[2]):
        print(entry["text"])
' "$1/results.jsonl" "$2"; }

verify() { # verify <dir> <engine>
    local dir="$1" engine="$2" n text expect
    echo "$engine:"
    check "$([ "$(wc -l < "$dir/results.jsonl")" -eq "$STEP_COUNT" ] && echo 1 || echo 0)" \
        "the engine answered all $STEP_COUNT steps"
    for n in $(seq 0 $((STEP_COUNT - 1))); do
        text="$(result_of "$dir" "$n")"
        expect=$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1]))[int(sys.argv[2])]; print(s["expect"], s["tool"], json.dumps(s["input"])[:60])' "$HERE/steps.json" "$n")
        if [ "${expect%% *}" = "blocked" ]; then
            grep -q "BLOCKED" <<< "$text" && c=1 || c=0
        else
            grep -q "e2e-ok" <<< "$text" && c=1 || c=0
        fi
        check "$c" "step $n (${expect#* }): ${expect%% *}"
    done
    check "$([ ! -e "$dir/project/.env" ] && [ ! -e "$dir/project/.venv" ] && echo 1 || echo 0)" \
        "no side effects in the project"
    check "$([ -s "$dir/seen.txt" ] && echo 1 || echo 0)" "the session started with the memory brief"
}

run_claude() {
    local dir="$WORK/claude"
    mkdir -p "$dir/home" "$dir/project"
    command -v claude >/dev/null 2>&1 || { echo "claude is not installed" >&2; return 2; }
    HOME="$dir/home" python3 "$REPO_ROOT/local/hooks/install-hooks.py" > "$dir/install-hooks.log" || return 2
    start_model "$dir" || return 2
    (
        cd "$dir/project" || exit 2
        HOME="$dir/home" ANTHROPIC_BASE_URL="http://127.0.0.1:$(cat "$dir/port")" \
            MEMORY_SERVICE_URL="http://127.0.0.1:$(cat "$dir/port")" \
            ANTHROPIC_API_KEY="e2e-not-a-key" CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
            DISABLE_AUTOUPDATER=1 \
            timeout "$RUN_TIMEOUT" claude -p "go" --permission-mode bypassPermissions \
            --output-format json > "$dir/stdout" 2> "$dir/stderr"
    )
    echo "claude exit code: $?" > "$dir/exit"
    stop_model
    verify "$dir" "Claude Code"
}

run_opencode() {
    local dir="$WORK/opencode" xdg rc
    mkdir -p "$dir/home" "$dir/project"
    command -v opencode >/dev/null 2>&1 || { echo "opencode is not installed" >&2; return 2; }
    xdg=(HOME="$dir/home" XDG_CONFIG_HOME="$dir/home/.config" XDG_DATA_HOME="$dir/home/.local/share"
        XDG_CACHE_HOME="$dir/home/.cache" XDG_STATE_HOME="$dir/home/.local/state")
    start_model "$dir" || return 2
    xdg+=(MEMORY_SERVICE_URL="http://127.0.0.1:$(cat "$dir/port")")
    env "${xdg[@]}" bash "$REPO_ROOT/bin/opencode/build-config.sh" > "$dir/build-config.log" 2>&1 || return 2
    local config="$dir/home/.config/opencode/opencode.json"
    jq --arg url "http://127.0.0.1:$(cat "$dir/port")/v1" '.provider.fake = {
        "name": "Fake", "npm": "@ai-sdk/openai-compatible", "models": {"fake": {"name": "fake"}},
        "options": {"apiKey": "e2e-not-a-key", "baseURL": $url}}' "$config" > "$config.n" \
        && mv "$config.n" "$config" || return 2
    (
        cd "$dir/project" || exit 2
        env "${xdg[@]}" timeout "$START_TIMEOUT" opencode run --standalone --auto --print-logs \
            --model fake/fake "go" > "$dir/stdout" 2> "$dir/stderr"
    )
    rc=$?
    grep -q 'msg="loading plugin"' "$dir/stderr" || echo "  (OpenCode stopped before loading any plugin)"
    echo "opencode exit code: $rc" > "$dir/exit"
    stop_model
    local loaded failed expected
    expected=$(find "$REPO_ROOT/.opencode/plugins" -maxdepth 1 -name '*.js' | wc -l)
    loaded=$(grep -c 'msg="loading plugin"' "$dir/stderr" || true)
    failed=$(grep -c "failed to load plugin" "$dir/stderr" || true)
    verify "$dir" "OpenCode"
    check "$([ "$loaded" -ge "$expected" ] && [ "$failed" = "0" ] && echo 1 || echo 0)" \
        "plugins loaded outside the kit's folder: $loaded of $expected, $failed failed"
}

case "$ENGINES" in
    claude) run_claude || exit 2 ;;
    opencode) run_opencode || exit 2 ;;
    all) { run_claude || exit 2; } && { run_opencode || exit 2; } ;;
    *) echo "usage: run.sh [claude|opencode|all]" >&2; exit 2 ;;
esac
echo "evidence: $WORK"
exit "$FAILED"
