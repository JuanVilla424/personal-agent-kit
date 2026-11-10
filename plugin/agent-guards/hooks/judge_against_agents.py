#!/usr/bin/env python3
"""judge_against_agents.py — semantic reviewer for the PostToolUse[Write|Edit] hook.

Plugin copy of local/hooks/judge_against_agents.py: reads AGENTS_MD from
${CLAUDE_PROJECT_DIR} (the plugin's *host* project, exported by Claude Code to every
hook process) instead of a path relative to this file — this script now lives inside
the plugin's own directory, not the target repo, so it can no longer assume its
parent's parent is the project root the way the original does.

Reads a just-written source file plus the host project's AGENTS.md, asks a fast
model whether the file complies with the project's conventions, and reports any
violations. Best-effort by design: if no model backend is reachable, the file
type is irrelevant, or anything goes wrong, it exits 0 (never wedges Claude).

On findings it emits a NON-BLOCKING additionalContext JSON (exit 0) with the
violations in English; Claude sees them as a system reminder and may act on the
next turn. It never blocks the write.

Code/comments: English. Judge prompt and verdicts: English (project rule).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import which

AGENTS_MD = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / "AGENTS.md"
MODEL = "claude-haiku-5-5"  # fast + cheap for per-write review
MAX_FILE_LINES = 400  # keep token cost bounded
TIMEOUT_S = 45

# Only judge real source files; skip docs, data, lockfiles, binaries, etc.
SOURCE_SUFFIXES = {
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".vue",
    ".go",
    ".tf",
    ".yml",
    ".yaml",
}


def _read_head(path: Path, max_lines: int) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    head = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        head += f"\n... [truncated: {len(lines) - max_lines} more lines]"
    return head


def _build_prompt(rules: str, file_path: str, code: str) -> str:
    return (
        "You are a code reviewer. Decide whether the file complies with the "
        "project conventions defined in AGENTS.md.\n\n"
        "Check especially: code in English; no hardcoded configuration "
        "(use os.getenv/.env); use .venv, not the system python; script "
        "structure (config/logger/main); non-root docker user usrapp; no "
        "hardcoded secrets.\n\n"
        "CONTEXT (do NOT flag this as a violation):\n"
        "- .py scripts load their own config via python-dotenv (config.py). Do NOT ask "
        "for '.env loaded before Python': that applies only to .sh scripts, never to "
        ".py files or commands that run .py.\n"
        "- A script run with ANOTHER tool's interpreter (e.g. notify/venv/bin/python3 "
        "running a memory_index script) is NOT 'borrowing a foreign venv' if that script IMPORTS "
        "that tool's package (from notify import ..., from ops import ...): it's intentional "
        "coupling and runs in the correct venv. Only flag 'foreign venv' when the tool is "
        "independent and does NOT import the package of the venv it's using.\n\n"
        "Flag ONLY unambiguous, HIGH-confidence violations of an explicit AGENTS.md "
        "rule. When in doubt, pass=true. Don't report style, inferences, or optional "
        "improvements.\n\n"
        "Respond ONLY with valid JSON, no surrounding text, in this shape:\n"
        '{"pass": true|false, "violations": [{"rule": "<rule>", "line": <n|null>, '
        '"detail": "<what is wrong and how to fix it>"}]}\n'
        "If everything complies: pass=true and violations=[].\n\n"
        f"=== AGENTS.md ===\n{rules}\n\n"
        f"=== File: {file_path} ===\n{code}\n"
    )


def _ask_claude(prompt: str) -> str:
    """Run the prompt through the headless claude CLI. Returns text or ''."""
    claude = which("claude")
    if not claude:
        return ""
    env = dict(os.environ, PAK_HOOK_RUNNING="1")  # stop our own hooks from recursing
    try:
        out = subprocess.run(
            [claude, "-p", prompt, "--model", MODEL],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=env,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _parse_verdict(text: str) -> dict | None:
    """Extract the JSON verdict from the model output. None if unparseable."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    path = Path(sys.argv[1])
    if path.suffix not in SOURCE_SUFFIXES or not path.is_file() or not AGENTS_MD.is_file():
        return 0

    try:
        rules = AGENTS_MD.read_text(encoding="utf-8", errors="replace")
        code = _read_head(path, MAX_FILE_LINES)
    except Exception:
        return 0

    verdict = _parse_verdict(_ask_claude(_build_prompt(rules, str(path), code)))
    if not verdict or verdict.get("pass", True):
        return 0  # pass, skipped, or unparseable -> don't block

    violations = verdict.get("violations") or []
    lines = [f"AGENTS.md JUDGE (advisory, non-blocking) — {path.name}:"]
    for v in violations[:8]:
        rule = v.get("rule", "?")
        line = v.get("line")
        detail = v.get("detail", "")
        loc = f" (line {line})" if line else ""
        lines.append(f"  • [{rule}]{loc} {detail}")
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0  # non-blocking: feedback goes in as context, never an error


if __name__ == "__main__":
    sys.exit(main())
