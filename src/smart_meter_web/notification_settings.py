"""Private notification settings and opt-in Discord anomaly alerts.

Settings are stored exclusively in the existing SQLite database shared by
the web and scheduler containers; no legacy environment variable fallback
is used for Discord or anomaly threshold settings.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("SMT_PROJECT_ROOT", "/app"))
DB = ROOT / "data" / "smt_interval_usage_history.sqlite"

DEFAULT_THRESHOLD = 3.5
MIN_THRESHOLD = 1.0
MAX_THRESHOLD = 10.0

_WEBHOOK_PATH = re.compile(r"/api/webhooks/[0-9]{15,25}/[A-Za-z0-9_-]{20,}", re.ASCII)


def _connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    # Creating the file explicitly ensures that the webhook is not stored in
    # a world-readable SQLite file even when the process umask is permissive.
    DB.touch(mode=0o600, exist_ok=True)
    if os.name == "posix":
        DB.chmod(0o600)
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables() -> None:
    with _connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS application_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS anomaly_notification_deliveries (
                usage_date TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                score REAL NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        con.commit()


def _saved_settings() -> dict[str, str]:
    _ensure_tables()
    with _connect() as con:
        return {
            row["setting_key"]: row["setting_value"]
            for row in con.execute("SELECT setting_key, setting_value FROM application_settings")
        }


def _webhook_url(settings: dict[str, str]) -> str:
    return settings.get("discord_webhook_url", "")


def _threshold(settings: dict[str, str]) -> float:
    raw = settings.get("anomaly_threshold", str(DEFAULT_THRESHOLD))
    try:
        score = float(raw)
    except (ValueError, TypeError):
        return DEFAULT_THRESHOLD
    if not math.isfinite(score) or not MIN_THRESHOLD <= score <= MAX_THRESHOLD:
        return DEFAULT_THRESHOLD
    return score


def anomaly_threshold() -> float:
    return _threshold(_saved_settings())


def _enabled(settings: dict[str, str]) -> bool:
    return settings.get("automatic_alerts_enabled", "false").lower() in {"true", "1", "yes", "on"}


def _valid_discord_webhook(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname in {"discord.com", "discordapp.com"}
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and _WEBHOOK_PATH.fullmatch(parsed.path)
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def notification_status() -> dict:
    settings = _saved_settings()
    url = _webhook_url(settings)
    with _connect() as con:
        last = con.execute(
            "SELECT usage_date, timestamp FROM anomaly_notification_deliveries "
            "WHERE state = 'sent' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    return {
        # Never send the URL (which is a bearer credential) to the browser.
        "discord_configured": bool(url) and _valid_discord_webhook(url),
        "webhook_source": "web_ui" if url else None,
        "anomaly_threshold": _threshold(settings),
        "automatic_alerts_enabled": _enabled(settings),
        "last_notification_date": last["usage_date"] if last else None,
        "last_notification_at": last["timestamp"] if last else None,
    }


def save_notification_settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Settings must be a JSON object.")
    current = _saved_settings()
    updates: dict[str, str] = {}

    if "anomaly_threshold" in payload:
        raw = payload["anomaly_threshold"]
        if isinstance(raw, bool):
            raise ValueError("Anomaly threshold must be a number.")
        try:
            score = float(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError("Anomaly threshold must be a number.") from exc
        if not math.isfinite(score) or not MIN_THRESHOLD <= score <= MAX_THRESHOLD:
            raise ValueError("Anomaly threshold must be between 1.0 and 10.0.")
        updates["anomaly_threshold"] = str(score)

    if "automatic_alerts_enabled" in payload:
        enabled = payload["automatic_alerts_enabled"]
        if not isinstance(enabled, bool):
            raise ValueError("Automatic alerts must be true or false.")
        updates["automatic_alerts_enabled"] = "true" if enabled else "false"

    if "discord_webhook_url" in payload:
        supplied = payload["discord_webhook_url"]
        if not isinstance(supplied, str):
            raise ValueError("Discord webhook must be a URL.")
        if supplied.strip():
            if not _valid_discord_webhook(supplied.strip()):
                raise ValueError("Only a valid HTTPS Discord webhook URL can be saved.")
            updates["discord_webhook_url"] = supplied.strip()

    if "clear_discord_webhook" in payload:
        if payload["clear_discord_webhook"] is not True:
            raise ValueError("clear_discord_webhook must be true.")
        if "discord_webhook_url" in updates:
            raise ValueError("Cannot replace and remove a webhook in the same request.")
        updates["discord_webhook_url"] = ""
        updates["automatic_alerts_enabled"] = "false"

    effective = dict(current)
    effective.update(updates)
    if _enabled(effective) and not _valid_discord_webhook(_webhook_url(effective)):
        raise ValueError("Configure a valid Discord webhook before enabling automatic alerts.")

    if updates:
        with _connect() as con:
            con.executemany(
                "INSERT INTO application_settings (setting_key, setting_value) VALUES (?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                list(updates.items()),
            )
            con.commit()
    return notification_status()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Do not follow a Discord redirect to another HTTP destination.
        return None


def _post_discord(url: str, message: str) -> None:
    if not _valid_discord_webhook(url):
        raise ValueError("Invalid Discord webhook configuration.")
    body = json.dumps({
        "content": message,
        "allowed_mentions": {"parse": []},
    }).encode("utf-8")
    request = Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "smart-meter-texas/0.2"},
        method="POST",
    )
    opener = build_opener(_NoRedirect())
    with opener.open(request, timeout=15) as response:
        response.read()


def send_discord_test() -> dict:
    url = _webhook_url(_saved_settings())
    if not url:
        return {"ok": False, "message": "Configure a Discord webhook before sending a test."}
    if not _valid_discord_webhook(url):
        return {"ok": False, "message": "The configured Discord webhook URL is invalid."}
    try:
        _post_discord(url, "Smart Meter Texas notification test: the connection is working.")
    except Exception:
        # Never reflect upstream errors; they may include the secret URL.
        return {"ok": False, "message": "Discord delivery failed. Check the webhook and network."}
    return {"ok": True, "message": "Test notification sent."}


def maybe_notify_latest_anomaly() -> dict:
    """Notify only on a fresh latest day after a successful scheduled/manual sync.

    One notification is sent at most once per usage day; historical alerts
    are not replayed on startup or when thresholds change. Failed sends can
    be retried by a subsequent sync.
    """
    settings = _saved_settings()
    if not _enabled(settings):
        return {"status": "disabled"}
    url = _webhook_url(settings)
    if not url or not _valid_discord_webhook(url):
        return {"status": "not_configured"}

    # Delayed import avoids a cycle: analytics uses anomaly_threshold().
    from smart_meter_web.analytics import _daily_usage, anomalies

    usage = _daily_usage()
    if len(usage) < 15:
        return {"status": "insufficient_history"}
    last_day = usage[-1]["date"]
    try:
        today = datetime.now(ZoneInfo(os.environ.get("SMT_TIMEZONE", "America/Chicago"))).date()
        lag_days = (today - date.fromisoformat(last_day)).days
    except (ValueError, KeyError):
        return {"status": "invalid_date"}
    if lag_days < 0 or lag_days > 2:
        return {"status": "stale_data"}

    findings = anomalies()
    latest = next((item for item in findings["items"] if item["date"] == last_day), None)
    if latest is None:
        return {"status": "no_anomaly"}

    stamp = datetime.now(ZoneInfo(os.environ.get("SMT_TIMEZONE", "America/Chicago"))).isoformat()
    with _connect() as con:
        reserved = con.execute(
            "INSERT OR IGNORE INTO anomaly_notification_deliveries "
            "(usage_date, state, score, timestamp) VALUES (?, 'sending', ?, ?)",
            (last_day, latest["score"], stamp),
        ).rowcount
        con.commit()
    if reserved != 1:
        return {"status": "already_sent"}

    direction = "higher" if latest["score"] > 0 else "lower"
    message = (
        "Smart Meter Texas usage anomaly: "
        f"{last_day} recorded {latest['kwh']:.2f} kWh, "
        f"{direction} than normal (modified Z-score {latest['score']:+.2f}; "
        f"threshold ±{_threshold(settings):g}). "
        "This is a statistical deviation, not a confirmed equipment fault."
    )
    try:
        _post_discord(url, message)
    except Exception:
        with _connect() as con:
            con.execute(
                "DELETE FROM anomaly_notification_deliveries "
                "WHERE usage_date = ? AND state = 'sending'", (last_day,)
            )
            con.commit()
        return {"status": "delivery_failed"}

    with _connect() as con:
        con.execute(
            "UPDATE anomaly_notification_deliveries SET state='sent', timestamp=? "
            "WHERE usage_date=? AND state='sending'", (stamp, last_day)
        )
        con.commit()
    return {"status": "sent"}
