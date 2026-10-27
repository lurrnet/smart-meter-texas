from __future__ import annotations

import json
import secrets
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from smart_meter_texas.intervals import daily_interval_slots
from smart_meter_web.analytics import (
    add_rate, anomalies, cost_series, cost_summary, delete_rate,
    hvac_analysis, list_rates, monthly_forecast, default_rate_settings,
    save_default_rate_settings, weather_settings, save_weather_settings,
    refresh_weather, weather_correlation,
)
from smart_meter_web.notification_settings import (
    maybe_notify_latest_anomaly, notification_status,
    save_notification_settings, send_discord_test,
)

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Smart Meter Texas", docs_url=None, redoc_url=None, openapi_url=None)
ROOT = Path(os.environ.get("SMT_PROJECT_ROOT", "/app"))
DB = ROOT / "data" / "smt_interval_usage_history.sqlite"
STATE = ROOT / "data" / "smt_interval_sync_state.json"
FRONTEND = ROOT / "frontend_dist"

# Basic authentication is enabled by default. Users who enforce authentication
# at a trusted reverse proxy (such as Cloudflare Zero Trust Access) can opt out.
# Unknown values deliberately leave authentication enabled, not disabled.
_DISABLED_AUTH_VALUES = frozenset({"0", "false", "no", "off"})


def web_auth_enabled() -> bool:
    setting = os.environ.get("SMT_WEB_AUTH_ENABLED", "true")
    return setting.strip().lower() not in _DISABLED_AUTH_VALUES


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    # Keep Docker's liveness endpoint public, but disclose no private data.
    if request.url.path == "/api/health":
        return await call_next(request)

    if not web_auth_enabled():
        # In this mode ALL routes are protected only by upstream access controls.
        # Users must prevent direct access to the origin outside that proxy.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    username = os.environ.get("SMT_WEB_USERNAME", "")
    password = os.environ.get("SMT_WEB_PASSWORD", "")
    if not username or len(password) < 16 or password.startswith("replace-with-"):
        return JSONResponse(
            status_code=503,
            content={"detail": "Web authentication is not configured. Set SMT_WEB_USERNAME and a unique SMT_WEB_PASSWORD of at least 16 characters."},
            headers={"Cache-Control": "no-store"},
        )

    import base64
    import binascii

    authorization = request.headers.get("authorization", "")
    authenticated = False
    if authorization.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authorization[6:].strip(), validate=True).decode("utf-8")
            supplied_username, separator, supplied_password = decoded.partition(":")
            authenticated = bool(separator) and secrets.compare_digest(supplied_username, username) and secrets.compare_digest(supplied_password, password)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            authenticated = False

    if not authenticated:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Smart Meter Texas"', "Cache-Control": "no-store"},
        )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response



def rows(query: str, params: tuple = ()) -> list[dict]:
    if not DB.exists():
        return []
    with sqlite3.connect(DB) as connection:
        connection.row_factory = sqlite3.Row
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='interval_usage'"
        ).fetchone():
            return []
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def state_payload() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@app.get("/api/health")
def health() -> dict:
    # Liveness only; never disclose local data presence before authentication.
    return {"ok": True}


@app.get("/api/summary")
def summary() -> dict:
    daily = rows(
        """
        SELECT
          date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2)) AS d,
          ROUND(SUM(CAST(NULLIF(USAGE_KWH,'') AS REAL)),3) AS kwh
        FROM interval_usage
        WHERE INTERVAL_STATUS <> 'MISSING'
        GROUP BY d
        ORDER BY d
        """
    )
    if not daily:
        return {"today": 0, "yesterday": 0, "month_to_date": 0, "latest_date": None}

    latest = daily[-1]["d"]
    latest_dt = datetime.fromisoformat(latest)
    yesterday = (latest_dt - timedelta(days=1)).date().isoformat()
    month_prefix = latest[:7]
    values = {item["d"]: item["kwh"] or 0 for item in daily}
    return {
        "today": values.get(latest, 0),
        "yesterday": values.get(yesterday, 0),
        "month_to_date": round(sum(value for day, value in values.items() if day.startswith(month_prefix)), 3),
        "latest_date": latest,
    }


@app.get("/api/daily")
def daily(days: int = 30) -> list[dict]:
    base_query = """
        SELECT
          date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2)) AS date,
          ROUND(SUM(CAST(NULLIF(USAGE_KWH,'') AS REAL)),3) AS kwh
        FROM interval_usage
        WHERE INTERVAL_STATUS <> 'MISSING'
        GROUP BY date
        ORDER BY date DESC
    """
    if days <= 0:
        result = rows(base_query)
    else:
        safe_days = max(1, min(days, 3660))
        result = rows(base_query + " LIMIT ?", (safe_days,))
    return list(reversed(result))


@app.get("/api/intervals/latest")
def latest_intervals() -> list[dict]:
    return rows(
        """
        SELECT
          USAGE_DATE AS usage_date,
          USAGE_START_TIME AS start_time,
          CAST(NULLIF(USAGE_KWH,'') AS REAL) AS kwh,
          INTERVAL_STATUS AS status
        FROM interval_usage
        WHERE USAGE_DATE = (
          SELECT USAGE_DATE
          FROM interval_usage
          ORDER BY date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2)) DESC
          LIMIT 1
        )
        ORDER BY CAST(INTERVAL_INDEX AS INTEGER)
        """
    )


@app.get("/api/heatmap")
def heatmap(days: int = 7) -> list[dict]:
    safe_days = max(1, min(days, 31))
    modifier = "-" + str(safe_days - 1) + " day"
    return rows(
        """
        SELECT
          date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2)) AS date,
          USAGE_START_TIME AS start_time,
          CAST(NULLIF(USAGE_KWH,'') AS REAL) AS kwh
        FROM interval_usage
        WHERE date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2))
          >= date(
            (
              SELECT max(date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2)))
              FROM interval_usage
            ),
            ?
          )
        ORDER BY date, CAST(INTERVAL_INDEX AS INTEGER)
        """,
        (modifier,),
    )


@app.get("/api/sync/status")
def sync_status() -> dict:
    state = state_payload()
    timezone = ZoneInfo(os.environ.get("SMT_TIMEZONE", "America/Chicago"))
    refresh_time = os.environ.get("SMT_REFRESH_TIME", "11:00")
    now = datetime.now(timezone)
    hour_text, minute_text = refresh_time.split(":", 1)
    next_run = now.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)

    return {
        "last_run_at": state.get("last_run_at"),
        "last_successful_run_at": state.get("last_successful_run_at"),
        "next_run_at": next_run.isoformat(),
        "incomplete_dates": state.get("incomplete_dates", []),
    }


def run_sync(extra_args: list[str] | None = None) -> dict:
    command = [
        sys.executable,
        "-m",
        "smart_meter_texas.intervals",
        "--overlap-days",
        os.environ.get("SMT_OVERLAP_DAYS", "7"),
        "--db-path",
        "data/smt_interval_usage_history.sqlite",
        "--state-path",
        "data/smt_interval_sync_state.json",
        "--raw-payload-dir",
        "logs/raw-payloads",
    ]
    if extra_args:
        command.extend(extra_args)
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Sync timed out") from exc

    if result.returncode != 0:
        # Raw stderr can include upstream meter IDs, account details, or response bodies.
        # Never forward it to a browser, even to an authenticated user.
        raise HTTPException(status_code=500, detail="Sync failed; review server-side diagnostics privately.")

    # Notification delivery must never turn an otherwise successful sync into
    # a failed API call. Alerts are optional and their errors stay private.
    try:
        maybe_notify_latest_anomaly()
    except Exception:
        pass
    return {"ok": True, "output": "Sync completed successfully."}


@app.post("/api/sync")
def sync_now() -> dict:
    return run_sync()


@app.post("/api/sync/catch-up")
def catch_up() -> dict:
    latest = rows(
        """
        SELECT max(
          date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2))
        ) AS latest_date
        FROM interval_usage
        """
    )
    latest_date = latest[0]["latest_date"] if latest and latest[0]["latest_date"] else None
    if not latest_date:
        return run_sync()
    result = run_sync(["--start-date", latest_date])
    result["start_date"] = latest_date
    return result


def data_health_snapshot() -> dict:
    if not DB.exists():
        return {
            "status": "empty",
            "coverage_pct": 0.0,
            "date_start": None,
            "date_end": None,
            "total_days": 0,
            "complete_days": 0,
            "missing_days": 0,
            "incomplete_days": 0,
            "missing_intervals": 0,
            "first_problem_date": None,
            "problem_dates": [],
        }

    daily_rows = rows(
        """
        SELECT
          USAGE_DATE,
          COUNT(DISTINCT CAST(INTERVAL_INDEX AS INTEGER)) AS interval_count,
          SUM(CASE WHEN INTERVAL_STATUS = 'MISSING' OR NULLIF(TRIM(USAGE_KWH),'') IS NULL THEN 1 ELSE 0 END) AS missing_intervals,
          SUM(CASE WHEN INTERVAL_STATUS <> 'MISSING' AND NULLIF(TRIM(USAGE_KWH),'') IS NOT NULL THEN 1 ELSE 0 END) AS populated_intervals
        FROM interval_usage
        GROUP BY USAGE_DATE
        ORDER BY date(substr(USAGE_DATE,7,4)||'-'||substr(USAGE_DATE,1,2)||'-'||substr(USAGE_DATE,4,2))
        """
    )
    if not daily_rows:
        return {
            "status": "empty",
            "coverage_pct": 0.0,
            "date_start": None,
            "date_end": None,
            "total_days": 0,
            "complete_days": 0,
            "missing_days": 0,
            "incomplete_days": 0,
            "missing_intervals": 0,
            "first_problem_date": None,
            "problem_dates": [],
        }

    by_date = {}
    for item in daily_rows:
        parsed = datetime.strptime(item["USAGE_DATE"], "%m/%d/%Y").date()
        by_date[parsed] = item

    start = min(by_date)
    end = max(by_date)
    cursor = start
    complete_days = 0
    missing_days = 0
    incomplete_days = 0
    missing_intervals = 0
    problems = []

    while cursor <= end:
        item = by_date.get(cursor)
        iso_date = cursor.isoformat()
        if item is None:
            missing_days += 1
            expected = len(daily_interval_slots(cursor.strftime("%m/%d/%Y")))
            missing_intervals += expected
            problems.append({"date": iso_date, "type": "missing_day", "missing_intervals": expected})
        else:
            expected = len(daily_interval_slots(item["USAGE_DATE"]))
            actual = int(item["interval_count"] or 0)
            populated = int(item["populated_intervals"] or 0)
            flagged_missing = int(item["missing_intervals"] or 0)
            structural_missing = max(0, expected - actual)
            total_missing = max(flagged_missing, structural_missing)
            dst_complete = actual >= expected and populated == expected
            if (actual == expected and total_missing == 0) or dst_complete:
                complete_days += 1
            else:
                incomplete_days += 1
                missing_intervals += total_missing
                problems.append({
                    "date": iso_date,
                    "type": "incomplete_day",
                    "expected_intervals": expected,
                    "actual_intervals": actual,
                    "missing_intervals": total_missing,
                })
        cursor += timedelta(days=1)

    total_days = (end - start).days + 1
    coverage_pct = round((complete_days / total_days) * 100, 2) if total_days else 0.0
    return {
        "status": "healthy" if not problems else "needs_attention",
        "coverage_pct": coverage_pct,
        "date_start": start.isoformat(),
        "date_end": end.isoformat(),
        "total_days": total_days,
        "complete_days": complete_days,
        "missing_days": missing_days,
        "incomplete_days": incomplete_days,
        "missing_intervals": missing_intervals,
        "first_problem_date": problems[0]["date"] if problems else None,
        "problem_dates": problems[:50],
    }


@app.get("/api/data-health")
def data_health() -> dict:
    return data_health_snapshot()


@app.post("/api/repair-gaps")
def repair_gaps() -> dict:
    health_before = data_health_snapshot()
    first_problem = health_before.get("first_problem_date")
    if not first_problem:
        return {"ok": True, "repaired": False, "message": "No gaps detected.", "health": health_before}

    result = run_sync(["--start-date", first_problem])
    health_after = data_health_snapshot()
    return {
        "ok": True,
        "repaired": True,
        "start_date": first_problem,
        "sync": result,
        "health": health_after,
    }


@app.get("/api/mvp2/rates")
def mvp2_rates() -> list[dict]:
    return list_rates()


@app.post("/api/mvp2/rates")
def mvp2_add_rate(payload: dict = Body(...)) -> dict:
    try:
        result = add_rate(
            start_date=str(payload.get("start_date") or ""),
            end_date=str(payload.get("end_date") or "") or None,
            cents_per_kwh=float(payload.get("cents_per_kwh")),
            monthly_fixed_fee=float(payload.get("monthly_fixed_fee") or 0),
            label=str(payload.get("label") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.delete("/api/mvp2/rates/{rate_id}")
def mvp2_delete_rate(rate_id: int) -> dict:
    try:
        return delete_rate(rate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/mvp2/default-rate")
def mvp2_default_rate() -> dict:
    return default_rate_settings()


@app.put("/api/mvp2/default-rate")
def mvp2_save_default_rate(payload: dict = Body(...)) -> dict:
    try:
        return save_default_rate_settings(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/mvp2/weather/settings")
def mvp2_weather_settings() -> dict:
    return weather_settings()


@app.put("/api/mvp2/weather/settings")
def mvp2_save_weather_settings(payload: dict = Body(...)) -> dict:
    try:
        return save_weather_settings(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/mvp2/cost-series")
def mvp2_cost_series() -> dict:
    return cost_series()


@app.get("/api/mvp2/cost")
def mvp2_cost() -> dict:
    return cost_summary()


@app.get("/api/mvp2/weather")
def mvp2_weather() -> dict:
    return weather_correlation()


@app.post("/api/mvp2/weather/refresh")
def mvp2_weather_refresh() -> dict:
    return refresh_weather()


@app.get("/api/mvp2/hvac")
def mvp2_hvac() -> dict:
    return hvac_analysis()


@app.get("/api/mvp2/anomalies")
def mvp2_anomalies() -> dict:
    return anomalies()


@app.get("/api/mvp2/forecast")
def mvp2_forecast() -> dict:
    return monthly_forecast()


@app.get("/api/mvp2/notifications")
def mvp2_notifications() -> dict:
    return notification_status()


@app.put("/api/mvp2/notifications/settings")
def mvp2_save_notification_settings(payload: dict = Body(...)) -> dict:
    try:
        return save_notification_settings(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/mvp2/notifications/test")
def mvp2_notification_test() -> dict:
    return send_discord_test()


if FRONTEND.exists() and (FRONTEND / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


@app.get("/{path:path}")
def single_page_app(path: str):
    # Serve only known compiled static file extensions from the frontend root.
    root = FRONTEND.resolve()
    candidate = (root / path).resolve()
    if path and candidate.is_file() and candidate.is_relative_to(root) and candidate.suffix in {".js", ".css", ".svg", ".png", ".ico", ".jpg", ".jpeg", ".webp", ".woff", ".woff2", ".txt"}:
        return FileResponse(candidate)
    if path.startswith("api/") or path.startswith(".") or path.startswith("assets/"):
        raise HTTPException(status_code=404, detail="Not found")
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Frontend build not found")
    return FileResponse(index)


def main() -> None:
    import uvicorn

    uvicorn.run("smart_meter_web.api:app", host="0.0.0.0", port=8090)
