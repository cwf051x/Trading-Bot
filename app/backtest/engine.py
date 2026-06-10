"""Simple CSV-based backtesting engine.
基于 CSV K 线的简易回测引擎。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.data.csv_loader import load_klines_csv
from app.exchange.binance import Kline
from app.risk.manager import RiskManager
from app.strategies.base import BaseStrategy, Signal


@dataclass(frozen=True)
class BacktestTrade:
    """Closed backtest trade.
    已平仓的回测交易记录。
    """

    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    entry_timestamp: int
    exit_timestamp: int
    exit_reason: str


@dataclass
class BacktestResult:
    """Backtest metrics and equity curve.
    回测指标和权益曲线。
    """

    metrics: dict[str, float]
    trades: list[BacktestTrade]
    equity_curve: list[dict[str, float]]

    def export_equity_curve(self, path: Path) -> None:
        """Export equity curve rows to CSV.
        将权益曲线导出为 CSV。
        """

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "equity"])
            writer.writeheader()
            writer.writerows(self.equity_curve)


class BacktestEngine:
    """Run a risk-sized one-position-at-a-time backtest.
    运行一次只持有一个仓位、并按风控计算仓位的简化回测。
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_equity: float = 10_000.0,
        symbol: str = "BTC/USDT:USDT",
        risk_per_trade_pct: float = 0.01,
        max_symbol_position_pct: float = 0.10,
        max_consecutive_losses: int = 3,
        btc_drop_threshold_15m: float = 0.03,
    ) -> None:
        self.strategy = strategy
        self.initial_equity = initial_equity
        self.symbol = symbol
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_symbol_position_pct = max_symbol_position_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.btc_drop_threshold_15m = btc_drop_threshold_15m

    def run_csv(self, csv_path: Path) -> BacktestResult:
        """Run backtest from historical OHLCV CSV.
        从历史 OHLCV CSV 文件运行回测。
        """

        return self.run(load_klines_csv(csv_path))

    def run(self, klines: list[Kline]) -> BacktestResult:
        """Run strategy over candles and compute metrics.
        在 K 线上执行策略并计算回测指标。
        """

        equity = self.initial_equity
        equity_curve: list[dict[str, float]] = []
        trades: list[BacktestTrade] = []
        open_signal: Signal | None = None
        open_quantity = 0.0
        entry_timestamp = 0
        consecutive_losses = 0

        for index, candle in enumerate(klines):
            equity_curve.append({"timestamp": float(candle.timestamp), "equity": equity})
            if open_signal and open_signal.entry_price is not None and open_signal.stop_loss is not None:
                exit_price, exit_reason = self._exit_price(open_signal, candle)
                if exit_price is not None:
                    pnl = self._pnl(open_signal.side, open_signal.entry_price, exit_price, open_quantity)
                    equity += pnl
                    consecutive_losses = consecutive_losses + 1 if pnl < 0 else 0
                    trades.append(
                        BacktestTrade(
                            symbol=open_signal.symbol,
                            side=open_signal.side,
                            entry_price=open_signal.entry_price,
                            exit_price=exit_price,
                            quantity=open_quantity,
                            pnl=pnl,
                            entry_timestamp=entry_timestamp,
                            exit_timestamp=candle.timestamp,
                            exit_reason=exit_reason,
                        )
                    )
                    open_signal = None
                    open_quantity = 0.0
                    equity_curve[-1]["equity"] = equity
                continue

            history = klines[: index + 1]
            signal = self.strategy.generate_signal({"symbol": self.symbol, "klines": history, "btc_klines": history})
            risk_manager = RiskManager(
                account_equity=equity,
                risk_per_trade_pct=self.risk_per_trade_pct,
                max_symbol_position_pct=self.max_symbol_position_pct,
                max_consecutive_losses=self.max_consecutive_losses,
                btc_drop_threshold_15m=self.btc_drop_threshold_15m,
            )
            risk_manager.consecutive_losses = consecutive_losses
            decision = risk_manager.evaluate(signal, market_context={"btc_klines": history})
            if decision.allowed:
                open_signal = signal
                open_quantity = decision.position_size
                entry_timestamp = candle.timestamp

        metrics = self._metrics(trades, equity_curve)
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)

    def _exit_price(self, signal: Signal, candle: Kline) -> tuple[float | None, str]:
        take_profit = signal.take_profit
        stop_loss = signal.stop_loss
        if stop_loss is None:
            return None, ""
        if signal.side == "long":
            if candle.low <= stop_loss:
                return stop_loss, "stop_loss"
            if take_profit is not None and candle.high >= take_profit:
                return take_profit, "take_profit"
        if signal.side == "short":
            if candle.high >= stop_loss:
                return stop_loss, "stop_loss"
            if take_profit is not None and candle.low <= take_profit:
                return take_profit, "take_profit"
        return None, ""

    @staticmethod
    def _pnl(side: str, entry: float, exit_price: float, quantity: float) -> float:
        return (exit_price - entry) * quantity if side == "long" else (entry - exit_price) * quantity

    def _metrics(self, trades: list[BacktestTrade], equity_curve: list[dict[str, float]]) -> dict[str, float]:
        wins = [trade.pnl for trade in trades if trade.pnl > 0]
        losses = [trade.pnl for trade in trades if trade.pnl < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        win_rate = len(wins) / len(trades) if trades else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss else float("inf") if gross_profit else 0.0
        max_drawdown = self._max_drawdown([row["equity"] for row in equity_curve])
        return {
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "trade_count": float(len(trades)),
            "final_equity": equity_curve[-1]["equity"] if equity_curve else self.initial_equity,
        }

    @staticmethod
    def _max_drawdown(equity_values: list[float]) -> float:
        peak = equity_values[0] if equity_values else 0.0
        max_dd = 0.0
        for equity in equity_values:
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)
        return max_dd
