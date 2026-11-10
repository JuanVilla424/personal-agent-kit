#!/usr/bin/env python3
"""local/hooks/url-guard.py — Claude Code PreToolUse (WebFetch, WebSearch) hook.

Same checks as the OpenCode plugin (.opencode/plugins/url-guard.js): one source of truth,
bin/url_guard.py. A refused call exits 2 with the reason on stderr, and so does a guard that
cannot judge.
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "bin"))


def main() -> None:
    if os.environ.get("PAK_HOOK_RUNNING"):
        sys.exit(0)  # never recurse into the POST judge's own `claude -p` runs
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # not a tool call: nothing to judge
    try:
        from url_guard import check_tool

        tool = str(payload.get("tool_name", "")).lower()
        reason = check_tool(tool, payload.get("tool_input") or {})
    except Exception as e:  # pylint: disable=broad-except
        reason = f"BLOCKED (url-guard): the guard could not judge this call ({type(e).__name__})"
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)  # exit code 2 = block


if __name__ == "__main__":
    main()
