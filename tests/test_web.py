"""Admin web panel tests.
管理后台测试。
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.web.env_editor import update_env_values
from app.web.server import create_app


def test_dashboard_renders_without_admin_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "Live Trading" in response.text


def test_admin_token_blocks_dashboard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "secret")
    client = TestClient(create_app(), follow_redirects=False)

    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_alerts_page_renders(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    client = TestClient(create_app())

    response = client.get("/alerts")

    assert response.status_code == 200
    assert "Market Alerts" in response.text


def test_env_editor_updates_only_allowed_keys(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("WATCH_SYMBOLS=BTC/USDT:USDT\nENABLE_LIVE_TRADING=false\n", encoding="utf-8")

    update_env_values(env_path, {"WATCH_SYMBOLS": "ETH/USDT:USDT", "ENABLE_LIVE_TRADING": "true"})

    content = env_path.read_text(encoding="utf-8")
    assert "WATCH_SYMBOLS=ETH/USDT:USDT" in content
    assert "ENABLE_LIVE_TRADING=false" in content
