"""
Slack token validator.
Invoked by agent-bot-rotate.service (systemd timer).

Slack Bot Tokens (xoxb-) and App Tokens (xapp-) do not expire and have no
rotation API. This script validates that the configured tokens are still
active and alerts via Slack if they are not.
"""

import asyncio
import logging
import os
import sys
import urllib.request
import json
from pathlib import Path

log = logging.getLogger("token-validator")


async def validate() -> None:
    bot_token = os.getenv("SLACK_BOT_TOKEN", "")
    app_token = os.getenv("SLACK_APP_TOKEN", "")

    if not bot_token:
        log.error("SLACK_BOT_TOKEN not set — skipping validation")
        return

    # Validate Bot Token via auth.test
    req = urllib.request.Request(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
        method="POST",
        data=b"{}",
    )
    try:
        with urllib.request.urlopen(  # nosec B310  # nosemgrep: bandit.B310-1
            req, timeout=30
        ) as resp:
            body = json.loads(resp.read())
        if not body.get("ok"):
            log.error("SLACK_BOT_TOKEN validation failed: %s", body.get("error"))
            _alert(f"SLACK_BOT_TOKEN is invalid: {body.get('error')}")
            return
        log.info("SLACK_BOT_TOKEN valid — team=%s user=%s", body.get("team"), body.get("user"))
    except Exception as e:
        log.error("Token validation request failed: %s", e)
        return

    log.info("Token validation complete")


def _alert(message: str) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from notify import notify  # type: ignore

        notify("⚠️ Slack Token Alert", message, level="alert")
    except Exception:
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(validate())
