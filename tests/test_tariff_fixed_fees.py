from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from smart_meter_web import analytics


def test_mid_month_rate_change_does_not_double_charge_fixed_fees(monkeypatch, tmp_path: Path):
    db = tmp_path / "usage.sqlite"
    monkeypatch.setattr(analytics, "DB", db)

    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE interval_usage (USAGE_DATE TEXT, USAGE_KWH TEXT, INTERVAL_STATUS TEXT)"
        )
        con.executemany(
            "INSERT INTO interval_usage VALUES (?, ?, ?)",
            [("10/01/2026", "1", "PRESENT"), ("10/15/2026", "1", "PRESENT")],
        )

    analytics.add_rate("2026-10-01", "2026-10-14", 10, 30, "Early plan")
    analytics.add_rate("2026-10-15", None, 20, 60, "New plan")

    result = analytics.cost_series()
    monthly_fee = 30 * 14 / 31 + 60 * 17 / 31
    daily_fees = sum(day["fixed_fee_applied"] for day in result["daily"])

    assert daily_fees == pytest.approx(round(monthly_fee, 2), abs=0.01)
    assert result["monthly"][0]["cost"] == pytest.approx(round(0.1 + 0.2 + monthly_fee, 2), abs=0.02)
    assert result["daily"][1]["fixed_fee_applied"] == 0
    assert analytics.cost_summary()["month_cost"] == pytest.approx(result["monthly"][0]["cost"])
