"""Hour-level one-way trend radar rule.
小时级单边趋势雷达规则。
"""

from __future__ import annotations

from typing import Any

from app.alerts.rules.base import AlertRule
from app.alerts.signal_models import AlertRuleResult, AlertType, MarketMetrics


class HourlyTrendRule(AlertRule):
    """Detect 1h trend start, acceleration, pullback entry watch, and overheat risk.
    识别 1h 趋势启动、加速、回踩接多观察和高位过热风险。
    """

    name = "hourly_trend"

    def required_timeframes(self) -> set[str]:
        return {"5m", "15m", "1h"}

    def required_oi_periods(self) -> set[str]:
        return {"1h"}

    def requires_funding_rate(self) -> bool:
        return True

    def evaluate(self, metrics: MarketMetrics, state: dict[str, Any]) -> list[AlertRuleResult]:
        if not bool(getattr(self.settings, "alert_rule_hourly_trend_enabled", True)):
            return []
        stats = metrics.trend
        if stats is None:
            return []
        for builder in (self._t3_pullback, self._t4_overheat, self._t2_acceleration, self._t1_start):
            result = builder(metrics)
            if result:
                return [result]
        return []

    def _t3_pullback(self, metrics: MarketMetrics) -> AlertRuleResult | None:
        """T3 has highest priority because it is the most actionable entry watch.
        T3 是最接近入场观察的信号，因此优先级最高。
        """

        stats = metrics.trend
        if stats is None:
            return None
        matched = (
            metrics.price > stats.ma25
            and stats.ma7 > stats.ma25
            and stats.price_change_12h > getattr(self.settings, "alert_hourly_t3_price_change_12h", 0.15)
            and stats.oi_change_12h > getattr(self.settings, "alert_hourly_t3_oi_change_12h", 0.10)
            and getattr(self.settings, "alert_hourly_t3_pullback_min", 0.04) <= stats.pullback_from_recent_high <= getattr(self.settings, "alert_hourly_t3_pullback_max", 0.10)
            and stats.near_ma7_or_ma25
            and stats.rsi15m_crossed_up
            and stats.reversal_15m
            and stats.pullback_volume_safe
            and stats.oi_pullback_from_high <= getattr(self.settings, "alert_hourly_t3_oi_pullback_max", 0.10)
        )
        if not matched:
            return None
        return AlertRuleResult(
            AlertType.HOURLY_TREND_T3,
            88,
            [
                "T3 pullback long watch / T3 回踩接多观察",
                "hourly trend remains intact / 小时级趋势结构仍保持",
            ],
            "T3 回踩接多观察，等待5m确认后用模拟单跟踪",
            invalidation_price=stats.ma25,
            target_1=metrics.price * 1.08,
            target_2=metrics.price * 1.16,
            metadata=self._metadata(stats, "T3", auto_paper=True),
        )

    def _t4_overheat(self, metrics: MarketMetrics) -> AlertRuleResult | None:
        stats = metrics.trend
        if stats is None:
            return None
        matched = (
            stats.price_change_24h > getattr(self.settings, "alert_hourly_t4_price_change_24h", 0.50)
            and stats.distance_to_ma25 > getattr(self.settings, "alert_hourly_t4_ma25_deviation", 0.20)
            and stats.rsi6 is not None
            and stats.rsi6 > getattr(self.settings, "alert_hourly_t4_rsi6", 85.0)
            and stats.rsi24 is not None
            and stats.rsi24 > getattr(self.settings, "alert_hourly_t4_rsi24", 75.0)
            and stats.oi_change_24h > getattr(self.settings, "alert_hourly_t4_oi_change_24h", 0.40)
            and (stats.long_upper_wick_1h or stats.long_upper_wick_2h or stats.consecutive_red_1h)
        )
        if not matched:
            return None
        return AlertRuleResult(
            AlertType.HOURLY_TREND_T4,
            90,
            [
                "T4 overheat risk / T4 高位过热风险",
                "not a short signal / 不是做空信号",
            ],
            "T4 高位过热风险，不是做空信号；禁止追高，等待风险释放",
            metadata=self._metadata(stats, "T4", auto_paper=False, risk_tags=["禁止追高", "高位过热"]),
        )

    def _t2_acceleration(self, metrics: MarketMetrics) -> AlertRuleResult | None:
        stats = metrics.trend
        if stats is None:
            return None
        matched = (
            stats.price_change_12h > getattr(self.settings, "alert_hourly_t2_price_change_12h", 0.20)
            and stats.bullish_1h_count_12 >= getattr(self.settings, "alert_hourly_t2_bullish_count_12", 8)
            and metrics.price > stats.ma7 > stats.ma25
            and stats.ma7_slope > 0
            and stats.ma25_slope > 0
            and stats.oi_change_12h > getattr(self.settings, "alert_hourly_t2_oi_change_12h", 0.15)
            and stats.volume_avg_12h > stats.volume_avg_48h * getattr(self.settings, "alert_hourly_t2_volume_expansion", 1.5)
            and stats.recent_3h_holds_ma25
        )
        if not matched:
            return None
        return AlertRuleResult(
            AlertType.HOURLY_TREND_T2,
            86,
            [
                "T2 trend acceleration / T2 趋势加速",
                "hourly moving averages are rising / 小时级均线同步上行",
            ],
            "T2 趋势加速，可用模拟单跟踪主升质量",
            invalidation_price=stats.ma25,
            target_1=metrics.price * 1.10,
            target_2=metrics.price * 1.20,
            metadata=self._metadata(stats, "T2", auto_paper=True),
        )

    def _t1_start(self, metrics: MarketMetrics) -> AlertRuleResult | None:
        stats = metrics.trend
        if stats is None:
            return None
        matched = (
            stats.price_change_6h > getattr(self.settings, "alert_hourly_t1_price_change_6h", 0.08)
            and metrics.price > stats.ma25
            and stats.ma7 >= stats.ma25 * getattr(self.settings, "alert_hourly_t1_ma7_ma25_min_ratio", 0.995)
            and stats.current_1h_volume > stats.volume_avg_20h * getattr(self.settings, "alert_hourly_t1_volume_multiplier", 1.5)
            and stats.oi_change_6h > getattr(self.settings, "alert_hourly_t1_oi_change_6h", 0.08)
            and stats.close_above_high_12h_previous
        )
        if not matched:
            return None
        return AlertRuleResult(
            AlertType.HOURLY_TREND_T1,
            72,
            [
                "T1 trend start / T1 趋势启动",
                "price broke above prior 12h high / 价格突破前12小时高点",
            ],
            "T1 趋势启动，先观察能否放量站稳",
            invalidation_price=stats.ma25,
            target_1=metrics.price * 1.06,
            target_2=metrics.price * 1.12,
            metadata=self._metadata(stats, "T1", auto_paper=False),
        )

    @staticmethod
    def _metadata(stats: Any, trend_level: str, auto_paper: bool, risk_tags: list[str] | None = None) -> dict[str, Any]:
        """Pack trend-only fields into raw_json instead of widening the alert table.
        将趋势专属字段放入 raw_json，避免频繁扩表。
        """

        return {
            "trend_level": trend_level,
            "auto_paper": auto_paper,
            "timeframe": "1h",
            "price_change_6h": stats.price_change_6h,
            "price_change_12h": stats.price_change_12h,
            "price_change_24h": stats.price_change_24h,
            "volume_ratio": stats.volume_ratio,
            "oi_change_6h": stats.oi_change_6h,
            "oi_change_12h": stats.oi_change_12h,
            "oi_change_24h": stats.oi_change_24h,
            "rsi6": stats.rsi6,
            "rsi24": stats.rsi24,
            "ma_structure": stats.ma_structure,
            "distance_to_ma7": stats.distance_to_ma7,
            "distance_to_ma25": stats.distance_to_ma25,
            "funding_rate": stats.funding_rate,
            "risk_tags": risk_tags or [],
        }

