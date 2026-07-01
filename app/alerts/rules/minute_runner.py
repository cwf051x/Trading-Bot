"""Minute Runner Radar rule declaration.
分钟级单边上涨雷达的数据需求声明。
"""

from __future__ import annotations

from typing import Any

from app.alerts.rules.base import AlertRule
from app.alerts.signal_models import AlertRuleResult, MarketMetrics


class MinuteRunnerRule(AlertRule):
    """Declare data needs for the stateful Minute Runner pool.
    为有状态单边上涨池声明 scanner 需要采集的数据。
    """

    name = "minute_runner"

    def required_timeframes(self) -> set[str]:
        return {"3m", "5m", "15m", "1h"}

    def required_oi_periods(self) -> set[str]:
        return {"5m"}

    def requires_funding_rate(self) -> bool:
        return True

    def evaluate(self, metrics: MarketMetrics, state: dict[str, Any]) -> list[AlertRuleResult]:
        # Minute Runner 通过独立 manager 做池榜和邮件，避免单币单条 Telegram 刷屏。
        return []
