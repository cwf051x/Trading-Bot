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
    ) -> None:
        self.storage = storage
        self.notifier = notifier
        self.default_quantity = default_quantity
        self.initial_equity = initial_equity
        self.leverage = max(leverage, 1.0)

    def process_signal(self, signal: Signal, quantity: float | None = None) -> PaperOrder | None:
        """Create a simulated order from an actionable signal.
        根据可执行信号创建模拟订单。
        """

        if not signal.is_actionable:
            return None
        if self.storage.has_open_position(signal.symbol, signal.side):
            return None
        if signal.entry_price is None or signal.stop_loss is None:
            raise ValueError("paper execution requires entry_price and stop_loss")

        order_id = self.storage.create_order(
            symbol=signal.symbol,
            side=signal.side,
            quantity=quantity or self.default_quantity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status="open",
            reason=signal.reason,
            timestamp=signal.timestamp,
        )
        order = PaperOrder(
            id=order_id,
            symbol=signal.symbol,
            side=signal.side,
            quantity=quantity or self.default_quantity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status="open",
        )
        self.storage.create_position(
            order_id,
            signal.symbol,
            signal.side,
            order.quantity,
            order.entry_price,
            signal.stop_loss,
            signal.take_profit,
            signal.timestamp,
        )
        if self.notifier:
            # 订单通知和下单记录分开处理，避免 Telegram 抖动影响模拟盘落库。
            sent = self.notifier.notify_paper_order(order)
            if sent:
                logger.info("Paper order #%s Telegram notification sent", order.id)
            else:
                logger.warning("Paper order #%s Telegram notification failed or disabled", order.id)
        return order

    def update_open_positions(self, symbol: str, price: float, timestamp: int) -> list[int]:
        """Close simulated positions when stop loss or take profit is hit.
        当价格触发止损或止盈时关闭模拟持仓。
        """

        closed: list[int] = []
        for position in self.storage.get_open_positions(symbol):
            side = position["side"]
            stop_loss = float(position["stop_loss"])
            take_profit = position["take_profit"]
            take_profit_value = float(take_profit) if take_profit is not None else None
            should_stop = side == "long" and price <= stop_loss or side == "short" and price >= stop_loss
            should_take = take_profit_value is not None and (side == "long" and price >= take_profit_value or side == "short" and price <= take_profit_value)
            if not should_stop and not should_take:
                continue

            exit_reason = "stop_loss" if should_stop else "take_profit"
            entry = float(position["entry_price"])
            quantity = float(position["quantity"])
            pnl = (price - entry) * quantity if side == "long" else (entry - price) * quantity
            self.storage.close_position(int(position["id"]), price, pnl, exit_reason, timestamp)
            closed.append(int(position["id"]))
        return closed

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
