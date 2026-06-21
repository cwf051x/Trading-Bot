"""Configuration loading tests.
配置加载测试。
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import RunMode, Settings


def test_settings_defaults(monkeypatch) -> None:
    for key in (
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_PROXY",
        "DATABASE_PATH",
        "RUN_MODE",
        "ENABLE_LIVE_TRADING",
        "BTC_DROP_THRESHOLD_15M",
        "ACCOUNT_EQUITY",
        "DEFAULT_SYMBOL",
        "WATCH_SYMBOLS",
        "DEFAULT_TIMEFRAME",
        "EXCHANGE_PROXY",
        "POLL_INTERVAL_SECONDS",
        "KLINE_LIMIT",
        "PAPER_LEVERAGE",
        "STRATEGY_BREAKOUT_WINDOW",
        "STRATEGY_VOLUME_WINDOW",
        "STRATEGY_VOLUME_MULTIPLIER",
        "STRATEGY_STOP_LOSS_PCT",
        "STRATEGY_TAKE_PROFIT_PCT",
        "WEB_ADMIN_TOKEN",
        "WEB_HOST",
        "WEB_PORT",
            "ALERT_RADAR_ENABLED",
            "ALERT_AUTO_PAPER_TRADING_ENABLED",
            "ALERT_SCAN_INTERVAL_SECONDS",
            "ALERT_TOP_GAINERS_LIMIT",
            "ALERT_MAX_ALERTS_PER_CYCLE",
            "ALERT_MIN_SCORE_TO_STORE",
            "ALERT_MIN_24H_QUOTE_VOLUME_USDT",
        "ALERT_BLACKLIST",
        "ALERT_WATCHLIST",
        "ALERT_SEND_A_LEVEL",
        "ALERT_SEND_B_LEVEL",
        "ALERT_SEND_C_LEVEL",
        "ALERT_COOLDOWN_A_SECONDS",
        "ALERT_COOLDOWN_B_SECONDS",
        "ALERT_COOLDOWN_C_SECONDS",
        "ALERT_SURGE_3M_THRESHOLD",
        "ALERT_SURGE_5M_THRESHOLD",
        "ALERT_SURGE_15M_THRESHOLD",
        "ALERT_VOLUME_RATIO_THRESHOLD",
        "ALERT_PULLBACK_MIN_RATIO",
        "ALERT_PULLBACK_MAX_RATIO",
        "ALERT_BTC_DUMP_15M_THRESHOLD",
        "ALERT_HIGH_RISK_15M_CHANGE",
        "ALERT_HIGH_RISK_1H_CHANGE",
        "ALERT_MIN_BREAKOUT_CLOSE_POSITION",
        "ALERT_SECOND_LEG_MIN_CLOSE_POSITION",
        "ALERT_PULLBACK_VOLUME_CONTRACTION_MAX",
        "ALERT_OVERHEAT_RSI",
        "ALERT_CANDIDATE_TOP_N",
        "ALERT_OI_TOP_N",
        "ALERT_KLINE_FAST_TTL_SECONDS",
        "ALERT_KLINE_MEDIUM_TTL_SECONDS",
        "ALERT_KLINE_SLOW_TTL_SECONDS",
        "ALERT_OI_TTL_SECONDS",
        "ALERT_HOT_SYMBOL_TTL_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)

    assert settings.run_mode == RunMode.PAPER
    assert settings.database_path == Path("data/trading_bot.sqlite")
    assert settings.exchange_proxy == ""
    assert settings.telegram_proxy == ""
    assert settings.poll_interval_seconds == 60
    assert settings.kline_limit == 120
    assert settings.watch_symbols == []
    assert settings.active_symbols == ["BTC/USDT:USDT"]
    assert settings.paper_leverage == 1.0
    assert settings.strategy_breakout_window == 20
    assert settings.strategy_volume_multiplier == 1.5
    assert settings.web_host == "127.0.0.1"
    assert settings.web_port == 8000
    assert settings.alert_radar_enabled is True
    assert settings.alert_auto_paper_trading_enabled is True
    assert settings.alert_scan_interval_seconds == 60
    assert settings.alert_top_gainers_limit == 30
    assert settings.alert_max_alerts_per_cycle == 5
    assert settings.alert_min_score_to_store == 70
    assert settings.alert_min_24h_quote_volume_usdt == 10_000_000
    assert settings.alert_blacklist == []
    assert settings.alert_watchlist == []
    assert settings.alert_send_a_level is True
    assert settings.alert_send_b_level is True
    assert settings.alert_send_c_level is False
    assert settings.alert_btc_dump_15m_threshold == -0.008
    assert settings.alert_min_breakout_close_position == 0.65
    assert settings.alert_second_leg_min_close_position == 0.55
    assert settings.alert_pullback_volume_contraction_max == 1.0
    assert settings.alert_overheat_rsi == 82.0
    assert settings.alert_candidate_top_n == 50
    assert settings.alert_oi_top_n == 30
    assert settings.alert_kline_fast_ttl_seconds == 0
    assert settings.alert_kline_medium_ttl_seconds == 180
    assert settings.alert_kline_slow_ttl_seconds == 600
    assert settings.alert_oi_ttl_seconds == 60
    assert settings.alert_hot_symbol_ttl_seconds == 900
    assert settings.live_trading_allowed is False


def test_exchange_proxy_setting() -> None:
    settings = Settings(EXCHANGE_PROXY="http://127.0.0.1:7890")

    assert settings.exchange_proxy == "http://127.0.0.1:7890"


def test_telegram_proxy_setting() -> None:
    settings = Settings(TELEGRAM_PROXY="http://127.0.0.1:7890")

    assert settings.telegram_proxy == "http://127.0.0.1:7890"


def test_watch_symbols_parse_comma_separated_env() -> None:
    settings = Settings(WATCH_SYMBOLS="BTC/USDT:USDT, ETH/USDT:USDT,SOL/USDT:USDT")

    assert settings.watch_symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
    assert settings.active_symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]


def test_alert_symbol_lists_parse_comma_separated_env() -> None:
    settings = Settings(ALERT_BLACKLIST="USDCUSDT,FDUSDUSDT", ALERT_WATCHLIST="BTCUSDT,ETH/USDT:USDT")

    assert settings.alert_blacklist == ["USDCUSDT", "FDUSDUSDT"]
    assert settings.alert_watchlist == ["BTCUSDT", "ETH/USDT:USDT"]


def test_live_trading_requires_mode_and_flag() -> None:
    paper = Settings(RUN_MODE="paper", ENABLE_LIVE_TRADING=True)
    live = Settings(RUN_MODE="live", ENABLE_LIVE_TRADING=True)

    assert paper.live_trading_allowed is False
    assert live.live_trading_allowed is True


def test_invalid_run_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(RUN_MODE="invalid")
