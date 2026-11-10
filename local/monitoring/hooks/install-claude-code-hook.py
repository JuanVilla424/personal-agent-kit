#!/usr/bin/env python3
"""Idempotently register the Claude Code metrics hook in ~/.claude/settings.json.

Adds a Stop hook that pushes per-turn session metrics to the local
Pushgateway (see push-claude-code-metric.sh). Safe to run multiple times;
never touches other settings.
"""

import json
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
HOOK_COMMAND = str(Path(__file__).resolve().parent / "push-claude-code-metric.sh")
HOOK_ENTRY = {"type": "command", "command": HOOK_COMMAND, "timeout": 5000}


def main() -> int:
    settings = {}
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text())
        except json.JSONDecodeError as e:
            print(f"ERROR: {SETTINGS_PATH} is not valid JSON ({e}) — not touching it")
            return 1

    hooks = settings.setdefault("hooks", {})
    stop_groups = hooks.setdefault("Stop", [])

    for group in stop_groups:
        for hook in group.get("hooks", []):
            if hook.get("command") == HOOK_COMMAND:
                print(f"OK: metrics hook already registered in {SETTINGS_PATH}")
                return 0

    stop_groups.append({"hooks": [HOOK_ENTRY]})
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"OK: metrics hook registered in {SETTINGS_PATH}")
    print("    Takes effect on new Claude Code sessions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
