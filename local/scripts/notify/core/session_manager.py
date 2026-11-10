import asyncio
import time
import uuid
from pathlib import Path

import aiosqlite

_DB_PATH = Path(__file__).parent.parent / "data" / "sessions.db"
_lock = asyncio.Lock()


async def _init(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            thread_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            claude_uuid TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_msg_at REAL NOT NULL,
            msg_count INTEGER NOT NULL DEFAULT 0,
            total_cost REAL NOT NULL DEFAULT 0.0
        )
    """)
    await db.commit()


async def get_or_create(thread_id: str, ttl_hours: int = 24) -> str:
    """Returns the human-readable session_id (e.g. slack-thread-<id>-<hex>).

    Use get_claude_uuid(thread_id) to get the UUID4 for --session-id.
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        async with db.execute(
            "SELECT session_id, last_msg_at FROM sessions WHERE thread_id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            session_id, last_msg_at = row
            if (now - last_msg_at) < ttl_hours * 3600:
                await db.execute(
                    "UPDATE sessions SET last_msg_at = ?, msg_count = msg_count + 1 WHERE thread_id = ?",
                    (now, thread_id),
                )
                await db.commit()
                return session_id
        session_id = f"slack-thread-{thread_id}-{uuid.uuid4().hex[:8]}"
        claude_uuid = str(uuid.uuid4())
        await db.execute(
            "INSERT OR REPLACE INTO sessions (thread_id, session_id, claude_uuid, created_at, last_msg_at, msg_count, total_cost) VALUES (?, ?, ?, ?, ?, 1, 0.0)",
            (thread_id, session_id, claude_uuid, now, now),
        )
        await db.commit()
        return session_id


async def get_claude_uuid(thread_id: str) -> str | None:
    """Returns the UUID4 to pass as --session-id to claude CLI."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        async with db.execute(
            "SELECT claude_uuid FROM sessions WHERE thread_id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None


async def get_msg_count(thread_id: str) -> int:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        async with db.execute(
            "SELECT msg_count FROM sessions WHERE thread_id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0


async def reset(thread_id: str) -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        await db.execute("DELETE FROM sessions WHERE thread_id = ?", (thread_id,))
        await db.commit()


async def add_cost(thread_id: str, cost: float) -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        await db.execute(
            "UPDATE sessions SET total_cost = total_cost + ? WHERE thread_id = ?", (cost, thread_id)
        )
        await db.commit()
