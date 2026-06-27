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
        if not bool(self.settings.radar_rule_config.get("volume_price_oi", {}).get("enabled", True)):
            return []
        result = self._volume_price_oi_resonance(metrics)
        return [result] if result else []

    def _volume_price_oi_resonance(self, metrics: MarketMetrics) -> AlertRuleResult | None:
        """Detect volume-price-OI resonance on 5m candles.
        识别 5m 主周期的量价 OI 共振拉升。
        """

        stats = metrics.resonance
        if stats is None:
            return None
        config = self.settings.radar_rule_config["volume_price_oi"]
        l1_config = config["l1"]
        l2_config = config["l2"]
        l3_config = config["l3"]
        l3 = (
            stats.price_change_60m > l3_config["price_change_60m"]
            and stats.rsi6 is not None
            and stats.rsi6 > l3_config["rsi6"]
            and stats.ma25_deviation > l3_config["ma25_deviation"]
            and stats.oi_change_60m > l3_config["oi_change_60m"]
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
            stats.price_change_30m > l2_config["price_change_30m"]
            and stats.price_change_60m > l2_config["price_change_60m"]
            and stats.bullish_5m_count_6 >= l2_config["bullish_5m_count_6"]
            and stats.volume_continuity >= l2_config["volume_continuity"]
            and stats.oi_change_30m > l2_config["oi_change_30m"]
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
            stats.price_change_15m > l1_config["price_change_15m"]
            and stats.volume_ratio > l1_config["volume_ratio"]
            and stats.oi_change_15m > l1_config["oi_change_15m"]
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
        return self._volume_price_oi_l0(metrics)

    def _volume_price_oi_l0(self, metrics: MarketMetrics) -> AlertRuleResult | None:
        """Detect early price-led moves with volume/OI quality scoring.
        用价格作为硬门槛，并用成交量与 OI 做质量打分，识别早期异动。
        """

        stats = metrics.resonance
        if stats is None:
            return None
        config = self.settings.radar_rule_config["volume_price_oi"].get("l0", {})
        if not bool(config.get("enabled", True)):
            return None
        hard_filters = config.get("hard_filters", {})
        price_move_ok = stats.price_change_5m >= float(hard_filters.get("price_change_5m", 0.015)) or stats.price_change_15m >= float(hard_filters.get("price_change_15m", 0.025))
        if not price_move_ok:
            return None
        if metrics.stats_5m.close_position < float(hard_filters.get("close_position_min", 0.60)):
            return None
        if bool(hard_filters.get("price_above_ma7", True)) and metrics.price <= stats.ma7:
            return None
        if bool(hard_filters.get("reject_long_upper_wick", True)) and stats.long_upper_wick:
            return None
        if metrics.btc_15m_change <= float(hard_filters.get("btc_15m_drop_min", -0.008)):
            return None

        scoring = config.get("scoring", {})
        score = int(scoring.get("base_score", 55))
        volume_points = self._threshold_points(
            stats.volume_ratio,
            [
                (3.0, int(scoring.get("volume_ratio_3_0", 20))),
                (2.0, int(scoring.get("volume_ratio_2_0", 14))),
                (1.5, int(scoring.get("volume_ratio_1_5", 8))),
            ],
        )
        oi_points = self._threshold_points(
            stats.oi_change_15m,
            [
                (0.04, int(scoring.get("oi_change_15m_4", 16))),
                (0.02, int(scoring.get("oi_change_15m_2", 10))),
                (0.01, int(scoring.get("oi_change_15m_1", 6))),
            ],
        )
        score += volume_points + oi_points
        if volume_points > 0 and oi_points > 0:
            score += int(scoring.get("both_volume_and_oi_bonus", 10))
        if metrics.price > stats.ma25:
            score += int(scoring.get("price_above_ma25_bonus", 5))
        if metrics.rank_24h is not None and metrics.rank_24h <= 10:
            score += int(scoring.get("top_gainer_rank_bonus", 5))
        min_score = int(config.get("min_score_to_store", 60))
        score = min(100, score)
        if score < min_score:
            return None
        return AlertRuleResult(
            AlertType.VOLUME_PRICE_OI_L0,
            score,
            [
                "L0 early volume-price-OI watch / L0 量价OI早期异动",
                "price move is confirmed, volume and OI are quality scores / 价格涨幅达标，成交量和OI作为质量加分",
            ],
            "L0 早期观察，先入热榜跟踪，等待是否升级 L1/L2",
            metadata={
                "resonance_level": "L0",
                "signal_stage": "L0",
                "rule_family": "volume_price_oi",
                "auto_paper": bool(config.get("auto_paper", False)),
                "send_to_telegram": bool(config.get("send_to_telegram", False)),
                "digest": bool(config.get("digest", True)),
                "min_score_to_store": min_score,
                "min_score_to_digest": int(config.get("min_score_to_digest", 65)),
                "volume_ratio": stats.volume_ratio,
                "oi_change_15m": stats.oi_change_15m,
                "price_change_5m": stats.price_change_5m,
                "price_change_15m": stats.price_change_15m,
                "rank_24h": metrics.rank_24h,
            },
        )

    @staticmethod
    def _threshold_points(value: float, thresholds: list[tuple[float, int]]) -> int:
        """Return points for the highest matched threshold.
        返回命中的最高阈值对应加分。
        """

        for threshold, points in thresholds:
            if value >= threshold:
                return points
        return 0
