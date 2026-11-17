"""brain_bus.py — the event bus of the brain page: one JSON line per thing the agent did.

Standard library only, so the hooks can import it without paying for the service's imports.
Writers: local/hooks/brain-emit.py (every tool call, prompt and compaction of a session) and
memory_service.py (every save, search, consolidation and forget). Reader: brain_page.py, which
numbers the lines and streams them to the page.

An event is {"ts", "kind", "path", "text"} plus optional "side", "ref", "origin" and "tag".
`path` is the route of the pulse through the regions the page draws, and `text` is what the
page's log says about it.
"""

import json
import os
import re
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REGIONS = frozenset(
    {"dlpfc", "apfc", "ofc", "atl", "post", "hip", "tha", "amy", "bg", "cb", "vta", "hypo"}
)
ISO_UTC = "%Y-%m-%dT%H:%M:%S+00:00"
# Past this size the bus is set aside as <name>.1 (one generation kept) and starts empty: the
# page only ever reads its tail.
MAX_BYTES = 8 * 1024 * 1024
TEXT_MAX = 160
_SECRET = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*\S+")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-.]{16,}")


def bus_path() -> Path:
    """Where the bus lives. BRAIN_EVENTS_LOG points the tests at a file of their own."""
    return Path(
        os.environ.get("BRAIN_EVENTS_LOG")
        or REPO_ROOT / "local" / "scripts" / "a2a" / "logs" / "brain_events.jsonl"
    )


def mask(text: str) -> str:
    """What a pulse may say about a command, a query or a memory: never a credential or a long
    token, and never more than a line."""
    keyed = _SECRET.sub(lambda m: re.split(r"[=:]", m.group(0))[0] + "=***", str(text))
    return " ".join(_LONG_TOKEN.sub("***", keyed).split())[:TEXT_MAX]


def emit(kind: str, text: str, path: list[str], **extra: str) -> bool:
    """Append one event; True when it was written. Best effort: the page is an observer, so a
    pulse that cannot be written never fails what caused it."""
    event = {
        "ts": time.strftime(ISO_UTC, time.gmtime()),
        "kind": kind,
        "path": [region for region in path if region in REGIONS] or ["hip"],
        "text": text,
    }
    event.update({key: value for key, value in extra.items() if value})
    bus = bus_path()
    try:
        bus.parent.mkdir(parents=True, exist_ok=True)
        if bus.exists() and bus.stat().st_size > MAX_BYTES:
            os.replace(bus, bus.with_name(bus.name + ".1"))
        with bus.open("a", encoding="utf-8") as lines:
            lines.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True
