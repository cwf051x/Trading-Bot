"""Pump pullback and second-wave radar rule.
爆拉后健康回调与二波启动雷达规则。
"""

from __future__ import annotations

from typing import Any

from app.alerts.rules.base import AlertRule
from app.alerts.signal_models import AlertRuleResult, AlertType, MarketMetrics, PumpPullbackStats


class PumpPullbackSecondWaveRule(AlertRule):
    """Detect healthy pullback after a first pump and second-wave restart.
    识别第一次爆拉后的健康回调，以及二波重新启动。
    """

    name = "pump_pullback_second_wave"

    def required_timeframes(self) -> set[str]:
        return {"5m", "15m", "1h"}

    def required_oi_periods(self) -> set[str]:
        return {"5m", "15m"}

    def evaluate(self, metrics: MarketMetrics, state: dict[str, Any]) -> list[AlertRuleResult]:
        config = self.settings.radar_rule_config["pump_pullback_second_wave"]
        if not bool(config["enabled"]):
            return []
        stats = metrics.pump_pullback
        if stats is None or not stats.has_first_pump:
            return []
        for builder in (self._p4_failure, self._p3_confirmation, self._p2_restart, self._p1_watch):
            result = builder(metrics, stats, state, config)
            if result:
                return [result]
        return []

    def _p1_watch(self, metrics: MarketMetrics, stats: PumpPullbackStats, state: dict[str, Any], config: dict[str, Any]) -> AlertRuleResult | None:
        if not self._healthy_pullback(stats, config):
            return None
        return AlertRuleResult(
            AlertType.PUMP_PULLBACK_P1,
            70,
            [
                "P1 healthy pullback after first pump / P1 爆拉后健康回调",
                "added to second-wave watch pool / 加入二波观察池",
            ],
            "P1 健康回调，加入二波观察池，不推手机",
            invalidation_price=stats.range_low or None,
            target_1=stats.range_high or None,
            target_2=stats.pump_high or None,
            metadata=self._metadata(stats, "P1", auto_paper=False, send_to_telegram=False),
        )

    def _p2_restart(self, metrics: MarketMetrics, stats: PumpPullbackStats, state: dict[str, Any], config: dict[str, Any]) -> AlertRuleResult | None:
        p2 = config["p2"]
        matched = (
            self._healthy_pullback(stats, config)
            and metrics.price > stats.ma7_15m
            and metrics.price > stats.ma25_15m
            and (stats.ma7_15m >= stats.ma25_15m or stats.ma7_crossed_above_ma25_15m)
            and stats.recent_15m_change_3bars > p2["recent_15m_change_3bars"]
            and stats.volume_ratio_15m > p2["volume_ratio_15m"]
            and stats.oi_change_30m > p2["oi_change_30m"]
            and stats.rsi6_crossed_above_rsi24_15m
            and stats.rsi24_15m is not None
            and stats.rsi24_15m > p2["rsi24_min"]
        )
        if not matched:
            return None
        return AlertRuleResult(
            AlertType.PUMP_PULLBACK_P2,
            82,
            [
                "P2 second-wave restart warning / P2 二波启动预警",
                "healthy pullback is ending / 健康回调接近结束",
            ],
            "P2 二波启动预警，可用模拟单跟踪",
            invalidation_price=stats.range_low or None,
            target_1=stats.range_high or None,
            target_2=stats.pump_high or None,
            metadata=self._metadata(stats, "P2", auto_paper=True, cooldown_seconds=p2["cooldown_seconds"]),
        )

    def _p3_confirmation(self, metrics: MarketMetrics, stats: PumpPullbackStats, state: dict[str, Any], config: dict[str, Any]) -> AlertRuleResult | None:
        p3 = config["p3"]
        matched = (
            self._p2_restart(metrics, stats, state, config) is not None
            and stats.price_breaks_range_high
            and stats.volume_ratio_15m > p3["volume_ratio_15m"]
            and stats.oi_change_1h > p3["oi_change_1h"]
            and metrics.price > stats.ma7_15m > stats.ma25_15m
            and (stats.one_hour_close_above_ma7 or stats.one_hour_reclaimed_ma7)
            and stats.price_near_or_above_pump_high
        )
        if not matched:
            return None
        return AlertRuleResult(
            AlertType.PUMP_PULLBACK_P3,
            90,
            [
                "P3 second-wave breakout confirmation / P3 二波确认突破",
                "range high has been cleared / 突破回调震荡平台高点",
            ],
            "P3 二波确认突破，优先级高，可用模拟单跟踪",
            invalidation_price=stats.range_low or None,
            target_1=stats.pump_high or None,
            target_2=metrics.price * 1.12,
            metadata=self._metadata(stats, "P3", auto_paper=True, range_breakout_key=round(stats.range_high, 10)),
        )

    def _p4_failure(self, metrics: MarketMetrics, stats: PumpPullbackStats, state: dict[str, Any], config: dict[str, Any]) -> AlertRuleResult | None:
        if state.get("state") not in {"pump_pullback_p2", "pump_pullback_p3"} and state.get("last_alert_type") not in {AlertType.PUMP_PULLBACK_P2.value, AlertType.PUMP_PULLBACK_P3.value}:
            return None
        matched = (
            stats.fell_back_into_range
            or metrics.price < stats.ma25_15m
            or stats.oi_up_price_down
            or stats.long_upper_wick_15m
            or stats.broke_pullback_low
        )
        if not matched:
            return None
        return AlertRuleResult(
            AlertType.PUMP_PULLBACK_P4,
            88,
            [
                "P4 second-wave failure risk / P4 二波失败风险",
                "cancel second-wave watch / 取消二波观察",
            ],
            "P4 二波失败风险，取消观察",
            metadata=self._metadata(stats, "P4", auto_paper=False, bypass_cooldown=True, cancel_watch=True, risk_tags=["二波失败", "取消观察"]),
        )

    @staticmethod
    def _healthy_pullback(stats: PumpPullbackStats, config: dict[str, Any]) -> bool:
        pullback = config["pullback"]
        return (
            stats.pullback_from_high >= pullback["min_pullback_from_high"]
            and stats.retracement_ratio <= pullback["max_retracement_ratio"]
            and stats.pullback_volume_ratio <= pullback["max_pullback_volume_ratio"]
            and stats.oi_drawdown_from_peak <= pullback["max_oi_drawdown_from_peak"]
            and stats.price_above_pump_start
            and stats.price_above_1h_ma25
            and stats.price_above_1h_ma99
        )

    @staticmethod
    def _metadata(
        stats: PumpPullbackStats,
        level: str,
        auto_paper: bool,
        send_to_telegram: bool = True,
        bypass_cooldown: bool = False,
        cancel_watch: bool = False,
        range_breakout_key: float | None = None,
        cooldown_seconds: int | None = None,
        risk_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Pack rule-specific fields into raw_json.
        将规则专属字段打包进 raw_json。
        """

        return {
            "pump_pullback_level": level,
            "timeframe": "15m",
            "auto_paper": auto_paper,
            "send_to_telegram": send_to_telegram,
            "bypass_cooldown": bypass_cooldown,
            "cancel_watch": cancel_watch,
            "range_breakout_key": range_breakout_key,
            "cooldown_seconds": cooldown_seconds,
            "pump_start_time": stats.pump_start_time,
            "pump_high_time": stats.pump_high_time,
            "pump_change": stats.pump_change,
            "pullback_from_high": stats.pullback_from_high,
            "retracement_ratio": stats.retracement_ratio,
            "pullback_volume_ratio": stats.pullback_volume_ratio,
            "oi_drawdown_from_peak": stats.oi_drawdown_from_peak,
            "oi_change_30m": stats.oi_change_30m,
            "oi_change_1h": stats.oi_change_1h,
            "volume_ratio_15m": stats.volume_ratio_15m,
            "rsi6_15m": stats.rsi6_15m,
            "rsi24_15m": stats.rsi24_15m,
            "ma_structure_15m": stats.ma_structure_15m,
            "ma_structure_1h": stats.ma_structure_1h,
            "range_high": stats.range_high,
            "range_low": stats.range_low,
            "risk_tags": risk_tags or [],
        }
