"""Market alert radar orchestration.
行情信号雷达编排模块。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.alerts.alert_rules import AlertRuleEngine
from app.alerts.alert_state import AlertStateManager
from app.alerts.profiling import CycleProfiler
from app.alerts.scanner import MarketScanner
from app.alerts.scoring import level_from_score
from app.alerts.signal_models import AlertLevel, AlertSignal, AlertType, MarketMetrics
from app.alerts.telegram_formatter import format_alert_message
from app.execution.paper import PaperTradingEngine
from app.notify.telegram import TelegramNotifier
from app.risk.manager import RiskManager
from app.storage.sqlite import SQLiteStorage
from app.strategies.base import Signal

logger = logging.getLogger(__name__)

ALERT_NOTIFICATION_PRIORITY = {
    AlertType.HIGH_RISK_EXTENSION: 100,
    AlertType.HOURLY_TREND_T4: 99,
    AlertType.PUMP_PULLBACK_P4: 99,
    AlertType.HOURLY_TREND_T3: 97,
    AlertType.PUMP_PULLBACK_P3: 96,
    AlertType.HOURLY_TREND_T2: 94,
    AlertType.PUMP_PULLBACK_P2: 93,
    AlertType.HOURLY_TREND_T1: 75,
    AlertType.PUMP_PULLBACK_P1: 65,
    AlertType.VOLUME_PRICE_OI_RESONANCE: 98,
    AlertType.PULLBACK_SECOND_LEG: 95,
    AlertType.MULTI_TIMEFRAME_BREAKOUT: 90,
    AlertType.SHORT_TERM_SURGE: 80,
    AlertType.TOP_GAINER_MOMENTUM: 70,
    AlertType.STRONG_PULLBACK_WATCH: 60,
}

AUTO_PAPER_ENTRY_TYPES = {
    AlertType.TOP_GAINER_MOMENTUM,
    AlertType.SHORT_TERM_SURGE,
    AlertType.MULTI_TIMEFRAME_BREAKOUT,
    AlertType.PULLBACK_SECOND_LEG,
    AlertType.VOLUME_PRICE_OI_RESONANCE,
    AlertType.HOURLY_TREND_T2,
    AlertType.HOURLY_TREND_T3,
    AlertType.PUMP_PULLBACK_P2,
    AlertType.PUMP_PULLBACK_P3,
}


class MarketAlertRadar:
    """Run one or more market alert scanning cycles.
    运行一轮或多轮行情雷达扫描。
    """

    def __init__(
        self,
        scanner: MarketScanner,
        storage: SQLiteStorage,
        notifier: TelegramNotifier,
        settings: Any,
        paper: PaperTradingEngine | None = None,
        risk_manager: RiskManager | None = None,
    ) -> None:
        self.scanner = scanner
        self.storage = storage
        self.notifier = notifier
        self.settings = settings
        self.paper = paper
        self.risk_manager = risk_manager
        self.rules = AlertRuleEngine(settings)
        self.state = AlertStateManager(storage, settings)
        self._last_error_sent_at = 0.0

    def run_once(self) -> list[AlertSignal]:
        """Run one scan, persist alerts, and send configured notifications.
        执行一轮扫描、保存提醒，并按配置发送通知。
        """

        cycle_started_at = time.perf_counter()
        profiler = CycleProfiler()
        alerts: list[AlertSignal] = []
        with profiler.measure("storage_initialize"):
            self.storage.initialize()
        try:
            if not self.settings.alert_radar_enabled:
                logger.info("Alert radar disabled by ALERT_RADAR_ENABLED=false")
                return []
            metrics_rows = self.scanner.scan()
            current_prices = {metrics.symbol: metrics.price for metrics in metrics_rows}
            scanner_profile = getattr(self.scanner, "last_profile", None)
            if scanner_profile is not None:
                profiler.merge(scanner_profile)
            profiler.set_meta(metrics=len(metrics_rows))
            cycle_candidates: list[AlertSignal] = []
            with profiler.measure("calculate_signals"):
                for metrics in metrics_rows:
                    if self.paper:
                        with profiler.measure("paper_mark_to_market"):
                            self.paper.update_open_positions(metrics.symbol, metrics.price, int(time.time() * 1000))
                    state = self.state.get_state(metrics.symbol)
                    symbol_alerts: list[AlertSignal] = []
                    for result in self.rules.evaluate(metrics, state):
                        alert = self._build_alert(metrics, result.alert_type, result.score, result.reasons, result.suggested_action, result.invalidation_price, result.target_1, result.target_2, result.metadata)
                        if alert.level == AlertLevel.IGNORE:
                            continue
                        if alert.score < self.settings.alert_min_score_to_store:
                            logger.info("Alert %s %s ignored because score %s is below store threshold", alert.symbol, alert.alert_type.value, alert.score)
                            continue
                        symbol_alerts.append(alert)
                    cycle_candidates.extend(self._select_symbol_family_winners(symbol_alerts))
            for alert in self._select_cycle_alerts(cycle_candidates):
                with profiler.measure("cooldown_check"):
                    should_record = self.state.should_record(alert)
                if not should_record:
                    logger.info("Alert %s %s skipped because storage cooldown blocked it", alert.symbol, alert.alert_type.value)
                    continue
                with profiler.measure("cooldown_check"):
                    should_send = self.state.should_send(alert)
                sent_to_telegram = False
                if should_send:
                    with profiler.measure("notify"):
                        sent_to_telegram = self.notifier.send_message(format_alert_message(alert))
                persisted_alert = AlertSignal(**{**alert.__dict__, "sent_to_telegram": sent_to_telegram})
                with profiler.measure("store_alerts"):
                    self.state.record_alert(persisted_alert, sent_to_telegram=sent_to_telegram)
                with profiler.measure("auto_paper"):
                    self._process_auto_paper_order(persisted_alert, current_prices=current_prices)
                notifier_enabled = bool(getattr(self.notifier, "enabled", False))
                if should_send and not sent_to_telegram and notifier_enabled:
                    logger.warning("Alert %s %s qualified for Telegram but send failed", alert.symbol, alert.alert_type.value)
                elif not should_send:
                    logger.info("Alert %s %s stored without Telegram because level config or cooldown blocked it", alert.symbol, alert.alert_type.value)
                alerts.append(persisted_alert)
            return sorted(alerts, key=lambda item: item.score, reverse=True)
        except Exception as exc:
            if "metrics_rows" not in locals():
                scanner_profile = getattr(self.scanner, "last_profile", None)
                if scanner_profile is not None:
                    profiler.merge(scanner_profile)
            logger.exception("Alert radar cycle failed: %s", exc)
            self._notify_error_throttled(f"Alert radar cycle failed: {exc}")
            return []
        finally:
            profiler.set_meta(alerts=len(alerts))
            profiler.log(logger, total_seconds=time.perf_counter() - cycle_started_at)

    def _process_auto_paper_order(self, alert: AlertSignal, current_prices: dict[str, float] | None = None) -> None:
        """Create a simulated order for actionable alert entries.
        根据可交易的 alert 创建模拟订单。
        """

        if not self.paper or not self.risk_manager:
            return
        if not self.settings.alert_auto_paper_trading_enabled:
            return
        if alert.alert_type not in AUTO_PAPER_ENTRY_TYPES:
            logger.info("Alert %s %s does not create paper order because it is not an entry type", alert.symbol, alert.alert_type.value)
            return
        if alert.raw.get("metadata", {}).get("auto_paper") is False:
            logger.info("Alert %s %s does not create paper order because metadata marks it risk-only", alert.symbol, alert.alert_type.value)
            return
        if alert.alert_type == AlertType.VOLUME_PRICE_OI_RESONANCE and alert.raw.get("metadata", {}).get("resonance_level") != "L2":
            logger.info("Alert %s %s does not create paper order because resonance level is not L2", alert.symbol, alert.alert_type.value)
            return
        if alert.price <= 0:
            return
        stop_loss = alert.invalidation_price if alert.invalidation_price is not None else alert.price * (1 - self.settings.strategy_stop_loss_pct)
        take_profit = alert.target_1 if alert.target_1 is not None else alert.price * (1 + self.settings.strategy_take_profit_pct)
        signal = Signal(
            symbol=alert.symbol,
            side="long",
            confidence=alert.score / 100,
            entry_price=alert.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=f"alert {alert.alert_type.value}: {alert.suggested_action}",
            timestamp=alert.timestamp,
        )
        decision = self.risk_manager.evaluate(signal, market_context={"current_prices": current_prices or {alert.symbol: alert.price}})
        if not decision.allowed:
            logger.info("Alert %s %s paper order blocked by risk: %s", alert.symbol, alert.alert_type.value, decision.reason)
            return
        order = self.paper.process_signal(signal, quantity=decision.position_size)
        if order:
            logger.info("Alert %s %s created paper order #%s", alert.symbol, alert.alert_type.value, order.id)

    def _select_notification_winner(self, alerts: list[AlertSignal]) -> AlertSignal | None:
        """Select at most one Telegram candidate for the same symbol in one cycle.
        为同一交易对同一轮扫描最多选择一条 Telegram 候选。
        """

        candidates = [alert for alert in alerts if alert.should_consider_notification]
        if not candidates:
            return None
        return max(candidates, key=lambda alert: (ALERT_NOTIFICATION_PRIORITY[alert.alert_type], alert.score))

    def _select_symbol_winner(self, alerts: list[AlertSignal]) -> AlertSignal | None:
        """Select the single strongest alert for one symbol in one cycle.
        为单个交易对在一轮扫描中只保留最强的一条提醒。
        """

        if not alerts:
            return None
        return max(alerts, key=self._alert_rank)

    def _select_symbol_family_winners(self, alerts: list[AlertSignal]) -> list[AlertSignal]:
        """Select one winner per rule family for a symbol in one cycle.
        同一交易对每个规则家族保留一条，避免短线共振盖掉趋势/二波观察。
        """

        winners: dict[str, AlertSignal] = {}
        for alert in alerts:
            family = self._alert_family(alert.alert_type)
            current = winners.get(family)
            if current is None or self._alert_rank(alert) > self._alert_rank(current):
                winners[family] = alert
        return sorted(winners.values(), key=self._alert_rank, reverse=True)

    def _select_cycle_alerts(self, alerts: list[AlertSignal]) -> list[AlertSignal]:
        """Select the highest-quality alerts allowed for one scan cycle.
        从一轮扫描中选出允许入库的最高质量提醒。
        """

        limit = max(0, int(self.settings.alert_max_alerts_per_cycle))
        if limit == 0:
            return []
        return sorted(alerts, key=self._alert_rank, reverse=True)[:limit]

    @staticmethod
    def _alert_rank(alert: AlertSignal) -> tuple[int, int, int]:
        """Rank alerts by level, rule priority, and score.
        按等级、规则优先级和分数给提醒排序。
        """

        level_rank = {AlertLevel.A: 3, AlertLevel.B: 2, AlertLevel.C: 1}.get(alert.level, 0)
        return (level_rank, ALERT_NOTIFICATION_PRIORITY[alert.alert_type], alert.score)

    @staticmethod
    def _alert_family(alert_type: AlertType) -> str:
        """Map alert types to independent rule families.
        将提醒类型映射到独立规则家族，用于同币多雷达并行观察。
        """

        if alert_type == AlertType.VOLUME_PRICE_OI_RESONANCE:
            return "volume_price_oi"
        if alert_type in {AlertType.HOURLY_TREND_T1, AlertType.HOURLY_TREND_T2, AlertType.HOURLY_TREND_T3, AlertType.HOURLY_TREND_T4}:
            return "hourly_trend"
        if alert_type in {AlertType.PUMP_PULLBACK_P1, AlertType.PUMP_PULLBACK_P2, AlertType.PUMP_PULLBACK_P3, AlertType.PUMP_PULLBACK_P4}:
            return "pump_pullback_second_wave"
        return "legacy_momentum"

    def _build_alert(
        self,
        metrics: MarketMetrics,
        alert_type: AlertType,
        score: int,
        reasons: list[str],
        suggested_action: str,
        invalidation_price: float | None,
        target_1: float | None,
        target_2: float | None,
        metadata: dict[str, Any],
    ) -> AlertSignal:
        """Build a normalized alert from rule output.
        根据规则输出构建标准化提醒。
        """

        volume_ratio = max(metrics.stats_3m.volume_ratio, metrics.stats_5m.volume_ratio, metrics.stats_15m.volume_ratio)
        price_change_15m = metrics.stats_15m.change
        price_change_1h = metrics.stats_1h.change
        if metrics.resonance is not None:
            volume_ratio = metrics.resonance.volume_ratio
            price_change_15m = metrics.resonance.price_change_15m
            price_change_1h = metrics.resonance.price_change_60m
        if alert_type in {AlertType.HOURLY_TREND_T1, AlertType.HOURLY_TREND_T2, AlertType.HOURLY_TREND_T3, AlertType.HOURLY_TREND_T4} and metrics.trend is not None:
            volume_ratio = metrics.trend.volume_ratio
            price_change_1h = metrics.stats_1h.change
        if alert_type in {AlertType.PUMP_PULLBACK_P1, AlertType.PUMP_PULLBACK_P2, AlertType.PUMP_PULLBACK_P3, AlertType.PUMP_PULLBACK_P4} and metrics.pump_pullback is not None:
            volume_ratio = metrics.pump_pullback.volume_ratio_15m
            price_change_15m = metrics.pump_pullback.recent_15m_change_3bars
            price_change_1h = metrics.stats_1h.change
        return AlertSignal(
            timestamp=int(time.time() * 1000),
            symbol=metrics.symbol,
            alert_type=alert_type,
            level=level_from_score(score),
            score=score,
            price=metrics.price,
            price_change_3m=metrics.stats_3m.change,
            price_change_5m=metrics.stats_5m.change,
            price_change_15m=price_change_15m,
            price_change_1h=price_change_1h,
            price_change_24h=metrics.price_change_24h,
            volume_ratio=volume_ratio,
            btc_15m_change=metrics.btc_15m_change,
            reasons=reasons,
            suggested_action=suggested_action,
            invalidation_price=invalidation_price,
            target_1=target_1,
            target_2=target_2,
            raw={"metrics": metrics.raw, "metadata": metadata},
        )

    def _notify_error_throttled(self, message: str) -> None:
        """Send radar errors at most once every five minutes.
        雷达错误通知最多每五分钟发送一次。
        """

        now = time.time()
        if now - self._last_error_sent_at < 300:
            return
        self._last_error_sent_at = now
        self.notifier.notify_error(message)
