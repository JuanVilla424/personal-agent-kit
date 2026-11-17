"""brain_page.py — the server side of the brain page (local/brain-ui, served at /brain).

The page draws what the agent does on a brain: every real event is one pulse through the
regions that stand for what happened, and every region shows the evidence behind it.

  /api/brain/state    what the regions and the health panel show, read from the kit's own
                      evidence: memory, guard log, TASKS.md, lessons, A2A, protocols, backups
  /api/brain/events   the recent past, newest first, and the place in the stream where it ends
  /api/brain/stream   server-sent events: every new line of the bus, numbered

The emitters stamp whole seconds, so the stream numbers every event: two that share a second
both arrive, and a page that reconnects resumes at its exact one. Nothing is read while no page
is open. The page shows what the agent is doing, so it is served to this machine only, by
address and by name (localhost, 127.0.0.1, ::1): a site that makes its own name resolve to this
machine cannot read it. From anywhere else, reach it through an SSH tunnel.
"""

import asyncio
import collections
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers

import brain_bus
from brain_bus import ISO_UTC, REGIONS, REPO_ROOT

UI_DIR = REPO_ROOT / "local" / "brain-ui"
TAIL_BLOCK = 64 * 1024
FEED_MAX_BYTES = 2 * 1024 * 1024  # how far back in the bus a page that opens can look
EVIDENCE_MAX_BYTES = 1024 * 1024  # the tail of a log that a reading counts
GIT_CACHE_S = 20.0
BACKUP_MAX_AGE_H = 7 * 24
NIGHT_MAX_AGE_S = 26 * 3600  # the consolidation runs every night
REPORT_MAX_AGE_S = 8 * 24 * 3600
NO_STORE = {"Cache-Control": "no-store"}
LOCAL_ONLY = "the brain page is served to this machine only"
LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})  # what this machine is called
_IDENT = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_OPEN_TASK = re.compile(r"^\s*- \[ \]\s+(.*)$")
_GATE = re.compile(r"--cov-fail-under=(\d+(?:\.\d+)?)")
_RATE = re.compile(r'<coverage\b[^>]*\bline-rate="([0-9.]+)"')
_LINES = re.compile(r'<coverage\b[^>]*\blines-valid="(\d+)"')


# ── the bus: reading it ──────────────────────────────────────────────────────


def tail_lines(path: Path, max_bytes: int, end: int | None = None):
    """The non-empty lines of a file, last first, reading backwards in blocks up to `max_bytes`.
    With `end`, backwards from that byte instead of from the end of the file."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        pos = handle.tell() if end is None else min(end, handle.tell())
        read, rest = 0, b""
        while pos > 0 and read < max_bytes:
            step = min(TAIL_BLOCK, pos)
            pos -= step
            handle.seek(pos)
            parts = (handle.read(step) + rest).split(b"\n")
            read += step
            rest = parts[0]  # maybe the end of a line that starts in the previous block
            for raw in reversed(parts[1:]):
                if raw.strip():
                    yield raw.decode("utf-8", "replace")
        if pos == 0 and rest.strip():
            yield rest.decode("utf-8", "replace")


def to_event(line: str) -> dict | None:
    """A line of the bus as the event the page draws; None for a line that is not one."""
    try:
        raw = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    text = raw.get("text")
    event = {
        "ts": str(raw.get("ts") or ""),
        "kind": str(raw.get("kind") or "event")[:40],
        "path": [region for region in raw.get("path") or [] if region in REGIONS] or ["hip"],
        "text": text[:300] if isinstance(text, str) else "",
        "ref": str(raw.get("ref") or "")[:120],
    }
    if raw.get("side") in ("L", "R", "both"):
        event["side"] = raw["side"]
    for key in ("origin", "tag"):  # identifiers only: the page ranks and labels by them
        if isinstance(raw.get(key), str) and _IDENT.fullmatch(raw[key]):
            event[key] = raw[key]
    return event


def feed(after: str = "", limit: int = 100, end: int | None = None) -> list[dict]:
    """The events of the bus, newest first: those after `after` (an ISO time), at most `limit`,
    and none past byte `end` of the file."""
    bus, events = brain_bus.bus_path(), []
    if not bus.is_file():
        return events
    for line in tail_lines(bus, FEED_MAX_BYTES, end):
        event = to_event(line)
        if not event:
            continue
        if after and event["ts"] <= after:
            break
        events.append(event)
        if len(events) >= limit:
            break
    return events


class _Reader:
    """Where the stream stands in the bus file: the whole lines appended since the last look."""

    def __init__(self) -> None:
        self.pos = 0
        self._inode = None
        self._started = False

    def start(self) -> None:
        """Begin at the end of the bus, once: what it already holds is history, not news."""
        if not self._started:
            self._started = True
            try:
                found = brain_bus.bus_path().stat()
                self.pos, self._inode = found.st_size, found.st_ino
            except OSError:
                self.pos, self._inode = 0, None

    def new_lines(self) -> list[str]:
        bus = brain_bus.bus_path()
        try:
            found = bus.stat()
        except OSError:
            return []
        if self._inode is not None and found.st_ino != self._inode:
            self.pos = 0  # the bus was set aside and started again: the new file is all news
        elif found.st_size < self.pos:
            self.pos = found.st_size  # cut short in place: replaying it would resend the past
        self._inode = found.st_ino
        if found.st_size <= self.pos:
            return []
        with bus.open("rb") as handle:
            handle.seek(self.pos)
            chunk = handle.read()
        # whole lines only: a line caught half-written waits for the next look. Taken now it
        # would be dropped as broken JSON, and its second half again later: an event lost
        whole = chunk[: chunk.rfind(b"\n") + 1]
        self.pos += len(whole)
        return [raw for raw in whole.decode("utf-8", "replace").splitlines() if raw.strip()]


# ── the stream: one reader for every open page ───────────────────────────────


def _steady(state, _at=()):
    """A state without what moves by itself between two reads (the time of the read): what is
    left changes only when something happened, so two reads can be compared."""
    if isinstance(state, dict):
        return {
            key: _steady(value, _at + (key,))
            for key, value in state.items()
            if not (key == "ts" and _at in ((), ("health", "checks")))
        }
    if isinstance(state, list):
        return [_steady(value, _at) for value in state]
    return state


def state_mark(current: dict) -> str:
    steady = json.dumps(_steady(current), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(steady.encode("utf-8")).hexdigest()


class Hub:
    """Reads the bus once for every open page and gives each event a number of its own, sent as
    the SSE id. Nothing runs while no page is connected."""

    BUS_S = 0.02  # how often the bus is looked at while a page is connected
    STATE_S = 5.0  # the state is read this often, and announced when it changed
    NEWS_S = 60.0  # older than this when first seen: history, not news
    RING = 2000  # numbered events kept for a page that reconnects
    QUEUE = 1000  # a page this far behind is closed: its browser reconnects and resumes

    def __init__(self) -> None:
        self.boot = secrets.token_hex(4)  # an id of another process (a restart) is not ours
        self.seq = 0
        self.reader = _Reader()
        self._ring: collections.deque = collections.deque(maxlen=self.RING)
        self._pages: list = []
        self._tasks: list = []
        self._loop = None
        self._mark = None

    def place(self) -> str:
        return f"{self.boot}-{self.seq}"

    def seq_of(self, place: str) -> int | None:
        """The number in an event id of this process; None for any other place."""
        boot, _, number = str(place or "").rpartition("-")
        return int(number) if boot == self.boot and number.isdigit() else None

    def subscribe(self, place: str = ""):
        """A page joins: its queue and the frames it missed since `place`. A place that is not
        an id of this process gets only what comes next."""
        self.reader.start()
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.QUEUE)
        number = self.seq_of(place)
        recent = time.monotonic() - self.NEWS_S
        missed = [
            f for n, at, f in self._ring if number is not None and n > number and at >= recent
        ]
        self._pages.append(queue)
        return queue, missed

    def unsubscribe(self, queue) -> None:
        if queue in self._pages:
            self._pages.remove(queue)
        if not self._pages:
            self.stop()

    def run(self) -> None:
        """Start reading for the pages. Idempotent; tasks left by a loop that closed are replaced."""
        loop = asyncio.get_running_loop()
        if self._tasks and self._loop is loop and not any(task.done() for task in self._tasks):
            return
        self.stop()
        self._loop = loop
        self._mark = None  # the first look at the state is the baseline, not a change
        self._tasks = [loop.create_task(job()) for job in (self._watch_bus, self._watch_state)]

    def stop(self) -> None:
        for task in self._tasks:
            try:
                task.cancel()
            except RuntimeError:
                pass  # its loop is already closed
        self._tasks = []

    def _is_news(self, event: dict) -> bool:
        """False for what was already old when first seen (a bus nobody watched for a while).
        The time is left in one format, whole UTC seconds."""
        now = time.time()
        try:
            at = datetime.fromisoformat(event["ts"].replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError, OSError):
            at = now  # no usable time: it was seen just now
        event["ts"] = time.strftime(ISO_UTC, time.gmtime(at))
        return now - at <= self.NEWS_S

    def _send(self, frame: str) -> None:
        for queue in list(self._pages):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                # a page that stopped reading: emptied and told to close. Its browser reconnects
                # and resumes at its last event; feeding it blindly would only grow the memory
                self._pages.remove(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)

    def pump(self) -> None:
        """One look at the bus: each new line that is news becomes a numbered event."""
        self.reader.start()
        for raw in self.reader.new_lines():
            event = to_event(raw)
            if event and self._is_news(event):
                self.seq += 1
                data = json.dumps(event, ensure_ascii=False)
                frame = f"id: {self.place()}\ndata: {data}\n\n"
                self._ring.append((self.seq, time.monotonic(), frame))
                self._send(frame)

    def snapshot(self, after: str = ""):
        """The recent past for a page that opens, and its place in the stream. The bus is read
        up to where the hub stands, so the stream continues exactly where the snapshot ends."""
        self.pump()
        return feed(after, 100, self.reader.pos), self.place()

    async def _watch_bus(self) -> None:
        while True:
            try:
                self.pump()
            except OSError:
                pass  # a bus that cannot be read now is read at the next look
            await asyncio.sleep(self.BUS_S)

    async def _watch_state(self) -> None:
        while True:
            mark = state_mark(await asyncio.to_thread(state))
            if self._mark is not None and mark != self._mark:
                self._send("event: state\ndata: 1\n\n")  # the page reads the state again
            self._mark = mark
            await asyncio.sleep(self.STATE_S)


HUB = Hub()


# ── the state: every reading names its evidence ──────────────────────────────


def _iso(epoch: float) -> str:
    return time.strftime(ISO_UTC, time.gmtime(epoch))


def _shown(path: Path) -> str:
    """A path the way the page shows it: inside the checkout, or under ~."""
    for base, prefix in ((REPO_ROOT, ""), (Path.home(), "~/")):
        try:
            return prefix + str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def _reading(key: str, status: str, source: str, at: float | None = None, **more) -> dict:
    row = {"id": key, "status": status, "source": source, **more}
    if at is not None:
        row["ts"] = _iso(at)
    return row


def _kit_module(name: str):
    """A module of the kit's bin/ (the lessons and the backups live there)."""
    bin_dir = str(REPO_ROOT / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    return __import__(name)


def read_tasks() -> dict:
    path = REPO_ROOT / "TASKS.md"
    if not path.is_file():
        return {}
    found = [_OPEN_TASK.match(line) for line in path.read_text("utf-8", "replace").splitlines()]
    titles = [match.group(1).replace("**", "").strip()[:90] for match in found if match]
    return {"total": len(titles), "pending_titles": titles[:5]}


def read_guard() -> dict:
    log = Path(os.environ.get("AUTO_GUARD_LOG") or REPO_ROOT / "logs" / "auto_guard_log.jsonl")
    counted: collections.Counter = collections.Counter()
    if log.is_file():
        for line in tail_lines(log, EVIDENCE_MAX_BYTES):
            try:
                counted[str(json.loads(line).get("severity") or "other")] += 1
            except (ValueError, AttributeError):
                continue
    return {"counters": {name: {"total": total} for name, total in sorted(counted.items())}}


def read_a2a(limit: int = 6) -> list[dict]:
    log = REPO_ROOT / "local" / "scripts" / "a2a" / "logs" / "a2a.jsonl"
    rows = []
    if log.is_file():
        for line in tail_lines(log, EVIDENCE_MAX_BYTES):
            try:
                row = json.loads(line)
                rows.append(
                    {
                        "cid": str(row.get("correlation_id") or ""),
                        "intent": str(row.get("intent") or ""),
                        "status": str(row.get("status") or ""),
                    }
                )
            except (ValueError, AttributeError):
                continue
            if len(rows) >= limit:
                break
    return rows


_git_cache: tuple[float, list[str]] = (0.0, [])


def read_git() -> list[str]:
    """The last commits of this checkout, cached: the page asks often and git answers slowly."""
    global _git_cache  # pylint: disable=global-statement
    if time.monotonic() < _git_cache[0]:
        return _git_cache[1]
    try:
        shown = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", "-3", "--format=%h %s"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        shown = ""
    commits = [line.strip() for line in shown.splitlines() if line.strip()]
    _git_cache = (time.monotonic() + GIT_CACHE_S, commits)
    return commits


def read_lessons() -> dict:
    try:
        lessons = _kit_module("lessons")
        return {"count": len(lessons.load()), "source": _shown(lessons.lessons_path())}
    except (ImportError, OSError, ValueError):
        return {}


def read_backup() -> dict:
    """The newest generation of the brain backups: the memory survives nowhere else."""
    try:
        backups = _kit_module("brain_backup")
        root, hours = backups.root(), backups.latest_age_hours()
    except (ImportError, OSError, ValueError):
        return _reading("snapshot", "unknown", "pak brain backup")
    if hours is None:
        return _reading("snapshot", "missing", _shown(root))
    marks = sorted(root.glob("latest.*.generation"), key=lambda mark: mark.stat().st_mtime)
    return _reading(
        "snapshot",
        "ok" if hours <= BACKUP_MAX_AGE_H else "stale",
        _shown(root),
        time.time() - hours * 3600,
        generation=marks[-1].read_text(encoding="utf-8").strip() if marks else "",
    )


def night_mark() -> Path:
    """Where the service notes each consolidation it ran (the evidence of the night cycle):
    next to the bus, so whatever moves the bus moves it too."""
    return brain_bus.bus_path().with_name("consolidation.json")


def note_night(merged: int) -> None:
    """A consolidation just ran: its pulse on the page and its mark for the health panel. Best
    effort, like every pulse."""
    brain_bus.emit("replay", f"consolidation · {merged} replaced by a newer one", ["tha", "hip"])
    mark = night_mark()
    try:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(json.dumps({"ts": _iso(time.time()), "merged": merged}), encoding="utf-8")
    except OSError:
        pass


def read_night() -> dict:
    mark = night_mark()
    try:
        at = mark.stat().st_mtime
    except OSError:
        return _reading("night", "missing", _shown(mark))
    fresh = time.time() - at <= NIGHT_MAX_AGE_S
    return _reading("night", "ok" if fresh else "stale", _shown(mark), at)


def read_coverage() -> dict | None:
    """The last test coverage report of the checkout, when there is one. Read as text: the
    numbers the page shows sit in the report's first tag and need no XML parser."""
    report = REPO_ROOT / "coverage.xml"
    try:
        text, at = report.read_text(encoding="utf-8", errors="replace"), report.stat().st_mtime
    except OSError:
        return None
    rate, lines = _RATE.search(text[:4096]), _LINES.search(text[:4096])
    if not rate:
        return None
    try:
        gate = _GATE.search((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    except OSError:
        gate = None
    return _reading(
        "coverage",
        "ok" if time.time() - at <= REPORT_MAX_AGE_S else "stale",
        "coverage.xml",
        at,
        total=round(float(rate.group(1)) * 100, 2),
        target=float(gate.group(1)) if gate else None,
        files=text.count("<class "),
        lines_valid=int(lines.group(1)) if lines else 0,
    )


def read_benchmark() -> dict | None:
    """The last memory benchmark (pak eval memory), when it was run: the share of the test
    questions whose answer came first."""
    report = REPO_ROOT / "temp" / "memory-benchmark" / "result.json"
    try:
        found = json.loads(report.read_text(encoding="utf-8"))
        score = float(found["results"][found["chosen_on_dev"]]["test"]["hit@1"])
        items, at = int(found["questions"]["test"]), report.stat().st_mtime
    except (OSError, ValueError, KeyError, TypeError):
        return None
    fresh = time.time() - at <= REPORT_MAX_AGE_S
    return _reading(
        "benchmark", "ok" if fresh else "stale", _shown(report), at, score=score, items=items
    )


def read_health(memory: dict) -> dict:
    """The health panel: one reading per layer, each with its status, its source and its time."""
    now, up = time.time(), memory.get("status") == "ok"
    probe = "/memory/health"
    checks = [
        _reading(
            "services", "ok" if up else "down", probe, now, detail=str(memory.get("error") or "")
        ),
        _reading("memory", "ok" if up else "down", probe, now, detail=memory.get("entries")),
        _reading(
            "memory_user", "ok" if up else "down", probe, now, detail=memory.get("user_entries")
        ),
    ]
    health = {"checks": checks, "snapshot": read_backup(), "cycles": [read_night()]}
    # the two reports of the checkout are shown when they exist, each with its own date: a kit
    # that never ran its tests or its benchmark is not a kit that needs attention
    for name, report in (("coverage", read_coverage()), ("benchmark", read_benchmark())):
        if report:
            health[name] = report
    return health


_memory_health = dict  # set by mount(): how the service reads its own collections


def state() -> dict:
    """Everything the page shows that is not an event."""
    memory = _memory_health()
    return {
        "ts": _iso(time.time()),
        "tasks": read_tasks(),
        "guard": read_guard(),
        "a2a": read_a2a(),
        "git": read_git(),
        "protocols": sorted(doc.stem for doc in (REPO_ROOT / "protocols").glob("*.md")),
        "lessons": read_lessons(),
        "memory_health": memory,
        "health": read_health(memory),
    }


# ── the routes ───────────────────────────────────────────────────────────────


def is_local(client) -> bool:
    """True for a caller on this machine. `client` is the (host, port) pair of the connection."""
    try:
        return ipaddress.ip_address(client[0]).is_loopback
    except (TypeError, IndexError, ValueError):
        return False


def _host_name(value: str) -> str:
    """The name in a Host header, without its port: `[::1]:7800` is `::1`."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def allowed(client, headers) -> bool:
    """True when the request comes from this machine AND names it. The connection alone is not
    enough: a site whose name is made to resolve to 127.0.0.1 (DNS rebinding) reaches this port
    from the user's own browser, but its requests carry its own name in Host and Origin."""
    if not is_local(client) or _host_name(headers.get("host", "")) not in LOCAL_NAMES:
        return False
    origin = headers.get("origin")
    return origin is None or (urlsplit(origin).hostname or "") in LOCAL_NAMES


def _local_only(request: Request) -> None:
    if not allowed(request.client, request.headers):
        raise HTTPException(status_code=403, detail=LOCAL_ONLY)


class _LocalFiles(StaticFiles):
    """The page's own files, with the same rule as its API."""

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and not allowed(scope.get("client"), Headers(scope=scope)):
            await JSONResponse({"detail": LOCAL_ONLY}, status_code=403)(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


router = APIRouter(dependencies=[Depends(_local_only)])


@router.get("/api/brain/state")
def brain_state():
    return JSONResponse(state(), headers=NO_STORE)  # no-store: a cached state freezes the page


@router.get("/api/brain/events")
def brain_events(after: str = ""):
    events, cursor = HUB.snapshot(after)
    return JSONResponse({"events": events, "cursor": cursor}, headers=NO_STORE)


async def live(request: Request, place: str):
    """The stream of one page: the frames it missed since `place`, then every new one, with a
    heartbeat a second so a closed connection is noticed."""
    yield "retry: 3000\n\n"
    if HUB.seq_of(place) is None:
        HUB.pump()  # a place from another process: what already happened is not resent
    queue, missed = HUB.subscribe(place)
    try:
        HUB.run()
        for frame in missed:
            yield frame
        loop, beat = asyncio.get_running_loop(), None
        while not await request.is_disconnected():
            now = loop.time()
            if beat is None or now - beat >= 1.0:
                beat = now
                yield ": hb\n\n"
                continue
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=1.0 - (now - beat))
            except asyncio.TimeoutError:
                continue
            if frame is None:  # too far behind: closed here, the browser resumes at its id
                return
            yield frame
    finally:
        HUB.unsubscribe(queue)


@router.get("/api/brain/stream")
async def brain_stream(request: Request, since: str = ""):
    """The page opens it with ?since=<cursor of /api/brain/events>; a browser that reconnects
    sends the Last-Event-ID of its last event, and the stream resumes there."""
    place = request.headers.get("last-event-id") or since
    return StreamingResponse(
        live(request, place),
        media_type="text/event-stream",
        headers={**NO_STORE, "X-Accel-Buffering": "no"},
    )


def mount(app, memory_health) -> None:
    """Add the page and its API to the memory service. `memory_health` is the service's own
    health reading."""
    global _memory_health  # pylint: disable=global-statement
    _memory_health = memory_health
    app.include_router(router)
    if UI_DIR.is_dir():
        app.mount("/brain", _LocalFiles(directory=str(UI_DIR), html=True), name="brain")
