import asyncio
import hashlib
import json
import time
from pathlib import Path

import aiosqlite

_DB_PATH = Path(__file__).parent.parent / "data" / "cache.db"
_lock = asyncio.Lock()
_MAX_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


async def _init(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            response TEXT NOT NULL,
            created_at REAL NOT NULL,
            ttl_seconds INTEGER NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    await db.commit()


def _make_key(prompt: str, session_id: str, model: str, tools: str) -> str:
    raw = json.dumps({"p": prompt, "s": session_id, "m": model, "t": tools}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


async def get(prompt: str, session_id: str, model: str, tools: str) -> str | None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = _make_key(prompt, session_id, model, tools)
    now = time.time()
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        async with db.execute(
            "SELECT response, created_at, ttl_seconds FROM cache WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        response, created_at, ttl = row
        if now - created_at > ttl:
            await db.execute("DELETE FROM cache WHERE key = ?", (key,))
            await db.commit()
            return None
        await db.execute("UPDATE cache SET hit_count = hit_count + 1 WHERE key = ?", (key,))
        await db.commit()
        return response


async def set(
    prompt: str, session_id: str, model: str, tools: str, response: str, ttl: int = 3600
) -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = _make_key(prompt, session_id, model, tools)
    now = time.time()
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        await db.execute(
            "INSERT OR REPLACE INTO cache (key, response, created_at, ttl_seconds) VALUES (?, ?, ?, ?)",
            (key, response, now, ttl),
        )
        # LRU eviction by size approximation
        async with db.execute("SELECT SUM(LENGTH(response)) FROM cache") as cur:
            row = await cur.fetchone()
        if row and row[0] and row[0] > _MAX_SIZE_BYTES:
            await db.execute(
                "DELETE FROM cache WHERE key IN (SELECT key FROM cache ORDER BY created_at ASC LIMIT 50)"
            )
        await db.commit()
