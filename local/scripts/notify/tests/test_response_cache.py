import asyncio
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_cache_miss_then_hit(tmp_path, monkeypatch):
    import core.response_cache as rc

    monkeypatch.setattr(rc, "_DB_PATH", tmp_path / "cache.db")

    result = await rc.get("prompt", "session1", "model", "Read")
    assert result is None

    await rc.set("prompt", "session1", "model", "Read", "response text", ttl=3600)
    result = await rc.get("prompt", "session1", "model", "Read")
    assert result == "response text"


@pytest.mark.asyncio
async def test_cache_ttl_expired(tmp_path, monkeypatch):
    import time
    import core.response_cache as rc

    monkeypatch.setattr(rc, "_DB_PATH", tmp_path / "cache.db")

    await rc.set("p", "s", "m", "t", "r", ttl=1)
    # Mock time to be in the future
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 10)
    result = await rc.get("p", "s", "m", "t")
    assert result is None


@pytest.mark.asyncio
async def test_different_keys_no_collision(tmp_path, monkeypatch):
    import core.response_cache as rc

    monkeypatch.setattr(rc, "_DB_PATH", tmp_path / "cache.db")

    await rc.set("prompt_a", "s", "m", "t", "response_a")
    await rc.set("prompt_b", "s", "m", "t", "response_b")

    assert await rc.get("prompt_a", "s", "m", "t") == "response_a"
    assert await rc.get("prompt_b", "s", "m", "t") == "response_b"
