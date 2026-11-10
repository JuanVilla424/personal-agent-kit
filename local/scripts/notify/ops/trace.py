"""Per-request trajectory trace for the bot — a structured, replayable record of ONE request.

Prometheus metrics (``ops/metrics.py``) give aggregates and ``session_manager`` tracks per-thread
cost; this adds the missing layer: a per-request TRAJECTORY — model, tokens, cost, latency and the
ordered tool-calls (spans) — written as one JSON line per request to a trace sink. Queryable and
replayable (the SOTA equivalent of a Langfuse/Phoenix trace, kept local as JSONL).

Robust by design: tracing must NEVER raise into the request path — a failing write is logged, not
fatal. The monotonic clock and the sink are injectable for deterministic tests.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger("trace")

_TRACE_PATH = Path(
    os.getenv("TRACE_FILE", Path(__file__).resolve().parents[1] / "logs" / "traces.jsonl")
)


@dataclass
class Span:
    name: str
    duration_s: float = 0.0
    meta: dict = field(default_factory=dict)


class Trace:
    """One request's trajectory. Create at request start, record steps, ``close()`` to persist."""

    def __init__(
        self,
        request_id: str,
        user_id: str = "",
        model: str = "",
        clock: Callable[[], float] = time.monotonic,
        sink: Callable[[dict], None] | None = None,
    ) -> None:
        self.request_id = request_id
        self.user_id = user_id
        self.model = model
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.tools: list[str] = []
        self.spans: list[Span] = []
        self.outcome = "unknown"
        self._clock = clock
        self._sink = sink
        self._t0 = clock()

    @contextmanager
    def span(self, name: str, **meta):
        """Time a step (e.g., a tool-call or the subprocess); appended to the trajectory on exit."""
        t0 = self._clock()
        try:
            yield
        finally:
            self.spans.append(Span(name=name, duration_s=round(self._clock() - t0, 4), meta=meta))

    def tool(self, name: str) -> None:
        """Record a tool-call by name (order preserved)."""
        if name:
            self.tools.append(name)

    def set(self, **fields) -> None:
        """Set known fields (model, tokens_in, tokens_out, cost_usd)."""
        for key, value in fields.items():
            if hasattr(self, key) and not key.startswith("_"):
                setattr(self, key, value)

    def record(self) -> dict:
        return {
            "ts": time.time(),
            "request_id": self.request_id,
            "user_id": self.user_id,
            "model": self.model,
            "latency_s": round(self._clock() - self._t0, 4),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "tools": self.tools,
            "spans": [{"name": s.name, "duration_s": s.duration_s, **s.meta} for s in self.spans],
            "outcome": self.outcome,
        }

    def close(self, outcome: str = "ok") -> dict:
        """Finalize the trajectory and persist it. Never raises into the caller."""
        self.outcome = outcome
        rec = self.record()
        try:
            if self._sink is not None:
                self._sink(rec)
            else:
                _TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with _TRACE_PATH.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as exc:  # tracing is best-effort, never fatal
            log.warning("trace write failed: %s", exc)
        return rec
