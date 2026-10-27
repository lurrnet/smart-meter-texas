from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smart_meter_web import api, analytics, notification_settings as notification


WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/" + "A" * 40


@pytest.fixture
def private_settings(monkeypatch, tmp_path: Path):
    db = tmp_path / "data" / "test.sqlite"
    monkeypatch.setattr(notification, "DB", db)
    monkeypatch.setattr(analytics, "DB", db)
    monkeypatch.setenv("SMT_WEB_AUTH_ENABLED", "false")
    return db


def test_settings_save_mask_override_and_remove(private_settings):
    assert notification.notification_status()["discord_configured"] is False
    saved = notification.save_notification_settings({
        "discord_webhook_url": WEBHOOK,
        "anomaly_threshold": 2.7,
        "automatic_alerts_enabled": True,
    })
    assert saved["discord_configured"] is True
    assert saved["anomaly_threshold"] == 2.7
    assert saved["automatic_alerts_enabled"] is True
    assert WEBHOOK not in str(saved)
    assert notification.anomaly_threshold() == 2.7
    assert notification.save_notification_settings({"clear_discord_webhook": True})["discord_configured"] is False
    assert notification.notification_status()["automatic_alerts_enabled"] is False
    assert private_settings.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("bad", [
    "http://discord.com/api/webhooks/123456789012345678/AAAA",
    "https://example.org/api/webhooks/123456789012345678/AAAAAAAAAAAAAAAAAAAA",
    "https://discord.com.evil.org/api/webhooks/123456789012345678/AAAAAAAAAAAAAAAAAAAA",
    "https://discord.com/api/webhooks/123456789012345678/AAAAAAAAAAAAAAAAAAAA?wait=true",
])
def test_rejects_webhook_ssrf(private_settings, bad):
    with pytest.raises(ValueError):
        notification.save_notification_settings({"discord_webhook_url": bad})


def test_threshold_rejects_invalid_and_controls_detection(private_settings, monkeypatch):
    for value in (0, 0.5, 11, float("nan"), "invalid"):
        with pytest.raises(ValueError):
            notification.save_notification_settings({"anomaly_threshold": value})
    samples = [{"date": f"2026-01-{n:02d}", "kwh": (40 + n % 4)} for n in range(1, 30)]
    samples.append({"date": "2026-01-30", "kwh": 46})
    monkeypatch.setattr(analytics, "_daily_usage", lambda: samples)
    baseline = analytics.anomalies()
    assert baseline["anomaly_threshold"] == 3.5
    notification.save_notification_settings({"anomaly_threshold": 2})
    assert analytics.anomalies()["anomaly_threshold"] == 2.0
    assert len(analytics.anomalies()["items"]) >= len(baseline["items"])


def test_api_routes_never_expose_secret(private_settings, monkeypatch):
    client = TestClient(api.app)
    response = client.put("/api/mvp2/notifications/settings", json={
        "discord_webhook_url": WEBHOOK, "automatic_alerts_enabled": True
    })
    assert response.status_code == 200
    assert WEBHOOK not in response.text
    assert client.get("/api/mvp2/notifications").json()["discord_configured"] is True
    assert WEBHOOK not in client.get("/api/mvp2/notifications").text
    assert client.put("/api/mvp2/notifications/settings", json={"anomaly_threshold": 20}).status_code == 400


def test_discord_test_does_not_expose_error_or_follow_redirect(private_settings, monkeypatch):
    notification.save_notification_settings({"discord_webhook_url": WEBHOOK})
    def failure(*args, **kwargs):
        raise RuntimeError(WEBHOOK)
    monkeypatch.setattr(notification, "_post_discord", failure)
    output = notification.send_discord_test()
    assert output["ok"] is False
    assert WEBHOOK not in str(output)


def test_automatic_alert_deduplicates(private_settings, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    day = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
    notification.save_notification_settings({"discord_webhook_url": WEBHOOK, "automatic_alerts_enabled": True})
    monkeypatch.setattr(analytics, "_daily_usage", lambda: [{"date": day, "kwh": 105.0}] * 16)
    monkeypatch.setattr(analytics, "anomalies", lambda: {"items": [{"date": day, "kwh": 105.0, "score": 4.5, "direction": "high"}]})
    sent = []
    monkeypatch.setattr(notification, "_post_discord", lambda url, message: sent.append(message))
    assert notification.maybe_notify_latest_anomaly()["status"] == "sent"
    assert notification.maybe_notify_latest_anomaly()["status"] == "already_sent"
    assert len(sent) == 1


def test_automatic_alerts_disabled_by_default(private_settings):
    assert notification.maybe_notify_latest_anomaly()["status"] == "disabled"
    with pytest.raises(ValueError):
        notification.save_notification_settings({"automatic_alerts_enabled": True})
