"""
Slack slash command handlers.
Registered in bot.py via register_slash_commands(app, bot).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import PartyBot

log = logging.getLogger("slash-commands")


def register_slash_commands(app, bot: "PartyBot") -> None:
    """Register all /party-* slash commands on the slack_bolt AsyncApp."""

    @app.command("/party-ask")
    async def ask(ack, body, say):
        await ack()
        query = body.get("text", "").strip()
        if not query:
            await say("Usage: `/party-ask <your question>`")
            return
        channel_id = body["channel_id"]
        user_id = body["user_id"]
        await bot.handle_query(
            client=app.client,
            channel_id=channel_id,
            user_id=user_id,
            content=query,
            reply_to_ts=None,
            locale="en",
            files=[],
        )

    @app.command("/party-agent")
    async def agent(ack, body, say):
        await ack()
        text = body.get("text", "").strip()
        if not text:
            await say("Usage: `/party-agent <Agent> <question>`")
            return
        channel_id = body["channel_id"]
        user_id = body["user_id"]
        await bot.handle_query(
            client=app.client,
            channel_id=channel_id,
            user_id=user_id,
            content=text,
            reply_to_ts=None,
            locale="en",
            files=[],
        )

    @app.command("/party-status")
    async def status(ack, respond):
        await ack()
        from core import thread_manager, subprocess_pool
        from core.i18n import t

        uptime = int(time.monotonic() - bot.start_time)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        text = t(
            "status_report",
            locale="en",
            pool_free=subprocess_pool.pool_healthy_size(),
            pool_size=subprocess_pool.pool_size(),
            threads=thread_manager.active_thread_count(),
            queue=0,
            uptime=f"{h}h{m}m{s}s",
        )
        await respond({"response_type": "ephemeral", "text": text})

    @app.command("/party-cancel")
    async def cancel(ack, respond, body):
        await ack()
        user_id = body["user_id"]
        proc = bot.active_procs.get(user_id)
        if proc and proc.returncode is None:
            proc.terminate()
            del bot.active_procs[user_id]
            await respond({"response_type": "ephemeral", "text": "❌ Query canceled."})
        else:
            await respond({"response_type": "ephemeral", "text": "You have no active query."})

    @app.command("/party-reset")
    async def reset(ack, respond, body):
        await ack()
        from core import session_manager

        channel_id = body["channel_id"]
        await session_manager.reset(channel_id)
        await respond({"response_type": "ephemeral", "text": "🔄 Session reset."})

    @app.command("/party-cost")
    async def cost(ack, respond, body):
        await ack()
        from ops.cost_tracker import get_user_cost
        from core.i18n import t

        user_id = body["user_id"]
        cost_val, queries = await get_user_cost(user_id)
        text = t("cost_report", locale="en", cost=cost_val, queries=queries)
        await respond({"response_type": "ephemeral", "text": text})
