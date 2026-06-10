"""Market alert scoring tests.
行情雷达评分测试。
"""

from app.alerts.scoring import level_from_score, score_metrics
from app.alerts.signal_models import AlertLevel, MarketMetrics, TimeframeStats


def make_metrics(**overrides) -> MarketMetrics:
    """Build test metrics with strong default features.
    构建带强势默认特征的测试指标。
    """

    metrics = MarketMetrics(
        symbol="ALLO/USDT:USDT",
        price=1.2,
        price_change_24h=0.30,
        quote_volume_24h=50_000_000,
        rank_24h=8,
        high_24h=1.3,
        low_24h=0.8,
        stats_3m=TimeframeStats(change=0.02, volume_ratio=2.0, recent_high=1.18, close_position=0.8),
        stats_5m=TimeframeStats(change=0.03, volume_ratio=2.2, recent_high=1.18, higher_lows=True, breakout=True, closes_above_ma=True, close_position=0.8),
        stats_15m=TimeframeStats(change=0.04, volume_ratio=1.7, recent_high=1.25, recent_low=1.05, higher_lows=True, close_position=0.7),
        stats_1h=TimeframeStats(change=0.08, volume_ratio=1.2),
        btc_15m_change=-0.002,
    )
    return MarketMetrics(**{**metrics.__dict__, **overrides})


def test_alert_score_rewards_top_gainer_momentum() -> None:
    metrics = make_metrics()

    score = score_metrics(metrics).normalized()

    assert score >= 85


def test_alert_score_penalizes_btc_dump_and_low_liquidity() -> None:
    metrics = make_metrics(btc_15m_change=-0.02, quote_volume_24h=1_000_000)

    score = score_metrics(metrics).normalized()

    assert score < 85


def test_alert_level_mapping() -> None:
    assert level_from_score(90) == AlertLevel.A
    assert level_from_score(75) == AlertLevel.B
    assert level_from_score(60) == AlertLevel.C
    assert level_from_score(40) == AlertLevel.IGNORE
