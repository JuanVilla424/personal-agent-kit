"""Coverage for ops/metrics_push.py — both the prometheus_client path (mocked in,
since the lib is not installed in this venv) and the stdlib text-push fallback."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops import metrics_push as mp  # noqa: E402


class TestNoPrometheus:
    def test_new_registry_raises(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", False)
        with pytest.raises(RuntimeError):
            mp.new_registry()

    def test_gauge_raises(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", False)
        with pytest.raises(RuntimeError):
            mp.gauge(None, "n", "d")

    def test_push_skips_without_lib(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", False)
        assert mp.push("job", None) is False

    def test_push_run_uses_text_fallback(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", False)
        sent = {}

        def fake_text(job, grouping, gauges):
            sent.update(gauges)
            return True

        monkeypatch.setattr(mp, "_push_text", fake_text)
        assert mp.push_run("finops", account="acc", duration_seconds=2.0, custom=9.0) is True
        assert sent["custom"] == 9.0
        assert "finops_last_run_timestamp_seconds" in sent
        assert sent["finops_run_duration_seconds"] == 2.0


class TestPushText:
    def test_success(self, monkeypatch):
        resp = MagicMock(status=204)
        cm = MagicMock()
        cm.__enter__.return_value = resp
        cm.__exit__.return_value = False
        monkeypatch.setattr(mp.urllib.request, "urlopen", lambda *a, **k: cm)
        assert mp._push_text("job", {"host": "h"}, {"m": 1.0}) is True

    def test_failure_swallowed(self, monkeypatch):
        monkeypatch.setattr(mp.urllib.request, "urlopen", MagicMock(side_effect=OSError("down")))
        assert mp._push_text("job", {"host": "h"}, {"m": 1.0}) is False


class TestWithPrometheus:
    def test_new_registry(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", True)
        monkeypatch.setattr(mp, "CollectorRegistry", MagicMock(return_value="REG"), raising=False)
        assert mp.new_registry() == "REG"

    def test_gauge(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", True)
        monkeypatch.setattr(mp, "Gauge", MagicMock(return_value="G"), raising=False)
        assert mp.gauge("reg", "n", "d") == "G"

    def test_push_success(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", True)
        ptg = MagicMock()
        monkeypatch.setattr(mp, "push_to_gateway", ptg, raising=False)
        assert mp.push("job", "reg", account="acc", extra_grouping={"k": "v"}) is True
        assert ptg.called

    def test_push_failure(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", True)
        monkeypatch.setattr(
            mp, "push_to_gateway", MagicMock(side_effect=OSError("x")), raising=False
        )
        assert mp.push("job", "reg") is False

    def test_push_run_registry_path(self, monkeypatch):
        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", True)
        monkeypatch.setattr(mp, "new_registry", lambda: MagicMock())
        monkeypatch.setattr(mp, "gauge", lambda *a, **k: MagicMock())
        monkeypatch.setattr(mp, "push", lambda *a, **k: True)
        assert mp.push_run("job", duration_seconds=1.5, custom_metric=2.0) is True
