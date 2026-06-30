"""Application configuration loaded from environment variables.
从环境变量和 `.env` 加载应用配置。
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class RunMode(str, Enum):
    """Supported runtime modes.
    支持的运行模式。
    """

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    """Runtime settings read from `.env` and process environment.
    从 `.env` 文件和进程环境变量读取的运行时配置。
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    binance_api_key: str = Field(default="", alias="BINANCE_API_KEY")
    binance_api_secret: str = Field(default="", alias="BINANCE_API_SECRET")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    telegram_proxy: str = Field(default="", alias="TELEGRAM_PROXY")
    telegram_order_enabled: bool = Field(default=True, alias="TELEGRAM_ORDER_ENABLED")
    telegram_order_bot_token: str = Field(default="", alias="TELEGRAM_ORDER_BOT_TOKEN")
    telegram_order_chat_id: str = Field(default="", alias="TELEGRAM_ORDER_CHAT_ID")
    telegram_order_proxy: str = Field(default="", alias="TELEGRAM_ORDER_PROXY")
    database_path: Path = Field(default=Path("data/trading_bot.sqlite"), alias="DATABASE_PATH")
    run_mode: RunMode = Field(default=RunMode.PAPER, alias="RUN_MODE")
    enable_live_trading: bool = Field(default=False, alias="ENABLE_LIVE_TRADING")
    btc_drop_threshold_15m: float = Field(default=0.03, alias="BTC_DROP_THRESHOLD_15M")
    account_equity: float = Field(default=10_000.0, alias="ACCOUNT_EQUITY")
    default_symbol: str = Field(default="BTC/USDT:USDT", alias="DEFAULT_SYMBOL")
    watch_symbols: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="WATCH_SYMBOLS")
    default_timeframe: str = Field(default="15m", alias="DEFAULT_TIMEFRAME")
    exchange_network_mode: str = Field(default="direct", alias="EXCHANGE_NETWORK_MODE")
    exchange_proxy: str = Field(default="", alias="EXCHANGE_PROXY")
    exchange_request_retries: int = Field(default=2, alias="EXCHANGE_REQUEST_RETRIES")
    exchange_retry_delay_seconds: float = Field(default=1.0, alias="EXCHANGE_RETRY_DELAY_SECONDS")
    poll_interval_seconds: int = Field(default=60, alias="POLL_INTERVAL_SECONDS")
    paper_error_notify_consecutive_failures: int = Field(default=3, alias="PAPER_ERROR_NOTIFY_CONSECUTIVE_FAILURES")
    kline_limit: int = Field(default=120, alias="KLINE_LIMIT")
    paper_leverage: float = Field(default=1.0, alias="PAPER_LEVERAGE")
    paper_fee_rate: float = Field(default=0.0, alias="PAPER_FEE_RATE")
    paper_slippage_pct: float = Field(default=0.0, alias="PAPER_SLIPPAGE_PCT")
    paper_funding_rate: float = Field(default=0.0, alias="PAPER_FUNDING_RATE")
    risk_max_total_exposure_pct: float = Field(default=0.50, alias="RISK_MAX_TOTAL_EXPOSURE_PCT")
    risk_max_open_positions: int = Field(default=5, alias="RISK_MAX_OPEN_POSITIONS")
    risk_max_symbol_position_pct: float = Field(default=0.10, alias="RISK_MAX_SYMBOL_POSITION_PCT")
    risk_per_trade_pct: float = Field(default=0.01, alias="RISK_PER_TRADE_PCT")
    risk_max_consecutive_losses: int = Field(default=3, alias="RISK_MAX_CONSECUTIVE_LOSSES")
    risk_loss_cooldown_seconds: int = Field(default=3600, alias="RISK_LOSS_COOLDOWN_SECONDS")
    strategy_breakout_window: int = Field(default=20, alias="STRATEGY_BREAKOUT_WINDOW")
    strategy_volume_window: int = Field(default=20, alias="STRATEGY_VOLUME_WINDOW")
    strategy_volume_multiplier: float = Field(default=1.5, alias="STRATEGY_VOLUME_MULTIPLIER")
    strategy_stop_loss_pct: float = Field(default=0.02, alias="STRATEGY_STOP_LOSS_PCT")
    strategy_take_profit_pct: float = Field(default=0.04, alias="STRATEGY_TAKE_PROFIT_PCT")
    web_admin_token: str = Field(default="", alias="WEB_ADMIN_TOKEN")
    web_host: str = Field(default="127.0.0.1", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")
    alert_radar_enabled: bool = Field(default=True, alias="ALERT_RADAR_ENABLED")
    alert_auto_paper_trading_enabled: bool = Field(default=False, alias="ALERT_AUTO_PAPER_TRADING_ENABLED")
    alert_scan_interval_seconds: int = Field(default=60, alias="ALERT_SCAN_INTERVAL_SECONDS")
    alert_top_gainers_limit: int = Field(default=30, alias="ALERT_TOP_GAINERS_LIMIT")
    alert_max_alerts_per_cycle: int = Field(default=5, alias="ALERT_MAX_ALERTS_PER_CYCLE")
    alert_min_score_to_store: int = Field(default=70, alias="ALERT_MIN_SCORE_TO_STORE")
    alert_min_24h_quote_volume_usdt: float = Field(default=10_000_000.0, alias="ALERT_MIN_24H_QUOTE_VOLUME_USDT")
    alert_blacklist: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="ALERT_BLACKLIST")
    alert_watchlist: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="ALERT_WATCHLIST")
    alert_send_a_level: bool = Field(default=True, alias="ALERT_SEND_A_LEVEL")
    alert_send_b_level: bool = Field(default=True, alias="ALERT_SEND_B_LEVEL")
    alert_send_c_level: bool = Field(default=False, alias="ALERT_SEND_C_LEVEL")
    alert_cooldown_a_seconds: int = Field(default=300, alias="ALERT_COOLDOWN_A_SECONDS")
    alert_cooldown_b_seconds: int = Field(default=600, alias="ALERT_COOLDOWN_B_SECONDS")
    alert_cooldown_c_seconds: int = Field(default=1800, alias="ALERT_COOLDOWN_C_SECONDS")
    alert_digest_enabled: bool = Field(default=True, alias="ALERT_DIGEST_ENABLED")
    alert_digest_interval_seconds: int = Field(default=900, alias="ALERT_DIGEST_INTERVAL_SECONDS")
    alert_digest_top_n: int = Field(default=10, alias="ALERT_DIGEST_TOP_N")
    alert_digest_lookback_seconds: int = Field(default=14400, alias="ALERT_DIGEST_LOOKBACK_SECONDS")
    alert_digest_active_seconds: int = Field(default=3600, alias="ALERT_DIGEST_ACTIVE_SECONDS")
    alert_digest_newcomer_seconds: int = Field(default=900, alias="ALERT_DIGEST_NEWCOMER_SECONDS")
    alert_digest_newcomer_top_n: int = Field(default=5, alias="ALERT_DIGEST_NEWCOMER_TOP_N")
    alert_digest_min_score: int = Field(default=60, alias="ALERT_DIGEST_MIN_SCORE")
    alert_surge_3m_threshold: float = Field(default=0.015, alias="ALERT_SURGE_3M_THRESHOLD")
    alert_surge_5m_threshold: float = Field(default=0.025, alias="ALERT_SURGE_5M_THRESHOLD")
    alert_surge_15m_threshold: float = Field(default=0.04, alias="ALERT_SURGE_15M_THRESHOLD")
    alert_volume_ratio_threshold: float = Field(default=1.8, alias="ALERT_VOLUME_RATIO_THRESHOLD")
    alert_pullback_min_ratio: float = Field(default=0.05, alias="ALERT_PULLBACK_MIN_RATIO")
    alert_pullback_max_ratio: float = Field(default=0.15, alias="ALERT_PULLBACK_MAX_RATIO")
    alert_btc_dump_15m_threshold: float = Field(default=-0.008, alias="ALERT_BTC_DUMP_15M_THRESHOLD")
    alert_high_risk_15m_change: float = Field(default=0.08, alias="ALERT_HIGH_RISK_15M_CHANGE")
    alert_high_risk_1h_change: float = Field(default=0.18, alias="ALERT_HIGH_RISK_1H_CHANGE")
    alert_min_breakout_close_position: float = Field(default=0.65, alias="ALERT_MIN_BREAKOUT_CLOSE_POSITION")
    alert_second_leg_min_close_position: float = Field(default=0.55, alias="ALERT_SECOND_LEG_MIN_CLOSE_POSITION")
    alert_pullback_volume_contraction_max: float = Field(default=1.0, alias="ALERT_PULLBACK_VOLUME_CONTRACTION_MAX")
    alert_overheat_rsi: float = Field(default=82.0, alias="ALERT_OVERHEAT_RSI")
    alert_candidate_top_n: int = Field(default=80, alias="ALERT_CANDIDATE_TOP_N")
    alert_candidate_gainers_top_n: int = Field(default=30, alias="ALERT_CANDIDATE_GAINERS_TOP_N")
    alert_candidate_volume_top_n: int = Field(default=30, alias="ALERT_CANDIDATE_VOLUME_TOP_N")
    alert_candidate_recent_change_top_n: int = Field(default=30, alias="ALERT_CANDIDATE_RECENT_CHANGE_TOP_N")
    alert_oi_top_n: int = Field(default=50, alias="ALERT_OI_TOP_N")
    alert_kline_fast_ttl_seconds: int = Field(default=0, alias="ALERT_KLINE_FAST_TTL_SECONDS")
    alert_kline_medium_ttl_seconds: int = Field(default=180, alias="ALERT_KLINE_MEDIUM_TTL_SECONDS")
    alert_kline_slow_ttl_seconds: int = Field(default=600, alias="ALERT_KLINE_SLOW_TTL_SECONDS")
    alert_oi_ttl_seconds: int = Field(default=60, alias="ALERT_OI_TTL_SECONDS")
    alert_hot_symbol_ttl_seconds: int = Field(default=900, alias="ALERT_HOT_SYMBOL_TTL_SECONDS")
    alert_fetch_concurrency: int = Field(default=6, alias="ALERT_FETCH_CONCURRENCY")
    alert_fetch_min_interval_seconds: float = Field(default=0.15, alias="ALERT_FETCH_MIN_INTERVAL_SECONDS")
    alert_incremental_klines_enabled: bool = Field(default=True, alias="ALERT_INCREMENTAL_KLINES_ENABLED")
    alert_incremental_kline_tail_limit: int = Field(default=3, alias="ALERT_INCREMENTAL_KLINE_TAIL_LIMIT")
    alert_full_kline_refresh_seconds: int = Field(default=1800, alias="ALERT_FULL_KLINE_REFRESH_SECONDS")
    alert_kline_cache_max_length: int = Field(default=200, alias="ALERT_KLINE_CACHE_MAX_LENGTH")
    alert_rate_limit_backoff_seconds: int = Field(default=120, alias="ALERT_RATE_LIMIT_BACKOFF_SECONDS")
    alert_rate_limit_backoff_concurrency: int = Field(default=2, alias="ALERT_RATE_LIMIT_BACKOFF_CONCURRENCY")
    alert_rate_limit_backoff_min_interval_seconds: float = Field(default=0.5, alias="ALERT_RATE_LIMIT_BACKOFF_MIN_INTERVAL_SECONDS")
    alert_oi_hot_ttl_seconds: int = Field(default=30, alias="ALERT_OI_HOT_TTL_SECONDS")
    alert_oi_warm_ttl_seconds: int = Field(default=90, alias="ALERT_OI_WARM_TTL_SECONDS")
    alert_oi_cold_ttl_seconds: int = Field(default=600, alias="ALERT_OI_COLD_TTL_SECONDS")
    alert_oi_max_refresh_per_loop: int = Field(default=30, alias="ALERT_OI_MAX_REFRESH_PER_LOOP")
    alert_funding_rate_ttl_seconds: int = Field(default=900, alias="ALERT_FUNDING_RATE_TTL_SECONDS")

    @field_validator("watch_symbols", mode="before")
    @classmethod
    def parse_watch_symbols(cls, value: object) -> list[str]:
        """Parse comma-separated watch symbols from `.env`.
        从 `.env` 解析逗号分隔的监控交易对。
        """

        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [symbol.strip() for symbol in value.split(",") if symbol.strip()]
        if isinstance(value, list):
            return [str(symbol).strip() for symbol in value if str(symbol).strip()]
        raise TypeError("WATCH_SYMBOLS must be a comma-separated string or list")

    @field_validator("alert_blacklist", "alert_watchlist", mode="before")
    @classmethod
    def parse_alert_symbol_lists(cls, value: object) -> list[str]:
        """Parse comma-separated alert symbol lists from `.env`.
        从 `.env` 解析行情雷达交易对列表。
        """

        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [symbol.strip() for symbol in value.split(",") if symbol.strip()]
        if isinstance(value, list):
            return [str(symbol).strip() for symbol in value if str(symbol).strip()]
        raise TypeError("Alert symbol lists must be comma-separated strings or lists")

    @field_validator("exchange_network_mode")
    @classmethod
    def validate_exchange_network_mode(cls, value: str) -> str:
        """Normalize the exchange network strategy.
        规范化交易所网络策略，避免本地/生产环境走错代理路径。
        """

        normalized = value.strip().lower()
        allowed = {"direct", "proxy", "direct_fallback", "proxy_fallback"}
        if normalized not in allowed:
            raise ValueError(f"EXCHANGE_NETWORK_MODE must be one of {', '.join(sorted(allowed))}")
        return normalized

    @property
    def active_symbols(self) -> list[str]:
        """Return configured watch symbols with default symbol fallback.
        返回实际监控交易对，未配置时回退到默认交易对。
        """

        return self.watch_symbols or [self.default_symbol]

    @property
    def live_trading_allowed(self) -> bool:
        """Return whether real orders may be attempted.
        判断当前配置是否允许尝试真实下单。
        """

        return self.run_mode == RunMode.LIVE and self.enable_live_trading


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings.
    返回带缓存的应用配置对象。
    """

    return Settings()
