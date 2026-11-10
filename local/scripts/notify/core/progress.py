import asyncio
import time
import logging

from slack_sdk.errors import SlackApiError

log = logging.getLogger("progress")

_MIN_INTERVAL_MS = 500
_RATE_LIMIT_BUDGET = 5
_RATE_LIMIT_WINDOW = 5.0


class ProgressUpdater:
    def __init__(self, client, channel: str, ts: str, locale: str = "en") -> None:
        self._client = client
        self._channel = channel
        self._ts = ts
        self._locale = locale
        self._last_update = 0.0
        self._edit_count = 0
        self._window_start = time.monotonic()

    async def update(self, accumulated: str, tool: str, token_count: int = 0) -> None:
        now = time.monotonic()
        elapsed_ms = (now - self._last_update) * 1000
        if elapsed_ms < _MIN_INTERVAL_MS:
            return

        # Rate limit guard: max 5 edits per 5 seconds
        window_elapsed = now - self._window_start
        if window_elapsed >= _RATE_LIMIT_WINDOW:
            self._edit_count = 0
            self._window_start = now
        if self._edit_count >= _RATE_LIMIT_BUDGET:
            return

        if self._locale == "es":
            status = f"🔧 `{tool}`" if tool else "🤔 pensando"
            label = "Procesando…"
        else:
            status = f"🔧 `{tool}`" if tool else "🤔 thinking"
            label = "Processing…"

        preview = ""
        if accumulated:
            tail = accumulated[-200:] if len(accumulated) > 200 else accumulated
            preview = f"\n\n```\n…{tail}\n```"

        progress_bar = ""
        if token_count:
            estimate = max(token_count, 500)
            filled = min(10, int(token_count / estimate * 10))
            bar = "█" * filled + "░" * (10 - filled)
            progress_bar = f"\n`[{bar}]` ~{token_count} tok"

        desc = f"⏳ {label} ({status}){progress_bar}{preview}"
        try:
            await self._client.chat_update(
                channel=self._channel,
                ts=self._ts,
                text=desc[:2900],
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": desc[:2900]}}],
            )
            self._edit_count += 1
            self._last_update = now
        except SlackApiError as e:
            log.debug("Progress update Slack error: %s", e)
