"""Admin web panel tests.
管理后台测试。
"""

from pathlib import Path
import re

from fastapi.testclient import TestClient

import app.web.server as web_server
from app.web.env_editor import update_env_values
from app.web.server import create_app
from app.web.work_logs import classify_source, load_work_log_view
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


def test_admin_token_required_for_non_local_bind(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")

    client = TestClient(create_app())
    response = client.get("/")

    assert response.status_code == 500
    assert "WEB_ADMIN_TOKEN is required" in response.text


def test_query_token_does_not_authenticate_admin(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "secret")
    client = TestClient(create_app(), follow_redirects=False)

    response = client.get("/?token=secret")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_post_settings_requires_csrf_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "secret")
    client = TestClient(create_app(), follow_redirects=False)
    client.post("/login", data={"token": "secret"})

    response = client.post("/settings", data={})

    assert response.status_code == 403
    assert "CSRF" in response.text


def test_alerts_page_renders(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    client = TestClient(create_app())

    response = client.get("/alerts")

    assert response.status_code == 200
    assert "行情雷达提醒" in response.text


def test_minute_runners_page_renders_current_pool(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "web.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    storage = SQLiteStorage(database_path)
    storage.initialize()
    storage.upsert_minute_runner_state(
        {
            "symbol": "IN/USDT:USDT",
            "state": "M2E",
            "runner_score": 89,
            "ranking_score": 110,
            "trend_id": "trend-1",
            "trend_age_minutes": 85,
            "last_score_update_at": 1_700_000_000_000,
            "last_price": 0.123,
            "price_change_1h": 0.28,
            "volume_ratio_15m": 2.6,
            "oi_change_30m": 0.052,
            "oi_change_1h": 0.068,
            "distance_to_ma25_5m": 0.084,
            "pullback_from_high": 0.02,
            "risk_tags_json": [],
            "metadata_json": {},
        }
    )
    client = TestClient(create_app())

    response = client.get("/minute-runners")

    assert response.status_code == 200
    assert "分钟单边上涨池" in response.text
    assert "M2E 早期确信" in response.text
    table_body = response.text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert ">IN</strong>" in table_body
    assert "IN/USDT:USDT" not in table_body


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
    assert response.text.index(">时间</a>") < response.text.index(">币种</a>")
    assert ">信号</a>" in response.text
    assert "<th>涨幅</th>" in response.text
    assert ">市场</a>" in response.text
    assert "<th>详情</th>" in response.text
    assert "<th>15m</th>" not in response.text
    assert "<th>Telegram</th>" not in response.text


def test_alerts_page_defaults_to_all_alerts(monkeypatch, tmp_path: Path) -> None:
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
    resonance_response = client.get("/alerts?type=VOLUME_PRICE_OI_RESONANCE")

    assert default_response.status_code == 200
    default_body = default_response.text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    resonance_body = resonance_response.text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert "NEW" in default_body
    assert "OLD" in default_body
    assert "VOLUME_PRICE_OI_RESONANCE" not in default_body
    assert "NEW" in resonance_body
    assert "OLD" not in resonance_body


def test_orders_page_supports_pagination_sorting_and_search(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "web.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    storage = SQLiteStorage(database_path)
    storage.initialize()
    for symbol in ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]:
        storage.create_order(
            symbol=symbol,
            side="long",
            quantity=1,
            entry_price=100,
            stop_loss=98,
            take_profit=104,
            status="open",
            reason=f"alert {symbol}",
            timestamp=1_700_000_000_000,
        )
    client = TestClient(create_app())

    response = client.get("/orders?per_page=2&page=2&sort=symbol&direction=asc&q=USDT")

    assert response.status_code == 200
    assert "Page 2 / 2" in response.text
    table_body = response.text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert "SOL/USDT:USDT" in table_body
    assert "BTC/USDT:USDT" not in table_body
    assert 'href="/orders?page=1&amp;per_page=2&amp;sort=symbol&amp;direction=asc&amp;q=USDT"' in response.text
    assert 'name="q" value="USDT"' in response.text
    assert "Sort by Symbol" in response.text


def test_orders_page_shows_paper_performance_summary(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "web.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    monkeypatch.setenv("PAPER_LEVERAGE", "2")
    storage = SQLiteStorage(database_path)
    storage.initialize()
    storage.create_order("WIN/USDT:USDT", "long", 2, 100, 95, 110, "open", "alert HOURLY_TREND_T3: win", 1)
    storage.create_position(1, "WIN/USDT:USDT", "long", 2, 100, 95, 110, 1)
    storage.close_position(1, 110, 20, "take_profit", 2)
    storage.create_order("OPEN/USDT:USDT", "long", 4, 50, 45, 60, "open", "alert VOLUME_PRICE_OI_RESONANCE: open", 3)
    storage.create_position(2, "OPEN/USDT:USDT", "long", 4, 50, 45, 60, 3)
    client = TestClient(create_app())

    response = client.get("/orders")

    assert response.status_code == 200
    assert "Paper Performance" in response.text
    assert "Realized PnL" in response.text
    assert "+20.00" in response.text
    assert "Win Rate" in response.text
    assert "100.00%" in response.text
    assert "Open Positions" in response.text
    assert "Open Margin" in response.text
    assert "100.00" in response.text


def test_order_tables_use_compact_numeric_display(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "web.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    storage = SQLiteStorage(database_path)
    storage.initialize()
    storage.create_order(
        "BEL/USDT:USDT",
        "long",
        475.80530047104725,
        0.21017,
        0.2059666,
        0.21857680000000002,
        "open",
        "alert VOLUME_PRICE_OI_RESONANCE",
        1,
    )
    client = TestClient(create_app())

    response = client.get("/orders")

    assert response.status_code == 200
    assert "475.8053" in response.text
    assert "475.80530047104725" not in response.text
    assert "0.218577" in response.text
    assert "0.21857680000000002" not in response.text


def test_trades_page_shows_paper_performance_summary(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "web.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    storage = SQLiteStorage(database_path)
    storage.initialize()
    storage.create_order("WIN/USDT:USDT", "long", 1, 100, 95, 110, "open", "alert HOURLY_TREND_T3: win", 1)
    storage.create_position(1, "WIN/USDT:USDT", "long", 1, 100, 95, 110, 1)
    storage.close_position(1, 110, 10, "take_profit", 2)
    client = TestClient(create_app())

    response = client.get("/trades")

    assert response.status_code == 200
    assert "Paper Performance" in response.text
    assert "Realized PnL" in response.text
    assert "+10.00" in response.text


def test_ledger_pages_render_table_controls_even_when_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    client = TestClient(create_app())

    for path in ["/orders", "/positions", "/trades"]:
        response = client.get(path)

        assert response.status_code == 200
        assert 'class="table-toolbar"' in response.text
        assert 'name="q" value=""' in response.text
        assert "Rows" in response.text


def test_orders_page_caps_page_to_last_available_page(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "web.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    storage = SQLiteStorage(database_path)
    storage.initialize()
    for symbol in ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]:
        storage.create_order(
            symbol=symbol,
            side="long",
            quantity=1,
            entry_price=100,
            stop_loss=98,
            take_profit=104,
            status="open",
            reason=f"alert {symbol}",
            timestamp=1_700_000_000_000,
        )
    client = TestClient(create_app())

    response = client.get("/orders?per_page=2&page=99&sort=symbol&direction=asc")

    assert response.status_code == 200
    assert "Page 2 / 2" in response.text
    assert "SOL/USDT:USDT" in response.text


def test_alerts_page_supports_search_and_sorting(monkeypatch, tmp_path: Path) -> None:
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
    storage.save_market_alert({**base_payload, "symbol": "BTC/USDT:USDT", "alert_type": "VOLUME_PRICE_OI_RESONANCE", "reason": "BTC resonance / BTC 共振"})
    storage.save_market_alert({**base_payload, "symbol": "SOL/USDT:USDT", "alert_type": "VOLUME_PRICE_OI_RESONANCE", "reason": "SOL resonance / SOL 共振", "score": 90})
    client = TestClient(create_app())

    response = client.get("/alerts?type=all&q=SOL&sort=score&direction=desc")
    table_body = response.text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]

    assert response.status_code == 200
    assert '<td class="symbol-cell">SOL</td>' in table_body
    assert '<td class="symbol-cell">BTC</td>' not in table_body
    assert 'name="q" value="SOL"' in response.text
    assert 'href="/alerts?page=1&amp;per_page=25&amp;sort=score&amp;direction=asc&amp;type=all&amp;q=SOL"' in response.text


def test_radar_replay_page_renders_form(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    client = TestClient(create_app())

    response = client.get("/replay")

    assert response.status_code == 200
    assert "Radar Replay" in response.text
    assert 'name="symbol"' in response.text
    assert 'name="days"' in response.text


def test_radar_replay_post_shows_summary_and_detail(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")

    def fake_run(symbol: str, days: int, warmup_bars: int, cooldown_bars: int):
        return web_server.RadarReplayView(
            symbol=symbol,
            days=days,
            detail_path=tmp_path / "detail.csv",
            summary_path=tmp_path / "summary.csv",
            signal_count=1,
            summary=[
                {
                    "signal_type": "VOLUME_PRICE_OI_RESONANCE",
                    "count": 1,
                    "win_rate_1h": 1.0,
                    "avg_return_1h": 0.0325,
                    "profit_factor_1h": 0.0,
                    "avg_mfe": 0.05,
                    "avg_mae": -0.01,
                }
            ],
            details=[
                {
                    "symbol": symbol,
                    "signal_type": "VOLUME_PRICE_OI_RESONANCE",
                    "level": "B",
                    "score": 72,
                    "trigger_time": 1_700_000_000_000,
                    "trigger_price": 100.0,
                    "1h": 0.0325,
                    "mfe": 0.05,
                    "mae": -0.01,
                    "reasons": "L2 strong rally / L2 强拉主升确认",
                }
            ],
        )

    monkeypatch.setattr(web_server, "run_radar_replay", fake_run)
    client = TestClient(create_app())
    form_page = client.get("/replay")
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', form_page.text).group(1)

    response = client.post("/replay", data={"csrf_token": csrf_token, "symbol": "ETH/USDT:USDT", "days": "7", "warmup_bars": "120", "cooldown_bars": "6"})

    assert response.status_code == 200
    assert "Replay generated 1 signals" in response.text
    assert "量价OI共振" in response.text
    assert "+3.25%" in response.text
    assert "ETH/USDT:USDT" in response.text


def test_logs_page_renders_local_work_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "alert_radar.log").write_text(
        "2026-06-21 17:59:31,264 INFO root Alert radar cycle finished with 0 alerts\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_server, "BASE_DIR", tmp_path)
    client = TestClient(create_app())

    response = client.get("/logs")

    assert response.status_code == 200
    assert "Work Logs" in response.text
    assert "Radar Loop" in response.text
    assert "Alert radar cycle finished with 0 alerts" in response.text
    assert 'href="/logs"' in response.text


def test_logs_page_hides_noisy_paper_routine_by_default(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "trading_bot.log").write_text(
        "\n".join(
            [
                "2026-06-22 10:08:07,100 INFO __main__ Signal BTC/USDT:USDT none: breakout or volume condition not met",
                "2026-06-22 10:08:07,200 INFO __main__ Risk ignored non-actionable signal BTC/USDT:USDT: signal is not actionable",
                "2026-06-22 10:08:07,300 INFO __main__ Paper account equity=1019.90 available=719.90 used_margin=300.00 realized_pnl=19.47 unrealized_pnl=0.43 open_positions=3",
            ]
        ),
        encoding="utf-8",
    )

    default_view = load_work_log_view(tmp_path, limit=20)
    paper_view = load_work_log_view(tmp_path, source="paper_cycle", limit=20)

    assert [entry.message for entry in default_view["entries"]] == [
        "Paper account equity=1019.90 available=719.90 used_margin=300.00 realized_pnl=19.47 unrealized_pnl=0.43 open_positions=3"
    ]
    assert len(paper_view["entries"]) == 3
    assert classify_source("__main__", "Paper account equity=1019.90 available=719.90") == "paper_cycle"


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


def test_env_editor_rejects_invalid_numeric_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("POLL_INTERVAL_SECONDS=60\n", encoding="utf-8")

    try:
        update_env_values(env_path, {"POLL_INTERVAL_SECONDS": "0"})
    except ValueError as exc:
        assert "Integer env value" in str(exc)
    else:
        raise AssertionError("invalid env value should be rejected")

    assert env_path.read_text(encoding="utf-8") == "POLL_INTERVAL_SECONDS=60\n"
