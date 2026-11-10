"""Coverage for ops/health_endpoint.py — FastAPI health/ready/version + start()."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from ops import health_endpoint as he  # noqa: E402


class TestState:
    def test_set_and_get(self):
        he.set_ready(True)
        assert he.get_state()["ready"] is True
        he.set_ready(False)


class TestEndpoints:
    def test_health_starting(self):
        he.set_ready(False)
        r = TestClient(he._app).get("/health")
        assert r.status_code == 503 and r.json()["status"] == "starting"

    def test_health_ok(self):
        he.set_ready(True)
        r = TestClient(he._app).get("/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"
        he.set_ready(False)

    def test_ready_true_then_false(self):
        he.set_ready(True)
        assert TestClient(he._app).get("/ready").status_code == 200
        he.set_ready(False)
        assert TestClient(he._app).get("/ready").status_code == 503

    def test_version(self):
        assert "version" in TestClient(he._app).get("/version").json()


class TestStart:
    def test_start_spawns_thread(self, monkeypatch):
        monkeypatch.setattr(he.uvicorn, "Server", MagicMock())
        monkeypatch.setattr(he.threading, "Thread", MagicMock())
        he.start(port=12399)
