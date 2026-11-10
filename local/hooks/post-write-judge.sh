#!/usr/bin/env bash
# post-write-judge.sh — PostToolUse[Write|Edit] reviewer for personal-agent-kit.
#
# Runs AFTER a Write/Edit has landed on disk. Two best-effort stages:
#   1. Syntax check on the real file (covers both Write AND Edit).
#   2. Semantic judge against AGENTS.md (delegated to judge_against_agents.py).
# PostToolUse cannot undo the write; feedback is NON-BLOCKING — we emit an
# additionalContext JSON (exit 0) that Claude sees as a system reminder and may
# act on next turn. Never blocks, never wedges the session.
#
# Code/comments: English. Reported reasons: English.
set -uo pipefail

# Don't recurse into the judge's own `claude -p` writes.
[ -n "${PAK_HOOK_RUNNING:-}" ] && exit 0
command -v jq >/dev/null 2>&1 || exit 0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD="$(cat)"
FILE="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // ""')"
[ -n "$FILE" ] && [ -f "$FILE" ] || exit 0

# ── 1. Syntax on disk (Write + Edit) ──────────────────────────────
syntax_error=""
case "$FILE" in
*.sh) command -v shellcheck >/dev/null 2>&1 && ! shellcheck -S error "$FILE" >/dev/null 2>&1 &&
	syntax_error="shellcheck: syntax error" ;;
*.py) command -v python3 >/dev/null 2>&1 && ! python3 -m py_compile "$FILE" 2>/dev/null &&
	syntax_error="python: syntax error" ;;
*.yml | *.yaml) command -v yamllint >/dev/null 2>&1 && ! yamllint -d relaxed "$FILE" >/dev/null 2>&1 &&
	syntax_error="yaml: parse error" ;;
esac
if [ -n "$syntax_error" ]; then
	# Non-blocking: surface the syntax problem as context (the write already happened).
	jq -n --arg c "POST-WRITE: ${syntax_error} in ${FILE}" \
		'{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $c}}'
	exit 0
fi

# ── 2. Semantic judge vs AGENTS.md (best-effort; may be skipped) ───
PY="$HERE/../../.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || exit 0

# The judge prints a non-blocking additionalContext JSON when it has feedback; never blocks.
PAK_HOOK_RUNNING=1 "$PY" "$HERE/judge_against_agents.py" "$FILE" || true
exit 0
