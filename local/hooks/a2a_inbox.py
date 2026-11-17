#!/usr/bin/env python3
"""local/hooks/a2a_inbox.py — the Claude-side drain of directed A2A messages.

SessionStart    → opens/refreshes this session's workspace cursor (temp/a2a-workspace-<sid>.json):
                  the ONLY local record of live Claude sessions — `a2a.py sessions --engine claude`
                  reads these files' mtimes, never any agents feature of the harness.
UserPromptSubmit → refreshes the cursor and delivers every queued kind="a2a" event addressed to
                  claude:<session-id> that this session has not delivered yet: the standard
                  envelope goes to stdout (on exit 0 the prompt's context picks it up) and each
                  delivery is acked in the registry (a2a.py list can tell delivered from queued).

RULES:
  - It NEVER blocks: always exit 0, everything best-effort (communication, not control).
  - The message body is the sender's responsibility: a2a.py writes the bus behind the
    auto-guard, and the envelope marks it as an agent's message, never the human's approval.
  - Exactly-once per session: the cursor stores the drained timestamp (ms precision — two
    messages inside one second are both deliverable).
"""

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CURSORS_DIR = REPO_ROOT / "temp"
BUS = REPO_ROOT / "local" / "scripts" / "a2a" / "logs" / "a2a_bus.jsonl"
REGISTRY = REPO_ROOT / "local" / "scripts" / "a2a" / "logs" / "a2a.jsonl"

sys.path.insert(0, str(REPO_ROOT / "local" / "scripts" / "a2a"))
from a2a import REGISTRY as A2A_REGISTRY, wrap_message  # noqa: E402  (single envelope source)


def _registry_append(rec: dict, registry: Path) -> None:
    registry.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(registry, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        while line:
            n = os.write(fd, line)
            line = line[n:]
    finally:
        os.close(fd)


def cursor_path(sid: str, cursors_dir: Path | None = None) -> Path:
    d = Path(cursors_dir) if cursors_dir else CURSORS_DIR
    return d / f"a2a-workspace-{sid}.json"


def touch(sid: str, cursors_dir: Path | None = None) -> Path:
    """Open or refresh this session's cursor; keeps the drained timestamp across prompts."""
    path = cursor_path(sid, cursors_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
    state["ts"] = time.time()
    state["sid"] = sid
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return path


def claude_sessions(cursors_dir: Path | None = None) -> list:
    d = Path(cursors_dir) if cursors_dir else CURSORS_DIR
    out = []
    for f in d.glob("a2a-workspace-*.json"):
        sid = f.name[len("a2a-workspace-") : -len(".json")]
        try:
            out.append({"id": sid, "last_active": f.stat().st_mtime})
        except OSError:
            continue
    return sorted(out, key=lambda s: -s["last_active"])


def _bus_events(bus: Path) -> list[dict]:
    if not bus.exists():
        return []
    events = []
    for line in bus.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("kind") == "a2a":
            events.append(row)
    return events


def drain(
    sid: str, registry: Path | None = None, bus: Path | None = None, cursors_dir: Path | None = None
) -> str:
    """Deliver every undelivered A2A event addressed to claude:<sid>; the envelopes joined,
    or "" when there is nothing. Each delivery is acked in the registry."""
    registry = registry or REGISTRY
    path = cursor_path(sid, cursors_dir)
    state = {}
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
    drained = state.get("drained_ts", "")
    pending = [
        e
        for e in _bus_events(bus or BUS)
        if e.get("to") == f"claude:{sid}" and str(e.get("ts", "")) > str(drained)
    ]
    if not pending:
        return ""
    out = []
    last = drained
    for e in pending:
        out.append(
            wrap_message(
                e.get("from", "?"),
                e.get("trust", "[INTERNAL]"),
                e.get("cid", "?"),
                e.get("text", ""),
            )
        )
        last = e.get("ts", last)
        _registry_append(
            {
                "ts": time.time(),
                "correlation_id": e.get("cid", "?"),
                "kind": "delivered",
                "event_ts": e.get("ts", ""),
                "session": sid,
                "status": "delivered",
            },
            registry,
        )
    state["drained_ts"] = last
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return "\n\n".join(out)


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    sid = payload.get("session_id") or os.getenv("CLAUDE_SESSION_ID") or ""
    if not sid:
        return  # no session identity: nothing to open, nothing to deliver
    event = payload.get("hook_event_name", "")
    touch(sid)
    if event == "SessionStart":
        return
    text = drain(sid)
    if text:
        print(text)
    # exit 0, always: this hook communicates, it never blocks


if __name__ == "__main__":  # pragma: no cover
    main()
