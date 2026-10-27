from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from smart_meter_texas.daily import save_state, choose_esiid, SmartMeterTexasError
from smart_meter_texas.intervals import capture_raw_payload, should_save_raw_payloads
from smart_meter_web import api


def test_raw_payload_capture_is_opt_in(monkeypatch):
    monkeypatch.delenv("SMT_SAVE_RAW_PAYLOADS", raising=False)
    assert not should_save_raw_payloads()
    monkeypatch.setenv("SMT_SAVE_RAW_PAYLOADS", "0")
    assert not should_save_raw_payloads()
    monkeypatch.setenv("SMT_SAVE_RAW_PAYLOADS", "1")
    assert should_save_raw_payloads()
    monkeypatch.setenv("SMT_SAVE_RAW_PAYLOADS", "0")
    assert should_save_raw_payloads(True)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_sensitive_files_are_private(tmp_path: Path):
    state = tmp_path / "private" / "state.json"
    save_state(state, {"esiid": "dummy"})
    assert state.stat().st_mode & 0o077 == 0

    target_dir = tmp_path / "raw"
    target = capture_raw_payload({"esiid": "dummy"}, target_dir, start=date(2026, 1, 1), end=date(2026, 1, 2))
    assert json.loads(target.read_text())["esiid"] == "dummy"
    assert target.stat().st_mode & 0o077 == 0
    assert target_dir.stat().st_mode & 0o077 == 0


def test_meter_selection_errors_do_not_expose_esiid():
    fake = Mock()
    fake.list_meters.return_value = [{"esiid": "TEST_SENSITIVE_000123"}]
    with pytest.raises(SmartMeterTexasError) as exc:
        choose_esiid(fake, "TEST_OTHER_000456")
    assert "TEST_OTHER_000456" not in str(exc.value)


def test_public_health_does_not_expose_data_file_status(monkeypatch):
    monkeypatch.delenv("SMT_WEB_USERNAME", raising=False)
    monkeypatch.delenv("SMT_WEB_PASSWORD", raising=False)
    response = TestClient(api.app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_sync_http_responses_never_echo_subprocess_output(monkeypatch):
    monkeypatch.setattr(api.subprocess, "run", lambda *a, **k: Mock(returncode=0, stdout="ESIID SECRET_METER", stderr=""))
    assert api.run_sync()["output"] == "Sync completed successfully."
    monkeypatch.setattr(api.subprocess, "run", lambda *a, **k: Mock(returncode=1, stdout="", stderr="SECRET_METER ERROR"))
    with pytest.raises(api.HTTPException) as exc:
        api.run_sync()
    assert exc.value.status_code == 500
    assert "SECRET_METER" not in str(exc.value.detail)
