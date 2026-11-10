"""Coverage for ops/metrics.py — prometheus_client metric definitions + exporter."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("prometheus_client")

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops import metrics as met  # noqa: E402


def test_metric_objects_defined():
    assert met.messages_received is not None
    assert met.anomaly_score is not None
    assert met.pool_size is not None


def test_start_exporter_serves_metrics(monkeypatch):
    captured = {}

    def fake_make_server(host, port, app):
        captured["app"] = app
        return MagicMock()

    monkeypatch.setattr(met, "make_server", fake_make_server)
    monkeypatch.setattr(met.threading, "Thread", MagicMock())
    met.start_exporter(port=19099)

    start_response = MagicMock()
    body = captured["app"]({}, start_response)
    assert body and isinstance(body[0], (bytes, bytearray))
    start_response.assert_called_once()
