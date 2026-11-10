import asyncio
import time
from pathlib import Path

import aiosqlite

_DB_PATH = Path(__file__).parent.parent / "data" / "ratelimit.db"
_lock = asyncio.Lock()
_GLOBAL_LIMIT_PER_HOUR = 60


async def _init(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS ratelimit (
            key TEXT PRIMARY KEY,
            tokens REAL NOT NULL,
            last_refill REAL NOT NULL
        )
    """)
    await db.commit()


async def try_acquire(user_id: str, rate_per_hour: int = 10) -> bool:
    if rate_per_hour <= 0:
        return False
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    refill_rate = rate_per_hour / 3600.0

    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)

        async def _check(key: str, limit: float, rate: float) -> bool:
            async with db.execute(
                "SELECT tokens, last_refill FROM ratelimit WHERE key = ?", (key,)
            ) as cur:
                row = await cur.fetchone()
            if row:
                tokens, last_refill = row
                elapsed = now - last_refill
                tokens = min(limit, tokens + elapsed * rate)
            else:
                tokens = limit
                last_refill = now
            if tokens < 1.0:
                await db.execute(
                    "INSERT OR REPLACE INTO ratelimit (key, tokens, last_refill) VALUES (?, ?, ?)",
                    (key, tokens, now),
                )
                await db.commit()
                return False
            tokens -= 1.0
            await db.execute(
                "INSERT OR REPLACE INTO ratelimit (key, tokens, last_refill) VALUES (?, ?, ?)",
                (key, tokens, now),
            )
            await db.commit()
            return True

        # User-level
        ok = await _check(f"user:{user_id}", float(rate_per_hour), refill_rate)
        if not ok:
            return False
        # Global
        ok = await _check("global", float(_GLOBAL_LIMIT_PER_HOUR), _GLOBAL_LIMIT_PER_HOUR / 3600.0)
        return ok
