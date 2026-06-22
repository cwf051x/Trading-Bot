"""Base interfaces for pluggable alert radar rules.
行情雷达插件式规则基础接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.alerts.signal_models import AlertRuleResult, MarketMetrics


class AlertRule(ABC):
    """Small interface implemented by every radar rule.
    每个雷达规则实现的轻量接口。
    """

    name: str = "base"

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def required_timeframes(self) -> set[str]:
        """Return candle timeframes needed by this rule.
        返回该规则需要的 K 线周期。
        """

        return set()

    def required_oi_periods(self) -> set[str]:
        """Return OI history periods needed by this rule.
        返回该规则需要的持仓量历史周期。
        """

        return set()

    def requires_funding_rate(self) -> bool:
        """Return whether this rule needs funding-rate data.
        返回该规则是否需要资金费率。
        """

        return False

    @abstractmethod
    def evaluate(self, metrics: MarketMetrics, state: dict[str, Any]) -> list[AlertRuleResult]:
        """Evaluate one symbol and return candidate alerts.
        评估单个交易对并返回候选提醒。
        """

