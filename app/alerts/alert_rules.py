"""Rule registry for market alert radar.
行情雷达规则注册器。
"""

from __future__ import annotations

from typing import Any

from app.alerts.rule_config import load_radar_rule_config
from app.alerts.rules.base import AlertRule
from app.alerts.rules.hourly_trend import HourlyTrendRule
from app.alerts.rules.pump_pullback_second_wave import PumpPullbackSecondWaveRule
from app.alerts.rules.volume_price_oi import VolumePriceOIRule
from app.alerts.signal_models import AlertRuleResult, MarketMetrics


class AlertRuleEngine:
    """Evaluate enabled radar rules for one symbol.
    对单个交易对执行已启用的雷达规则。
    """

    def __init__(self, settings: Any, rules: list[AlertRule] | None = None) -> None:
        self.settings = settings
        if not hasattr(self.settings, "radar_rule_config"):
            object.__setattr__(self.settings, "radar_rule_config", load_radar_rule_config())
        self.rules = rules or [
            VolumePriceOIRule(settings),
            HourlyTrendRule(settings),
            PumpPullbackSecondWaveRule(settings),
        ]

    def evaluate(self, metrics: MarketMetrics, state: dict[str, Any] | None = None) -> list[AlertRuleResult]:
        """Run all registered alert rules for one symbol.
        对单个交易对运行所有已注册提醒规则。
        """

        if metrics.price <= 0:
            return []
        state = state or {}
        results: list[AlertRuleResult] = []
        for rule in self.rules:
            results.extend(rule.evaluate(metrics, state))
        return results
