"""bin/opencode/mcp_memory_server.py — each answer of memory_service as the model reads it."""

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin" / "opencode"))

import mcp_memory_server as mms  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402


class _Reply:
    def __init__(self, status: int, body: dict | None = None, text: str = ""):
        self.status_code = status
        self.ok = status < 400
        self._body = body or {}
        self.text = text

    def json(self) -> dict:
        return self._body


def _answer(monkeypatch, reply):
    def fake(*_args, **_kwargs):
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(mms.requests, "request", fake)


def test_a_memory_is_added_and_returned(monkeypatch):
    _answer(monkeypatch, _Reply(200, {"id": "m1"}))
    assert mms.memory_add("prefers tabs") == {"id": "m1"}


@pytest.mark.parametrize(
    "reply, message",
    [
        (_Reply(401), "rejected the token"),
        (_Reply(403, {"detail": "not yours"}), "not yours"),
        (_Reply(404, {"detail": "no such memory"}), "no such memory"),
        (
            _Reply(422, {"detail": {"reason": "injection signals", "signals": ["exfiltration"]}}),
            "injection signals (exfiltration)",
        ),
        (
            _Reply(422, {"detail": [{"msg": "field required"}]}, "bad body"),
            "returned 422: bad body",
        ),
        (_Reply(500, text="boom"), "returned 500: boom"),
        (requests.ConnectionError("refused"), "unreachable"),
    ],
)
def test_each_failure_reaches_the_model_as_a_readable_error(monkeypatch, reply, message):
    _answer(monkeypatch, reply)
    with pytest.raises(ToolError, match=message.replace("(", r"\(").replace(")", r"\)")):
        mms.memory_add("x")
