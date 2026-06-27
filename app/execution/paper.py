"""Paper trading execution engine.
模拟盘交易执行引擎。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.notify.telegram import TelegramNotifier
from app.storage.sqlite import SQLiteStorage
from app.strategies.base import Signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaperOrder:
    """Simulated order.
    模拟订单对象。
    """

    id: int
    symbol: str
    side: str
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float | None
    status: str


@dataclass(frozen=True)
class PaperAccountSnapshot:
    """Computed paper account state.
    计算得出的模拟账户状态。
    """

    initial_equity: float
    cash_balance: float
    used_margin: float
    realized_pnl: float
    unrealized_pnl: float
    equity: float
    available_balance: float
    open_position_count: int


class PaperTradingEngine:
    """Execute strategy signals in simulation only.
    仅在模拟环境中执行策略信号。
    """

    def __init__(
        self,
        storage: SQLiteStorage,
        notifier: TelegramNotifier | None = None,
        default_quantity: float = 1.0,
        initial_equity: float = 10_000.0,
        leverage: float = 1.0,
        fee_rate: float = 0.0,
        slippage_pct: float = 0.0,
        funding_rate: float = 0.0,
    ) -> None:
        self.storage = storage
        self.notifier = notifier
        self.default_quantity = default_quantity
        self.initial_equity = initial_equity
        self.leverage = max(leverage, 1.0)
        self.fee_rate = max(float(fee_rate), 0.0)
        self.slippage_pct = max(float(slippage_pct), 0.0)
        self.funding_rate = float(funding_rate)

    def process_signal(self, signal: Signal, quantity: float | None = None) -> PaperOrder | None:
        """Create a simulated order from an actionable signal.
        根据可执行信号创建模拟订单。
        """

        if not signal.is_actionable:
            return None
        if signal.entry_price is None or signal.stop_loss is None:
            raise ValueError("paper execution requires entry_price and stop_loss")

        requested_quantity = quantity or self.default_quantity
        created = self.storage.create_open_order_position(
            symbol=signal.symbol,
            side=signal.side,
            quantity=requested_quantity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=signal.reason,
            timestamp=signal.timestamp,
        )
        if created is None:
            return None
        order = PaperOrder(
            id=created["order_id"],
            symbol=signal.symbol,
            side=signal.side,
            quantity=requested_quantity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status="open",
        )
        if self.notifier:
            # 订单通知和下单记录分开处理，避免 Telegram 抖动影响模拟盘落库。
            sent = self.notifier.notify_paper_order(order)
            if sent:
                logger.info("Paper order #%s Telegram notification sent", order.id)
            else:
                logger.warning("Paper order #%s Telegram notification failed or disabled", order.id)
        return order

    def update_open_positions(self, symbol: str, price: float, timestamp: int, high: float | None = None, low: float | None = None) -> list[int]:
        """Close simulated positions when stop loss or take profit is hit.
        当价格触发止损或止盈时关闭模拟持仓。
        """

        closed: list[int] = []
        for position in self.storage.get_open_positions(symbol):
            side = position["side"]
            stop_loss = float(position["stop_loss"])
            take_profit = position["take_profit"]
            take_profit_value = float(take_profit) if take_profit is not None else None
            candle_high = float(high if high is not None else price)
            candle_low = float(low if low is not None else price)
            should_stop = side == "long" and candle_low <= stop_loss or side == "short" and candle_high >= stop_loss
            should_take = take_profit_value is not None and (side == "long" and candle_high >= take_profit_value or side == "short" and candle_low <= take_profit_value)
            if not should_stop and not should_take:
                continue

            # 同一根已完成 K 线同时触发止损/止盈时保守按止损处理，避免高估模拟盘收益。
            exit_reason = "stop_loss" if should_stop else "take_profit"
            exit_price = stop_loss if should_stop else float(take_profit_value)
            exit_price = self._apply_exit_slippage(exit_price, side)
            entry = float(position["entry_price"])
            quantity = float(position["quantity"])
            gross_pnl = (exit_price - entry) * quantity if side == "long" else (entry - exit_price) * quantity
            fees = (entry * quantity + exit_price * quantity) * self.fee_rate
            funding = entry * quantity * self.funding_rate
            pnl = gross_pnl - fees - funding
            if self.storage.close_position(int(position["id"]), exit_price, pnl, exit_reason, timestamp):
                closed.append(int(position["id"]))
        return closed

    def _apply_exit_slippage(self, exit_price: float, side: str) -> float:
        """Apply conservative simulated slippage at exit.
        在平仓价上应用保守滑点，默认滑点为 0。
        """

        if self.slippage_pct <= 0:
            return exit_price
        if side == "long":
            return exit_price * (1 - self.slippage_pct)
        return exit_price * (1 + self.slippage_pct)

    def get_account_snapshot(self, current_prices: dict[str, float] | None = None) -> PaperAccountSnapshot:
        """Return account balance, margin, realized PnL, and floating PnL.
        返回账户余额、已用保证金、已实现盈亏和浮动盈亏。
        """

        prices = current_prices or {}
        positions = self.storage.get_open_positions()
        used_margin = 0.0
        unrealized_pnl = 0.0
        for position in positions:
            entry = float(position["entry_price"])
            quantity = float(position["quantity"])
            side = str(position["side"])
            current_price = float(prices.get(str(position["symbol"]), entry))
            notional = entry * quantity
            used_margin += notional / self.leverage
            unrealized_pnl += (current_price - entry) * quantity if side == "long" else (entry - current_price) * quantity

        realized_pnl = self.storage.get_realized_pnl()
        cash_balance = self.initial_equity + realized_pnl
        equity = cash_balance + unrealized_pnl
        available_balance = equity - used_margin
        return PaperAccountSnapshot(
            initial_equity=self.initial_equity,
            cash_balance=cash_balance,
            used_margin=used_margin,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            equity=equity,
            available_balance=available_balance,
            open_position_count=len(positions),
        )
