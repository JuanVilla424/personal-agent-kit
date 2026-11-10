"""Coverage for security/anomaly_detector.py and security/token_rotator.py."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from security import anomaly_detector as ad  # noqa: E402
from security import token_rotator as trot  # noqa: E402


class TestAnomaly:
    def test_jaccard(self):
        assert ad._jaccard(set(), set()) == 0.0
        assert ad._jaccard({"a", "b"}, {"a"}) == 0.5

    def test_score_short_no_history(self):
        ad._history.clear()
        assert ad._score("short text") == 0.0

    def test_score_with_history(self):
        ad._history.clear()
        ad._history.append({"text": "hello world foo", "user": "u", "ts": 0})
        assert ad._score("hello world foo") > 0.0

    async def test_check_normal(self, monkeypatch):
        ad._history.clear()
        monkeypatch.setattr(ad.metrics, "anomaly_score", MagicMock())
        assert await ad.check("u", "normal message") is False

    async def test_check_anomaly(self, monkeypatch):
        ad._history.clear()
        ad._history.append({"text": "a", "user": "u", "ts": 0})
        monkeypatch.setattr(ad.metrics, "anomaly_score", MagicMock())
        assert await ad.check("u", "a " * 3000) is True

    async def test_alert_swallows_errors(self):
        await ad.alert("u", "some text")  # no webhook configured — swallowed, not raised


class TestTokenRotator:
    async def test_no_token_returns_early(self, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        await trot.validate()

    def _resp(self, body):
        resp = MagicMock()
        resp.read.return_value = body
        cm = MagicMock()
        cm.__enter__.return_value = resp
        cm.__exit__.return_value = False
        return cm

    async def test_valid_token(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
        monkeypatch.setattr(
            trot.urllib.request,
            "urlopen",
            lambda *a, **k: self._resp(b'{"ok": true, "team": "T", "user": "U"}'),
        )
        await trot.validate()

    async def test_invalid_token_alerts(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
        monkeypatch.setattr(
            trot.urllib.request,
            "urlopen",
            lambda *a, **k: self._resp(b'{"ok": false, "error": "invalid_auth"}'),
        )
        monkeypatch.setattr(trot, "_alert", lambda m: None)
        await trot.validate()

    async def test_request_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
        monkeypatch.setattr(trot.urllib.request, "urlopen", MagicMock(side_effect=OSError("x")))
        await trot.validate()

    def test_alert_helper(self):
        trot._alert("a message")  # notify with no webhook → returns False, no raise
