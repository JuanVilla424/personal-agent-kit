#!/usr/bin/env bash
# rm-guard.sh — PreToolUse[Bash] guard for personal-agent-kit.
#
# Blocks recursive+forced `rm` targeting generated/sensitive directories (.git, .venv, venv,
# node_modules, __pycache__, dist, build) when one appears as a whole path segment of the
# command — never blocks reads, execution, or installs. Replaces
# .claude/scripts/validate-bash.sh, which never registered and had real false positives: a
# bare substring match on "venv" would have blocked this repo's own mandatory
# `.venv/bin/python3 ...` invocation pattern, and ".env" matched ".env.template" too. Reads
# the Claude Code hook payload (JSON) on stdin, same convention as pre-write-guard.sh.
#
# Code/comments: English. Block reason: English.
set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0 # no parser -> never block blindly
PAYLOAD="$(cat)"
COMMAND="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // empty')"
[ -n "$COMMAND" ] || exit 0

# Only commands combining recursive + force rm flags (either order, combined or separate).
if printf '%s' "$COMMAND" | grep -qE '\brm[[:space:]]+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\b|-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\b|-r\b[[:space:]]+-f\b|-f\b[[:space:]]+-r\b)'; then
	# ...and the target is one of these directories as a whole path segment, never a substring
	# (so ".venv/bin/python3", "cat .env.template", "npm install" never match).
	if printf '%s' "$COMMAND" | grep -qE '(^|[[:space:]/])(\.git|\.venv|venv|node_modules|__pycache__|dist|build)([[:space:]/]|$)'; then
		echo "BLOCKED (rm-guard): recursive/forced rm on a generated/sensitive directory — check the path" >&2
		exit 2
	fi
fi

exit 0
