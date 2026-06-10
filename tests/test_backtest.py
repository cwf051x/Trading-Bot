"""Backtest engine tests.
回测引擎测试。
"""

from __future__ import annotations

from pathlib import Path

from app.backtest.engine import BacktestEngine
from app.exchange.binance import Kline
from app.strategies.momentum_oi import MomentumOIStrategy


def candle(index: int, close: float, volume: float = 100.0, high: float | None = None, low: float | None = None) -> Kline:
    return Kline(timestamp=index, open=close, high=high or close, low=low or close, close=close, volume=volume)


def test_backtest_runs_and_exports_equity_curve(tmp_path: Path) -> None:
    klines = [candle(i, 100, 100, high=101, low=99) for i in range(21)]
    klines.append(candle(22, 105, 300, high=105, low=104))
    klines.append(candle(23, 109.2, 100, high=110, low=108))
    strategy = MomentumOIStrategy()
    engine = BacktestEngine(strategy=strategy, initial_equity=10_000)

    result = engine.run(klines)
    export_path = tmp_path / "equity.csv"
    result.export_equity_curve(export_path)

    assert result.metrics["trade_count"] == 1
    assert result.metrics["win_rate"] == 1
    assert result.trades[0].quantity == 1000 / 105
    assert export_path.exists()


def test_backtest_uses_risk_sized_quantity() -> None:
    klines = [candle(i, 100, 100, high=101, low=99) for i in range(21)]
    klines.append(candle(22, 105, 300, high=105, low=104))
    klines.append(candle(23, 109.2, 100, high=110, low=108))
    strategy = MomentumOIStrategy()
    engine = BacktestEngine(strategy=strategy, initial_equity=10_000, risk_per_trade_pct=0.01, max_symbol_position_pct=0.10)

    result = engine.run(klines)

    assert result.trades[0].quantity == 1000 / 105
    assert result.trades[0].pnl == result.trades[0].quantity * (105 * 1.04 - 105)
    assert result.metrics["final_equity"] > 10_000
