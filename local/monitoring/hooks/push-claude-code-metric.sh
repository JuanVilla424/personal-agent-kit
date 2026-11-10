#!/usr/bin/env bash
# Thin wrapper: settings.json registers this path; the logic lives in the
# python script (transcript parsing + per-agent attribution). stdin (hook
# payload JSON) passes through. Must NEVER fail the session.
# Prefer the repo .venv; fall back to system python3 (script is stdlib-only).
PY="$(dirname "$0")/../../../.venv/bin/python3"
[ -x "$PY" ] || PY=python3
exec "$PY" "$(dirname "$0")/push-claude-code-metric.py" 2>/dev/null || exit 0
