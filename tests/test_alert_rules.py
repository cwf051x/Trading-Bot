"""Market alert rule tests.
行情雷达规则测试。
"""

from app.alerts.alert_rules import AlertRuleEngine
from app.alerts.signal_models import AlertType, HourlyTrendStats, MarketMetrics, ResonanceStats, TimeframeStats
from app.config import Settings
from app.data.market_snapshot import build_market_metrics
from app.exchange.binance import Kline


def make_settings() -> Settings:
    """Return isolated settings for alert tests.
    返回雷达测试使用的隔离配置。
    """

    return Settings(_env_file=None)


def make_metrics(**overrides) -> MarketMetrics:
    """Build test market metrics.
    构建测试行情指标。
    """

    metrics = MarketMetrics(
        symbol="ALLO/USDT:USDT",
        price=1.2,
        price_change_24h=0.30,
        quote_volume_24h=50_000_000,
        rank_24h=8,
        high_24h=1.3,
        low_24h=0.8,
        stats_1m=TimeframeStats(change=0.005, volume_ratio=1.2),
        stats_3m=TimeframeStats(change=0.02, volume_ratio=2.0, recent_high=1.18, close_position=0.8),
        stats_5m=TimeframeStats(change=0.03, volume_ratio=2.1, recent_high=1.18, higher_lows=True, breakout=True, closes_above_ma=True, close_position=0.8),
        stats_15m=TimeframeStats(change=0.04, volume_ratio=1.9, recent_high=1.25, recent_low=1.05, higher_lows=True, breakout=True, close_position=0.7),
        stats_1h=TimeframeStats(change=0.08, volume_ratio=1.2),
        btc_15m_change=-0.002,
    )
    return MarketMetrics(**{**metrics.__dict__, **overrides})


def make_resonance(**overrides) -> ResonanceStats:
    stats = ResonanceStats(
        price_change_15m=0.04,
        price_change_30m=0.07,
        price_change_60m=0.12,
        volume_ratio=2.5,
        volume_continuity=4,
        oi_change_15m=0.04,
        oi_change_30m=0.09,
        oi_change_60m=0.12,
        ma7=1.18,
        ma25=1.10,
        ma99=0.95,
        rsi6=72,
        rsi24=68,
        bullish_5m_count_6=4,
        ma25_deviation=0.04,
    )
    return ResonanceStats(**{**stats.__dict__, **overrides})


def alert_types(metrics: MarketMetrics, state: dict | None = None) -> set[AlertType]:
    """Evaluate rules and return alert types.
    执行规则并返回提醒类型集合。
    """

    return {result.alert_type for result in AlertRuleEngine(make_settings()).evaluate(metrics, state)}


def make_hourly_trend(**overrides) -> HourlyTrendStats:
    """Build hourly trend stats for rule tests.
    构建小时级趋势规则测试指标。
    """

    stats = HourlyTrendStats(
        ma7=1.18,
        ma25=1.10,
        ma99=0.95,
        rsi6=72,
        rsi24=66,
        price_change_6h=0.10,
        price_change_12h=0.22,
        price_change_24h=0.35,
        current_1h_volume=1800,
        volume_avg_6h=1200,
        volume_avg_12h=1600,
        volume_avg_20h=1000,
        volume_avg_24h=1100,
        volume_avg_48h=1000,
        volume_ratio=1.8,
        oi_change_6h=0.10,
        oi_change_12h=0.18,
        oi_change_24h=0.30,
        distance_to_ma7=0.015,
        distance_to_ma25=0.09,
        bullish_1h_count_12=9,
        long_upper_wick_1h=False,
        long_upper_wick_2h=False,
        consecutive_red_1h=False,
        close_above_high_12h_previous=True,
        ma7_slope=0.01,
        ma25_slope=0.006,
        recent_3h_holds_ma25=True,
        pullback_from_recent_high=0.06,
        near_ma7_or_ma25=True,
        rsi15m_crossed_up=True,
        reversal_15m=True,
        pullback_volume_safe=True,
        oi_pullback_from_high=0.05,
        funding_rate=0.0002,
        ma_structure="多头排列",
    )
    return HourlyTrendStats(**{**stats.__dict__, **overrides})


def test_top_gainer_momentum_rule() -> None:
    types = alert_types(make_metrics(resonance=make_resonance()))

    assert AlertType.VOLUME_PRICE_OI_RESONANCE in types


def test_legacy_alert_rules_are_disabled() -> None:
    types = alert_types(make_metrics())

    assert AlertType.TOP_GAINER_MOMENTUM not in types


def test_short_term_surge_rule() -> None:
    metrics = make_metrics(stats_3m=TimeframeStats(change=0.02, volume_ratio=2.0, recent_high=1.18, close_position=0.8))

    types = alert_types(metrics)

    assert AlertType.SHORT_TERM_SURGE not in types


def test_short_term_surge_requires_strong_close() -> None:
    metrics = make_metrics(stats_3m=TimeframeStats(change=0.02, volume_ratio=2.0, recent_high=1.18), stats_5m=TimeframeStats(change=0.03, volume_ratio=2.1, recent_high=1.18, close_position=0.3))

    types = alert_types(metrics)

    assert AlertType.SHORT_TERM_SURGE not in types


def test_multi_timeframe_breakout_rule() -> None:
    types = alert_types(make_metrics())

    assert AlertType.MULTI_TIMEFRAME_BREAKOUT not in types


def test_strong_pullback_watch_rule() -> None:
    metrics = make_metrics(
        price=1.10,
        stats_5m=TimeframeStats(change=-0.01, volume_ratio=0.8, recent_high=1.20, higher_lows=True, closes_above_ma=False, close_position=0.5),
        stats_15m=TimeframeStats(change=-0.02, volume_ratio=0.8, recent_high=1.25, recent_low=1.02, pullback_ratio=0.12, higher_lows=True, close_position=0.4),
    )

    types = alert_types(metrics)

    assert AlertType.STRONG_PULLBACK_WATCH not in types


def test_pullback_second_leg_rule() -> None:
    metrics = make_metrics(
        stats_5m=TimeframeStats(change=0.025, volume_ratio=2.1, recent_high=1.18, higher_lows=True, closes_above_ma=True, close_position=0.7),
        stats_15m=TimeframeStats(change=0.03, volume_ratio=1.8, recent_high=1.25, recent_low=1.05, higher_lows=True, close_position=0.65),
    )

    types = alert_types(metrics, {"state": "pullback_watch", "support_price": 1.02, "watch_high": 1.25})

    assert AlertType.PULLBACK_SECOND_LEG not in types


def test_high_risk_extension_rule() -> None:
    metrics = make_metrics(resonance=make_resonance(price_change_60m=0.22, rsi6=88, ma25_deviation=0.12, oi_change_60m=0.25, long_upper_wick=True))

    types = alert_types(metrics)

    assert AlertType.VOLUME_PRICE_OI_RESONANCE in types


def test_hourly_trend_t3_pullback_has_priority() -> None:
    metrics = make_metrics(trend=make_hourly_trend())

    results = AlertRuleEngine(make_settings()).evaluate(metrics)

    assert results[0].alert_type == AlertType.HOURLY_TREND_T3
    assert results[0].metadata["trend_level"] == "T3"
    assert "回踩接多观察" in results[0].suggested_action


def test_hourly_trend_t4_is_risk_only() -> None:
    metrics = make_metrics(
        trend=make_hourly_trend(
            price_change_24h=0.55,
            distance_to_ma25=0.22,
            rsi6=88,
            rsi24=78,
            oi_change_24h=0.45,
            long_upper_wick_1h=True,
            pullback_from_recent_high=0.0,
            near_ma7_or_ma25=False,
            rsi15m_crossed_up=False,
            reversal_15m=False,
        )
    )

    results = AlertRuleEngine(make_settings()).evaluate(metrics)

    assert results[0].alert_type == AlertType.HOURLY_TREND_T4
    assert results[0].metadata["auto_paper"] is False
    assert "不是做空信号" in results[0].suggested_action


def test_btc_dump_blocks_long_bias_alerts() -> None:
    metrics = make_metrics(btc_15m_change=-0.02)

    types = alert_types(metrics)

    assert AlertType.MULTI_TIMEFRAME_BREAKOUT not in types


def test_insufficient_market_data_returns_no_metrics() -> None:
    ticker = {"symbol": "ALLO/USDT:USDT", "last": 1.0, "percentage": 10, "quote_volume": 20_000_000}
    one_kline = [Kline(timestamp=1, open=1, high=1, low=1, close=1, volume=1)]

    metrics = build_market_metrics(ticker, {"1m": one_kline, "3m": one_kline, "5m": one_kline, "15m": one_kline, "1h": one_kline}, 0.0, 1)

    assert metrics is None
