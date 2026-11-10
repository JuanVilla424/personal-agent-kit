"""Coverage for core/subprocess_pool.py — process pool with the spawn fn mocked."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import subprocess_pool as sp  # noqa: E402


class TestSpawnWarm:
    async def test_success(self, monkeypatch):
        proc = MagicMock(returncode=None)
        monkeypatch.setattr(sp, "_spawn", AsyncMock(return_value=proc))
        assert await sp._spawn_warm(["x"], {}) is proc

    async def test_failure(self, monkeypatch):
        monkeypatch.setattr(sp, "_spawn", AsyncMock(side_effect=OSError("x")))
        assert await sp._spawn_warm(["x"], {}) is None


class TestPoolLifecycle:
    async def test_init_acquire_release(self, monkeypatch):
        sp._pool.clear()
        proc = MagicMock(returncode=None)
        monkeypatch.setattr(sp, "_spawn", AsyncMock(return_value=proc))
        await sp.init_pool(2, ["x"], {})
        assert sp.pool_size() == 2 and sp.pool_healthy_size() == 2
        assert await sp.acquire() is proc
        await sp.release(proc)
        assert sp.pool_size() >= 1

    async def test_acquire_empty(self):
        sp._pool.clear()
        assert await sp.acquire() is None

    async def test_acquire_skips_dead(self):
        sp._pool.clear()
        sp._pool.append(MagicMock(returncode=1))
        assert await sp.acquire() is None

    async def test_release_dead_not_returned(self):
        sp._pool.clear()
        await sp.release(MagicMock(returncode=1, pid=123))
        assert sp.pool_size() == 0

    async def test_spawn_adhoc(self, monkeypatch):
        proc = MagicMock()
        monkeypatch.setattr(sp, "_spawn", AsyncMock(return_value=proc))
        assert await sp.spawn_adhoc("claude", ["--flag"], {}, "/cwd", "sysprompt") is proc
