"""Market alert radar orchestration tests.
行情雷达编排测试。
"""

from app.alerts.radar import MarketAlertRadar
from app.alerts.signal_models import AlertLevel, AlertSignal, AlertType


def make_alert(alert_type: AlertType, level: AlertLevel, score: int) -> AlertSignal:
    """Build a minimal alert for orchestration tests.
    为编排测试构建最小提醒对象。
    """

    return AlertSignal(
        timestamp=1,
        symbol="PIPPIN/USDT:USDT",
        alert_type=alert_type,
        level=level,
        score=score,
        price=0.018,
        price_change_3m=0.01,
        price_change_5m=0.02,
        price_change_15m=0.30,
        price_change_1h=0.08,
        price_change_24h=0.50,
        volume_ratio=2.0,
        btc_15m_change=0.0,
        reasons=["test / 测试"],
        suggested_action="test",
    )


def test_high_risk_wins_same_cycle_notification_priority() -> None:
    radar = MarketAlertRadar.__new__(MarketAlertRadar)
    high_risk = make_alert(AlertType.HIGH_RISK_EXTENSION, AlertLevel.B, 70)
    top_gainer = make_alert(AlertType.TOP_GAINER_MOMENTUM, AlertLevel.C, 80)

    winner = radar._select_notification_winner([top_gainer, high_risk])

    assert winner == high_risk
