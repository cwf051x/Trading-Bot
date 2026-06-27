"""Paper trading engine tests.
模拟盘执行引擎测试。
"""

from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

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


def test_close_position_is_idempotent_and_does_not_duplicate_trade(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    order_id = storage.create_order("ETH/USDT:USDT", "long", 2, 100, 98, 104, "open", "test", 1)
    position_id = storage.create_position(order_id, "ETH/USDT:USDT", "long", 2, 100, 98, 104, 1)

    first = storage.close_position(position_id, 104, 8, "take_profit", 2)
    second = storage.close_position(position_id, 103, 6, "take_profit", 3)

    trades = storage.get_trades()
    positions = storage.get_positions()
    assert first is True
    assert second is False
    assert len(trades) == 1
    assert trades[0]["exit_price"] == 104
    assert positions[0]["closed_at"] == 2


def test_create_open_order_position_skips_existing_open_position_atomically(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()

    first = storage.create_open_order_position(
        symbol="ETH/USDT:USDT",
        side="long",
        quantity=2,
        entry_price=100,
        stop_loss=98,
        take_profit=104,
        reason="test",
        timestamp=1,
    )
    second = storage.create_open_order_position(
        symbol="ETH/USDT:USDT",
        side="long",
        quantity=3,
        entry_price=101,
        stop_loss=99,
        take_profit=105,
        reason="duplicate",
        timestamp=2,
    )

    assert first is not None
    assert second is None
    assert len(storage.get_orders()) == 1
    assert len(storage.get_open_positions("ETH/USDT:USDT")) == 1


def test_initialize_reports_duplicate_open_positions_before_unique_index(tmp_path: Path) -> None:
    database_path = tmp_path / "dirty.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL,
                status TEXT NOT NULL,
                exit_price REAL,
                pnl REAL,
                exit_reason TEXT,
                opened_at INTEGER NOT NULL DEFAULT 0,
                closed_at INTEGER
            )
            """
        )
        for order_id in [1, 2]:
            connection.execute(
                """
                INSERT INTO positions(order_id, symbol, side, quantity, entry_price, stop_loss, take_profit, status, opened_at)
                VALUES (?, 'ETH/USDT:USDT', 'long', 1, 100, 98, 104, 'open', ?)
                """,
                (order_id, order_id),
            )

    storage = SQLiteStorage(database_path)

    try:
        storage.initialize()
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("duplicate open positions should be reported before creating unique index")

    assert "duplicate open positions" in message
    assert "ETH/USDT:USDT" in message
    assert "long" in message


def test_concurrent_create_open_order_position_allows_only_one_writer(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()

    def create_once(index: int):
        return storage.create_open_order_position(
            symbol="ETH/USDT:USDT",
            side="long",
            quantity=1,
            entry_price=100 + index,
            stop_loss=98,
            take_profit=104,
            reason=f"thread-{index}",
            timestamp=index,
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(create_once, range(10)))

    assert sum(result is not None for result in results) == 1
    assert len(storage.get_orders()) == 1
    assert len(storage.get_open_positions("ETH/USDT:USDT")) == 1


def test_concurrent_close_position_writes_only_one_trade(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    order_id = storage.create_order("ETH/USDT:USDT", "long", 2, 100, 98, 104, "open", "test", 1)
    position_id = storage.create_position(order_id, "ETH/USDT:USDT", "long", 2, 100, 98, 104, 1)

    def close_once(index: int) -> bool:
        return storage.close_position(position_id, 104 + index, 8 + index, "take_profit", 10 + index)

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(close_once, range(10)))

    assert sum(results) == 1
    assert len(storage.get_trades()) == 1
    assert storage.get_positions()[0]["status"] == "closed"


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


def test_paper_high_low_triggers_intrabar_take_profit(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    engine = PaperTradingEngine(storage=storage)
    signal = Signal("ETH/USDT:USDT", "long", 0.8, 100.0, 98.0, 104.0, "test", 1)

    engine.process_signal(signal, quantity=2)
    closed = engine.update_open_positions("ETH/USDT:USDT", price=101.0, timestamp=2, high=104.5, low=100.5)

    trades = storage.get_trades()
    assert closed == [1]
    assert trades[0]["exit_reason"] == "take_profit"
    assert trades[0]["exit_price"] == 104.0


def test_paper_high_low_triggers_intrabar_stop_loss(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "paper.sqlite")
    storage.initialize()
    engine = PaperTradingEngine(storage=storage)
    signal = Signal("ETH/USDT:USDT", "long", 0.8, 100.0, 98.0, 104.0, "test", 1)

    engine.process_signal(signal, quantity=2)
    closed = engine.update_open_positions("ETH/USDT:USDT", price=101.0, timestamp=2, high=103.0, low=97.5)

    trades = storage.get_trades()
    assert closed == [1]
    assert trades[0]["exit_reason"] == "stop_loss"
    assert trades[0]["exit_price"] == 98.0


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
