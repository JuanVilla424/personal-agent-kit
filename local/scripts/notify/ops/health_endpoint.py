"""FastAPI health endpoint at :9091/health."""

import asyncio
import logging
import os
import threading
import time

import uvicorn
from fastapi import FastAPI, Response

log = logging.getLogger("health")

_app = FastAPI(title="agent-bot health")
_bot_state: dict = {"ready": False, "start_time": time.monotonic()}


def set_ready(ready: bool) -> None:
    _bot_state["ready"] = ready


def get_state() -> dict:
    return _bot_state


@_app.get("/health")
async def health():
    from core import thread_manager, subprocess_pool

    uptime = int(time.monotonic() - _bot_state.get("start_time", time.monotonic()))
    payload = {
        "status": "ok" if _bot_state.get("ready") else "starting",
        "uptime_seconds": uptime,
        "slack_ready": _bot_state.get("ready", False),
        "pool_size": subprocess_pool.pool_size(),
        "pool_healthy": subprocess_pool.pool_healthy_size(),
        "threads_active": thread_manager.active_thread_count(),
    }
    code = 200 if _bot_state.get("ready") else 503
    return Response(
        content=__import__("json").dumps(payload), media_type="application/json", status_code=code
    )


@_app.get("/ready")
async def ready():
    if not _bot_state.get("ready"):
        return Response(status_code=503, content="not ready")
    return Response(status_code=200, content="ok")


@_app.get("/version")
async def version():
    import subprocess

    try:
        sha = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], timeout=3)
            .decode()
            .strip()
        )
    except Exception:
        sha = "unknown"
    return {"version": sha}


def start(port: int = 9091) -> None:
    config = uvicorn.Config(_app, host="0.0.0.0", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    log.info("Health endpoint at :%d/health", port)
