"""Coverage for memory_index/main.py — index/query CLI with Qdrant + fastembed mocked."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import main as mi  # noqa: E402


def _fake_model():
    m = MagicMock()
    m.embed = lambda texts: [MagicMock(tolist=lambda: [0.0] * 384) for _ in texts]
    return m


class TestPureHelpers:
    def test_stable_id_deterministic(self):
        assert mi.stable_id("src", "sec") == mi.stable_id("src", "sec")
        assert len(mi.stable_id("a", "b")) == 36

    def test_cache_dir(self):
        assert "fastembed" in mi._cache_dir()

    def test_trust_label(self):
        assert "INTERNAL" in mi._trust_label("TROUBLESHOOTING.md")
        assert "EXTERNAL" in mi._trust_label("http://evil")

    def test_chunk_markdown(self, tmp_path):
        f = tmp_path / "TROUBLESHOOTING.md"
        f.write_text(
            "intro text that is definitely longer than thirty characters here\n"
            "## Section A\nbody content well beyond the thirty character minimum\n"
            "## Section B\nshort"
        )
        chunks = mi.chunk_markdown(f, tmp_path)
        assert any(c["section"] == "Section A" for c in chunks)
        assert all(c["case_id"] == "TROUBLESHOOTING" for c in chunks)

    def test_get_target_docs(self, tmp_path):
        (tmp_path / "TROUBLESHOOTING.md").write_text("tr")
        names = [d.name for d in mi.get_target_docs(tmp_path)]
        assert names == ["TROUBLESHOOTING.md"]

    def test_get_target_docs_empty(self, tmp_path):
        assert mi.get_target_docs(tmp_path) == []


class TestClientAndMetrics:
    def test_get_client_success(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(mi, "QdrantClient", lambda **k: client)
        assert mi.get_client() is client

    def test_get_client_failure(self, monkeypatch):
        monkeypatch.setattr(mi, "QdrantClient", MagicMock(side_effect=Exception("x")))
        assert mi.get_client() is None

    def test_ensure_collection(self):
        client = MagicMock()
        mi.ensure_collection(client)
        client.recreate_collection.assert_called_once()

    def test_read_count_and_bump(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mi, "_METRICS_STATE", tmp_path / "ms")
        assert mi._read_count("q.count") == 0
        assert mi._bump("q.count") == 1
        assert mi._read_count("q.count") == 1

    def test_record_query(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mi, "_METRICS_STATE", tmp_path / "ms")
        monkeypatch.setattr(mi, "metrics_push", MagicMock())
        mi._record_query(True, 0.9)


class TestCmdIndex:
    def test_no_client_exits(self, monkeypatch):
        monkeypatch.setattr(mi, "get_client", lambda: None)
        with pytest.raises(SystemExit):
            mi.cmd_index(None)

    def test_no_chunks_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mi, "get_client", lambda: MagicMock())
        monkeypatch.setattr(mi, "get_target_docs", lambda r: [])
        monkeypatch.setattr(mi.config, "DOCS_ROOT", str(tmp_path))
        with pytest.raises(SystemExit):
            mi.cmd_index(None)

    def test_success(self, monkeypatch, tmp_path):
        client = MagicMock()
        monkeypatch.setattr(mi, "get_client", lambda: client)
        docs_root = tmp_path / "docs"
        docs_root.mkdir(parents=True)
        (docs_root / "TROUBLESHOOTING.md").write_text(
            "intro long enough to pass the thirty char threshold\n## S\nbody well over thirty characters here for sure"
        )
        monkeypatch.setattr(mi.config, "DOCS_ROOT", str(docs_root))
        monkeypatch.setattr(mi, "_load_model", _fake_model)
        stats = mi.cmd_index(None)
        assert stats["docs"] == 1 and stats["chunks"] >= 1
        client.upsert.assert_called()


class TestCmdQuery:
    def _args(self, as_json=False):
        a = MagicMock()
        a.text, a.top_k, a.threshold, a.as_json = "sym", 5, 0.5, as_json
        return a

    def test_no_client(self, monkeypatch):
        monkeypatch.setattr(mi, "get_client", lambda: None)
        with pytest.raises(SystemExit):
            mi.cmd_query(self._args())

    def test_no_collection(self, monkeypatch):
        client = MagicMock()
        client.collection_exists.return_value = False
        monkeypatch.setattr(mi, "get_client", lambda: client)
        with pytest.raises(SystemExit):
            mi.cmd_query(self._args())

    def _ready_client(self, points):
        client = MagicMock()
        client.collection_exists.return_value = True
        client.query_points.return_value = MagicMock(points=points)
        return client

    def test_no_results(self, monkeypatch):
        monkeypatch.setattr(mi, "get_client", lambda: self._ready_client([]))
        monkeypatch.setattr(mi, "_load_model", _fake_model)
        monkeypatch.setattr(mi, "_record_query", lambda *a: None)
        with pytest.raises(SystemExit):
            mi.cmd_query(self._args())

    def test_results_text(self, monkeypatch):
        pt = MagicMock(
            score=0.9,
            payload={
                "case_id": "CA-1",
                "source": "TROUBLESHOOTING.md",
                "section": "S",
                "text": "snip",
            },
        )
        monkeypatch.setattr(mi, "get_client", lambda: self._ready_client([pt]))
        monkeypatch.setattr(mi, "_load_model", _fake_model)
        monkeypatch.setattr(mi, "_record_query", lambda *a: None)
        mi.cmd_query(self._args())

    def test_results_json(self, monkeypatch, capsys):
        pt = MagicMock(
            score=0.9,
            payload={
                "case_id": "CA-1",
                "source": "TROUBLESHOOTING.md",
                "section": "S",
                "text": "snip",
            },
        )
        monkeypatch.setattr(mi, "get_client", lambda: self._ready_client([pt]))
        monkeypatch.setattr(mi, "_load_model", _fake_model)
        monkeypatch.setattr(mi, "_record_query", lambda *a: None)
        mi.cmd_query(self._args(as_json=True))
        assert "CA-1" in capsys.readouterr().out


class TestMain:
    def test_index(self, monkeypatch):
        monkeypatch.setattr(mi.sys, "argv", ["main.py", "index"])
        monkeypatch.setattr(
            mi,
            "cmd_index",
            lambda a: {
                "docs": 1,
                "chunks": 2,
                "avg_chunks": 2.0,
                "newest_ts": 0.0,
            },
        )
        monkeypatch.setattr(mi, "metrics_push", MagicMock())
        mi.main()

    def test_query(self, monkeypatch):
        monkeypatch.setattr(mi.sys, "argv", ["main.py", "query", "symptom"])
        monkeypatch.setattr(mi, "cmd_query", lambda a: None)
        mi.main()

    def test_help(self, monkeypatch):
        monkeypatch.setattr(mi.sys, "argv", ["main.py"])
        mi.main()
