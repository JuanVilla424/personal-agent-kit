"""Coverage for core/progress.py — Slack live progress editor (async, client mocked)."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import progress as pg  # noqa: E402


def _updater(locale="en"):
    client = MagicMock()
    client.chat_update = AsyncMock()
    return pg.ProgressUpdater(client, "C1", "ts1", locale), client


class TestProgressUpdater:
    async def test_skips_when_too_soon(self):
        u, client = _updater()
        u._last_update = pg.time.monotonic()
        await u.update("text", "Tool")
        client.chat_update.assert_not_called()

    async def test_updates_spanish_resets_window(self):
        u, client = _updater("es")
        u._last_update = 0.0
        u._window_start = 0.0  # force the rate-window reset branch
        await u.update("some accumulated text", "Read", token_count=600)
        client.chat_update.assert_awaited()

    async def test_updates_english_no_tokens(self):
        u, client = _updater("en")
        u._last_update = 0.0
        await u.update("x" * 300, "", token_count=0)
        client.chat_update.assert_awaited()

    async def test_rate_limit_budget_exhausted(self):
        u, client = _updater()
        u._last_update = 0.0
        u._window_start = pg.time.monotonic()
        u._edit_count = 5
        await u.update("text", "Tool")
        client.chat_update.assert_not_called()

    async def test_slack_error_swallowed(self):
        u, client = _updater()
        u._last_update = 0.0
        client.chat_update = AsyncMock(side_effect=pg.SlackApiError("err", {}))
        await u.update("text", "Tool")  # must not raise
