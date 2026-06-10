"""Rule engine for market alert radar.
行情雷达规则引擎。
"""

from __future__ import annotations

from typing import Any

from app.alerts.scoring import score_metrics
from app.alerts.signal_models import AlertRuleResult, AlertType, MarketMetrics


class AlertRuleEngine:
    """Evaluate market metrics and emit alert candidates.
    评估行情指标并输出提醒候选。
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def evaluate(self, metrics: MarketMetrics, state: dict[str, Any] | None = None) -> list[AlertRuleResult]:
        """Run all alert rules for one symbol.
        对单个交易对运行全部提醒规则。
        """

        if metrics.price <= 0:
            return []
        state = state or {}
        results: list[AlertRuleResult] = []
        for rule in (
            self._top_gainer_momentum,
            self._short_term_surge,
            self._multi_timeframe_breakout,
            self._strong_pullback_watch,
            self._pullback_second_leg,
            self._high_risk_extension,
        ):
            result = rule(metrics, state)
            if result:
                results.append(result)
        return results

    def _base_score(self, metrics: MarketMetrics) -> tuple[int, list[str]]:
        score = score_metrics(metrics)
        return score.normalized(), list(score.reasons)

    def _top_gainer_momentum(self, metrics: MarketMetrics, state: dict[str, Any]) -> AlertRuleResult | None:
        if metrics.rank_24h is None or metrics.rank_24h > self.settings.alert_top_gainers_limit:
            return None
        if metrics.quote_volume_24h < self.settings.alert_min_24h_quote_volume_usdt:
            return None
        if metrics.stats_1h.change <= 0 or metrics.stats_15m.change <= -0.03:
            return None
        if metrics.stats_15m.rejection:
            return None
        score, reasons = self._base_score(metrics)
        reasons.append("top gainer momentum candidate / 涨幅榜强势候选")
        suggested_action = "强势延续，可关注突破/轻仓追踪"
        if self._is_overheated(metrics):
            suggested_action = "高位加速，谨慎追高，等待回调"
        elif metrics.stats_5m.higher_lows and metrics.stats_5m.volume_ratio < self.settings.alert_volume_ratio_threshold:
            suggested_action = "强势横盘，关注再次放量突破"
        return AlertRuleResult(AlertType.TOP_GAINER_MOMENTUM, score, reasons, suggested_action)

    def _short_term_surge(self, metrics: MarketMetrics, state: dict[str, Any]) -> AlertRuleResult | None:
        surge = (
            metrics.stats_3m.change >= self.settings.alert_surge_3m_threshold
            or metrics.stats_5m.change >= self.settings.alert_surge_5m_threshold
            or metrics.stats_15m.change >= self.settings.alert_surge_15m_threshold
        )
        volume_ratio = max(metrics.stats_3m.volume_ratio, metrics.stats_5m.volume_ratio, metrics.stats_15m.volume_ratio)
        near_high = metrics.stats_5m.recent_high is not None and metrics.price >= metrics.stats_5m.recent_high * 0.985
        if not surge or volume_ratio < self.settings.alert_volume_ratio_threshold or not near_high:
            return None
        if metrics.stats_5m.close_position < self.settings.alert_min_breakout_close_position:
            return None
        if metrics.stats_5m.rejection or metrics.stats_15m.rejection:
            return None
        score, reasons = self._base_score(metrics)
        reasons.append("short-term surge with volume / 短周期放量异动")
        return AlertRuleResult(AlertType.SHORT_TERM_SURGE, score, reasons, "短周期异动，建议加入突破追踪")

    def _multi_timeframe_breakout(self, metrics: MarketMetrics, state: dict[str, Any]) -> AlertRuleResult | None:
        if not metrics.stats_5m.breakout:
            return None
        if not (metrics.stats_15m.breakout or (metrics.stats_15m.recent_high is not None and metrics.price >= metrics.stats_15m.recent_high * 0.99)):
            return None
        if not metrics.stats_5m.higher_lows or not metrics.stats_15m.higher_lows:
            return None
        if metrics.stats_5m.volume_ratio < self.settings.alert_volume_ratio_threshold:
            return None
        if metrics.stats_15m.volume_ratio < self.settings.alert_volume_ratio_threshold * 0.65:
            return None
        if metrics.stats_5m.close_position < self.settings.alert_min_breakout_close_position:
            return None
        if metrics.btc_15m_change <= self.settings.alert_btc_dump_15m_threshold:
            return None
        score, reasons = self._base_score(metrics)
        reasons.append("multi-timeframe breakout / 多周期连续突破")
        action = "突破确认"
        if metrics.stats_5m.rejection:
            action = "假突破风险"
        elif metrics.stats_5m.volume_ratio < self.settings.alert_volume_ratio_threshold * 1.2:
            action = "等待回踩确认"
        return AlertRuleResult(AlertType.MULTI_TIMEFRAME_BREAKOUT, score, reasons, action)

    def _strong_pullback_watch(self, metrics: MarketMetrics, state: dict[str, Any]) -> AlertRuleResult | None:
        was_strong = metrics.price_change_24h >= 0.12 or metrics.stats_1h.change >= 0.06
        pullback = metrics.stats_15m.pullback_ratio
        if not was_strong:
            return None
        if pullback < self.settings.alert_pullback_min_ratio or pullback > self.settings.alert_pullback_max_ratio:
            return None
        if metrics.stats_15m.volume_ratio >= self.settings.alert_pullback_volume_contraction_max:
            return None
        if metrics.stats_15m.recent_low is not None and metrics.price < metrics.stats_15m.recent_low:
            return None
        if metrics.btc_15m_change <= self.settings.alert_btc_dump_15m_threshold:
            return None
        score, reasons = self._base_score(metrics)
        reasons.append("strong coin pullback watch / 强势币回调观察")
        invalidation = metrics.stats_15m.recent_low
        target_1 = metrics.stats_15m.recent_high
        target_2 = target_1 * 1.08 if target_1 else None
        return AlertRuleResult(AlertType.STRONG_PULLBACK_WATCH, score, reasons, "当前处于回调观察，等待二次启动确认", invalidation, target_1, target_2)

    def _pullback_second_leg(self, metrics: MarketMetrics, state: dict[str, Any]) -> AlertRuleResult | None:
        if state.get("state") not in {"pullback_watch", AlertType.STRONG_PULLBACK_WATCH.value}:
            return None
        support = float(state.get("support_price") or state.get("watch_low") or metrics.stats_15m.recent_low or 0.0)
        if support and metrics.price < support:
            return None
        restarted = (
            (metrics.stats_5m.change > 0 and metrics.stats_5m.volume_ratio >= self.settings.alert_volume_ratio_threshold)
            or (metrics.stats_15m.change > 0 and metrics.stats_15m.volume_ratio >= self.settings.alert_volume_ratio_threshold)
        )
        if not restarted or not metrics.stats_5m.higher_lows or not metrics.stats_5m.closes_above_ma:
            return None
        if metrics.stats_5m.close_position < self.settings.alert_second_leg_min_close_position:
            return None
        if metrics.stats_5m.rejection:
            return None
        if metrics.btc_15m_change <= self.settings.alert_btc_dump_15m_threshold:
            return None
        score, reasons = self._base_score(metrics)
        score = min(100, score + 10)
        reasons.append("pullback second leg restart / 回调后二次启动")
        invalidation = support or metrics.stats_5m.recent_low
        target_1 = float(state.get("watch_high") or metrics.stats_15m.recent_high or metrics.price * 1.05)
        target_2 = target_1 * 1.08
        return AlertRuleResult(AlertType.PULLBACK_SECOND_LEG, score, reasons, "回调二启，观察5m收稳后的低风险入场区", invalidation, target_1, target_2)

    def _high_risk_extension(self, metrics: MarketMetrics, state: dict[str, Any]) -> AlertRuleResult | None:
        overextended = (
            self._is_overheated(metrics)
            or metrics.stats_15m.distance_to_ma > 0.10
            or metrics.stats_15m.large_green_count >= 3
            or metrics.stats_15m.rejection
        )
        if not overextended:
            return None
        score, reasons = self._base_score(metrics)
        score = max(score, 70)
        reasons.append("high risk extension detected / 检测到高位延伸风险")
        return AlertRuleResult(AlertType.HIGH_RISK_EXTENSION, score, reasons, "高位风险，谨慎追入，更适合等待回调")

    def _is_overheated(self, metrics: MarketMetrics) -> bool:
        """Return whether the move is stretched enough to prefer caution.
        判断行情是否已经延伸过度，应优先谨慎。
        """

        rsi_overheated = (
            (metrics.stats_15m.rsi is not None and metrics.stats_15m.rsi >= self.settings.alert_overheat_rsi)
            or (metrics.stats_1h.rsi is not None and metrics.stats_1h.rsi >= self.settings.alert_overheat_rsi)
        )
        return metrics.stats_15m.change >= self.settings.alert_high_risk_15m_change or metrics.stats_1h.change >= self.settings.alert_high_risk_1h_change or rsi_overheated
