"""Historical replay utilities for radar signal quality checks.
雷达信号历史回放工具，用于评估准确性和及时性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.alerts.alert_rules import AlertRuleEngine
from app.alerts.rule_config import DEFAULT_RADAR_RULE_CONFIG
from app.data.market_snapshot import aggregate_klines, build_market_metrics
from app.exchange.binance import Kline, OpenInterestPoint


@dataclass(frozen=True)
class ReplayConfig:
    """Configuration for historical replay.
    历史回放配置。
    """

    min_warmup_bars: int = 120
    outcome_horizons: tuple[int, ...] = (3, 6, 12, 48, 288)
    cooldown_bars: int = 6
    quote_volume_24h: float = 0.0


@dataclass(frozen=True)
class ReplayOutcome:
    """One replayed signal and its forward performance.
    单条回放信号及其后验表现。
    """

    symbol: str
    signal_type: str
    level: str
    score: int
    trigger_time: int
    trigger_price: float
    forward_returns: dict[str, float] = field(default_factory=dict)
    max_favorable_return: float = 0.0
    max_adverse_return: float = 0.0
    reasons: str = ""


def replay_symbol(
    symbol: str,
    klines_5m: list[Kline],
    *,
    oi_5m: list[OpenInterestPoint] | None = None,
    oi_15m: list[OpenInterestPoint] | None = None,
    oi_1h: list[OpenInterestPoint] | None = None,
    config: ReplayConfig | None = None,
    radar_rule_config: dict[str, Any] | None = None,
    settings: Any | None = None,
) -> list[ReplayOutcome]:
    """Replay one symbol candle-by-candle without using future candles for signals.
    对单个交易对逐根 K 线回放；信号计算只使用当前及以前数据。
    """

    cfg = config or ReplayConfig()
    rule_config = radar_rule_config or DEFAULT_RADAR_RULE_CONFIG
    replay_settings = settings or _ReplaySettings(rule_config)
    engine = AlertRuleEngine(replay_settings)
    outcomes: list[ReplayOutcome] = []
    last_alert_bar: dict[str, int] = {}
    # Require only the shortest forward horizon so short local samples can still be evaluated.
    # Longer horizons are left blank when future candles are insufficient.
    latest_possible_index = max(cfg.min_warmup_bars, len(klines_5m) - min(cfg.outcome_horizons, default=1))
    for index in range(cfg.min_warmup_bars, latest_possible_index):
        history_5m = klines_5m[: index + 1]
        metrics = _build_replay_metrics(
            symbol,
            history_5m,
            oi_5m=_slice_oi(oi_5m, history_5m[-1].timestamp),
            oi_15m=_slice_oi(oi_15m, history_5m[-1].timestamp),
            oi_1h=_slice_oi(oi_1h, history_5m[-1].timestamp),
            quote_volume_24h=cfg.quote_volume_24h,
            radar_rule_config=rule_config,
        )
        if metrics is None:
            continue
        for result in engine.evaluate(metrics):
            key = f"{symbol}:{result.alert_type.value}"
            if key in last_alert_bar and index - last_alert_bar[key] < cfg.cooldown_bars:
                continue
            last_alert_bar[key] = index
            outcomes.append(_build_outcome(symbol, result, history_5m[-1], klines_5m[index + 1 :], cfg))
    return outcomes


def _build_replay_metrics(
    symbol: str,
    klines_5m: list[Kline],
    *,
    oi_5m: list[OpenInterestPoint],
    oi_15m: list[OpenInterestPoint],
    oi_1h: list[OpenInterestPoint],
    quote_volume_24h: float,
    radar_rule_config: dict[str, Any],
):
    """Build MarketMetrics from replay history only.
    只使用回放当前时刻以前的数据构建 MarketMetrics。
    """

    klines_15m = aggregate_klines(klines_5m, 3)
    klines_1h = aggregate_klines(klines_5m, 12)
    latest = klines_5m[-1]
    day_start_index = max(0, len(klines_5m) - 288)
    day_start = klines_5m[day_start_index].close
    ticker = {
        "symbol": symbol,
        "last": latest.close,
        "percentage": (latest.close / day_start - 1) * 100 if day_start else 0.0,
        "quote_volume": quote_volume_24h,
        "high": max(item.high for item in klines_5m[day_start_index:]),
        "low": min(item.low for item in klines_5m[day_start_index:]),
    }
    return build_market_metrics(
        ticker,
        {"5m": klines_5m, "15m": klines_15m, "1h": klines_1h},
        btc_15m_change=0.0,
        oi_history=oi_5m,
        trend_oi_history=oi_1h,
        pump_oi_history_15m=oi_15m,
        radar_rule_config=radar_rule_config,
        required_timeframes={"5m", "15m", "1h"},
    )


def _build_outcome(symbol: str, result: Any, trigger: Kline, future: list[Kline], config: ReplayConfig) -> ReplayOutcome:
    """Build forward performance for one triggered signal.
    为单个触发信号计算未来收益表现。
    """

    trigger_price = trigger.close
    horizon_returns: dict[str, float] = {}
    for bars in config.outcome_horizons:
        if len(future) >= bars:
            horizon_returns[_horizon_label(bars)] = future[bars - 1].close / trigger_price - 1
    evaluation_window = future[: max(config.outcome_horizons, default=1)]
    max_high = max((item.high for item in evaluation_window), default=trigger_price)
    min_low = min((item.low for item in evaluation_window), default=trigger_price)
    return ReplayOutcome(
        symbol=symbol,
        signal_type=result.alert_type.value,
        level=result.metadata.get("resonance_level") or result.metadata.get("trend_level") or result.metadata.get("pump_pullback_level") or "",
        score=result.score,
        trigger_time=trigger.timestamp,
        trigger_price=trigger_price,
        forward_returns=horizon_returns,
        max_favorable_return=max_high / trigger_price - 1,
        max_adverse_return=min_low / trigger_price - 1,
        reasons="; ".join(result.reasons),
    )


def _horizon_label(bars_5m: int) -> str:
    minutes = bars_5m * 5
    return f"{minutes // 60}h" if minutes >= 60 and minutes % 60 == 0 else f"{minutes}m"


def _slice_oi(history: list[OpenInterestPoint] | None, timestamp: int) -> list[OpenInterestPoint]:
    if not history:
        return []
    return [item for item in history if item.timestamp <= timestamp]


class _ReplaySettings:
    """Tiny settings object for AlertRuleEngine during replay.
    回放时供规则引擎读取的轻量配置对象。
    """

    def __init__(self, radar_rule_config: dict[str, Any]) -> None:
        self.radar_rule_config = radar_rule_config
