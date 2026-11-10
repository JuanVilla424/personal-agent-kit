#!/usr/bin/env python3
"""local/hooks/auto-guard.py — Claude Code PreToolUse (Bash) hook with the shared guard rules.

Same rules as the OpenCode plugin (.opencode/plugins/auto-guard.js): one source of truth,
BLOCK_RULES in bin/auto_guard.py. Stage 1 only (instant, no LLM):
  block     → exit 2: Claude Code does not run the command; the reason goes to stderr
  challenge → permissionDecision "ask": the native dialog asks the human. With auto-approval on
              (configs/auto-guard.json) it passes and is logged
  no match  → exit 0
  a failure → exit 2: a guard that cannot judge never lets a command through
What to do with each result: protocols/decision-protocol.md §"How to use the guard".
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "bin"))


def _snapshot_in_background(directory: str, reason: str) -> None:
    """A challenge may be approved: the session's repository is copied first, outside it
    (bin/snapshot.py), so what the approved command destroys comes back. The guard's answer
    never waits for the copy."""
    try:
        subprocess.Popen(  # pylint: disable=consider-using-with
            [
                sys.executable,
                str(REPO_ROOT / "bin" / "snapshot.py"),
                "take",
                directory,
                "--reason",
                reason,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        print(f"[auto-guard] no snapshot before this challenge: {e}", file=sys.stderr)


def _ask_output(reason: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        },
        ensure_ascii=False,
    )


def judge(command: str, cwd: str = "") -> tuple[int, str, str]:
    """(exit code, stdout, stderr) for one command run in `cwd`."""
    from auto_guard import (
        PROTOCOL,
        auto_approve_enabled,
        auto_approve_result,
        check_block_rules,
        guard_response,
        log_guard_event,
    )

    hit = check_block_rules(command)
    if not hit:
        return 0, "", ""
    if hit.action == "challenge" and auto_approve_enabled():
        auto_approve_result(hit, command, "claude")
        return 0, "", ""

    log_guard_event("claude", hit, command)
    resp = guard_response(hit)
    reason = f"auto-guard [{hit.rule_id}] {hit.description}. {resp['instruction']} ({PROTOCOL})"
    if hit.action == "challenge":
        if cwd:
            _snapshot_in_background(cwd, f"challenge:{hit.rule_id}")
        return 0, _ask_output(reason), ""
    return 2, "", f"BLOCKED {reason}"


def main() -> None:
    if os.environ.get("PAK_HOOK_RUNNING"):
        sys.exit(0)  # never recurse into the POST judge's own `claude -p` runs
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # not a tool call: nothing to judge
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command", "")
    try:
        code, out, err = judge(command, str(payload.get("cwd") or ""))
    except Exception as e:  # pylint: disable=broad-except
        code, out = 2, ""
        err = (
            f"BLOCKED auto-guard could not judge this command ({type(e).__name__}: {e}). "
            "Fix the guard, or ask the human: python3 bin/auto_guard.py --status"
        )
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    sys.exit(code)  # exit code 2 = block


if __name__ == "__main__":
    main()
