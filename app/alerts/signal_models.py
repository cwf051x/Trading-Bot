"""Data models for market alert radar signals.
行情雷达信号的数据模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AlertType(str, Enum):
    """Supported radar alert types.
    支持的雷达提醒类型。
    """

    TOP_GAINER_MOMENTUM = "TOP_GAINER_MOMENTUM"
    SHORT_TERM_SURGE = "SHORT_TERM_SURGE"
    MULTI_TIMEFRAME_BREAKOUT = "MULTI_TIMEFRAME_BREAKOUT"
    STRONG_PULLBACK_WATCH = "STRONG_PULLBACK_WATCH"
    PULLBACK_SECOND_LEG = "PULLBACK_SECOND_LEG"
    HIGH_RISK_EXTENSION = "HIGH_RISK_EXTENSION"
    VOLUME_PRICE_OI_RESONANCE = "VOLUME_PRICE_OI_RESONANCE"
    HOURLY_TREND_T1 = "HOURLY_TREND_T1"
    HOURLY_TREND_T2 = "HOURLY_TREND_T2"
    HOURLY_TREND_T3 = "HOURLY_TREND_T3"
    HOURLY_TREND_T4 = "HOURLY_TREND_T4"
    PUMP_PULLBACK_P1 = "PUMP_PULLBACK_P1"
    PUMP_PULLBACK_P2 = "PUMP_PULLBACK_P2"
    PUMP_PULLBACK_P3 = "PUMP_PULLBACK_P3"
    PUMP_PULLBACK_P4 = "PUMP_PULLBACK_P4"


class AlertLevel(str, Enum):
    """Telegram and storage alert severity levels.
    Telegram 与数据库使用的提醒等级。
    """

    A = "A"
    B = "B"
    C = "C"
    IGNORE = "IGNORE"


@dataclass(frozen=True)
class TimeframeStats:
    """Compact derived statistics for one timeframe.
    单个周期的紧凑派生统计。
    """

    change: float = 0.0
    volume_ratio: float = 0.0
    recent_high: float | None = None
    recent_low: float | None = None
    higher_lows: bool = False
    breakout: bool = False
    pullback_ratio: float = 0.0
    closes_above_ma: bool = False
    rejection: bool = False
    large_green_count: int = 0
    distance_to_ma: float = 0.0
    close_position: float = 0.0
    rsi: float | None = None
    atr_ratio: float = 0.0


@dataclass(frozen=True)
class ResonanceStats:
    """Derived fields for volume-price-OI resonance.
    量价 OI 共振使用的派生字段。
    """

    price_change_15m: float = 0.0
    price_change_30m: float = 0.0
    price_change_60m: float = 0.0
    volume_ratio: float = 0.0
    volume_continuity: int = 0
    oi_change_15m: float = 0.0
    oi_change_30m: float = 0.0
    oi_change_60m: float = 0.0
    ma7: float = 0.0
    ma25: float = 0.0
    ma99: float = 0.0
    rsi6: float | None = None
    rsi24: float | None = None
    bullish_5m_count_6: int = 0
    ma25_deviation: float = 0.0
    long_upper_wick: bool = False
    consecutive_red_5m: bool = False


@dataclass(frozen=True)
class HourlyTrendStats:
    """Derived fields for hour-level one-way trend radar.
    小时级单边趋势雷达使用的派生字段。
    """

    ma7: float = 0.0
    ma25: float = 0.0
    ma99: float = 0.0
    rsi6: float | None = None
    rsi24: float | None = None
    price_change_6h: float = 0.0
    price_change_12h: float = 0.0
    price_change_24h: float = 0.0
    current_1h_volume: float = 0.0
    volume_avg_6h: float = 0.0
    volume_avg_12h: float = 0.0
    volume_avg_20h: float = 0.0
    volume_avg_24h: float = 0.0
    volume_avg_48h: float = 0.0
    volume_ratio: float = 0.0
    oi_change_6h: float = 0.0
    oi_change_12h: float = 0.0
    oi_change_24h: float = 0.0
    distance_to_ma7: float = 0.0
    distance_to_ma25: float = 0.0
    bullish_1h_count_12: int = 0
    long_upper_wick_1h: bool = False
    long_upper_wick_2h: bool = False
    consecutive_red_1h: bool = False
    close_above_high_12h_previous: bool = False
    ma7_slope: float = 0.0
    ma25_slope: float = 0.0
    recent_3h_holds_ma25: bool = False
    pullback_from_recent_high: float = 0.0
    near_ma7_or_ma25: bool = False
    rsi15m_crossed_up: bool = False
    reversal_15m: bool = False
    pullback_volume_safe: bool = False
    oi_pullback_from_high: float = 0.0
    funding_rate: float | None = None
    ma_structure: str = ""


@dataclass(frozen=True)
class PumpPullbackStats:
    """Derived fields for pump pullback and second-wave radar.
    爆拉后健康回调与二波启动雷达使用的派生字段。
    """

    has_first_pump: bool = False
    pump_start_time: int | None = None
    pump_high_time: int | None = None
    pump_start_price: float = 0.0
    pump_high: float = 0.0
    pump_change: float = 0.0
    pullback_from_high: float = 0.0
    retracement_ratio: float = 0.0
    pullback_volume_ratio: float = 0.0
    oi_drawdown_from_peak: float = 0.0
    price_above_pump_start: bool = False
    price_above_1h_ma25: bool = False
    price_above_1h_ma99: bool = False
    ma7_15m: float = 0.0
    ma25_15m: float = 0.0
    ma7_crossed_above_ma25_15m: bool = False
    rsi6_15m: float | None = None
    rsi24_15m: float | None = None
    rsi6_crossed_above_rsi24_15m: bool = False
    recent_15m_change_3bars: float = 0.0
    volume_ratio_15m: float = 0.0
    oi_change_30m: float = 0.0
    oi_change_1h: float = 0.0
    range_high: float = 0.0
    range_low: float = 0.0
    price_breaks_range_high: bool = False
    price_near_or_above_pump_high: bool = False
    one_hour_close_above_ma7: bool = False
    one_hour_reclaimed_ma7: bool = False
    fell_back_into_range: bool = False
    oi_up_price_down: bool = False
    long_upper_wick_15m: bool = False
    broke_pullback_low: bool = False
    ma_structure_15m: str = ""
    ma_structure_1h: str = ""


@dataclass(frozen=True)
class MarketMetrics:
    """Derived market metrics consumed by rules and scoring.
    供规则和评分使用的行情派生指标。
    """

    symbol: str
    price: float
    price_change_24h: float
    quote_volume_24h: float
    rank_24h: int | None
    high_24h: float | None
    low_24h: float | None
    stats_1m: TimeframeStats = field(default_factory=TimeframeStats)
    stats_3m: TimeframeStats = field(default_factory=TimeframeStats)
    stats_5m: TimeframeStats = field(default_factory=TimeframeStats)
    stats_15m: TimeframeStats = field(default_factory=TimeframeStats)
    stats_1h: TimeframeStats = field(default_factory=TimeframeStats)
    btc_15m_change: float = 0.0
    funding_rate: float | None = None
    open_interest: float | None = None
    resonance: ResonanceStats | None = None
    trend: HourlyTrendStats | None = None
    pump_pullback: PumpPullbackStats | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertSignal:
    """Normalized radar alert persisted and optionally sent to Telegram.
    标准化雷达提醒，会入库并按规则选择是否发送 Telegram。
    """

    timestamp: int
    symbol: str
    alert_type: AlertType
    level: AlertLevel
    score: int
    price: float
    price_change_3m: float
    price_change_5m: float
    price_change_15m: float
    price_change_1h: float
    price_change_24h: float
    volume_ratio: float
    btc_15m_change: float
    reasons: list[str]
    suggested_action: str
    invalidation_price: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    sent_to_telegram: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def reason_text(self) -> str:
        """Return a compact reason string for storage.
        返回适合入库的紧凑理由文本。
        """

        return "; ".join(self.reasons)

    @property
    def should_consider_notification(self) -> bool:
        """Return whether this alert level can be pushed.
        判断该等级是否具备推送资格。
        """

        return self.level in {AlertLevel.A, AlertLevel.B, AlertLevel.C}


@dataclass(frozen=True)
class AlertRuleResult:
    """Intermediate rule output before cooldown and persistence.
    冷却与持久化之前的规则中间结果。
    """

    alert_type: AlertType
    score: int
    reasons: list[str]
    suggested_action: str
    invalidation_price: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
