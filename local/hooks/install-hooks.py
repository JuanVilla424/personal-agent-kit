#!/usr/bin/env python3
"""Idempotently register personal-agent-kit's hooks in ~/.claude/settings.json.

Registers:
  - PreToolUse      (Write|Edit)    -> pre-write-guard.sh
  - PreToolUse      (Bash)          -> rm-guard.sh, auto-guard.py (the shared guard rules)
  - PreToolUse      (WebFetch|WebSearch) -> url-guard.py
  - PostToolUse     (Write|Edit)    -> post-write-judge.sh
  - PostToolUse     (ExitPlanMode)  -> post-plan-approval.sh
  - PreCompact      (manual|auto)   -> pre-compact-reminder.sh
  - UserPromptSubmit (any)          -> token-check-reminder.sh
  - SessionStart    (any)           -> session-start.sh (temp/ cleanup + orientation.txt injection)
  - Stop            (any)           -> tts_hook.py (speaks the response out loud — docs/stories/tts-hook-persona.md)
  - Notification    (any)           -> tts_hook.py (speaks permission requests out loud)
  - PreToolUse, UserPromptSubmit, PreCompact, SessionStart, SessionEnd (any) -> brain-emit.py
    (one pulse on the brain page for each; it only observes)

Removes superseded global hooks (e.g. ~/.claude/hooks/pre-write-validation.sh, now
replaced by pre-write-guard.sh; ~/.claude/hooks/check-tokens.sh, now replaced by
token-check-reminder.sh). Everything else is preserved verbatim: the Bash safety
check, the Stop metrics hook, and the whole permissions block. Safe to re-run
(writes only when something actually changes).
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
HOOKS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOOKS_DIR.parent.parent
MATCHER = "Write|Edit"

# Hooks we own: (event, matcher, absolute command, timeout_ms).
MANAGED = [
    ("PreToolUse", MATCHER, str(HOOKS_DIR / "pre-write-guard.sh"), 10000),
    ("PreToolUse", "Bash", str(HOOKS_DIR / "rm-guard.sh"), 5000),
    ("PreToolUse", "Bash", str(HOOKS_DIR / "auto-guard.py"), 10000),
    ("PreToolUse", "WebFetch|WebSearch", str(HOOKS_DIR / "url-guard.py"), 10000),
    ("PostToolUse", MATCHER, str(HOOKS_DIR / "post-write-judge.sh"), 60000),
    ("PostToolUse", "ExitPlanMode", str(HOOKS_DIR / "post-plan-approval.sh"), 5000),
    ("PreCompact", "manual|auto", str(HOOKS_DIR / "pre-compact-reminder.sh"), 5000),
    ("UserPromptSubmit", "", str(HOOKS_DIR / "token-check-reminder.sh"), 5000),
    ("SessionStart", "", str(HOOKS_DIR / "a2a_inbox.py"), 5000),
    ("UserPromptSubmit", "", str(HOOKS_DIR / "a2a_inbox.py"), 5000),
    ("SessionStart", "", str(REPO_ROOT / ".claude" / "hooks" / "session-start.sh"), 10000),
    ("Stop", "", str(REPO_ROOT / ".claude" / "hooks" / "tts_hook.py"), 5000),
    ("Notification", "", str(REPO_ROOT / ".claude" / "hooks" / "tts_hook.py"), 5000),
]

# Hooks that only watch, registered like the rest: the brain page gets one pulse for every tool
# call, prompt, compaction and session boundary. A list of its own, because the worker's
# container takes its guards from MANAGED (bin/pak_worker.py) and an observer is not one.
OBSERVERS = [
    ("PreToolUse", "", str(HOOKS_DIR / "brain-emit.py"), 5000),
    ("UserPromptSubmit", "", str(HOOKS_DIR / "brain-emit.py"), 5000),
    ("PreCompact", "manual|auto", str(HOOKS_DIR / "brain-emit.py"), 5000),
    ("SessionStart", "", str(HOOKS_DIR / "brain-emit.py"), 5000),
    ("SessionEnd", "", str(HOOKS_DIR / "brain-emit.py"), 5000),
]

# Command basenames these supersede — removed from any event if found.
SUPERSEDED = {"pre-write-validation.sh", "check-tokens.sh"}


def _without_superseded(groups: list) -> list:
    """Drop hook entries whose command basename is superseded; drop emptied groups."""
    cleaned = []
    for group in groups:
        hooks = [
            h for h in group.get("hooks", []) if Path(h.get("command", "")).name not in SUPERSEDED
        ]
        if hooks:
            cleaned.append(dict(group, hooks=hooks))
    return cleaned


def _ensure(groups: list, matcher: str, command: str, timeout: int) -> list:
    """Ensure the `matcher` group contains `command` exactly once."""
    for group in groups:
        if group.get("matcher") == matcher:
            if any(h.get("command") == command for h in group.get("hooks", [])):
                return groups
            group.setdefault("hooks", []).append(
                {"type": "command", "command": command, "timeout": timeout}
            )
            return groups
    groups.append(
        {
            "matcher": matcher,
            "hooks": [{"type": "command", "command": command, "timeout": timeout}],
        }
    )
    return groups


def main() -> None:
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    before = json.dumps(settings, sort_keys=True)

    hooks = settings.setdefault("hooks", {})
    for event in list(hooks):  # strip superseded everywhere first
        hooks[event] = _without_superseded(hooks[event])
    for event, matcher, command, timeout in MANAGED + OBSERVERS:
        hooks[event] = _ensure(hooks.get(event, []), matcher, command, timeout)
    for event in [e for e, v in hooks.items() if not v]:  # drop empty events
        del hooks[event]

    if before == json.dumps(settings, sort_keys=True):
        print(f"OK: hooks already registered in {SETTINGS} (no changes)")
        return
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"OK: hooks registered (guards, judge, session and voice) in {SETTINGS}")


if __name__ == "__main__":
    main()
