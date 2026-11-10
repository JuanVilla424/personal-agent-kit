#!/usr/bin/env bash
# post-plan-approval.sh — PostToolUse[ExitPlanMode] logger for personal-agent-kit.
#
# ExitPlanMode's tool_input carries no plan text (only a deprecated allowedPrompts
# field) — the model writes the plan to a file beforehand and this tool just reads
# it back on approval. So on every ExitPlanMode call we pick up the most-recently
# modified file in ~/.claude/plans/ and append it to TASKS.md. This substitutes for
# TodoWrite, which is not available in this project's cloud/background sessions (see
# memory project_session_tool_roster_no_todowrite). Non-blocking, best-effort: never
# fails the tool call either way.
#
# KNOWN LIMITATION (flagged by personal-agent-kit-5d's review, 2026-09-06):
# ~/.claude/plans/ is shared by every session under this $HOME. If another session is
# mid-draft on an unapproved plan with a newer mtime at the exact moment this fires,
# that draft — not the one just approved here — gets logged. Low blast radius (a
# mislabeled Historial entry, nothing executes or breaks). Not fixed: checked
# ~/.claude/plans/ for a session_id-correlated sidecar/index file — none exists, so
# there's no clean way to filter by session from inside this hook.
#
# Code/comments: English.
set -uo pipefail

cat >/dev/null  # drain stdin; ExitPlanMode's input has no usable plan content

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLANS_DIR="${HOME}/.claude/plans"
TASKS_FILE="${HERE}/../../TASKS.md"

LATEST_PLAN="$(find "${PLANS_DIR}" -maxdepth 1 -name '*.md' -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"
[ -z "$LATEST_PLAN" ] && exit 0

{
  printf '\n### %s -- %s\n\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$(basename "$LATEST_PLAN")"
  cat "$LATEST_PLAN"
  printf '\n'
} >> "$TASKS_FILE"

exit 0
