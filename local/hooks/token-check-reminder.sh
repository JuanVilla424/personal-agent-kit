#!/usr/bin/env bash
# token-check-reminder.sh — UserPromptSubmit reminder for personal-agent-kit.
#
# Fires on every user prompt. Non-blocking: emits an additionalContext JSON (exit 0) that
# Claude sees as a system reminder, same convention as pre-compact-reminder.sh. This hook
# cannot see real token usage (no such API exists for hooks) — it only points the model at
# the thresholds in protocols/token-management.md so it self-reports from the context-window
# information it already receives natively. Replaces the old .claude/hooks/check-tokens.sh,
# which bundled this reminder with a dead auto-continue mechanism (superseded by party-mode)
# and never measured real usage either — see protocols/token-management.md for the full
# Green/Yellow/Red/Critical policy this reminder summarizes.
#
# Code/comments: English. Reminder text: English.
set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0

cat >/dev/null # drain stdin, no input needed from this event

jq -n --arg c "TOKEN CHECK (protocols/token-management.md): if context usage is at 120-150k/200k (60-75%), report it and suggest /compact once the current task is done; if it's at 150-170k (75-85%), suggest it BEFORE continuing; if it's above 170k (85%+), wait for explicit user confirmation before large operations." \
	'{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $c}}'
exit 0
