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
