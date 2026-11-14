"""local/hooks/a2a_inbox.py — the drain: exactly-once delivery, registry acks, envelope contract."""

import json
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "local" / "hooks"))
sys.path.insert(0, str(REPO / "local" / "scripts" / "a2a"))

import a2a  # noqa: E402
import a2a_inbox as inbox  # noqa: E402


@pytest.fixture()
def wiring(tmp_path, monkeypatch):
    registry = tmp_path / "a2a.jsonl"
    bus = tmp_path / "a2a_bus.jsonl"
    cursors = tmp_path / "cursors"
    cursors.mkdir()
    monkeypatch.setattr(inbox, "CURSORS_DIR", cursors)
    monkeypatch.setattr(inbox, "BUS", bus)
    monkeypatch.setattr(inbox, "REGISTRY", registry)
    return {"registry": registry, "bus": bus, "cursors": cursors}


def _queue(bus: Path, sid: str, cid: str, ts: str, text="hello from raven"):
    bus.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": ts,
        "kind": "a2a",
        "to": f"claude:{sid}",
        "from": "orchestrator",
        "trust": "[INTERNAL]",
        "cid": cid,
        "text": text,
    }
    with open(bus, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def test_touch_opens_and_refreshes_the_cursor(wiring):
    path = inbox.touch("sesA")
    first = path.read_text()
    assert "sesA" in first
    time.sleep(0.01)
    inbox.touch("sesA")
    assert path.read_text() != first


def test_claude_sessions_lists_newest_first(wiring):
    inbox.touch("sesOld")
    time.sleep(0.01)
    inbox.touch("sesNew")
    sessions = inbox.claude_sessions()
    assert [s["id"] for s in sessions] == ["sesNew", "sesOld"]


def test_drain_delivers_every_pending_event_exactly_once(wiring):
    _queue(wiring["bus"], "sesA", "a2a-d1", "2026-11-14T00:00:00.000Z", "first")
    _queue(wiring["bus"], "sesA", "a2a-d2", "2026-11-14T00:00:01.000Z", "second")
    _queue(wiring["bus"], "sesB", "a2a-d3", "2026-11-14T00:00:02.000Z", "for someone else")
    text = inbox.drain("sesA")
    assert "first" in text and "second" in text and "for someone else" not in text
    assert "<<<A2A-a2a-d1" in text and "A2A-a2a-d2>>>" in text and "for someone else" not in text
    assert text.split("\n\n")[0] == a2a.wrap_message(  # envelope contract: identical to a2a.py's
        "orchestrator", "[INTERNAL]", "a2a-d1", "first"
    )
    # exactly once: a second drain returns nothing
    assert inbox.drain("sesA") == ""
    acks = [json.loads(l) for l in wiring["registry"].read_text().splitlines()]
    assert [a["correlation_id"] for a in acks] == ["a2a-d1", "a2a-d2"]
    assert all(a["status"] == "delivered" and a["session"] == "sesA" for a in acks)
    cursor = json.loads(inbox.cursor_path("sesA").read_text())
    assert cursor["drained_ts"] == "2026-11-14T00:00:01.000Z"


def test_drain_skips_malformed_bus_lines(wiring):
    wiring["bus"].write_text("not json at all\n")
    assert inbox.drain("sesA") == ""


def test_main_delivers_on_user_prompt_submit_and_opens_on_session_start(
    wiring, monkeypatch, capsys
):
    monkeypatch.setattr(inbox, "CURSORS_DIR", wiring["cursors"])
    monkeypatch.setattr(inbox, "BUS", wiring["bus"])
    monkeypatch.setattr(inbox, "REGISTRY", wiring["registry"])

    def _stdin(payload):
        import io

        return io.StringIO(json.dumps(payload))

    monkeypatch.setattr(
        sys, "stdin", _stdin({"session_id": "sesA", "hook_event_name": "SessionStart"})
    )
    inbox.main()
    assert inbox.cursor_path("sesA", wiring["cursors"]).exists()
    assert capsys.readouterr().out == ""

    _queue(wiring["bus"], "sesA", "a2a-m1", "2026-11-14T01:00:00.000Z", "message one")
    monkeypatch.setattr(
        sys, "stdin", _stdin({"session_id": "sesA", "hook_event_name": "UserPromptSubmit"})
    )
    inbox.main()
    out = capsys.readouterr().out
    assert "message one" in out and "<<<A2A-a2a-m1" in out
    assert inbox.drain("sesA") == ""  # delivered exactly once


def test_main_without_a_session_identity_is_a_noop(wiring, monkeypatch, capsys):
    monkeypatch.setattr(inbox, "CURSORS_DIR", wiring["cursors"])
    monkeypatch.setattr(sys, "stdin", _stdin({}))
    inbox.main()
    assert capsys.readouterr().out == ""
    assert list(wiring["cursors"].glob("*.json")) == []


def _stdin(payload):
    import io

    return io.StringIO(json.dumps(payload))
