#!/usr/bin/env python3
"""Push Claude Code session activity to the local Pushgateway.

Fired by the Stop hook after each completed turn. Reads the hook payload from
stdin to locate the session transcript and detect which BMAD agent/workflow
handled the turn (party-mode, cloud, cost, ...), so direct sessions are
attributable per agent just like the Slack bot path.

Must NEVER fail the session: every error path exits 0 silently.
"""

import fcntl
import getpass
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "metrics-state")
AGENT_MANIFEST = os.path.join(REPO_ROOT, ".bmad", "_cfg", "agent-manifest.csv")


def _root_env_value(key: str) -> str:
    """Read one key from the root .env, stdlib-only.

    The Stop hook may run under the system python3 (no python-dotenv), so we
    parse the file by hand instead of importing dotenv. Returns "" if absent.
    Only used for non-secret config (PUSHGATEWAY_URL); never log the value.
    """
    try:
        with open(os.path.join(REPO_ROOT, ".env"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                if name.strip() == key:
                    return value.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


# Real env var wins (explicit override); else the root .env; else local default.
PUSHGATEWAY_URL = (
    os.getenv("PUSHGATEWAY_URL") or _root_env_value("PUSHGATEWAY_URL") or "http://localhost:9391"
)

# <command-name>/bmad:core:workflows:party-mode</command-name> → party-mode
_COMMAND_RE = re.compile(r"<command-name>/?([^<]+)</command-name>")
_LOCAL_COMMANDS = ("model", "clear", "help", "config", "stats")


def load_manifest():
    """Return (displayName list, slug→displayName map) from the BMAD manifest."""
    names, slug_map = [], {}
    try:
        import csv

        with open(AGENT_MANIFEST, encoding="utf-8") as fh:
            for rec in csv.DictReader(fh):
                display = (rec.get("displayName") or "").strip()
                slug = (rec.get("name") or "").strip()
                if display:
                    names.append(display)
                    if slug:
                        slug_map[slug] = display
    except Exception:
        pass
    return names, slug_map


def _text_blocks(message) -> str:
    """Concatenate the plain-text blocks of a transcript message (tool calls excluded)."""
    content = (message or {}).get("content")
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(parts)


def detect_turn_agents(transcript_path: str):
    """Return (agents spoken in the last completed turn, last command slug).

    Parses each JSONL entry and inspects ONLY assistant text blocks — tool
    call payloads mention agent names in code/docstrings and must not count.
    A turn boundary is a real human message (type user, no tool_result, not a
    system-reminder injection); headers like '**🎨 Sally (UX):**' after it
    identify who spoke.
    """
    names, slug_map = load_manifest()
    header_res = [
        (name, re.compile(r"\*\*[^*\n]{0,24}\b" + re.escape(name) + r"\b[^*\n]{0,60}?:?\*\*"))
        for name in names
    ]
    agents: set = set()
    slug = ""
    try:
        with open(transcript_path, "rb") as fh:
            for raw in fh:
                try:
                    entry = json.loads(raw)
                except Exception:
                    continue
                etype = entry.get("type")
                message = entry.get("message") or {}
                if etype == "user":
                    content = message.get("content")
                    has_tool_result = isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                    )
                    text = _text_blocks(message)
                    for match in _COMMAND_RE.findall(text):
                        cand = match.split(":")[-1].strip()
                        if cand and cand not in _LOCAL_COMMANDS:
                            slug = cand
                    if not has_tool_result and "<system-reminder>" not in text:
                        agents.clear()
                elif etype == "assistant":
                    text = _text_blocks(message)
                    if text:
                        for name, rx in header_res:
                            if name not in agents and rx.search(text):
                                agents.add(name)
    except Exception:
        pass
    if not agents:
        fallback = slug_map.get(slug, slug) or "direct"
        agents = {fallback}
    return sorted(agents), slug or "direct"


def bump_counter(name: str) -> int:
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, name)
    with open(path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        raw = fh.read().strip()
        value = int(raw) + 1 if raw.isdigit() else 1
        fh.seek(0)
        fh.truncate()
        fh.write(str(value))
        return value


def push(job: str, grouping: dict, gauges: dict) -> None:
    segments = [f"job/{urllib.parse.quote(job, safe='')}"]
    for key, value in grouping.items():
        clean = str(value).replace("/", "_") or "unknown"
        segments.append(f"{key}/{urllib.parse.quote(clean, safe='')}")
    body = "".join(f"{name} {value}\n" for name, value in gauges.items()).encode()
    url = f"{PUSHGATEWAY_URL}/metrics/{'/'.join(segments)}"
    req = urllib.request.Request(url, data=body, method="PUT")
    with urllib.request.urlopen(req, timeout=2):
        pass


def main() -> int:
    try:
        try:
            payload = json.load(sys.stdin)
        except Exception:
            payload = {}

        # The final assistant message can land in the transcript a moment
        # after Stop fires — give the flush a beat before parsing.
        time.sleep(1)
        agents, _slug = detect_turn_agents(payload.get("transcript_path", "") or "")
        host = socket.gethostname()
        user = os.getenv("PAK_INVOKED_BY", "") or getpass.getuser()
        now = time.time()

        total = bump_counter("claude-code-turns.count")
        push(
            "claude_code",
            {"host": host, "invoked_by": user},
            {"claude_code_turns_total": total, "claude_code_last_run_timestamp_seconds": now},
        )
        for agent in agents:
            per_agent = bump_counter(f"claude-code-turns-{agent}.count")
            push(
                "claude_code_agent",
                {"host": host, "invoked_by": user, "agent": agent},
                {"claude_code_agent_turns_total": per_agent},
            )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
