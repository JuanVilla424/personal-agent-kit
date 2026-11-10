import asyncio
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_create_session(tmp_path, monkeypatch):
    import core.session_manager as sm

    monkeypatch.setattr(sm, "_DB_PATH", tmp_path / "sessions.db")

    sid1 = await sm.get_or_create("thread_abc")
    sid2 = await sm.get_or_create("thread_abc")
    assert sid1 == sid2
    assert "slack-thread-thread_abc" in sid1


@pytest.mark.asyncio
async def test_reset_creates_new_session(tmp_path, monkeypatch):
    import core.session_manager as sm

    monkeypatch.setattr(sm, "_DB_PATH", tmp_path / "sessions.db")

    sid1 = await sm.get_or_create("thread_xyz")
    await sm.reset("thread_xyz")
    sid2 = await sm.get_or_create("thread_xyz")
    assert sid1 != sid2


@pytest.mark.asyncio
async def test_different_threads_different_sessions(tmp_path, monkeypatch):
    import core.session_manager as sm

    monkeypatch.setattr(sm, "_DB_PATH", tmp_path / "sessions.db")

    sid1 = await sm.get_or_create("thread_1")
    sid2 = await sm.get_or_create("thread_2")
    assert sid1 != sid2
