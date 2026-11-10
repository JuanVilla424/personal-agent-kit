"""
Slack interactive elements: cancel button, agent selector, TOTP prompt.

Note: Slack interactive elements require Block Kit action handlers registered
on the app. Buttons are posted as message blocks and handled via @app.action().
"""

from __future__ import annotations

import logging
from typing import Callable, Awaitable

log = logging.getLogger("interactive")


async def attach_cancel_button(
    client,
    channel_id: str,
    ts: str,
    user_id: str,
    on_cancel: Callable[[], Awaitable[None]],
) -> None:
    """Update a processing message to include a Cancel button block.

    The cancel action is handled by @app.action("cancel_query") registered in bot.py,
    which calls the on_cancel callback stored in bot._pending_cancels[user_id].
    """
    try:
        await client.chat_update(
            channel=channel_id,
            ts=ts,
            text="⏳ Processing…",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "⏳ Processing your query…"},
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ Cancel"},
                            "style": "danger",
                            "action_id": "cancel_query",
                            "value": user_id,
                        }
                    ],
                },
            ],
        )
    except Exception as e:
        log.debug("attach_cancel_button: %s", e)
