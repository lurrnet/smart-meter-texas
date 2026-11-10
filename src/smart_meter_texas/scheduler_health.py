"""File-backed scheduler heartbeat and Docker liveness/deadline check.

The scheduler does not serve HTTP. Its heartbeat is written atomically and
contains scheduling metadata only (never meter data or credentials).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HEARTBEAT_INTERVAL_SECONDS = 30
MAX_HEARTBEAT_AGE_SECONDS = 180
SCHEDULE_GRACE_SECONDS = 15 * 60
MAX_RUN_SECONDS = 4 * 60 * 60


def heartbeat_path() -> Path:
    return Path(os.environ.get("SMT_SCHEDULER_HEARTBEAT_PATH", "data/scheduler_heartbeat.json"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp() -> str:
    return utc_now().isoformat()


def save_heartbeat(path: Path, payload: dict[str, Any]) -> None:
    """Replace the state file atomically with POSIX-restricted permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class SchedulerHeartbeat:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else heartbeat_path()
        started = timestamp()
        self.state: dict[str, Any] = {
            "schema_version": 1,
            "pid": os.getpid(),
            "started_at": started,
            "status": "starting",
            "next_run_at": None,
            "last_scheduled_at": None,
            "current_scheduled_at": None,
            "current_run_started_at": None,
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "last_run_returncode": None,
        }
        self.pulse()

    def pulse(self, **fields: Any) -> None:
        self.state.update(fields)
        self.state["heartbeat_at"] = timestamp()
        save_heartbeat(self.path, self.state)


def _read_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def check_heartbeat(
    path: Path | None = None,
    *,
    now: datetime | None = None,
    max_age_seconds: int = MAX_HEARTBEAT_AGE_SECONDS,
    schedule_grace_seconds: int = SCHEDULE_GRACE_SECONDS,
    max_run_seconds: int = MAX_RUN_SECONDS,
) -> tuple[bool, str]:
    """Check process liveness, heartbeat freshness, and scheduled-run deadline."""
    source = path if path is not None else heartbeat_path()
    try:
        state = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            return False, "invalid heartbeat schema"
        pid = state.get("pid")
        if type(pid) is not int or pid < 1:
            return False, "invalid scheduler pid"
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False, "scheduler process missing"
        except PermissionError:
            pass  # A running process may not be signalable by this user.

        current = (now if now is not None else utc_now()).astimezone(timezone.utc)
        heartbeat = _read_time(state.get("heartbeat_at"))
        age = (current - heartbeat).total_seconds()
        if age > max_age_seconds or age < -120:
            return False, "scheduler heartbeat stale or clock skewed"

        status = state.get("status")
        if status == "sleeping":
            next_run = _read_time(state.get("next_run_at"))
            if current > next_run + timedelta(seconds=schedule_grace_seconds):
                return False, "scheduled run overdue"
        elif status == "running":
            started = _read_time(state.get("current_run_started_at"))
            if current > started + timedelta(seconds=max_run_seconds):
                return False, "scheduled run exceeded maximum duration"
        elif status not in {"starting", "finished"}:
            return False, "invalid scheduler status"
        # A failed sync does not mean the scheduler is stuck; report the result in
        # the state file, rather than triggering unhelpful container restarts.
        return True, f"scheduler {status}"
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return False, f"unreadable scheduler heartbeat: {type(exc).__name__}"


def main() -> None:
    ok, message = check_heartbeat()
    print(message)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
