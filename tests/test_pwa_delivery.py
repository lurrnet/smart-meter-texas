from pathlib import Path

from fastapi.testclient import TestClient

from smart_meter_web import api


def test_pwa_static_routes_are_authenticated_and_correct(monkeypatch, tmp_path: Path):
    frontend = tmp_path / "frontend_dist"
    (frontend / "icons").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>DASHBOARD</html>")
    (frontend / "manifest.webmanifest").write_text('{"name":"Smart Meter Texas"}')
    (frontend / "sw.js").write_text("self.addEventListener('fetch', () => {});")
    (frontend / "pwa-register.js").write_text("/* register */")
    (frontend / "icons" / "icon-192.png").write_bytes(b"fake-icon")

    monkeypatch.setattr(api, "FRONTEND", frontend)
    monkeypatch.setenv("SMT_WEB_AUTH_ENABLED", "true")
    monkeypatch.setenv("SMT_WEB_USERNAME", "viewer")
    monkeypatch.setenv("SMT_WEB_PASSWORD", "test-password-with-24-characters")
    client = TestClient(api.app)

    for path in ("/manifest.webmanifest", "/sw.js", "/pwa-register.js", "/icons/icon-192.png"):
        assert client.get(path).status_code == 401

    import base64
    creds = base64.b64encode(b"viewer:test-password-with-24-characters").decode()
    headers = {"Authorization": f"Basic {creds}"}

    response = client.get("/manifest.webmanifest", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    assert response.json()["name"] == "Smart Meter Texas"
    assert response.headers["cache-control"] == "no-store"

    assert client.get("/sw.js", headers=headers).text.startswith("self.addEventListener")
    assert client.get("/pwa-register.js", headers=headers).status_code == 200
    assert client.get("/icons/icon-192.png", headers=headers).content == b"fake-icon"
    assert client.get("/manifest.webmanifest/unknown", headers=headers).text == "<html>DASHBOARD</html>"
