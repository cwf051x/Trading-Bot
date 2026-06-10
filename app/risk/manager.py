"""Pre-trade risk checks for strategy signals.
针对策略信号的交易前风控检查。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.exchange.binance import Kline
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
        max_consecutive_losses: int = 3,
        btc_drop_threshold_15m: float = 0.03,
    ) -> None:
        self.account_equity = account_equity
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_symbol_position_pct = max_symbol_position_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.btc_drop_threshold_15m = btc_drop_threshold_15m
        self.consecutive_losses = 0

    def evaluate(self, signal: Signal, market_context: dict[str, Any] | None = None) -> RiskDecision:
        """Return whether a signal can be passed to execution.
        判断信号是否可以进入执行模块。
        """

        if not signal.is_actionable:
            return RiskDecision(False, "signal is not actionable")
        if self.consecutive_losses >= self.max_consecutive_losses:
            return RiskDecision(False, "cooldown active after consecutive losses")
        if signal.stop_loss is None:
            return RiskDecision(False, "signal has no stop_loss")
        if signal.entry_price is None or signal.entry_price <= 0:
            return RiskDecision(False, "signal has invalid entry_price")
        if signal.side == "long" and self._btc_is_dumping(market_context or {}):
            return RiskDecision(False, "BTC 15m drawdown blocks long entries")

        risk_budget = self.account_equity * self.risk_per_trade_pct
        unit_risk = abs(signal.entry_price - signal.stop_loss)
        if unit_risk <= 0:
            return RiskDecision(False, "stop_loss does not define positive risk")
        raw_size = risk_budget / unit_risk
        max_notional = self.account_equity * self.max_symbol_position_pct
        notional = raw_size * signal.entry_price
        if notional > max_notional:
            raw_size = max_notional / signal.entry_price
            notional = max_notional

        if notional <= 0:
            return RiskDecision(False, "computed position size is zero")
        if risk_budget > self.account_equity * self.risk_per_trade_pct:
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
