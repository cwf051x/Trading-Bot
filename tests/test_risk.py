"""Risk manager tests.
风控管理器测试。
"""

from __future__ import annotations

from app.exchange.binance import Kline
from app.risk.manager import RiskManager
from app.strategies.base import Signal


def signal(stop_loss: float | None = 98.0, entry: float | None = 100.0) -> Signal:
    return Signal("ETH/USDT:USDT", "long", 0.8, entry, stop_loss, 110.0, "test", 1)


def test_risk_blocks_missing_stop_loss() -> None:
    manager = RiskManager(account_equity=10_000)

    decision = manager.evaluate(signal(stop_loss=None))

    assert decision.allowed is False
    assert "stop_loss" in decision.reason


def test_risk_caps_position_to_ten_percent_equity() -> None:
    manager = RiskManager(account_equity=10_000)

    decision = manager.evaluate(signal(stop_loss=99))

    assert decision.allowed is True
    assert decision.notional_value == 1_000


def test_risk_blocks_after_three_losses() -> None:
    manager = RiskManager(account_equity=10_000)
    manager.record_trade_result(-1)
    manager.record_trade_result(-1)
    manager.record_trade_result(-1)

    decision = manager.evaluate(signal())

    assert decision.allowed is False
    assert "cooldown" in decision.reason


def test_risk_blocks_btc_dump_for_longs() -> None:
    manager = RiskManager(account_equity=10_000, btc_drop_threshold_15m=0.03)
    btc = [
        Kline(timestamp=1, open=100, high=100, low=100, close=100, volume=1),
        Kline(timestamp=2, open=95, high=95, low=95, close=95, volume=1),
    ]

    decision = manager.evaluate(signal(), {"btc_klines": btc})

    assert decision.allowed is False
    assert "BTC" in decision.reason
