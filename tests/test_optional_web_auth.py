"""Tests for optional app-level HTTP Basic auth behind Cloudflare Access."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from smart_meter_web import api


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off", " false "])
def test_explicit_disable_allows_dashboard_api_without_basic_credentials(monkeypatch, value):
    monkeypatch.setenv("SMT_WEB_AUTH_ENABLED", value)
    monkeypatch.delenv("SMT_WEB_USERNAME", raising=False)
    monkeypatch.delenv("SMT_WEB_PASSWORD", raising=False)

    # Read routes are reachable even without an app-level username/password.
    client = TestClient(api.app)
    result = client.get("/api/summary")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"

    # Mutation endpoints also bypass the app's authentication middleware;
    # the upstream gateway must protect these, not only the HTML page.
    monkeypatch.setattr(api, "run_sync", lambda *args, **kwargs: {"ok": True})
    result = client.post("/api/sync")
    assert result.status_code == 200
    assert result.json() == {"ok": True}


@pytest.mark.parametrize("value", [None, "", "true", "TRUE", "1", "on", "fales", "disabled"])
def test_default_and_unknown_values_fail_closed_without_credentials(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SMT_WEB_AUTH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("SMT_WEB_AUTH_ENABLED", value)
    monkeypatch.delenv("SMT_WEB_USERNAME", raising=False)
    monkeypatch.delenv("SMT_WEB_PASSWORD", raising=False)

    client = TestClient(api.app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/summary").status_code == 503
    assert client.post("/api/sync").status_code == 503


def test_enabled_mode_still_requires_basic_auth(monkeypatch):
    monkeypatch.setenv("SMT_WEB_AUTH_ENABLED", "true")
    monkeypatch.setenv("SMT_WEB_USERNAME", "viewer")
    monkeypatch.setenv("SMT_WEB_PASSWORD", "a-long-unique-password-for-tests")
    client = TestClient(api.app)
    assert client.get("/api/summary").status_code == 401
    assert client.post("/api/sync").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_no_app_auth_does_not_weaken_liveness_endpoint(monkeypatch):
    monkeypatch.setenv("SMT_WEB_AUTH_ENABLED", "false")
    client = TestClient(api.app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
