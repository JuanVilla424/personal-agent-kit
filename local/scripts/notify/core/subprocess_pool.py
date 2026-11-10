import asyncio
import logging
import os
from pathlib import Path

log = logging.getLogger("subprocess-pool")

_spawn = asyncio.create_subprocess_exec

_pool: list[asyncio.subprocess.Process] = []
_lock = asyncio.Lock()
_MAX_USES = 20


async def _spawn_warm(cmd: list[str], env: dict) -> asyncio.subprocess.Process | None:
    try:
        proc = await _spawn(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        return proc
    except Exception as e:
        log.warning("Pool warm spawn failed: %s", e)
        return None


async def init_pool(size: int, cmd: list[str], env: dict) -> None:
    async with _lock:
        for _ in range(size):
            proc = await _spawn_warm(cmd, env)
            if proc:
                _pool.append(proc)
    log.info("Pool initialized: %d/%d processes", len(_pool), size)


async def acquire() -> asyncio.subprocess.Process | None:
    async with _lock:
        while _pool:
            proc = _pool.pop(0)
            if proc.returncode is None:
                return proc
    return None


async def release(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        async with _lock:
            _pool.append(proc)
    else:
        log.debug("Process %d already exited, not returning to pool", proc.pid)


async def spawn_adhoc(
    claude_bin: str,
    base_flags: list[str],
    env: dict,
    cwd: str,
    system_prompt: str,
) -> asyncio.subprocess.Process:
    cmd = (
        [
            claude_bin,
            "-p",
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
        ]
        + base_flags
        + ["--system-prompt", system_prompt]
    )
    return await _spawn(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )


def pool_size() -> int:
    return len(_pool)


def pool_healthy_size() -> int:
    return sum(1 for p in _pool if p.returncode is None)
