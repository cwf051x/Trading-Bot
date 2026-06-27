"""Risk manager tests.
风控管理器测试。
"""

from __future__ import annotations

from app.exchange.binance import Kline
from app.risk.manager import RiskManager
from app.storage.sqlite import SQLiteStorage
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


def test_risk_blocks_when_max_open_positions_reached(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "risk.sqlite")
    storage.initialize()
    order_id = storage.create_order("BTC/USDT:USDT", "long", 1, 100, 95, 110, "open", "existing", 1)
    storage.create_position(order_id, "BTC/USDT:USDT", "long", 1, 100, 95, 110, 1)
    manager = RiskManager(account_equity=10_000, storage=storage, max_open_positions=1)

    decision = manager.evaluate(signal())

    assert decision.allowed is False
    assert "max open positions" in decision.reason


def test_risk_blocks_total_exposure_limit(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "risk.sqlite")
    storage.initialize()
    order_id = storage.create_order("BTC/USDT:USDT", "long", 15, 100, 95, 110, "open", "existing", 1)
    storage.create_position(order_id, "BTC/USDT:USDT", "long", 15, 100, 95, 110, 1)
    manager = RiskManager(account_equity=10_000, storage=storage, max_total_exposure_pct=0.20)

    decision = manager.evaluate(signal(stop_loss=99))

    assert decision.allowed is False
    assert "total exposure" in decision.reason


def test_risk_blocks_symbol_exposure_limit(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "risk.sqlite")
    storage.initialize()
    order_id = storage.create_order("ETH/USDT:USDT", "long", 8, 100, 95, 110, "open", "existing", 1)
    storage.create_position(order_id, "ETH/USDT:USDT", "long", 8, 100, 95, 110, 1)
    manager = RiskManager(account_equity=10_000, storage=storage, max_symbol_position_pct=0.10)

    decision = manager.evaluate(signal(stop_loss=99))

    assert decision.allowed is False
    assert "symbol exposure" in decision.reason


def test_risk_cooldown_reads_recent_closed_trades(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "risk.sqlite")
    storage.initialize()
    for index in range(3):
        order_id = storage.create_order(f"LOSS{index}/USDT:USDT", "long", 1, 100, 95, 110, "open", "loss", index)
        position_id = storage.create_position(order_id, f"LOSS{index}/USDT:USDT", "long", 1, 100, 95, 110, index)
        storage.close_position(position_id, 95, -5, "stop_loss", index + 10)
    manager = RiskManager(account_equity=10_000, storage=storage, max_consecutive_losses=3)

    decision = manager.evaluate(signal())

    assert decision.allowed is False
    assert "cooldown" in decision.reason


def test_risk_uses_current_prices_for_existing_position_exposure(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "risk.sqlite")
    storage.initialize()
    order_id = storage.create_order("BTC/USDT:USDT", "long", 1, 100, 95, 110, "open", "existing", 1)
    storage.create_position(order_id, "BTC/USDT:USDT", "long", 1, 100, 95, 110, 1)
    manager = RiskManager(account_equity=1_000, storage=storage, risk_per_trade_pct=0.001, max_total_exposure_pct=0.20, max_symbol_position_pct=0.50)

    stale_price_decision = manager.evaluate(signal(stop_loss=99), market_context={"current_prices": {"BTC/USDT:USDT": 100}})
    fresh_price_decision = manager.evaluate(signal(stop_loss=99), market_context={"current_prices": {"BTC/USDT:USDT": 150}})

    assert stale_price_decision.allowed is True
    assert fresh_price_decision.allowed is False
    assert "total exposure" in fresh_price_decision.reason
