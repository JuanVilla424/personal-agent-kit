#!/usr/bin/env python3
"""lessons.py — what went wrong, the control that answers it, and when that control expires.

A control without its incident is a rule nobody can question, and a control without an expiry
outlives its reason. Each lesson keeps the three together:

  incident   what happened, in one line
  control    what now prevents it: a guard rule, a protocol line, a habit
  expires    a date, or a condition, after which the control is reviewed and kept or retired

Lessons live in ~/.pak/lessons.jsonl (PAK_LESSONS overrides it). Each new lesson is also written to
the memory service as a `security` memory, so a search finds it; that part is best-effort.

Usage:
  bin/lessons.py add --incident "…" --control "…" (--expires 2027-05-01 | --until "…")
  bin/lessons.py list                 # every lesson, the expired ones marked
  bin/lessons.py expired              # exit 1 when a control is due for review
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY_CLI = REPO_ROOT / "local" / "scripts" / "memory_index" / "memory.py"
MEMORY_TIMEOUT_S = 30


def lessons_path() -> Path:
    return Path(os.environ.get("PAK_LESSONS") or Path.home() / ".pak" / "lessons.jsonl")


def load() -> list[dict]:
    path = lessons_path()
    if not path.exists():
        return []
    lessons = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            lessons.append(json.loads(line))
    return lessons


def is_expired(lesson: dict, today: date) -> bool:
    """A dated control expires on its date. A condition is never decided by a script: it stays
    listed for the human to judge."""
    expires = lesson.get("expires")
    return bool(expires) and date.fromisoformat(expires) <= today


def add(incident: str, control: str, expires: str = "", until: str = "") -> dict:
    if not incident.strip() or not control.strip():
        raise ValueError("a lesson needs both its incident and its control")
    if bool(expires) == bool(until):
        raise ValueError("give exactly one of --expires DATE or --until CONDITION")
    if expires:
        date.fromisoformat(expires)  # a bad date fails here, not when it is checked
    lesson = {
        "id": uuid.uuid4().hex[:12],
        "incident": incident.strip(),
        "control": control.strip(),
        "expires": expires,
        "until": until.strip(),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = lessons_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(lesson, ensure_ascii=False) + "\n")
    return lesson


def remember(lesson: dict) -> bool:
    """Write the lesson to the memory service too. Best-effort: the file is the record."""
    text = f"Lesson: {lesson['incident']} Control: {lesson['control']}"
    python = REPO_ROOT / ".venv" / "bin" / "python3"
    if not python.exists() or not MEMORY_CLI.exists():
        return False
    proc = subprocess.run(
        [str(python), str(MEMORY_CLI), "add", text, "--category", "security"],
        capture_output=True,
        text=True,
        timeout=MEMORY_TIMEOUT_S,
        check=False,
    )
    return proc.returncode == 0 and "remembered" in proc.stdout


def describe(lesson: dict, today: date) -> str:
    when = lesson["expires"] or f"until {lesson['until']}"
    mark = "EXPIRED " if is_expired(lesson, today) else ""
    return f"{mark}[{lesson['id']}] {lesson['incident']} → {lesson['control']} ({when})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="incidents, their controls and when each expires")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="record a lesson")
    p_add.add_argument("--incident", required=True)
    p_add.add_argument("--control", required=True)
    p_add.add_argument("--expires", default="", help="YYYY-MM-DD: review the control on this date")
    p_add.add_argument("--until", default="", help="the condition that retires the control")
    sub.add_parser("list", help="every lesson")
    sub.add_parser("expired", help="the controls due for review; exit 1 if any")
    args = ap.parse_args(argv)

    today = date.today()
    if args.cmd == "add":
        try:
            lesson = add(args.incident, args.control, args.expires, args.until)
        except ValueError as e:
            print(f"lessons: {e}", file=sys.stderr)
            return 2
        stored = "and in memory" if remember(lesson) else "(memory service not reached)"
        print(f"lessons: recorded {lesson['id']} in {lessons_path()} {stored}")
        return 0
    lessons = load()
    if args.cmd == "list":
        for lesson in lessons:
            print(describe(lesson, today))
        if not lessons:
            print("lessons: none yet")
        return 0
    expired = [lesson for lesson in lessons if is_expired(lesson, today)]
    for lesson in expired:
        print(describe(lesson, today))
    return 1 if expired else 0


if __name__ == "__main__":
    sys.exit(main())
