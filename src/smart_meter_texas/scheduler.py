from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smart_meter_texas.scheduler_health import HEARTBEAT_INTERVAL_SECONDS, SchedulerHeartbeat, timestamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Smart Meter Texas interval refresh on a daily schedule.")
    parser.add_argument("--time", default=os.environ.get("SMT_REFRESH_TIME", "11:00"), help="Daily run time HH:MM.")
    parser.add_argument("--timezone", default=os.environ.get("SMT_TIMEZONE", "America/Chicago"))
    parser.add_argument("--overlap-days", type=int, default=int(os.environ.get("SMT_OVERLAP_DAYS", "7")))
    parser.add_argument("--run-on-start", action="store_true", default=os.environ.get("SMT_RUN_ON_START", "0") in {"1", "true", "TRUE", "yes"})
    parser.add_argument("--once", action="store_true", help="Run once and exit.")
    return parser.parse_args()


def next_run(now: datetime, hhmm: str) -> datetime:
    hour_text, minute_text = hhmm.split(":", 1)
    candidate = now.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def run_refresh(
    overlap_days: int,
    heartbeat: SchedulerHeartbeat | None = None,
    scheduled_for: datetime | None = None,
) -> int:
    command = [
        sys.executable,
        "-m",
        "smart_meter_texas.intervals",
        "--overlap-days",
        str(overlap_days),
        "--db-path",
        "data/smt_interval_usage_history.sqlite",
        "--state-path",
        "data/smt_interval_sync_state.json",
        "--raw-payload-dir",
        "logs/raw-payloads",
    ]
    if heartbeat is not None:
        heartbeat.pulse(
            status="running",
            next_run_at=None,
            last_scheduled_at=scheduled_for.isoformat() if scheduled_for is not None else None,
            last_run_started_at=timestamp(),
            last_run_finished_at=None,
            last_run_returncode=None,
        )

    print(json.dumps({"event": "refresh_start", "command": command, "ts": datetime.now().isoformat()}), flush=True)
    try:
        if heartbeat is None:
            # One-off runs deliberately do not overwrite the live scheduler's
            # heartbeat when a second container shares the same data volume.
            code = subprocess.run(command).returncode
        else:
            process = subprocess.Popen(command)
            while True:
                try:
                    code = process.wait(timeout=HEARTBEAT_INTERVAL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    heartbeat.pulse(status="running")
    except BaseException:
        if heartbeat is not None:
            heartbeat.pulse(
                status="finished",
                last_run_finished_at=timestamp(),
                last_run_returncode=127,
            )
        raise

    print(json.dumps({"event": "refresh_end", "returncode": code, "ts": datetime.now().isoformat()}), flush=True)
    if code == 0:
        try:
            from smart_meter_web.notification_settings import maybe_notify_latest_anomaly
            notification = maybe_notify_latest_anomaly()
            print(json.dumps({"event": "anomaly_alert", "status": notification["status"]}), flush=True)
        except Exception:
            # Preserve sync success; avoid logging secret webhook URLs or usage details.
            print(json.dumps({"event": "anomaly_alert", "status": "error"}), flush=True)

    if heartbeat is not None:
        heartbeat.pulse(
            status="finished",
            last_run_finished_at=timestamp(),
            last_run_returncode=code,
        )
    return code


def sleep_until(target: datetime, heartbeat: SchedulerHeartbeat) -> None:
    heartbeat.pulse(status="sleeping", next_run_at=target.isoformat())
    while True:
        remaining = (target - datetime.now(target.tzinfo)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, HEARTBEAT_INTERVAL_SECONDS))
        heartbeat.pulse()


def main() -> None:
    args = parse_args()
    timezone = ZoneInfo(args.timezone)

    if args.once:
        raise SystemExit(run_refresh(args.overlap_days))

    heartbeat = SchedulerHeartbeat()
    if args.run_on_start:
        run_refresh(args.overlap_days, heartbeat=heartbeat)

    while True:
        now = datetime.now(timezone)
        target = next_run(now, args.time)
        sleep_seconds = max(1, int((target - now).total_seconds()))
        print(json.dumps({"event": "sleep", "until": target.isoformat(), "seconds": sleep_seconds}), flush=True)
        sleep_until(target, heartbeat)
        run_refresh(args.overlap_days, heartbeat=heartbeat, scheduled_for=target)


if __name__ == "__main__":
    main()
