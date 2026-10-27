from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient


def _auth(username="viewer", password="my-very-long-test-password"):
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def test_health_public_and_everything_else_fails_closed(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SMT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("SMT_WEB_USERNAME", raising=False)
    monkeypatch.delenv("SMT_WEB_PASSWORD", raising=False)
    from smart_meter_web.api import app

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/summary").status_code == 503
    assert client.post("/api/sync").status_code == 503


def test_authentication_is_required_for_read_and_mutating_endpoints(monkeypatch):
    monkeypatch.setenv("SMT_WEB_USERNAME", "viewer")
    monkeypatch.setenv("SMT_WEB_PASSWORD", "my-very-long-test-password")
    from smart_meter_web.api import app

    client = TestClient(app)
    for method, path in [
        ("get", "/api/summary"),
        ("get", "/api/mvp2/rates"),
        ("post", "/api/sync"),
        ("post", "/api/repair-gaps"),
        ("delete", "/api/mvp2/rates/1"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic")
    assert client.get("/api/summary", headers=_auth()).status_code == 200
    assert client.get("/api/summary", headers=_auth(password="wrong")).status_code == 401
    assert client.get("/api/summary", headers=_auth()).headers["cache-control"] == "no-store"


def test_frontend_cannot_serve_private_files(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SMT_WEB_USERNAME", "viewer")
    monkeypatch.setenv("SMT_WEB_PASSWORD", "my-very-long-test-password")
    from smart_meter_web import api

    frontend = tmp_path / "frontend_dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>APP</html>")
    (tmp_path / ".env").write_text("SMT_PASSWORD=private")
    (tmp_path / "private.js").write_text("secret")
    monkeypatch.setattr(api, "FRONTEND", frontend)

    client = TestClient(api.app)
    for path in ("/.env", "/..%2F.env", "/%2e%2e%2f.env", "/assets/../../../private.js"):
        response = client.get(path, headers=_auth())
        assert "SMT_PASSWORD=private" not in response.text
        assert "secret" not in response.text
    assert client.get("/dashboard", headers=_auth()).text == "<html>APP</html>"

def test_example_or_short_web_password_is_rejected(monkeypatch):
    from smart_meter_web.api import app

    client = TestClient(app)
    monkeypatch.setenv("SMT_WEB_USERNAME", "admin")
    for password in ("replace-with-a-strong-unique-password", "123456"):
        monkeypatch.setenv("SMT_WEB_PASSWORD", password)
        assert client.get("/api/summary", headers=_auth("admin", password)).status_code == 503


def test_rates_can_be_opened_before_first_usage_sync(monkeypatch, tmp_path: Path):
    from smart_meter_web import api, analytics

    db = tmp_path / "intervals.sqlite"
    monkeypatch.setattr(api, "DB", db)
    monkeypatch.setattr(analytics, "DB", db)
    monkeypatch.setenv("SMT_WEB_USERNAME", "viewer")
    monkeypatch.setenv("SMT_WEB_PASSWORD", "my-very-long-test-password")
    client = TestClient(api.app)

    assert client.get("/api/mvp2/rates", headers=_auth()).status_code == 200
    response = client.get("/api/summary", headers=_auth())
    assert response.status_code == 200
    assert response.json()["month_to_date"] == 0
    assert client.get("/api/mvp2/cost", headers=_auth()).status_code == 200
