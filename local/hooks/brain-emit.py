#!/usr/bin/env python3
"""local/hooks/brain-emit.py — one pulse on the brain page for every move of a session.

Registered by install-hooks.py for PreToolUse, UserPromptSubmit, PreCompact, SessionStart and
SessionEnd. It reads the hook's JSON on stdin and appends one event to the bus the brain page
streams (local/scripts/memory_index/brain_bus.py); local/brain-ui/cortex-map.json says which
regions a tool lights.

It only observes: it prints nothing, always exits 0 and never changes what the session does.
A tool pulse says the tool and a masked line of what it was given; what the human typed never
reaches the bus.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "local" / "scripts" / "memory_index"))

import brain_bus  # noqa: E402

CORTEX_MAP = REPO_ROOT / "local" / "brain-ui" / "cortex-map.json"
# What a tool pulse shows of the tool's input: the one field that says what it is about.
SUBJECT = {
    "Bash": "command",
    "Write": "file_path",
    "Edit": "file_path",
    "NotebookEdit": "notebook_path",
    "Read": "file_path",
    "Grep": "pattern",
    "Glob": "pattern",
    "WebFetch": "url",
    "WebSearch": "query",
    "Task": "description",
    "Agent": "description",
    "Skill": "skill",
}
# The session events that are a pulse, and what the page's log says about each.
MOMENTS = {
    "UserPromptSubmit": ("human", "the human spoke", "human_prompt"),
    "PreCompact": ("compact", "context compaction", "compact"),
    "SessionStart": ("session", "session started", "session_start"),
    "SessionEnd": ("session", "session ended", "session_end"),
}


def cortex_map() -> dict:
    try:
        return json.loads(CORTEX_MAP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tool_key(name: str) -> str:
    """The name a tool has in the map: an MCP tool loses its prefix, mcp__memory__memory_add
    becomes memory_memory_add."""
    return name.removeprefix("mcp__").replace("__", "_")


def pulse_of(hook: dict, regions: dict) -> dict | None:
    """The event a hook call stands for; None when it is not one the page draws."""
    defaults = regions.get("defaults") or {}
    moment = MOMENTS.get(hook.get("hook_event_name"))
    if moment:
        kind, text, where = moment
        return {"kind": kind, "text": text, "path": defaults.get(where) or []}
    if hook.get("hook_event_name") != "PreToolUse" or not isinstance(hook.get("tool_name"), str):
        return None
    tool, given = hook["tool_name"], hook.get("tool_input")
    key = tool_key(tool)
    subject = given.get(SUBJECT.get(tool, "")) if isinstance(given, dict) else None
    return {
        "kind": "tool",
        "text": (
            f"{key} · {brain_bus.mask(subject)}" if isinstance(subject, str) and subject else key
        ),
        "path": (regions.get("pre") or {}).get(key) or defaults.get("pre") or [],
        "side": (regions.get("tool_side") or {}).get(key, ""),
    }


def main() -> int:
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    pulse = pulse_of(hook, cortex_map()) if isinstance(hook, dict) else None
    if pulse:
        brain_bus.emit(pulse["kind"], pulse["text"], pulse["path"], side=pulse.get("side", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
