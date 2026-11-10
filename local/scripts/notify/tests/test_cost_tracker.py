"""Coverage for ops/cost_tracker.py — SQLite cost ledger (throwaway DB per test)."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("aiosqlite")

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops import cost_tracker as ct  # noqa: E402


@pytest.fixture
def costdb(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "_DB_PATH", tmp_path / "data" / "cost.db")


async def test_record_and_get_user_cost(costdb):
    await ct.record("u1", "q1", 0.5, 100, 200)
    await ct.record("u1", "q2", 0.3, 50, 60)
    cost, n = await ct.get_user_cost("u1")
    assert round(cost, 2) == 0.8 and n == 2


async def test_get_user_cost_empty(costdb):
    cost, n = await ct.get_user_cost("nobody")
    assert cost == 0.0 and n == 0


async def test_monthly_report_ordered(costdb):
    await ct.record("u1", "q1", 0.5)
    await ct.record("u2", "q2", 1.0)
    report = await ct.monthly_report()
    assert len(report) == 2
    assert report[0]["cost_usd"] >= report[1]["cost_usd"]


async def test_over_budget_under_when_no_spend(costdb):
    over, spent, cap = await ct.over_budget("u1", 50.0)
    assert over is False
    assert spent == 0.0
    assert cap == 50.0


async def test_over_budget_when_spend_reaches_cap(costdb):
    await ct.record("u1", "q1", 30.0)
    await ct.record("u1", "q2", 25.0)  # 55 >= 50
    over, spent, _cap = await ct.over_budget("u1", 50.0)
    assert over is True
    assert round(spent, 2) == 55.0


async def test_over_budget_cap_zero_disables(costdb):
    await ct.record("u1", "q1", 1000.0)
    over, _spent, _cap = await ct.over_budget("u1", 0.0)
    assert over is False


async def test_over_budget_is_per_user(costdb):
    await ct.record("u1", "q1", 60.0)
    over, spent, _cap = await ct.over_budget("u2", 50.0)
    assert over is False
    assert spent == 0.0
