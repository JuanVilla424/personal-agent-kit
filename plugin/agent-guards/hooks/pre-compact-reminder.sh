#!/usr/bin/env bash
# pre-compact-reminder.sh — PreCompact reminder for personal-agent-kit.
#
# Fires right before a compaction (manual /compact or auto). Non-blocking: emits an
# additionalContext JSON (exit 0) that Claude sees as a system reminder, same convention
# as post-write-judge.sh. The actual rule (only temp/current-context.md, max 100 lines)
# lives in .claude/skills/pre-compact/SKILL.md — this hook just triggers it, never
# duplicates its content.
#
# Code/comments: English. Reminder text: English.
set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0

cat >/dev/null # drain stdin, no input needed from this event

jq -n --arg c "PRE-COMPACT: before compacting, invoke the pre-compact skill (updates ONLY temp/current-context.md, max 100 lines)." \
	'{hookSpecificOutput: {hookEventName: "PreCompact", additionalContext: $c}}'
exit 0
