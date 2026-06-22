"""Volume-price-OI resonance radar rule.
量价 OI 共振雷达规则。
"""

from __future__ import annotations

from typing import Any

from app.alerts.rules.base import AlertRule
from app.alerts.signal_models import AlertRuleResult, AlertType, MarketMetrics


class VolumePriceOIRule(AlertRule):
    """Detect short-term 5m price, volume, and OI resonance.
    识别 5m 级别价格、成交量、持仓量共振拉升。
    """

    name = "volume_price_oi"

    def required_timeframes(self) -> set[str]:
        return {"5m"}

    def required_oi_periods(self) -> set[str]:
        return {"5m"}

    def evaluate(self, metrics: MarketMetrics, state: dict[str, Any]) -> list[AlertRuleResult]:
        result = self._volume_price_oi_resonance(metrics)
        return [result] if result else []

    def _volume_price_oi_resonance(self, metrics: MarketMetrics) -> AlertRuleResult | None:
        """Detect volume-price-OI resonance on 5m candles.
        识别 5m 主周期的量价 OI 共振拉升。
        """

        stats = metrics.resonance
        if stats is None:
            return None
        l3 = (
            stats.price_change_60m > 0.20
            and stats.rsi6 is not None
            and stats.rsi6 > 85
            and stats.ma25_deviation > 0.10
            and stats.oi_change_60m > 0.20
            and (stats.long_upper_wick or stats.consecutive_red_5m)
        )
        if l3:
            return AlertRuleResult(
                AlertType.VOLUME_PRICE_OI_RESONANCE,
                90,
                [
                    "L3 high extension risk / L3 高位过热风险",
                    "price, volume and OI expanded together / 价格、成交量、持仓量同步扩张",
                ],
                "L3 高位过热风险，优先观察回落，不自动追入",
                metadata={"resonance_level": "L3", "auto_paper": False},
            )
        l2 = (
            stats.price_change_30m > 0.06
            and stats.price_change_60m > 0.10
            and stats.bullish_5m_count_6 >= 4
            and stats.volume_continuity >= 4
            and stats.oi_change_30m > 0.08
            and metrics.price > stats.ma7 > stats.ma25
        )
        if l2:
            return AlertRuleResult(
                AlertType.VOLUME_PRICE_OI_RESONANCE,
                85,
                [
                    "L2 main rally confirmation / L2 强拉主升确认",
                    "price, volume and OI expanded together / 价格、成交量、持仓量同步扩张",
                ],
                "L2 强拉主升确认，可用模拟单跟踪信号质量",
                metadata={"resonance_level": "L2", "auto_paper": True},
            )
        l1 = (
            stats.price_change_15m > 0.03
            and stats.volume_ratio > 2
            and stats.oi_change_15m > 0.03
            and metrics.price > stats.ma7
            and metrics.price > stats.ma25
        )
        if l1:
            return AlertRuleResult(
                AlertType.VOLUME_PRICE_OI_RESONANCE,
                70,
                [
                    "L1 unusual move watch / L1 异动观察",
                    "price, volume and OI expanded together / 价格、成交量、持仓量同步扩张",
                ],
                "L1 异动观察，等待是否升级为主升确认",
                metadata={"resonance_level": "L1", "auto_paper": False},
            )
        return None

