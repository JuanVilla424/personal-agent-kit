import asyncio
import time
from pathlib import Path

import aiosqlite

_DB_PATH = Path(__file__).parent.parent / "data" / "cost.db"
_lock = asyncio.Lock()


async def _init(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS cost (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            ts REAL NOT NULL,
            query_id TEXT NOT NULL,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            tokens_in INTEGER NOT NULL DEFAULT 0,
            tokens_out INTEGER NOT NULL DEFAULT 0
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_user_ts ON cost(user_id, ts)")
    await db.commit()


async def record(
    user_id: str, query_id: str, cost_usd: float, tokens_in: int = 0, tokens_out: int = 0
) -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        await db.execute(
            "INSERT INTO cost (user_id, ts, query_id, cost_usd, tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?, ?)",
            (str(user_id), time.time(), query_id, cost_usd, tokens_in, tokens_out),
        )
        await db.commit()


async def get_user_cost(user_id: str) -> tuple[float, int]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    import calendar
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    start_of_month = datetime.datetime(
        now.year, now.month, 1, tzinfo=datetime.timezone.utc
    ).timestamp()
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        async with db.execute(
            "SELECT SUM(cost_usd), COUNT(*) FROM cost WHERE user_id = ? AND ts >= ?",
            (str(user_id), start_of_month),
        ) as cur:
            row = await cur.fetchone()
    if row and row[0]:
        return float(row[0]), int(row[1])
    return 0.0, 0


async def over_budget(user_id: str, cap_usd: float) -> tuple[bool, float, float]:
    """Return (is_over, spent_this_month, cap_usd) for a per-user monthly spend cap.

    A ``cap_usd <= 0`` disables the cap (always under). Used to refuse a request BEFORE spending
    when the user has already reached their monthly budget — the cumulative complement to the
    per-query ``decision.budget_usd`` (which only bounds a single call)."""
    if cap_usd <= 0:
        return False, 0.0, cap_usd
    spent, _count = await get_user_cost(user_id)
    return spent >= cap_usd, spent, cap_usd


async def monthly_report() -> list[dict]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    start_of_month = datetime.datetime(
        now.year, now.month, 1, tzinfo=datetime.timezone.utc
    ).timestamp()
    async with _lock, aiosqlite.connect(_DB_PATH) as db:
        await _init(db)
        async with db.execute(
            "SELECT user_id, SUM(cost_usd), COUNT(*) FROM cost WHERE ts >= ? GROUP BY user_id ORDER BY SUM(cost_usd) DESC",
            (start_of_month,),
        ) as cur:
            rows = await cur.fetchall()
    return [{"user_id": r[0], "cost_usd": r[1], "queries": r[2]} for r in rows]
