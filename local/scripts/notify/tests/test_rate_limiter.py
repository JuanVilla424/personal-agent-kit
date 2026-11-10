import asyncio
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_allows_within_limit(tmp_path, monkeypatch):
    import security.rate_limiter as rl

    monkeypatch.setattr(rl, "_DB_PATH", tmp_path / "rl.db")
    monkeypatch.setattr(rl, "_GLOBAL_LIMIT_PER_HOUR", 1000)

    ok = await rl.try_acquire("user1", rate_per_hour=10)
    assert ok


@pytest.mark.asyncio
async def test_blocks_zero_rate(tmp_path, monkeypatch):
    import security.rate_limiter as rl

    monkeypatch.setattr(rl, "_DB_PATH", tmp_path / "rl.db")

    ok = await rl.try_acquire("user2", rate_per_hour=0)
    assert not ok


@pytest.mark.asyncio
async def test_exhausts_tokens(tmp_path, monkeypatch):
    import security.rate_limiter as rl

    monkeypatch.setattr(rl, "_DB_PATH", tmp_path / "rl.db")
    monkeypatch.setattr(rl, "_GLOBAL_LIMIT_PER_HOUR", 1000)

    # Rate=2 per hour means 2 tokens total
    for _ in range(2):
        ok = await rl.try_acquire("user3", rate_per_hour=2)
        assert ok
    # 3rd should fail
    ok = await rl.try_acquire("user3", rate_per_hour=2)
    assert not ok
