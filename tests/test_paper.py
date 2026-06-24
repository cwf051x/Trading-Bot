"""Paper trading engine tests.
模拟盘执行引擎测试。
"""

from pathlib import Path

from app.execution.paper import PaperTradingEngine
from app.storage.sqlite import SQLiteStorage
from app.strategies.base import Signal


def test_paper_order_and_stop_loss_close(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    engine = PaperTradingEngine(storage=storage)
    signal = Signal("ETH/USDT:USDT", "long", 0.8, 100.0, 98.0, 104.0, "test", 1)

    order = engine.process_signal(signal, quantity=2)
    closed = engine.update_open_positions("ETH/USDT:USDT", price=97.5, timestamp=2)

    assert order is not None
    assert order.id == 1
    assert closed == [1]
    assert storage.get_open_positions("ETH/USDT:USDT") == []
    assert len(storage.get_trades()) == 1


def test_paper_does_not_duplicate_open_position(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    engine = PaperTradingEngine(storage=storage)
    signal = Signal("ETH/USDT:USDT", "long", 0.8, 100.0, 98.0, 104.0, "test", 1)

    first = engine.process_signal(signal, quantity=2)
    second = engine.process_signal(signal, quantity=2)

    assert first is not None
    assert second is None
    assert len(storage.get_open_positions("ETH/USDT:USDT")) == 1


def test_paper_account_snapshot_tracks_margin_and_pnl(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    engine = PaperTradingEngine(storage=storage, initial_equity=1_000, leverage=2)
    signal = Signal("ETH/USDT:USDT", "long", 0.8, 100.0, 98.0, 104.0, "test", 1)

    engine.process_signal(signal, quantity=2)
    open_snapshot = engine.get_account_snapshot({"ETH/USDT:USDT": 103.0})
    engine.update_open_positions("ETH/USDT:USDT", price=104.0, timestamp=2)
    closed_snapshot = engine.get_account_snapshot({"ETH/USDT:USDT": 104.0})

    assert open_snapshot.used_margin == 100.0
    assert open_snapshot.unrealized_pnl == 6.0
    assert open_snapshot.equity == 1_006.0
    assert open_snapshot.open_position_count == 1
    assert closed_snapshot.realized_pnl == 8.0
    assert closed_snapshot.used_margin == 0.0
    assert closed_snapshot.equity == 1_008.0
    assert closed_snapshot.open_position_count == 0


def test_paper_performance_summary_tracks_closed_and_open_risk(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    engine = PaperTradingEngine(storage=storage, initial_equity=1_000, leverage=2)
    win = Signal("WIN/USDT:USDT", "long", 0.9, 100.0, 95.0, 110.0, "alert HOURLY_TREND_T3: win", 1)
    loss = Signal("LOSS/USDT:USDT", "long", 0.8, 100.0, 90.0, 120.0, "alert PUMP_PULLBACK_P2: loss", 2)
    open_signal = Signal("OPEN/USDT:USDT", "long", 0.7, 50.0, 45.0, 60.0, "alert VOLUME_PRICE_OI_RESONANCE: open", 3)

    engine.process_signal(win, quantity=2)
    engine.update_open_positions("WIN/USDT:USDT", price=110.0, timestamp=4)
    engine.process_signal(loss, quantity=1)
    engine.update_open_positions("LOSS/USDT:USDT", price=90.0, timestamp=5)
    engine.process_signal(open_signal, quantity=4)

    summary = storage.get_paper_performance_summary(leverage=2)

    assert summary["total_orders"] == 3
    assert summary["open_positions"] == 1
    assert summary["closed_trades"] == 2
    assert summary["winning_trades"] == 1
    assert summary["losing_trades"] == 1
    assert summary["win_rate"] == 0.5
    assert summary["realized_pnl"] == 10.0
    assert summary["gross_profit"] == 20.0
    assert summary["gross_loss"] == 10.0
    assert summary["profit_factor"] == 2.0
    assert summary["avg_win"] == 20.0
    assert summary["avg_loss"] == -10.0
    assert summary["max_win"] == 20.0
    assert summary["max_loss"] == -10.0
    assert summary["take_profit_count"] == 1
    assert summary["stop_loss_count"] == 1
    assert summary["open_notional"] == 200.0
    assert summary["open_margin"] == 100.0
