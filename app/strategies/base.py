"""Base strategy interfaces and signal model.
策略基础接口与标准信号模型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

SignalSide = Literal["long", "short", "none"]


@dataclass(frozen=True)
class Signal:
    """Standard strategy signal returned by all strategies.
    所有策略统一返回的标准交易信号。
    """

    symbol: str
    side: SignalSide
    confidence: float
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    reason: str
    timestamp: int

    @property
    def is_actionable(self) -> bool:
        """Return whether this signal asks the execution layer to act.
        判断该信号是否需要执行层采取动作。
        """

        return self.side in {"long", "short"}


class BaseStrategy(ABC):
    """Abstract strategy contract.
    策略抽象基类契约。
    """

    name: str

    @abstractmethod
    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        """Generate a normalized trading signal from market data.
        根据行情数据生成标准化交易信号。
        """
