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
        "TELEGRAM_ORDER_ENABLED",
        "TELEGRAM_ORDER_BOT_TOKEN",
        "TELEGRAM_ORDER_CHAT_ID",
        "TELEGRAM_ORDER_PROXY",
        "DATABASE_PATH",
        "RUN_MODE",
        "ENABLE_LIVE_TRADING",
        "BTC_DROP_THRESHOLD_15M",
        "ACCOUNT_EQUITY",
        "DEFAULT_SYMBOL",
        "WATCH_SYMBOLS",
        "DEFAULT_TIMEFRAME",
        "EXCHANGE_NETWORK_MODE",
        "EXCHANGE_PROXY",
        "EXCHANGE_REQUEST_RETRIES",
        "EXCHANGE_RETRY_DELAY_SECONDS",
        "POLL_INTERVAL_SECONDS",
        "PAPER_ERROR_NOTIFY_CONSECUTIVE_FAILURES",
        "KLINE_LIMIT",
        "PAPER_LEVERAGE",
        "PAPER_FEE_RATE",
        "PAPER_SLIPPAGE_PCT",
        "PAPER_FUNDING_RATE",
        "RISK_MAX_TOTAL_EXPOSURE_PCT",
        "RISK_MAX_OPEN_POSITIONS",
        "RISK_MAX_SYMBOL_POSITION_PCT",
        "RISK_PER_TRADE_PCT",
        "RISK_MAX_CONSECUTIVE_LOSSES",
        "RISK_LOSS_COOLDOWN_SECONDS",
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
        "ALERT_DIGEST_ENABLED",
        "ALERT_DIGEST_INTERVAL_SECONDS",
        "ALERT_DIGEST_TOP_N",
        "ALERT_DIGEST_LOOKBACK_SECONDS",
        "ALERT_DIGEST_ACTIVE_SECONDS",
        "ALERT_DIGEST_NEWCOMER_SECONDS",
        "ALERT_DIGEST_NEWCOMER_TOP_N",
        "ALERT_DIGEST_MIN_SCORE",
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
        "ALERT_CANDIDATE_GAINERS_TOP_N",
        "ALERT_CANDIDATE_VOLUME_TOP_N",
        "ALERT_CANDIDATE_RECENT_CHANGE_TOP_N",
        "ALERT_OI_TOP_N",
        "ALERT_KLINE_FAST_TTL_SECONDS",
        "ALERT_KLINE_MEDIUM_TTL_SECONDS",
        "ALERT_KLINE_SLOW_TTL_SECONDS",
        "ALERT_OI_TTL_SECONDS",
        "ALERT_HOT_SYMBOL_TTL_SECONDS",
        "ALERT_FETCH_CONCURRENCY",
        "ALERT_FETCH_MIN_INTERVAL_SECONDS",
        "ALERT_INCREMENTAL_KLINES_ENABLED",
        "ALERT_INCREMENTAL_KLINE_TAIL_LIMIT",
        "ALERT_FULL_KLINE_REFRESH_SECONDS",
        "ALERT_KLINE_CACHE_MAX_LENGTH",
        "ALERT_RATE_LIMIT_BACKOFF_SECONDS",
        "ALERT_RATE_LIMIT_BACKOFF_CONCURRENCY",
        "ALERT_RATE_LIMIT_BACKOFF_MIN_INTERVAL_SECONDS",
        "ALERT_OI_HOT_TTL_SECONDS",
        "ALERT_OI_WARM_TTL_SECONDS",
        "ALERT_OI_COLD_TTL_SECONDS",
        "ALERT_OI_MAX_REFRESH_PER_LOOP",
        "ALERT_FUNDING_RATE_TTL_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)

    assert settings.run_mode == RunMode.PAPER
    assert settings.database_path == Path("data/trading_bot.sqlite")
    assert settings.exchange_proxy == ""
    assert settings.telegram_proxy == ""
    assert settings.telegram_order_enabled is True
    assert settings.telegram_order_bot_token == ""
    assert settings.telegram_order_chat_id == ""
    assert settings.telegram_order_proxy == ""
    assert settings.poll_interval_seconds == 60
    assert settings.kline_limit == 120
    assert settings.watch_symbols == []
    assert settings.active_symbols == ["BTC/USDT:USDT"]
    assert settings.exchange_network_mode == "direct"
    assert settings.exchange_request_retries == 2
    assert settings.exchange_retry_delay_seconds == 1.0
    assert settings.paper_error_notify_consecutive_failures == 3
    assert settings.paper_leverage == 1.0
    assert settings.paper_fee_rate == 0.0
    assert settings.paper_slippage_pct == 0.0
    assert settings.paper_funding_rate == 0.0
    assert settings.risk_max_total_exposure_pct == 0.50
    assert settings.risk_max_open_positions == 5
    assert settings.risk_max_symbol_position_pct == 0.10
    assert settings.risk_per_trade_pct == 0.01
    assert settings.risk_max_consecutive_losses == 3
    assert settings.risk_loss_cooldown_seconds == 3600
    assert settings.strategy_breakout_window == 20
    assert settings.strategy_volume_multiplier == 1.5
    assert settings.web_host == "127.0.0.1"
    assert settings.web_port == 8000
    assert settings.alert_radar_enabled is True
    assert settings.alert_auto_paper_trading_enabled is False
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
    assert settings.alert_digest_enabled is True
    assert settings.alert_digest_interval_seconds == 900
    assert settings.alert_digest_top_n == 10
    assert settings.alert_digest_lookback_seconds == 14400
    assert settings.alert_digest_active_seconds == 3600
    assert settings.alert_digest_newcomer_seconds == 900
    assert settings.alert_digest_newcomer_top_n == 5
    assert settings.alert_digest_min_score == 60
    assert settings.alert_btc_dump_15m_threshold == -0.008
    assert settings.alert_min_breakout_close_position == 0.65
    assert settings.alert_second_leg_min_close_position == 0.55
    assert settings.alert_pullback_volume_contraction_max == 1.0
    assert settings.alert_overheat_rsi == 82.0
    assert settings.alert_candidate_top_n == 80
    assert settings.alert_candidate_gainers_top_n == 30
    assert settings.alert_candidate_volume_top_n == 30
    assert settings.alert_candidate_recent_change_top_n == 30
    assert settings.alert_oi_top_n == 50
    assert settings.alert_kline_fast_ttl_seconds == 0
    assert settings.alert_kline_medium_ttl_seconds == 180
    assert settings.alert_kline_slow_ttl_seconds == 600
    assert settings.alert_oi_ttl_seconds == 60
    assert settings.alert_hot_symbol_ttl_seconds == 900
    assert settings.alert_fetch_concurrency == 6
    assert settings.alert_fetch_min_interval_seconds == 0.15
    assert settings.alert_incremental_klines_enabled is True
    assert settings.alert_incremental_kline_tail_limit == 3
    assert settings.alert_full_kline_refresh_seconds == 1800
    assert settings.alert_kline_cache_max_length == 200
    assert settings.alert_rate_limit_backoff_seconds == 120
    assert settings.alert_rate_limit_backoff_concurrency == 2
    assert settings.alert_rate_limit_backoff_min_interval_seconds == 0.5
    assert settings.alert_oi_hot_ttl_seconds == 30
    assert settings.alert_oi_warm_ttl_seconds == 90
    assert settings.alert_oi_cold_ttl_seconds == 600
    assert settings.alert_oi_max_refresh_per_loop == 30
    assert settings.alert_funding_rate_ttl_seconds == 900
    assert settings.live_trading_allowed is False


def test_exchange_proxy_setting() -> None:
    settings = Settings(EXCHANGE_NETWORK_MODE="proxy", EXCHANGE_PROXY="http://127.0.0.1:7890")

    assert settings.exchange_network_mode == "proxy"
    assert settings.exchange_proxy == "http://127.0.0.1:7890"


def test_invalid_exchange_network_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(EXCHANGE_NETWORK_MODE="auto")


def test_telegram_proxy_setting() -> None:
    settings = Settings(TELEGRAM_PROXY="http://127.0.0.1:7890")

    assert settings.telegram_proxy == "http://127.0.0.1:7890"


def test_telegram_order_channel_settings() -> None:
    settings = Settings(
        TELEGRAM_ORDER_ENABLED=False,
        TELEGRAM_ORDER_BOT_TOKEN="order-token",
        TELEGRAM_ORDER_CHAT_ID="order-chat",
        TELEGRAM_ORDER_PROXY="http://127.0.0.1:7890",
    )

    assert settings.telegram_order_enabled is False
    assert settings.telegram_order_bot_token == "order-token"
    assert settings.telegram_order_chat_id == "order-chat"
    assert settings.telegram_order_proxy == "http://127.0.0.1:7890"


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
