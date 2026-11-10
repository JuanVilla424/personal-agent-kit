"""Coverage for ops/trace.py — per-request trajectory tracing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops.trace import Trace  # noqa: E402


class FakeClock:
    """Monotonic stub that advances by ``step`` on every call (deterministic durations)."""

    def __init__(self, step: float = 1.0):
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def _sink():
    captured: list[dict] = []
    return captured, captured.append


def test_close_writes_record_to_sink():
    captured, sink = _sink()
    Trace("req-1", user_id="U1", model="opus", clock=FakeClock(), sink=sink).close("ok")
    assert len(captured) == 1
    rec = captured[0]
    assert rec["request_id"] == "req-1"
    assert rec["user_id"] == "U1"
    assert rec["model"] == "opus"
    assert rec["outcome"] == "ok"


def test_span_records_duration_and_meta():
    captured, sink = _sink()
    tr = Trace("r", clock=FakeClock(step=2.0), sink=sink)
    with tr.span("subprocess", model="haiku"):
        pass
    tr.close()
    span = captured[0]["spans"][0]
    assert span["name"] == "subprocess"
    assert span["duration_s"] == 2.0
    assert span["model"] == "haiku"


def test_tools_order_preserved_and_empty_ignored():
    captured, sink = _sink()
    tr = Trace("r", clock=FakeClock(), sink=sink)
    tr.tool("Bash")
    tr.tool("Read")
    tr.tool("")
    tr.close()
    assert captured[0]["tools"] == ["Bash", "Read"]


def test_set_updates_known_fields_only():
    _, sink = _sink()
    tr = Trace("r", clock=FakeClock(), sink=sink)
    tr.set(tokens_in=100, tokens_out=50, cost_usd=0.01, bogus="x", _t0=9)
    rec = tr.close()
    assert rec["tokens_in"] == 100
    assert rec["tokens_out"] == 50
    assert rec["cost_usd"] == 0.01
    assert "bogus" not in rec


def test_latency_from_injected_clock():
    captured, sink = _sink()
    tr = Trace("r", clock=FakeClock(step=1.0), sink=sink)  # init -> t0=1
    tr.close()  # record -> clock=2 ; latency = 1
    assert captured[0]["latency_s"] == 1.0


def test_close_never_raises_on_failing_sink():
    def bad_sink(_rec):
        raise IOError("disk full")

    rec = Trace("r", clock=FakeClock(), sink=bad_sink).close("error")
    assert rec["outcome"] == "error"  # returned even though the write failed
