from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone

from smart_meter_texas import scheduler
from smart_meter_texas.scheduler_health import (
    HEARTBEAT_INTERVAL_SECONDS,
    SchedulerHeartbeat,
    check_heartbeat,
    save_heartbeat,
)


def test_heartbeat_is_private_and_atomic(tmp_path) -> None:
    path = tmp_path / "nested" / "scheduler_heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["pid"] == os.getpid()
    heartbeat.pulse(status="sleeping", next_run_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["status"] == "sleeping"
    assert not list(path.parent.glob(".*.tmp"))


def test_healthy_daily_sleep_is_not_mistaken_for_failure(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    future = datetime.now(timezone.utc) + timedelta(hours=23)
    heartbeat.pulse(status="sleeping", next_run_at=future.isoformat())
    ok, message = check_heartbeat(path)
    assert ok and message == "scheduler sleeping"


def test_recent_sleep_past_due_within_grace_is_healthy(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    heartbeat.pulse(status="sleeping", next_run_at=(datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat())
    assert check_heartbeat(path)[0]


def test_overdue_schedule_is_unhealthy_even_with_fresh_heartbeat(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    heartbeat.pulse(status="sleeping", next_run_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    ok, reason = check_heartbeat(path)
    assert not ok
    assert reason == "scheduled run overdue"


def test_stale_heartbeat_is_unhealthy(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    save_heartbeat(path, {**heartbeat.state, "heartbeat_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()})
    ok, reason = check_heartbeat(path)
    assert not ok and "stale" in reason


def test_missing_process_is_unhealthy(tmp_path, monkeypatch) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    def missing_pid(pid, sig):
        raise ProcessLookupError()
    monkeypatch.setattr("smart_meter_texas.scheduler_health.os.kill", missing_pid)
    assert check_heartbeat(path) == (False, "scheduler process missing")


def test_overlong_run_is_unhealthy_despite_fresh_heartbeat(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    heartbeat.pulse(
        status="running",
        last_run_started_at=(datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
    )
    assert check_heartbeat(path) == (False, "scheduled run exceeded maximum duration")


def test_recent_running_job_is_healthy(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    heartbeat.pulse(
        status="running",
        last_run_started_at=(datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat(),
    )
    assert check_heartbeat(path) == (True, "scheduler running")


def test_failed_sync_result_does_not_masquerade_as_scheduler_failure(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    heartbeat.pulse(
        status="sleeping",
        next_run_at=(datetime.now(timezone.utc) + timedelta(hours=20)).isoformat(),
        last_run_returncode=1,
        last_run_finished_at=datetime.now(timezone.utc).isoformat(),
    )
    assert check_heartbeat(path)[0] is True
    assert json.loads(path.read_text())["last_run_returncode"] == 1


def test_missing_or_corrupted_state_is_unhealthy(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    assert check_heartbeat(path)[0] is False
    path.write_text("{oops")
    assert check_heartbeat(path)[0] is False


def test_scheduler_refresh_pulses_during_long_running_subprocess(tmp_path, monkeypatch) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    class LongRunningProcess:
        calls = 0
        def wait(self, *, timeout):
            self.calls += 1
            assert timeout == HEARTBEAT_INTERVAL_SECONDS
            if self.calls == 1:
                raise subprocess.TimeoutExpired(cmd="intervals", timeout=timeout)
            return 2
    process = LongRunningProcess()
    monkeypatch.setattr(scheduler.subprocess, "Popen", lambda command: process)
    assert scheduler.run_refresh(7, heartbeat=heartbeat) == 2
    state = json.loads(path.read_text())
    assert process.calls == 2
    assert state["status"] == "finished"
    assert state["last_run_started_at"] is not None
    assert state["last_run_finished_at"] is not None
    assert state["last_run_returncode"] == 2


def test_once_run_does_not_clobber_existing_scheduler_state(tmp_path, monkeypatch) -> None:
    path = tmp_path / "heartbeat.json"
    existing = SchedulerHeartbeat(path)
    before = path.read_bytes()
    class Result:
        returncode = 1
    monkeypatch.setattr(scheduler.subprocess, "run", lambda command: Result())
    assert scheduler.run_refresh(7) == 1
    assert path.read_bytes() == before


def test_invalid_timestamp_or_schema_is_unhealthy(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"
    heartbeat = SchedulerHeartbeat(path)
    save_heartbeat(path, {**heartbeat.state, "status": "sleeping", "next_run_at": "2026-11-09T11:00:00"})
    assert check_heartbeat(path)[0] is False
    save_heartbeat(path, {**heartbeat.state, "schema_version": 99})
    assert check_heartbeat(path)[0] is False
