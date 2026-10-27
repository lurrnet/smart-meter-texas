from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from smart_meter_web.notification_settings import anomaly_threshold

ROOT = Path(os.environ.get("SMT_PROJECT_ROOT", "/app"))
DB = ROOT / "data" / "smt_interval_usage_history.sqlite"

# Defaults are application constants. The Web UI owns the persisted settings.
DEFAULT_RATE_CENTS_PER_KWH = 15.0
DEFAULT_MONTHLY_FIXED_FEE = 0.0


def _connect():
    con = sqlite3.connect(DB)
    if os.name == "posix":
        DB.chmod(0o600)
    con.row_factory = sqlite3.Row
    return con


def _daily_usage():
    if not DB.exists():
        return []
    with _connect() as con:
        has_intervals = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='interval_usage'"
        ).fetchone()
        if not has_intervals:
            return []
        rows = con.execute("""
          SELECT date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2)) date,
                 SUM(CAST(NULLIF(USAGE_KWH,'') AS REAL)) kwh
          FROM interval_usage
          WHERE INTERVAL_STATUS <> 'MISSING'
          GROUP BY date ORDER BY date
        """).fetchall()
    return [{"date": r["date"], "kwh": float(r["kwh"] or 0)} for r in rows]



def _validate_rate(cents: float, fixed: float) -> tuple[float, float]:
    cents, fixed = float(cents), float(fixed)
    if not math.isfinite(cents) or not 0 <= cents <= 1000:
        raise ValueError("Rate must be between 0 and 1000 cents/kWh.")
    if not math.isfinite(fixed) or not 0 <= fixed <= 100000:
        raise ValueError("Monthly fixed fee must be between 0 and 100000 dollars.")
    return cents, fixed


def _rate_table():
    with _connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS electricity_rates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          start_date TEXT NOT NULL,
          end_date TEXT,
          cents_per_kwh REAL NOT NULL,
          monthly_fixed_fee REAL NOT NULL DEFAULT 0,
          label TEXT
        )""")
        # The baseline is a real rate period; retain additional historical
        # periods and avoid rewriting past rates when adjusting the baseline.
        existing = con.execute(
            "SELECT id FROM electricity_rates WHERE start_date='1900-01-01' ORDER BY id LIMIT 1"
        ).fetchone()
        if not existing:
            con.execute(
                "INSERT INTO electricity_rates (start_date, end_date, cents_per_kwh, monthly_fixed_fee, label) VALUES (?,?,?,?,?)",
                ("1900-01-01", None, DEFAULT_RATE_CENTS_PER_KWH, DEFAULT_MONTHLY_FIXED_FEE, "Default rate"),
            )
        con.commit()


def default_rate_settings() -> dict:
    _rate_table()
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM electricity_rates WHERE start_date='1900-01-01' ORDER BY id LIMIT 1"
        ).fetchone()
    return {"cents_per_kwh": row["cents_per_kwh"], "monthly_fixed_fee": row["monthly_fixed_fee"]}


def save_default_rate_settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Settings must be an object.")
    if "cents_per_kwh" not in payload or "monthly_fixed_fee" not in payload:
        raise ValueError("Both rate and monthly fixed fee are required.")
    if any(isinstance(payload[key], bool) or payload[key] is None for key in ("cents_per_kwh", "monthly_fixed_fee")):
        raise ValueError("Rate and fee must be numbers.")
    try:
        cents, fixed = _validate_rate(payload["cents_per_kwh"], payload["monthly_fixed_fee"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Provide valid nonnegative rate and monthly fee.") from exc
    _rate_table()
    with _connect() as con:
        con.execute(
            "UPDATE electricity_rates SET cents_per_kwh=?, monthly_fixed_fee=? WHERE id=("
            "SELECT id FROM electricity_rates WHERE start_date='1900-01-01' ORDER BY id LIMIT 1)",
            (cents, fixed),
        )
        con.commit()
    return default_rate_settings()


def list_rates():
    _rate_table()
    with _connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM electricity_rates ORDER BY start_date, id").fetchall()]


def add_rate(start_date: str, end_date: str | None, cents_per_kwh: float, monthly_fixed_fee: float = 0, label: str = ""):
    date.fromisoformat(start_date)
    if end_date:
        date.fromisoformat(end_date)
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
    _validate_rate(cents_per_kwh, monthly_fixed_fee)
    if start_date == "1900-01-01":
        raise ValueError("Edit the baseline rate using Default Rate Settings.")
    _rate_table()
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO electricity_rates (start_date, end_date, cents_per_kwh, monthly_fixed_fee, label) VALUES (?,?,?,?,?)",
            (start_date, end_date or None, float(cents_per_kwh), float(monthly_fixed_fee or 0), label.strip() or None),
        )
        con.commit()
        return {"id": cur.lastrowid}


def delete_rate(rate_id: int):
    _rate_table()
    with _connect() as con:
        baseline = con.execute("SELECT id FROM electricity_rates WHERE id=? AND start_date='1900-01-01'", (rate_id,)).fetchone()
        if baseline:
            raise ValueError("Edit the default rate instead of deleting it.")
        con.execute("DELETE FROM electricity_rates WHERE id = ?", (rate_id,))
        con.commit()
    return {"ok": True}


def _rate_for_day(day: str, rates: list[dict]):
    matches = [
        r for r in rates
        if r["start_date"] <= day and (not r["end_date"] or day <= r["end_date"])
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda r: (r["start_date"], r["id"]))[-1]


def _fixed_fee_for_month(month: str, rates: list[dict]) -> float:
    """Estimate one monthly fixed fee, prorating across any tariff changes.

    The daily series allocates this complete monthly fee to the first
    recorded usage day to avoid double-charging when tariffs change.
    """
    first_day = date.fromisoformat(f"{month}-01")
    next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
    days = (next_month - first_day).days
    fallback_fixed = rate_config()["monthly_fixed_fee"]
    total_fixed = 0.0
    for offset in range(days):
        applicable_day = (first_day + timedelta(days=offset)).isoformat()
        rate = _rate_for_day(applicable_day, rates)
        fixed = float(rate["monthly_fixed_fee"] or 0) if rate else fallback_fixed
        total_fixed += fixed / days
    return total_fixed


def cost_series():
    usage = _daily_usage()
    rates = list_rates()
    baseline = next(rate for rate in rates if rate["start_date"] == "1900-01-01")
    daily = []
    monthly = {}
    fixed_seen = set()
    for item in usage:
        rate = _rate_for_day(item["date"], rates)
        cents = float(rate["cents_per_kwh"]) if rate else float(baseline["cents_per_kwh"])
        variable_cost = item["kwh"] * cents / 100
        month = item["date"][:7]
        fixed = 0.0
        if month not in fixed_seen:
            fixed = _fixed_fee_for_month(month, rates)
            fixed_seen.add(month)
        total_cost = variable_cost + fixed
        daily.append({
            "date": item["date"],
            "kwh": round(item["kwh"], 3),
            "rate_cents": round(cents, 4),
            "variable_cost": round(variable_cost, 4),
            "fixed_fee_applied": round(fixed, 2),
            "cost": round(total_cost, 4),
            "rate_label": rate.get("label") if rate else "Fallback",
        })
        bucket = monthly.setdefault(month, {"month": month, "kwh": 0.0, "cost": 0.0})
        bucket["kwh"] += item["kwh"]
        bucket["cost"] += total_cost
    monthly_rows = [
        {"month": m["month"], "kwh": round(m["kwh"], 2), "cost": round(m["cost"], 2)}
        for m in monthly.values()
    ]
    return {"daily": daily, "monthly": monthly_rows, "rates": rates}


def rate_config():
    return default_rate_settings()


def cost_summary():
    data = _daily_usage()
    if not data:
        return {"rate": rate_config(), "month_kwh": 0, "month_cost": 0, "projected_cost": 0}
    series = cost_series()
    latest = date.fromisoformat(data[-1]["date"])
    month = latest.strftime("%Y-%m")
    month_rows = [x for x in series["daily"] if x["date"].startswith(month)]
    kwh = sum(x["kwh"] for x in month_rows)
    month_cost = sum(x["cost"] for x in month_rows)
    days_elapsed = latest.day
    next_month = (latest.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_in_month = (next_month - timedelta(days=1)).day
    projected_kwh = kwh / max(days_elapsed, 1) * days_in_month
    latest_rate = _rate_for_day(latest.isoformat(), series["rates"])
    cents = float(latest_rate["cents_per_kwh"]) if latest_rate else rate_config()["cents_per_kwh"]
    fixed = _fixed_fee_for_month(month, series["rates"])
    return {
        "rate": {"cents_per_kwh": cents, "monthly_fixed_fee": fixed},
        "month": month,
        "month_kwh": round(kwh, 2),
        "month_cost": round(month_cost, 2),
        "projected_kwh": round(projected_kwh, 2),
        "projected_cost": round(projected_kwh * cents / 100 + fixed, 2),
    }


def _weather_table():
    with _connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS weather_daily (
          weather_date TEXT PRIMARY KEY,
          temp_mean_f REAL, temp_max_f REAL, temp_min_f REAL,
          apparent_mean_f REAL, humidity_mean REAL, precipitation_in REAL,
          fetched_at TEXT NOT NULL
        )""")
        con.commit()


def _weather_preferences() -> dict:
    from smart_meter_web.notification_settings import _saved_settings
    saved = _saved_settings()
    source = saved.get("weather_location_source", "none")
    if source not in {"none", "zip", "coordinates"}:
        source = "none"
    return {
        "source": source,
        "zip_code": saved.get("weather_zip", ""),
        "latitude": saved.get("weather_latitude", ""),
        "longitude": saved.get("weather_longitude", ""),
        "revision": saved.get("weather_revision", ""),
        "refreshed_revision": saved.get("weather_refreshed_revision", ""),
    }


def weather_settings() -> dict:
    p = _weather_preferences()
    active = p["source"]
    return {
        "mode": active, "zip_code": p["zip_code"],
        "latitude": p["latitude"], "longitude": p["longitude"],
        "needs_refresh": bool(p["revision"] and p["revision"] != p["refreshed_revision"]),
    }


def save_weather_settings(payload: dict) -> dict:
    import re
    import uuid
    if not isinstance(payload, dict):
        raise ValueError("Settings must be an object.")
    mode = payload.get("mode")
    if mode not in {"zip", "coordinates", "none"}:
        raise ValueError("Select ZIP code, coordinates, or disabled.")
    zip_code = str(payload.get("zip_code") or "").strip()
    if zip_code and not re.fullmatch(r"\d{5}", zip_code):
        raise ValueError("ZIP code must contain exactly five digits.")
    lat_text = str(payload.get("latitude") if payload.get("latitude") is not None else "").strip()
    lon_text = str(payload.get("longitude") if payload.get("longitude") is not None else "").strip()
    if bool(lat_text) != bool(lon_text):
        raise ValueError("Enter both latitude and longitude.")
    if lat_text:
        try:
            lat, lon = float(lat_text), float(lon_text)
        except ValueError as exc:
            raise ValueError("Coordinates must be numeric.") from exc
        if not (math.isfinite(lat) and -90 <= lat <= 90 and math.isfinite(lon) and -180 <= lon <= 180):
            raise ValueError("Latitude must be -90..90; longitude -180..180.")
    if mode == "zip" and not zip_code:
        raise ValueError("Enter a valid five-digit ZIP code.")
    if mode == "coordinates" and not lat_text:
        raise ValueError("Enter latitude and longitude.")
    from smart_meter_web.notification_settings import _connect, _ensure_tables
    old = weather_settings()
    changed = old["mode"] != mode or (mode == "zip" and old["zip_code"] != zip_code) or (
        mode == "coordinates" and (old["latitude"] != lat_text or old["longitude"] != lon_text)
    )
    updates = {
        "weather_location_source": mode,
        "weather_zip": zip_code,
        "weather_latitude": lat_text,
        "weather_longitude": lon_text,
    }
    if changed:
        updates["weather_revision"] = uuid.uuid4().hex
    _ensure_tables()
    with _connect() as con:
        con.executemany(
            "INSERT INTO application_settings (setting_key, setting_value) VALUES (?,?) "
            "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
            list(updates.items()),
        )
        con.commit()
    return weather_settings()


def _weather_location():
    p = _weather_preferences()
    mode = weather_settings()["mode"]
    if mode == "none":
        return None
    if mode == "coordinates":
        return {"latitude": p["latitude"], "longitude": p["longitude"], "source": "coordinates"}
    zip_code = p["zip_code"]
    if not zip_code:
        return None

    params = {"name": zip_code, "count": 10, "language": "en", "format": "json", "countryCode": "US"}
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "smart-meter-texas/0.2"})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    results = payload.get("results") or []
    if not results:
        return None
    match = results[0]
    return {
        "latitude": str(match["latitude"]), "longitude": str(match["longitude"]),
        "source": "zip", "zip": zip_code, "name": match.get("name"), "admin1": match.get("admin1"),
    }


def refresh_weather():
    location = _weather_location()
    if not location:
        return {"configured": False, "message": "Configure weather location in Weather & HVAC settings."}
    latitude = location["latitude"]
    longitude = location["longitude"]
    usage = _daily_usage()
    if not usage:
        return {"configured": True, "rows": 0}
    start = usage[0]["date"]
    end = usage[-1]["date"]
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_mean,temperature_2m_max,temperature_2m_min,apparent_temperature_mean,relative_humidity_2m_mean,precipitation_sum",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": os.environ.get("SMT_TIMEZONE", "America/Chicago"),
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "smart-meter-texas/0.2"})
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    daily = payload.get("daily", {})
    times = daily.get("time", [])
    _weather_table()
    with _connect() as con:
        for i, day in enumerate(times):
            con.execute("""INSERT INTO weather_daily VALUES (?,?,?,?,?,?,?,?)
              ON CONFLICT(weather_date) DO UPDATE SET
                temp_mean_f=excluded.temp_mean_f,temp_max_f=excluded.temp_max_f,
                temp_min_f=excluded.temp_min_f,apparent_mean_f=excluded.apparent_mean_f,
                humidity_mean=excluded.humidity_mean,precipitation_in=excluded.precipitation_in,
                fetched_at=excluded.fetched_at""",
              (day, daily["temperature_2m_mean"][i], daily["temperature_2m_max"][i],
               daily["temperature_2m_min"][i], daily["apparent_temperature_mean"][i],
               daily["relative_humidity_2m_mean"][i], daily["precipitation_sum"][i],
               datetime.utcnow().isoformat()))
        con.commit()
    from smart_meter_web.notification_settings import _connect as settings_connect, _ensure_tables
    _ensure_tables()
    with settings_connect() as con:
        con.execute(
            "INSERT INTO application_settings (setting_key, setting_value) VALUES ('weather_refreshed_revision', ?) "
            "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
            (_weather_preferences()["revision"],),
        )
        con.commit()
    return {"configured": True, "rows": len(times), "date_start": start, "date_end": end}


def weather_correlation():
    settings = weather_settings()
    if settings["needs_refresh"] or settings["mode"] == "none":
        return {"configured": settings["mode"] != "none", "points": [], "correlation": None, "needs_refresh": settings["needs_refresh"]}
    _weather_table()
    with _connect() as con:
        weather = {r["weather_date"]: dict(r) for r in con.execute("SELECT * FROM weather_daily")}
    merged = []
    for item in _daily_usage():
        w = weather.get(item["date"])
        if w and w["temp_mean_f"] is not None:
            merged.append({**item, **w})
    if len(merged) < 3:
        return {"configured": settings["mode"] != "none", "points": merged, "correlation": None}
    xs = [x["temp_mean_f"] for x in merged]
    ys = [x["kwh"] for x in merged]
    corr = statistics.correlation(xs, ys) if len(set(xs)) > 1 and len(set(ys)) > 1 else 0
    return {"configured": True, "points": merged[-180:], "correlation": round(corr, 3)}


def hvac_analysis():
    location_settings = weather_settings()
    if location_settings["mode"] == "none":
        return {"method": "Configure a weather location to see HVAC estimates.", "baseline_kwh": 0, "recent": []}
    if location_settings["needs_refresh"]:
        return {"method": "Weather location changed; refresh weather history to update estimates.", "baseline_kwh": 0, "recent": []}
    _weather_table()
    usage = _daily_usage()
    with _connect() as con:
        weather = {r["weather_date"]: dict(r) for r in con.execute("SELECT * FROM weather_daily")}
    mild = [x["kwh"] for x in usage if x["date"] in weather and weather[x["date"]]["temp_mean_f"] is not None and 60 <= weather[x["date"]]["temp_mean_f"] <= 72]
    baseline = statistics.median(mild) if mild else (statistics.median([x["kwh"] for x in usage]) if usage else 0)
    recent = []
    for x in usage[-30:]:
        w = weather.get(x["date"])
        recent.append({
            "date": x["date"], "kwh": round(x["kwh"], 2),
            "temp_mean_f": w["temp_mean_f"] if w else None,
            "estimated_hvac_kwh": round(max(0, x["kwh"] - baseline), 2),
        })
    return {
        "method": "Weather-normalized inference; not direct HVAC submetering.",
        "baseline_kwh": round(baseline, 2),
        "recent": recent,
    }


def anomalies():
    data = _daily_usage()
    threshold = anomaly_threshold()
    if len(data) < 15:
        return {"items": [], "anomaly_threshold": threshold}
    values = [x["kwh"] for x in data]
    window = values[-91:-1] if len(values) > 91 else values[:-1]
    med = statistics.median(window)
    deviations = [abs(x - med) for x in window]
    mad = statistics.median(deviations) or 0.01
    items = []
    for item in data[-30:]:
        score = 0.6745 * (item["kwh"] - med) / mad
        if abs(score) >= threshold:
            items.append({**item, "score": round(score, 2), "direction": "high" if score > 0 else "low"})
    return {
        "median_kwh": round(med, 2),
        "mad_kwh": round(mad, 3),
        "anomaly_threshold": threshold,
        "items": items,
    }


def monthly_forecast():
    data = _daily_usage()
    if not data:
        return {}
    latest = date.fromisoformat(data[-1]["date"])
    month = latest.strftime("%Y-%m")
    current = [x for x in data if x["date"].startswith(month)]
    used = sum(x["kwh"] for x in current)
    next_month = (latest.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_in_month = (next_month - timedelta(days=1)).day
    recent = [x["kwh"] for x in data[-28:]]
    avg = statistics.mean(recent) if recent else 0
    remaining = max(0, days_in_month - latest.day)
    forecast = used + avg * remaining
    rates = list_rates()
    current_rate = _rate_for_day(latest.isoformat(), rates)
    if current_rate:
        cents = float(current_rate["cents_per_kwh"])
        fixed = float(current_rate["monthly_fixed_fee"] or 0)
    else:
        fallback = rate_config()
        cents = fallback["cents_per_kwh"]
        fixed = fallback["monthly_fixed_fee"]
    fixed = _fixed_fee_for_month(month, rates)
    return {
        "month": month, "actual_kwh": round(used, 2), "days_elapsed": latest.day,
        "days_in_month": days_in_month, "forecast_kwh": round(forecast, 2),
        "forecast_cost": round(forecast * cents / 100 + fixed, 2),
        "method": "Current month actuals + trailing 28-day average, current variable rate, and prorated monthly fixed fee.",
    }


# Discord notification configuration and delivery live in notification_settings.
# Import the shared anomaly_threshold() above so UI changes affect detection.
