from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smart_meter_web import analytics, api, notification_settings


@pytest.fixture
def isolated(monkeypatch, tmp_path: Path):
    db = tmp_path / "private.sqlite"
    monkeypatch.setattr(analytics, "DB", db)
    monkeypatch.setattr(notification_settings, "DB", db)
    monkeypatch.setenv("SMT_WEB_AUTH_ENABLED", "false")
    return db


def test_baseline_rate_edit_preserves_periods(isolated):
    assert analytics.default_rate_settings()["cents_per_kwh"] == 15.0
    period = analytics.add_rate("2026-09-01", None, 15.0, 4.0, "Autumn")
    updated = analytics.save_default_rate_settings({"cents_per_kwh": 13.1, "monthly_fixed_fee": 1.5})
    assert updated == {"cents_per_kwh": 13.1, "monthly_fixed_fee": 1.5}
    rates = analytics.list_rates()
    assert len(rates) == 2
    assert next(x for x in rates if x["id"] == period["id"])["cents_per_kwh"] == 15.0
    assert analytics._rate_for_day("2026-10-01", rates)["cents_per_kwh"] == 15.0


def test_baseline_is_not_deletable(isolated):
    baseline = analytics.list_rates()[0]
    with pytest.raises(ValueError):
        analytics.delete_rate(baseline["id"])
    assert len(analytics.list_rates()) == 1


@pytest.mark.parametrize("bad", [
    {"cents_per_kwh": -1, "monthly_fixed_fee": 0},
    {"cents_per_kwh": 3, "monthly_fixed_fee": float("nan")},
    {"cents_per_kwh": True, "monthly_fixed_fee": 0},
])
def test_invalid_baseline_rejected(isolated, bad):
    with pytest.raises(ValueError):
        analytics.save_default_rate_settings(bad)


def test_weather_zip_coordinates_and_disabled(isolated):
    initial = analytics.weather_settings()
    assert initial["mode"] == "none"
    assert initial["zip_code"] == ""
    updated = analytics.save_weather_settings({
        "mode": "zip", "zip_code": "10002", "latitude": "", "longitude": ""
    })
    assert updated["needs_refresh"] is True
    assert analytics.weather_correlation()["points"] == []
    updated = analytics.save_weather_settings({
        "mode": "coordinates", "zip_code": "10002", "latitude": "40.75", "longitude": "-73.99"
    })
    assert updated["mode"] == "coordinates"
    assert analytics._weather_location()["latitude"] == "40.75"
    assert analytics.save_weather_settings({"mode": "none", "zip_code": "10002"})["mode"] == "none"
    assert analytics._weather_location() is None


@pytest.mark.parametrize("bad", [
    {"mode": "zip", "zip_code": "999"},
    {"mode": "coordinates", "latitude": "91", "longitude": "0"},
    {"mode": "coordinates", "latitude": "29"},
])
def test_bad_weather_locations_rejected(isolated, bad):
    with pytest.raises(ValueError):
        analytics.save_weather_settings(bad)


def test_api_settings_persist_after_reload(isolated):
    client = TestClient(api.app)
    assert client.get("/api/mvp2/default-rate").json()["cents_per_kwh"] == 15.0
    assert client.put("/api/mvp2/default-rate", json={"cents_per_kwh": 13.5, "monthly_fixed_fee": 2}).status_code == 200
    assert client.put("/api/mvp2/weather/settings", json={
        "mode": "zip", "zip_code": "10001", "latitude": "", "longitude": ""
    }).status_code == 200
    assert client.get("/api/mvp2/default-rate").json()["cents_per_kwh"] == 13.5
    assert client.get("/api/mvp2/weather/settings").json()["zip_code"] == "10001"


def test_legacy_ui_environment_variables_do_not_change_settings(monkeypatch, tmp_path: Path):
    """UI-first onboarding must work using only the core SMT/.env values."""
    db = tmp_path / "settings.sqlite"
    monkeypatch.setattr(analytics, "DB", db)
    monkeypatch.setattr(notification_settings, "DB", db)
    for key in (
        "SMT_RATE_CENTS_PER_KWH", "SMT_MONTHLY_FIXED_FEE",
        "SMT_WEATHER_ZIP", "SMT_WEATHER_LATITUDE", "SMT_WEATHER_LONGITUDE",
        "SMT_DISCORD_WEBHOOK_URL", "SMT_ANOMALY_NOTIFY_SCORE",
    ):
        monkeypatch.setenv(key, "999")

    assert analytics.default_rate_settings() == {
        "cents_per_kwh": 15.0,
        "monthly_fixed_fee": 0.0,
    }
    assert analytics.weather_settings()["mode"] == "none"
    assert analytics.weather_settings()["zip_code"] == ""
    status = notification_settings.notification_status()
    assert status["discord_configured"] is False
    assert status["anomaly_threshold"] == 3.5
    assert status["automatic_alerts_enabled"] is False

    # All three domains can subsequently be configured and persisted via UI APIs.
    analytics.save_default_rate_settings({"cents_per_kwh": 12.5, "monthly_fixed_fee": 0})
    analytics.save_weather_settings({
        "mode": "zip", "zip_code": "10001", "latitude": "", "longitude": ""
    })
    notification_settings.save_notification_settings({"anomaly_threshold": 2.5})
    assert analytics.default_rate_settings()["cents_per_kwh"] == 12.5
    assert analytics.weather_settings()["zip_code"] == "10001"
    assert notification_settings.notification_status()["anomaly_threshold"] == 2.5
