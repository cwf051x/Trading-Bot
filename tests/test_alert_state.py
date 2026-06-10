"""Market alert state and formatting tests.
行情雷达状态与格式化测试。
"""

from pathlib import Path

from app.alerts.alert_state import AlertStateManager
from app.alerts.signal_models import AlertLevel, AlertSignal, AlertType
from app.alerts.telegram_formatter import format_alert_message
from app.config import Settings
from app.storage.sqlite import SQLiteStorage


def make_alert(timestamp: int = 1_000_000) -> AlertSignal:
    """Build a sample alert.
    构建示例提醒。
    """

    return AlertSignal(
        timestamp=timestamp,
        symbol="ALLO/USDT:USDT",
        alert_type=AlertType.PULLBACK_SECOND_LEG,
        level=AlertLevel.A,
        score=88,
        price=0.1842,
        price_change_3m=0.012,
        price_change_5m=0.021,
        price_change_15m=0.038,
        price_change_1h=0.095,
        price_change_24h=0.386,
        volume_ratio=2.4,
        btc_15m_change=-0.001,
        reasons=["pullback second leg restart / 回调后二次启动"],
        suggested_action="回调二启，观察5m收稳后的低风险入场区",
        invalidation_price=0.172,
        target_1=0.195,
        target_2=0.21,
    )


def test_alert_state_cooldown_blocks_duplicate(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "alerts.sqlite")
    storage.initialize()
    manager = AlertStateManager(storage, Settings(_env_file=None))
    alert = make_alert()

    assert manager.should_send(alert, now_ms=alert.timestamp) is True
    manager.record_alert(alert, sent_to_telegram=True)

    assert manager.should_send(make_alert(timestamp=alert.timestamp + 60_000), now_ms=alert.timestamp + 60_000) is False
    assert manager.should_send(make_alert(timestamp=alert.timestamp + 700_000), now_ms=alert.timestamp + 700_000) is True


def test_alert_state_persists_market_alert(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "alerts.sqlite")
    storage.initialize()
    manager = AlertStateManager(storage, Settings(_env_file=None))

    manager.record_alert(make_alert(), sent_to_telegram=True)

    rows = storage.get_market_alerts()
    assert rows[0]["symbol"] == "ALLO/USDT:USDT"
    assert rows[0]["sent_to_telegram"] == 1


def test_alert_cooldown_is_per_symbol_and_alert_type(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "alerts.sqlite")
    storage.initialize()
    manager = AlertStateManager(storage, Settings(_env_file=None))
    first = make_alert()
    other_type = AlertSignal(**{**first.__dict__, "alert_type": AlertType.HIGH_RISK_EXTENSION, "timestamp": first.timestamp + 10_000})

    manager.record_alert(first, sent_to_telegram=True)
    manager.record_alert(other_type, sent_to_telegram=True)

    assert manager.should_send(make_alert(timestamp=first.timestamp + 60_000), now_ms=first.timestamp + 60_000) is False


def test_telegram_alert_formatter_contains_risk_warning() -> None:
    message = format_alert_message(make_alert())

    assert "A级信号" in message
    assert "ALLO/USDT:USDT" in message
    assert "风险提示" in message
    assert "不是交易指令" in message
