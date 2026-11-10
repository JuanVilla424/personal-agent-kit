"""Coverage for memory_index/logger.py (by-path load) and seed_memory.py."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

MI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MI))


def _load_logger():
    spec = importlib.util.spec_from_file_location("mi_logger_under_test", MI / "logger.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMiLogger:
    def test_module_logger_exists(self):
        assert _load_logger().logger is not None

    def test_setup_with_file(self, tmp_path):
        lg = _load_logger().setup_logger("mi-test-1", log_file=str(tmp_path / "x.log"))
        assert len(lg.handlers) >= 2

    def test_idempotent(self):
        mod = _load_logger()
        lg = mod.setup_logger("mi-test-2")
        n = len(lg.handlers)
        assert len(mod.setup_logger("mi-test-2").handlers) == n


import seed_memory as sm  # noqa: E402


class TestSeedMemory:
    def test_loads_and_posts(self, monkeypatch, tmp_path):
        (tmp_path / "seed_memories.json").write_text(json.dumps([{"text": "a"}, {"text": "b"}]))
        monkeypatch.setattr(sm, "THIS", tmp_path / "seed_memory.py")
        monkeypatch.setattr(sm.requests, "post", lambda *a, **k: MagicMock(ok=True))
        sm.main()

    def test_service_down_exits(self, monkeypatch, tmp_path):
        (tmp_path / "seed_memories.json").write_text(json.dumps([{"text": "a"}]))
        monkeypatch.setattr(sm, "THIS", tmp_path / "seed_memory.py")
        monkeypatch.setattr(
            sm.requests, "post", MagicMock(side_effect=sm.requests.exceptions.RequestException("x"))
        )
        with pytest.raises(SystemExit):
            sm.main()
