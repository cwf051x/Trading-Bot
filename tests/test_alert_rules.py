"""Market alert rule tests.
行情雷达规则测试。
"""

from app.alerts.alert_rules import AlertRuleEngine
from app.alerts.signal_models import AlertType, MarketMetrics, TimeframeStats
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


def alert_types(metrics: MarketMetrics, state: dict | None = None) -> set[AlertType]:
    """Evaluate rules and return alert types.
    执行规则并返回提醒类型集合。
    """

    return {result.alert_type for result in AlertRuleEngine(make_settings()).evaluate(metrics, state)}


def test_top_gainer_momentum_rule() -> None:
    types = alert_types(make_metrics())

    assert AlertType.TOP_GAINER_MOMENTUM in types


def test_short_term_surge_rule() -> None:
    metrics = make_metrics(stats_3m=TimeframeStats(change=0.02, volume_ratio=2.0, recent_high=1.18, close_position=0.8))

    types = alert_types(metrics)

    assert AlertType.SHORT_TERM_SURGE in types


def test_short_term_surge_requires_strong_close() -> None:
    metrics = make_metrics(stats_3m=TimeframeStats(change=0.02, volume_ratio=2.0, recent_high=1.18), stats_5m=TimeframeStats(change=0.03, volume_ratio=2.1, recent_high=1.18, close_position=0.3))

    types = alert_types(metrics)

    assert AlertType.SHORT_TERM_SURGE not in types


def test_multi_timeframe_breakout_rule() -> None:
    types = alert_types(make_metrics())

    assert AlertType.MULTI_TIMEFRAME_BREAKOUT in types


def test_strong_pullback_watch_rule() -> None:
    metrics = make_metrics(
        price=1.10,
        stats_5m=TimeframeStats(change=-0.01, volume_ratio=0.8, recent_high=1.20, higher_lows=True, closes_above_ma=False, close_position=0.5),
        stats_15m=TimeframeStats(change=-0.02, volume_ratio=0.8, recent_high=1.25, recent_low=1.02, pullback_ratio=0.12, higher_lows=True, close_position=0.4),
    )

    types = alert_types(metrics)

    assert AlertType.STRONG_PULLBACK_WATCH in types


def test_pullback_second_leg_rule() -> None:
    metrics = make_metrics(
        stats_5m=TimeframeStats(change=0.025, volume_ratio=2.1, recent_high=1.18, higher_lows=True, closes_above_ma=True, close_position=0.7),
        stats_15m=TimeframeStats(change=0.03, volume_ratio=1.8, recent_high=1.25, recent_low=1.05, higher_lows=True, close_position=0.65),
    )

    types = alert_types(metrics, {"state": "pullback_watch", "support_price": 1.02, "watch_high": 1.25})

    assert AlertType.PULLBACK_SECOND_LEG in types


def test_high_risk_extension_rule() -> None:
    metrics = make_metrics(stats_15m=TimeframeStats(change=0.10, volume_ratio=2.8, recent_high=1.25, higher_lows=True, large_green_count=4))

    types = alert_types(metrics)

    assert AlertType.HIGH_RISK_EXTENSION in types


def test_btc_dump_blocks_long_bias_alerts() -> None:
    metrics = make_metrics(btc_15m_change=-0.02)

    types = alert_types(metrics)

    assert AlertType.MULTI_TIMEFRAME_BREAKOUT not in types


def test_insufficient_market_data_returns_no_metrics() -> None:
    ticker = {"symbol": "ALLO/USDT:USDT", "last": 1.0, "percentage": 10, "quote_volume": 20_000_000}
    one_kline = [Kline(timestamp=1, open=1, high=1, low=1, close=1, volume=1)]

    metrics = build_market_metrics(ticker, {"1m": one_kline, "3m": one_kline, "5m": one_kline, "15m": one_kline, "1h": one_kline}, 0.0, 1)

    assert metrics is None
