"""Coverage for core/session_manager.py — uses a throwaway SQLite DB per test."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("aiosqlite")

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import session_manager as sm  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "_DB_PATH", tmp_path / "data" / "sessions.db")


async def test_session_lifecycle(db):
    sid = await sm.get_or_create("thread-1")
    assert sid.startswith("slack-thread-thread-1-")
    assert await sm.get_claude_uuid("thread-1") is not None
    assert await sm.get_msg_count("thread-1") == 1

    # reuse within ttl → same id, incremented count
    assert await sm.get_or_create("thread-1") == sid
    assert await sm.get_msg_count("thread-1") == 2

    await sm.add_cost("thread-1", 0.5)
    await sm.reset("thread-1")
    assert await sm.get_msg_count("thread-1") == 0
    assert await sm.get_claude_uuid("thread-1") is None


async def test_unknown_thread_defaults(db):
    assert await sm.get_claude_uuid("nope") is None
    assert await sm.get_msg_count("nope") == 0


async def test_expired_session_creates_new(db):
    sid = await sm.get_or_create("t2", ttl_hours=24)
    sid2 = await sm.get_or_create("t2", ttl_hours=0)  # ttl 0 → never reuse
    assert sid2 != sid
