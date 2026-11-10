#!/usr/bin/env bash
# pre-write-guard.sh — PreToolUse[Write|Edit] guard for personal-agent-kit.
#
# Fast, deterministic checks on the INCOMING text, before it reaches disk.
# Reads the Claude Code hook payload (JSON) on stdin. Blocks with exit 2
# (reason on stderr, shown to the agent) on a hard-rule violation; exit 0
# otherwise. Best-effort: any internal problem falls through to "allow" so a
# hook bug can never wedge the session. Deeper, semantic review against
# AGENTS.md lives in the POST judge (post-write-judge.sh).
#
# Code/comments: English. Block reasons: English.
set -uo pipefail

# Re-entrancy guard: the POST judge spawns `claude -p`, whose own writes would
# re-trigger this hook. That child runs with PAK_HOOK_RUNNING=1.
[ -n "${PAK_HOOK_RUNNING:-}" ] && exit 0

command -v jq >/dev/null 2>&1 || exit 0 # no parser -> never block blindly
PAYLOAD="$(cat)"

TOOL="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // ""')"
FILE="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // ""')"
# Write carries the full .content; Edit carries .new_string. Either is the new text.
TEXT="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.content // .tool_input.new_string // ""')"

[ -n "$FILE" ] || exit 0

block() {
	printf 'BLOCKED (pre-write-guard): %s\n' "$1" >&2
	exit 2
}

# 1. Never author secret-bearing files (templates without secrets are allowed).
case "$FILE" in
*.env.template | *.env.example | *.env.sample) : ;;
*.env | *.env.* | *.pem | *.key | *.ppk | *.p12 | *.pfx | */secrets/* | */credentials)
	block "credential/secret files are not written: ${FILE} (the value goes in the encrypted .env)"
	;;
esac

# 1b. The guard's settings and its approvals: an agent that edits them approves itself.
case "$FILE" in
*/configs/auto-guard.json | configs/auto-guard.json | *auto_guard_approvals.json | *auto_guard_log.jsonl)
	block "the guard's settings and approvals are the human's: ${FILE}"
	;;
esac

# 2. No versioned filenames — versions belong in git, not in names.
if printf '%s' "$FILE" | grep -qE '\-v[0-9]+(\.[A-Za-z0-9]+)?$'; then
	block "versioned filename not allowed: ${FILE} (version with git, not -vN)"
fi

# 3. Hardcoded secrets in the incoming text.
if printf '%s' "$TEXT" | grep -qE '(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|aws_secret_access_key[[:space:]]*=[[:space:]]*[A-Za-z0-9/+]{30,})'; then
	block "hardcoded secret in the content (AWS key / private key / secret) — use .env"
fi

# 4. Syntax gate — only for Write, where we hold the complete file content.
#    Edit lacks the full file here; its syntax is checked on disk by the POST judge.
if [ "$TOOL" = "Write" ] && [ -n "$TEXT" ]; then
	tmp="$(mktemp)" || exit 0
	trap 'rm -f "$tmp"' EXIT
	printf '%s' "$TEXT" >"$tmp"
	case "$FILE" in
	*.sh)
		if command -v shellcheck >/dev/null 2>&1 && ! shellcheck -S error "$tmp" >/dev/null 2>&1; then
			block "shellcheck: syntax error in ${FILE}"
		fi
		;;
	*.py)
		if command -v python3 >/dev/null 2>&1 && ! python3 -m py_compile "$tmp" 2>/dev/null; then
			block "python: syntax error in ${FILE}"
		fi
		;;
	esac
fi

exit 0
