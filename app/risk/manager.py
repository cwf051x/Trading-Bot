"""Pre-trade risk checks for strategy signals.
针对策略信号的交易前风控检查。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.exchange.binance import Kline
from app.storage.sqlite import SQLiteStorage
from app.strategies.base import Signal


@dataclass(frozen=True)
class RiskDecision:
    """Risk check result.
    风控检查结果。
    """

    allowed: bool
    reason: str
    position_size: float = 0.0
    notional_value: float = 0.0


class RiskManager:
    """Apply first-stage risk rules before execution.
    在执行前应用第一阶段风控规则。
    """

    def __init__(
        self,
        account_equity: float,
        risk_per_trade_pct: float = 0.01,
        max_symbol_position_pct: float = 0.10,
        max_total_exposure_pct: float = 0.50,
        max_open_positions: int = 5,
        max_consecutive_losses: int = 3,
        btc_drop_threshold_15m: float = 0.03,
        storage: SQLiteStorage | None = None,
        fee_rate: float = 0.0,
        slippage_pct: float = 0.0,
        funding_rate: float = 0.0,
    ) -> None:
        self.account_equity = account_equity
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_symbol_position_pct = max_symbol_position_pct
        self.max_total_exposure_pct = max_total_exposure_pct
        self.max_open_positions = max_open_positions
        self.max_consecutive_losses = max_consecutive_losses
        self.btc_drop_threshold_15m = btc_drop_threshold_15m
        self.storage = storage
        self.fee_rate = max(float(fee_rate), 0.0)
        self.slippage_pct = max(float(slippage_pct), 0.0)
        self.funding_rate = float(funding_rate)
        self.consecutive_losses = 0

    def evaluate(self, signal: Signal, market_context: dict[str, Any] | None = None) -> RiskDecision:
        """Return whether a signal can be passed to execution.
        判断信号是否可以进入执行模块。
        """

        if not signal.is_actionable:
            return RiskDecision(False, "signal is not actionable")
        account_state = self._account_state(market_context or {})
        if self._consecutive_losses_from_storage() >= self.max_consecutive_losses:
            return RiskDecision(False, "cooldown active after consecutive losses")
        if signal.stop_loss is None:
            return RiskDecision(False, "signal has no stop_loss")
        if signal.entry_price is None or signal.entry_price <= 0:
            return RiskDecision(False, "signal has invalid entry_price")
        if signal.side == "long" and self._btc_is_dumping(market_context or {}):
            return RiskDecision(False, "BTC 15m drawdown blocks long entries")

        risk_base_equity = max(account_state["equity"], 0.0)
        if risk_base_equity <= 0:
            return RiskDecision(False, "account equity is depleted")
        risk_budget = risk_base_equity * self.risk_per_trade_pct
        unit_risk = abs(signal.entry_price - signal.stop_loss)
        if unit_risk <= 0:
            return RiskDecision(False, "stop_loss does not define positive risk")
        raw_size = risk_budget / unit_risk
        max_notional = risk_base_equity * self.max_symbol_position_pct
        notional = raw_size * signal.entry_price
        if notional > max_notional:
            raw_size = max_notional / signal.entry_price
            notional = max_notional

        if account_state["open_position_count"] >= self.max_open_positions:
            return RiskDecision(False, "max open positions reached")
        total_after = account_state["open_notional"] + notional
        total_limit = risk_base_equity * self.max_total_exposure_pct
        if total_after > total_limit:
            return RiskDecision(False, "total exposure limit exceeded")
        symbol_after = account_state["symbol_notional"].get(signal.symbol, 0.0) + notional
        symbol_limit = risk_base_equity * self.max_symbol_position_pct
        if symbol_after > symbol_limit:
            return RiskDecision(False, "symbol exposure limit exceeded")
        if notional <= 0:
            return RiskDecision(False, "computed position size is zero")
        estimated_costs = notional * (self.fee_rate * 2 + self.slippage_pct + max(self.funding_rate, 0.0))
        if estimated_costs >= risk_budget:
            return RiskDecision(False, "estimated costs exceed risk budget")
        if risk_budget > risk_base_equity * self.risk_per_trade_pct:
            return RiskDecision(False, "risk budget exceeded")
        return RiskDecision(True, "risk checks passed", position_size=raw_size, notional_value=notional)

    def record_trade_result(self, pnl: float) -> None:
        """Update consecutive loss state after a closed trade.
        在交易平仓后更新连续亏损状态。
        """

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def _btc_is_dumping(self, market_context: dict[str, Any]) -> bool:
        btc_klines: list[Kline] = list(market_context.get("btc_klines", []))
        if len(btc_klines) < 2:
            return False
        previous = btc_klines[-2].close
        current = btc_klines[-1].close
        if previous <= 0:
            return False
        return (previous - current) / previous >= self.btc_drop_threshold_15m

    def _account_state(self, market_context: dict[str, Any]) -> dict[str, Any]:
        """Read runtime account exposure from storage when available.
        优先从 SQLite 读取当前持仓和已实现盈亏，避免只依赖启动时静态 equity。
        """

        if self.storage is None:
            return {"equity": self.account_equity, "open_notional": 0.0, "symbol_notional": {}, "open_position_count": 0}
        current_prices = dict(market_context.get("current_prices", {}))
        positions = self.storage.get_open_positions()
        realized_pnl = self.storage.get_realized_pnl()
        open_notional = 0.0
        unrealized_pnl = 0.0
        symbol_notional: dict[str, float] = {}
        for position in positions:
            symbol = str(position["symbol"])
            entry = float(position["entry_price"])
            quantity = float(position["quantity"])
            side = str(position["side"])
            current_price = float(current_prices.get(symbol, entry))
            notional = current_price * quantity
            open_notional += notional
            symbol_notional[symbol] = symbol_notional.get(symbol, 0.0) + notional
            unrealized_pnl += (current_price - entry) * quantity if side == "long" else (entry - current_price) * quantity
        return {
            "equity": self.account_equity + realized_pnl + unrealized_pnl,
            "open_notional": open_notional,
            "symbol_notional": symbol_notional,
            "open_position_count": len(positions),
        }

    def _consecutive_losses_from_storage(self) -> int:
        """Use recent closed trades as durable loss-cooldown state.
        用最近平仓交易恢复连续亏损状态，避免进程重启后内存计数清零。
        """

        if self.storage is None:
            return self.consecutive_losses
        losses = 0
        for trade in self.storage.get_recent_closed_trades(limit=max(self.max_consecutive_losses, 1)):
            if float(trade["pnl"]) < 0:
                losses += 1
                continue
            break
        return losses
