"""The brain page's server side: the bus (brain_bus.py) and what the page reads (brain_page.py)."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import brain_page as ba  # noqa: E402
import brain_bus  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

HERE = ("127.0.0.1", 50000)


@pytest.fixture()
def bus(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "brain_events.jsonl"
    monkeypatch.setenv("BRAIN_EVENTS_LOG", str(path))
    return path


@pytest.fixture()
def checkout(tmp_path, monkeypatch):
    """A scratch checkout for the readings that look at the repository."""
    monkeypatch.setattr(ba, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ba, "_git_cache", (0.0, []))
    monkeypatch.delenv("AUTO_GUARD_LOG", raising=False)
    return tmp_path


def _line(text: str, at: float | None = None, **more) -> str:
    stamp = time.strftime(brain_bus.ISO_UTC, time.gmtime(at or time.time()))
    return json.dumps({"ts": stamp, "kind": "tool", "path": ["dlpfc"], "text": text, **more}) + "\n"


def _append(bus: Path, *lines: str) -> None:
    bus.parent.mkdir(parents=True, exist_ok=True)
    with bus.open("a", encoding="utf-8") as handle:
        handle.writelines(lines)


# ── the bus ───────────────────────────────────────────────────────────────────


def test_an_event_is_one_line_with_only_known_regions(bus):
    assert brain_bus.emit("memory", "memory saved", ["hip", "nowhere"], side="L", ref="") is True
    written = json.loads(bus.read_text(encoding="utf-8"))
    assert written["path"] == ["hip"] and written["text"] == "memory saved"
    assert written["side"] == "L" and "ref" not in written
    brain_bus.emit("tool", "x", ["nowhere"])
    assert json.loads(bus.read_text(encoding="utf-8").splitlines()[1])["path"] == ["hip"]


def test_a_pulse_never_carries_a_credential_or_a_long_token():
    said = brain_bus.mask("curl -H token=abc123 https://x  a" + "b" * 40 + "\nnext line")
    assert "abc123" not in said and "b" * 16 not in said and "\n" not in said
    assert len(brain_bus.mask("word " * 100)) <= brain_bus.TEXT_MAX


def test_a_full_bus_is_set_aside_and_started_again(bus, monkeypatch):
    monkeypatch.setattr(brain_bus, "MAX_BYTES", 10)
    brain_bus.emit("tool", "first", ["bg"])
    brain_bus.emit("tool", "second", ["bg"])
    assert "first" in bus.with_name(bus.name + ".1").read_text(encoding="utf-8")
    assert "second" in bus.read_text(encoding="utf-8") and "first" not in bus.read_text("utf-8")


def test_a_pulse_that_cannot_be_written_does_not_fail_its_cause(tmp_path, monkeypatch):
    (tmp_path / "file").write_text("x", encoding="utf-8")
    monkeypatch.setenv("BRAIN_EVENTS_LOG", str(tmp_path / "file" / "bus.jsonl"))
    assert brain_bus.emit("tool", "x", ["bg"]) is False


# ── reading it ────────────────────────────────────────────────────────────────


def test_lines_are_read_backwards_across_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "TAIL_BLOCK", 7)
    log = tmp_path / "log"
    log.write_text("one\n\ntwo\nthree\n", encoding="utf-8")
    assert list(ba.tail_lines(log, 1000)) == ["three", "two", "one"]
    assert list(ba.tail_lines(log, 1000, end=9)) == ["two", "one"]
    assert list(ba.tail_lines(log, 7)) == ["three"]


def test_a_line_becomes_the_event_the_page_draws():
    raw = {"ts": "t", "kind": "tool", "path": ["bg", "bogus"], "text": "ran", "side": "L"}
    event = ba.to_event(json.dumps({**raw, "origin": "hook", "tag": "not an id!", "ref": "r"}))
    assert event == {
        "ts": "t",
        "kind": "tool",
        "path": ["bg"],
        "text": "ran",
        "ref": "r",
        "side": "L",
        "origin": "hook",
    }
    assert ba.to_event(json.dumps({"text": {"en": "old shape"}}))["text"] == ""
    assert ba.to_event("not json") is None and ba.to_event("[1]") is None


def test_the_feed_is_newest_first_and_stops_at_what_the_page_has(bus):
    assert ba.feed() == []
    _append(bus, _line("old", 1000), "broken\n", _line("mid", 2000), _line("new", 3000))
    assert [event["text"] for event in ba.feed()] == ["new", "mid", "old"]
    assert [event["text"] for event in ba.feed(limit=1)] == ["new"]
    after = time.strftime(brain_bus.ISO_UTC, time.gmtime(2000))
    assert [event["text"] for event in ba.feed(after)] == ["new"]


def test_the_reader_starts_at_the_end_and_takes_whole_lines_only(bus):
    _append(bus, _line("history"))
    reader = ba._Reader()
    reader.start()
    assert reader.new_lines() == []
    _append(bus, _line("whole"), '{"half')
    assert [json.loads(raw)["text"] for raw in reader.new_lines()] == ["whole"]
    _append(bus, '": 1}\n')
    assert reader.new_lines() == ['{"half": 1}']


def test_the_reader_follows_a_bus_that_was_replaced_or_cut(bus):
    reader = ba._Reader()
    reader.start()  # no bus yet
    assert reader.new_lines() == []
    _append(bus, _line("a"), _line("b"))
    assert len(reader.new_lines()) == 2
    os.replace(bus, bus.with_name("old"))  # set aside: the new file is all news
    _append(bus, _line("c"))
    assert [json.loads(raw)["text"] for raw in reader.new_lines()] == ["c"]
    _append(bus, _line("d"))
    reader.new_lines()
    with bus.open("r+", encoding="utf-8") as handle:
        handle.truncate(5)  # cut short in place: nothing is resent
    assert reader.new_lines() == []


# ── the stream ────────────────────────────────────────────────────────────────


def test_every_new_event_gets_its_own_number_and_old_ones_are_history(bus):
    hub = ba.Hub()
    queue, missed = hub.subscribe()
    assert missed == []
    _append(bus, _line("one"), _line("two"), _line("stale", time.time() - 3600), "broken\n")
    hub.pump()
    frames = [queue.get_nowait(), queue.get_nowait()]
    assert queue.empty()
    assert [frame.split("\n")[0] for frame in frames] == [f"id: {hub.boot}-1", f"id: {hub.boot}-2"]
    assert json.loads(frames[1].split("data: ")[1])["text"] == "two"
    hub.unsubscribe(queue)
    hub.unsubscribe(queue)  # twice is harmless


def test_a_page_that_reconnects_resumes_at_its_exact_event(bus):
    hub = ba.Hub()
    hub.reader.start()
    _append(bus, _line("one"), _line("two"), _line("three"))
    hub.pump()
    _, missed = hub.subscribe(f"{hub.boot}-1")
    assert [json.loads(f.split("data: ")[1])["text"] for f in missed] == ["two", "three"]
    assert hub.subscribe("otherboot-1")[1] == [] and hub.subscribe("")[1] == []
    assert hub.seq_of(f"{hub.boot}-7") == 7 and hub.seq_of("nonsense") is None


def test_a_page_that_stops_reading_is_closed_not_fed(bus, monkeypatch):
    monkeypatch.setattr(ba.Hub, "QUEUE", 1)
    hub = ba.Hub()
    queue, _ = hub.subscribe()
    _append(bus, _line("one"), _line("two"))
    hub.pump()
    assert queue.get_nowait() is None and queue.empty()


def test_the_snapshot_ends_where_the_stream_continues(bus):
    hub = ba.Hub()
    hub.reader.start()
    _append(bus, _line("seen"))
    events, cursor = hub.snapshot()
    assert [event["text"] for event in events] == ["seen"] and cursor == f"{hub.boot}-1"
    _append(bus, _line("no usable time").replace(json.loads(_line("x"))["ts"], "whenever"))
    hub.pump()
    assert hub.place() == f"{hub.boot}-2"  # an event without a time was seen just now


def test_a_state_is_compared_without_the_time_of_its_reading():
    first = {"ts": "1", "health": {"checks": [{"id": "memory", "ts": "1", "status": "ok"}]}}
    later = {"ts": "2", "health": {"checks": [{"id": "memory", "ts": "2", "status": "ok"}]}}
    assert ba.state_mark(first) == ba.state_mark(later)
    later["health"]["checks"][0]["status"] = "down"
    assert ba.state_mark(first) != ba.state_mark(later)


class _Page:
    """The connection of one page: it leaves after `beats` looks."""

    def __init__(self, beats: int, last_event_id: str = "") -> None:
        self.beats = beats
        self.headers = {"last-event-id": last_event_id} if last_event_id else {}
        self.client = SimpleNamespace(host="127.0.0.1")

    async def is_disconnected(self) -> bool:
        self.beats -= 1
        return self.beats < 0


async def test_the_stream_sends_what_was_missed_then_what_comes(bus, monkeypatch):
    hub = ba.Hub()
    monkeypatch.setattr(ba, "HUB", hub)
    monkeypatch.setattr(ba.Hub, "STATE_S", 0.01)
    states = iter([{"n": 1}, {"n": 2}])
    monkeypatch.setattr(ba, "state", lambda: next(states, {"n": 2}))
    hub.reader.start()
    _append(bus, _line("missed"))
    hub.pump()
    frames = []

    async def read():
        async for frame in ba.live(_Page(beats=40), f"{hub.boot}-0"):
            frames.append(frame)
            if len(frames) == 3:
                _append(bus, _line("live"))

    await asyncio.wait_for(read(), timeout=20)
    sent = "".join(frames)
    assert frames[0] == "retry: 3000\n\n" and ": hb\n\n" in frames
    assert sent.index('"missed"') < sent.index('"live"')
    assert "event: state\ndata: 1\n\n" in frames  # the state changed while the page was open
    assert hub._pages == [] and hub._tasks == []  # nothing runs once the last page leaves


async def test_a_page_too_far_behind_is_closed_and_a_foreign_place_gets_only_news(bus):
    hub = ba.Hub()
    ba.HUB, kept = hub, ba.HUB
    try:
        _append(bus, _line("before the page"))
        frames = []
        async for frame in ba.live(_Page(beats=3), "anotherprocess-9"):
            frames.append(frame)
            if len(frames) == 2:
                hub._pages[0].put_nowait(None)
        assert "before the page" not in "".join(frames) and hub._pages == []
    finally:
        ba.HUB = kept


async def test_the_stream_route_resumes_at_the_browsers_last_event(monkeypatch):
    seen = []

    async def fake_live(_request, place):
        seen.append(place)
        yield ""

    monkeypatch.setattr(ba, "live", fake_live)
    response = await ba.brain_stream(_Page(1, last_event_id="boot-5"), since="boot-2")
    assert response.media_type == "text/event-stream"
    assert [frame async for frame in response.body_iterator] == [""] and seen == ["boot-5"]
    response = await ba.brain_stream(_Page(1), since="boot-2")
    assert [frame async for frame in response.body_iterator] == [""]
    assert seen == ["boot-5", "boot-2"]


async def test_the_hub_reads_once_for_every_page_and_survives_a_look_that_fails(monkeypatch):
    hub = ba.Hub()
    monkeypatch.setattr(ba.Hub, "BUS_S", 0.001)
    monkeypatch.setattr(ba, "state", dict)
    looks = []

    def fails_once():
        looks.append(1)
        if len(looks) == 1:
            raise OSError("busy")

    monkeypatch.setattr(hub, "pump", fails_once)
    hub.run()
    readers = list(hub._tasks)
    hub.run()  # a second page: the same readers
    assert hub._tasks == readers
    await asyncio.sleep(0.05)
    assert len(looks) > 1
    hub.stop()

    def cancel_on_a_closed_loop():
        raise RuntimeError("Event loop is closed")

    hub._tasks = [SimpleNamespace(cancel=cancel_on_a_closed_loop)]
    hub.stop()
    assert hub._tasks == []


# ── the state ─────────────────────────────────────────────────────────────────


def test_open_tasks_come_from_the_task_file(checkout):
    assert ba.read_tasks() == {}
    (checkout / "TASKS.md").write_text(
        "- [x] done\n- [ ] **Write the page**: the brain\n  - [ ] its tests\n", encoding="utf-8"
    )
    assert ba.read_tasks() == {
        "total": 2,
        "pending_titles": ["Write the page: the brain", "its tests"],
    }


def test_guard_verdicts_and_delegations_are_counted_from_their_logs(checkout):
    assert ba.read_guard() == {"counters": {}} and ba.read_a2a() == []
    (checkout / "logs").mkdir()
    (checkout / "logs" / "auto_guard_log.jsonl").write_text(
        '{"severity": "block"}\nbroken\n[1]\n{"severity": "block"}\n{"rule": "x"}\n', "utf-8"
    )
    assert ba.read_guard() == {"counters": {"block": {"total": 2}, "other": {"total": 1}}}
    a2a = checkout / "local" / "scripts" / "a2a" / "logs"
    a2a.mkdir(parents=True)
    rows = [{"correlation_id": f"a2a-{n}", "intent": "message", "status": "sent"} for n in "123"]
    (a2a / "a2a.jsonl").write_text(
        "broken\n" + "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    assert [row["cid"] for row in ba.read_a2a(limit=2)] == ["a2a-3", "a2a-2"]
    assert len(ba.read_a2a()) == 3  # the broken line is skipped


def test_the_last_commits_are_read_once_and_kept(checkout, monkeypatch):
    calls = []

    def fake_git(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="abc1234 first\n\ndef5678 second\n")

    monkeypatch.setattr(ba.subprocess, "run", fake_git)
    assert ba.read_git() == ["abc1234 first", "def5678 second"]
    assert ba.read_git() == ["abc1234 first", "def5678 second"] and len(calls) == 1
    monkeypatch.setattr(ba, "_git_cache", (0.0, []))
    monkeypatch.setattr(ba.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    assert ba.read_git() == []


def test_lessons_and_backups_are_read_from_the_kits_own_tools(checkout, monkeypatch):
    backups = checkout / "backups"
    backups.mkdir()
    kit = {
        "lessons": SimpleNamespace(load=lambda: [1, 2], lessons_path=lambda: checkout / "l.jsonl"),
        "brain_backup": SimpleNamespace(root=lambda: backups, latest_age_hours=lambda: None),
    }
    monkeypatch.setattr(ba, "_kit_module", lambda name: kit[name])
    assert ba.read_lessons() == {"count": 2, "source": "l.jsonl"}
    assert ba.read_backup()["status"] == "missing"
    (backups / "latest.agent_memory.generation").write_text("170-abc.snapshot\n", encoding="utf-8")
    kit["brain_backup"].latest_age_hours = lambda: 2.0
    assert ba.read_backup()["status"] == "ok"
    assert ba.read_backup()["generation"] == "170-abc.snapshot"
    kit["brain_backup"].latest_age_hours = lambda: 30 * 24.0
    assert ba.read_backup()["status"] == "stale"
    monkeypatch.setattr(ba, "_kit_module", lambda _name: (_ for _ in ()).throw(ImportError()))
    assert ba.read_lessons() == {} and ba.read_backup()["status"] == "unknown"


def test_the_kits_tools_are_found_in_its_bin(monkeypatch):
    monkeypatch.setattr(ba, "REPO_ROOT", Path(__file__).resolve().parents[4])
    assert hasattr(ba._kit_module("lessons"), "lessons_path")
    assert ba._shown(Path.home() / ".pak" / "x") == "~/.pak/x" and ba._shown(Path("/x")) == "/x"


def test_the_night_cycle_is_what_the_service_noted(bus):
    assert ba.read_night()["status"] == "missing"
    ba.note_night(3)
    assert ba.read_night()["status"] == "ok"
    assert json.loads(ba.night_mark().read_text(encoding="utf-8"))["merged"] == 3
    assert "3 replaced" in ba.feed()[0]["text"]
    old = time.time() - 3 * 86400
    os.utime(ba.night_mark(), (old, old))
    assert ba.read_night()["status"] == "stale"


def test_a_night_that_cannot_be_noted_does_not_fail_the_consolidation(tmp_path, monkeypatch):
    (tmp_path / "file").write_text("x", encoding="utf-8")
    monkeypatch.setenv("BRAIN_EVENTS_LOG", str(tmp_path / "file" / "bus.jsonl"))
    ba.note_night(1)


def test_coverage_is_shown_only_when_there_is_a_report(checkout):
    assert ba.read_coverage() is None
    report = checkout / "coverage.xml"
    report.write_text("<nothing/>", encoding="utf-8")
    assert ba.read_coverage() is None
    report.write_text(
        '<?xml version="1.0" ?>\n<coverage version="7" lines-valid="200" line-rate="0.9604">'
        '<class name="a"/><class name="b"/></coverage>',
        encoding="utf-8",
    )
    found = ba.read_coverage()
    assert (found["total"], found["files"], found["lines_valid"]) == (96.04, 2, 200)
    assert found["target"] is None and found["status"] == "ok"
    (checkout / "pyproject.toml").write_text('addopts = "--cov-fail-under=96"', encoding="utf-8")
    assert ba.read_coverage()["target"] == 96.0
    old = time.time() - 30 * 86400
    os.utime(report, (old, old))
    assert ba.read_coverage()["status"] == "stale"


def test_the_state_names_the_evidence_of_every_reading(checkout, bus, monkeypatch):
    (checkout / "protocols").mkdir()
    (checkout / "protocols" / "memory-protocol.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ba, "_kit_module", lambda _name: (_ for _ in ()).throw(ImportError()))
    monkeypatch.setattr(ba.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout=""))
    monkeypatch.setattr(ba, "_memory_health", lambda: {"status": "ok", "entries": 2})
    found = ba.state()
    assert found["protocols"] == ["memory-protocol"] and found["memory_health"]["entries"] == 2
    checks = {row["id"]: row for row in found["health"]["checks"]}
    assert set(checks) == {"services", "memory", "memory_user"}
    assert all(row["status"] == "ok" and row["source"] and row["ts"] for row in checks.values())
    assert found["health"]["cycles"][0]["id"] == "night"
    assert "coverage" not in found["health"] and "benchmark" not in found["health"]

    (checkout / "coverage.xml").write_text('<coverage line-rate="1" lines-valid="1">', "utf-8")
    monkeypatch.setattr(ba, "_memory_health", lambda: {"status": "degraded", "error": "down"})
    health = ba.state()["health"]
    assert {row["status"] for row in health["checks"]} == {"down"}
    assert health["coverage"]["source"] == "coverage.xml"


def test_the_memory_benchmark_is_shown_only_when_it_was_run(checkout):
    assert ba.read_benchmark() is None
    report = checkout / "temp" / "memory-benchmark" / "result.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"results": {}}', encoding="utf-8")
    assert ba.read_benchmark() is None
    scores = {"pak (convex)": {"test": {"hit@1": 0.625}}}
    report.write_text(
        json.dumps({"chosen_on_dev": "pak (convex)", "questions": {"test": 40}, "results": scores}),
        encoding="utf-8",
    )
    found = ba.read_benchmark()
    assert (found["score"], found["items"], found["status"]) == (0.625, 40, "ok")
    assert found["source"] == "temp/memory-benchmark/result.json"
    old = time.time() - 30 * 86400
    os.utime(report, (old, old))
    assert ba.read_benchmark()["status"] == "stale"
    assert ba.read_health({"status": "ok"})["benchmark"]["items"] == 40


# ── the routes: this machine only ─────────────────────────────────────────────


def _app(tmp_path, monkeypatch) -> FastAPI:
    ui = tmp_path / "brain-ui"
    ui.mkdir()
    (ui / "index.html").write_text("<title>brain</title>", encoding="utf-8")
    monkeypatch.setattr(ba, "UI_DIR", ui)
    monkeypatch.setattr(ba, "HUB", ba.Hub())
    monkeypatch.setattr(ba, "state", lambda: {"ts": "now"})
    app = FastAPI()
    ba.mount(app, lambda: {"status": "ok"})
    return app


def test_the_page_and_its_api_answer_this_machine(tmp_path, bus, monkeypatch):
    client = TestClient(_app(tmp_path, monkeypatch), client=HERE)
    page = client.get("/brain/")
    assert page.status_code == 200 and "brain" in page.text
    state = client.get("/api/brain/state")
    assert state.json() == {"ts": "now"} and state.headers["cache-control"] == "no-store"
    _append(bus, _line("seen"))
    events = client.get("/api/brain/events").json()
    assert events["events"][0]["text"] == "seen" and events["cursor"].endswith("-0")
    assert ba._memory_health() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/brain/", "/api/brain/state", "/api/brain/events"])
def test_nothing_of_the_page_is_served_to_another_machine(tmp_path, monkeypatch, path):
    client = TestClient(_app(tmp_path, monkeypatch), client=("192.0.2.7", 50000))
    refused = client.get(path)
    assert refused.status_code == 403 and "this machine only" in refused.text


def test_only_a_loopback_address_is_this_machine():
    assert ba.is_local(("127.0.0.1", 1)) and ba.is_local(("::1", 1))
    assert not ba.is_local(("192.0.2.7", 1)) and not ba.is_local(("testclient", 1))
    assert not ba.is_local(None) and not ba.is_local(())


def test_a_service_without_the_page_files_still_serves_the_api(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "UI_DIR", tmp_path / "missing")
    monkeypatch.setattr(ba, "state", lambda: {"ts": "now"})
    app = FastAPI()
    ba.mount(app, dict)
    client = TestClient(app, client=HERE)
    assert client.get("/api/brain/state").status_code == 200
    assert client.get("/brain/").status_code == 404
