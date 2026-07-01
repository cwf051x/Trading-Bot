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
        if not self._enabled():
            return set()
        return {"5m", "15m", "1h"}

    def required_oi_periods(self) -> set[str]:
        if not self._enabled():
            return set()
        return {"5m"}

    def requires_funding_rate(self) -> bool:
        if not self._enabled():
            return False
        return True

    def evaluate(self, metrics: MarketMetrics, state: dict[str, Any]) -> list[AlertRuleResult]:
        # Minute Runner 通过独立 manager 做池榜和邮件，避免单币单条 Telegram 刷屏。
        return []

    def _enabled(self) -> bool:
        """Return the final Minute Runner switch after env/YAML gates.
        返回环境变量和 YAML 双重开关之后的最终启用状态。
        """

        rule_config = getattr(self.settings, "radar_rule_config", {})
        return bool(getattr(self.settings, "minute_runner_enabled", True)) and bool(rule_config.get("minute_runner", {}).get("enabled", True))
