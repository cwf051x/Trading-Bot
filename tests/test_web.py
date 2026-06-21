"""Admin web panel tests.
管理后台测试。
"""

from pathlib import Path

from fastapi.testclient import TestClient

import app.web.server as web_server
from app.web.env_editor import update_env_values
from app.web.server import create_app
from app.storage.sqlite import SQLiteStorage


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


def test_alerts_page_uses_compact_chinese_table_display(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "web.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    storage = SQLiteStorage(database_path)
    storage.initialize()
    storage.save_market_alert(
        {
            "timestamp": 1_700_000_000_000,
            "symbol": "BTC/USDT:USDT",
            "alert_type": "TOP_GAINER_MOMENTUM",
            "level": "A",
            "score": 88,
            "price": 100.0,
            "price_change_3m": 0.01,
            "price_change_5m": 0.02,
            "price_change_15m": 0.03,
            "price_change_1h": 0.04,
            "price_change_24h": 0.05,
            "volume_ratio": 2.0,
            "btc_15m_change": 0.0,
            "reason": "24h gainer rank top 10 / 24小时涨幅榜前10",
            "suggested_action": "观察",
            "sent_to_telegram": False,
            "raw_json": {},
        }
    )
    client = TestClient(create_app())

    response = client.get("/alerts?type=all")
    table_body = response.text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]

    assert response.status_code == 200
    assert '<td class="symbol-cell">BTC</td>' in table_body
    assert "涨幅榜强势" in table_body
    assert "24小时涨幅榜前10" in table_body
    assert "BTC/USDT:USDT" not in table_body
    assert "TOP_GAINER_MOMENTUM" not in table_body
    assert "24h gainer rank top 10" not in table_body
    assert response.text.index("<th>Time</th>") < response.text.index("<th>Symbol</th>")
    assert "<th>Signal</th>" in response.text
    assert "<th>Change</th>" in response.text
    assert "<th>Market</th>" in response.text
    assert "<th>Detail</th>" in response.text
    assert "<th>15m</th>" not in response.text
    assert "<th>Telegram</th>" not in response.text


def test_alerts_page_defaults_to_volume_price_oi_resonance(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "web.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    storage = SQLiteStorage(database_path)
    storage.initialize()
    base_payload = {
        "timestamp": 1_700_000_000_000,
        "level": "B",
        "score": 70,
        "price": 100.0,
        "price_change_3m": 0.01,
        "price_change_5m": 0.02,
        "price_change_15m": 0.03,
        "price_change_1h": 0.04,
        "price_change_24h": 0.05,
        "volume_ratio": 2.0,
        "btc_15m_change": 0.0,
        "suggested_action": "观察",
        "sent_to_telegram": False,
        "raw_json": {},
    }
    storage.save_market_alert({**base_payload, "symbol": "OLD/USDT:USDT", "alert_type": "HIGH_RISK_EXTENSION", "reason": "old / 旧信号"})
    storage.save_market_alert({**base_payload, "symbol": "NEW/USDT:USDT", "alert_type": "VOLUME_PRICE_OI_RESONANCE", "reason": "L1 unusual move watch / L1 异动观察"})
    client = TestClient(create_app())

    default_response = client.get("/alerts")
    all_response = client.get("/alerts?type=all")

    assert default_response.status_code == 200
    assert "NEW" in default_response.text
    assert "OLD" not in default_response.text
    assert "VOLUME_PRICE_OI_RESONANCE" not in default_response.text
    assert "OLD" in all_response.text


def test_alert_display_helpers_use_compact_chinese_text() -> None:
    assert web_server.display_symbol_base("BTC/USDT:USDT") == "BTC"
    assert web_server.display_symbol_base("ETHUSDT") == "ETH"
    assert web_server.alert_type_label("TOP_GAINER_MOMENTUM") == "涨幅榜强势"
    assert web_server.chinese_reason_text("24h gainer rank top 10 / 24小时涨幅榜前10; short-term surge / 短周期异动") == "24小时涨幅榜前10；短周期异动"


def test_env_editor_updates_only_allowed_keys(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("WATCH_SYMBOLS=BTC/USDT:USDT\nENABLE_LIVE_TRADING=false\n", encoding="utf-8")

    update_env_values(env_path, {"WATCH_SYMBOLS": "ETH/USDT:USDT", "ENABLE_LIVE_TRADING": "true"})

    content = env_path.read_text(encoding="utf-8")
    assert "WATCH_SYMBOLS=ETH/USDT:USDT" in content
    assert "ENABLE_LIVE_TRADING=false" in content
