"""Coverage for memory_index/memory.py — HTTP client for the memory service."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import memory as mem  # noqa: E402


def _resp(payload):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = payload
    return r


class TestCommands:
    def test_cmd_add(self, monkeypatch, capsys):
        monkeypatch.setattr(
            mem.requests,
            "post",
            lambda *a, **k: _resp({"scope": "user", "category": "estilo", "id": "id1"}),
        )
        mem.cmd_add(MagicMock(text="t", scope="user", category="estilo", inferred=False))
        assert "remembered" in capsys.readouterr().out

    def test_cmd_search_results(self, monkeypatch, capsys):
        payload = {
            "results": [
                {
                    "scope": "user",
                    "source": "stated",
                    "score": 0.9,
                    "category": "estilo",
                    "text": "x",
                },
                {
                    "scope": "shared",
                    "source": "inferred",
                    "score": 0.7,
                    "category": "negocio",
                    "text": "y",
                },
            ]
        }
        monkeypatch.setattr(mem.requests, "get", lambda *a, **k: _resp(payload))
        mem.cmd_search(MagicMock(query="q", k=5))
        out = capsys.readouterr().out
        assert "estilo" in out and "inferred" in out

    def test_cmd_add_sends_the_state_key(self, monkeypatch, capsys):
        sent = {}

        def post(*_a, **kwargs):
            sent.update(kwargs["json"])
            return _resp({"scope": "user", "category": "systems", "id": "id2"})

        monkeypatch.setattr(mem.requests, "post", post)
        mem.cmd_add(
            MagicMock(
                text="t", scope="user", category="systems", inferred=False, state_key="laptop"
            )
        )
        assert sent["state_key"] == "laptop"

    def test_cmd_brief_prints_markdown_or_nothing(self, monkeypatch, capsys):
        payload = {"memories": [{"category": "security", "text": "rotate keys"}]}
        monkeypatch.setattr(mem.requests, "get", lambda *a, **k: _resp(payload))
        mem.cmd_brief(MagicMock())
        out = capsys.readouterr().out
        assert out.startswith("# What you remember") and "- [security] rotate keys" in out
        monkeypatch.setattr(mem.requests, "get", lambda *a, **k: _resp({"memories": []}))
        mem.cmd_brief(MagicMock())
        assert capsys.readouterr().out == ""

    def test_cmd_search_empty(self, monkeypatch, capsys):
        monkeypatch.setattr(mem.requests, "get", lambda *a, **k: _resp({"results": []}))
        mem.cmd_search(MagicMock(query="q", k=5))
        assert "no relevant memories" in capsys.readouterr().out

    def test_cmd_search_routes_to_local_url(self, monkeypatch):
        monkeypatch.setattr(mem, "LOCAL_URL", "http://local")
        calls = []
        monkeypatch.setattr(
            mem.requests, "get", lambda url, **k: calls.append(url) or _resp({"results": []})
        )
        mem.cmd_search(MagicMock(query="q", k=5))
        assert calls == ["http://local/memory/search"]

    def test_cmd_forget(self, monkeypatch, capsys):
        monkeypatch.setattr(mem.requests, "post", lambda *a, **k: _resp({}))
        mem.cmd_forget(MagicMock(id="id1"))
        assert "forgot" in capsys.readouterr().out


class TestMain:
    def test_no_cmd_prints_help(self, monkeypatch):
        monkeypatch.setattr(mem.sys, "argv", ["memory.py"])
        mem.main()

    def test_dispatch_add(self, monkeypatch):
        monkeypatch.setattr(mem.sys, "argv", ["memory.py", "add", "hello", "--scope", "user"])
        called = {}
        monkeypatch.setattr(mem, "cmd_add", lambda a: called.setdefault("ok", True))
        mem.main()
        assert called["ok"]

    def test_service_down_exits_zero(self, monkeypatch):
        monkeypatch.setattr(mem.sys, "argv", ["memory.py", "search", "q"])
        monkeypatch.setattr(
            mem, "cmd_search", MagicMock(side_effect=mem.requests.exceptions.RequestException("x"))
        )
        with pytest.raises(SystemExit) as exc:
            mem.main()
        assert exc.value.code == 0


def test_cmd_consolidate_reports_the_count(monkeypatch, capsys):
    monkeypatch.setattr(mem.requests, "post", lambda *a, **k: _resp({"merged": 2, "pairs": []}))
    mem.cmd_consolidate(MagicMock())
    assert "2 duplicates" in capsys.readouterr().out
