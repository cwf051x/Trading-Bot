"""Market alert radar orchestration.
行情信号雷达编排模块。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.alerts.alert_rules import AlertRuleEngine
from app.alerts.alert_state import AlertStateManager
from app.alerts.scanner import MarketScanner
from app.alerts.scoring import level_from_score
from app.alerts.signal_models import AlertLevel, AlertSignal, AlertType, MarketMetrics
from app.alerts.telegram_formatter import format_alert_message
from app.notify.telegram import TelegramNotifier
from app.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

ALERT_NOTIFICATION_PRIORITY = {
    AlertType.HIGH_RISK_EXTENSION: 100,
    AlertType.PULLBACK_SECOND_LEG: 95,
    AlertType.MULTI_TIMEFRAME_BREAKOUT: 90,
    AlertType.SHORT_TERM_SURGE: 80,
    AlertType.TOP_GAINER_MOMENTUM: 70,
    AlertType.STRONG_PULLBACK_WATCH: 60,
}


class MarketAlertRadar:
    """Run one or more market alert scanning cycles.
    运行一轮或多轮行情雷达扫描。
    """

    def __init__(self, scanner: MarketScanner, storage: SQLiteStorage, notifier: TelegramNotifier, settings: Any) -> None:
        self.scanner = scanner
        self.storage = storage
        self.notifier = notifier
        self.settings = settings
        self.rules = AlertRuleEngine(settings)
        self.state = AlertStateManager(storage, settings)
        self._last_error_sent_at = 0.0

    def run_once(self) -> list[AlertSignal]:
        """Run one scan, persist alerts, and send configured notifications.
        执行一轮扫描、保存提醒，并按配置发送通知。
        """

        self.storage.initialize()
        if not self.settings.alert_radar_enabled:
            logger.info("Alert radar disabled by ALERT_RADAR_ENABLED=false")
            return []
        try:
            metrics_rows = self.scanner.scan()
        except Exception as exc:
            logger.exception("Alert radar scan failed: %s", exc)
            self._notify_error_throttled(f"Alert radar scan failed: {exc}")
            return []
        alerts: list[AlertSignal] = []
        for metrics in metrics_rows:
            state = self.state.get_state(metrics.symbol)
            symbol_alerts: list[AlertSignal] = []
            for result in self.rules.evaluate(metrics, state):
                alert = self._build_alert(metrics, result.alert_type, result.score, result.reasons, result.suggested_action, result.invalidation_price, result.target_1, result.target_2, result.metadata)
                if alert.level == AlertLevel.IGNORE:
                    continue
                symbol_alerts.append(alert)
            notification_winner = self._select_notification_winner(symbol_alerts)
            for alert in symbol_alerts:
                should_send = self.state.should_send(alert)
                if notification_winner and alert.alert_type != notification_winner.alert_type:
                    should_send = False
                sent_to_telegram = False
                if should_send:
                    sent_to_telegram = self.notifier.send_message(format_alert_message(alert))
                persisted_alert = AlertSignal(**{**alert.__dict__, "sent_to_telegram": sent_to_telegram})
                self.state.record_alert(persisted_alert, sent_to_telegram=sent_to_telegram)
                if should_send and not sent_to_telegram:
                    logger.warning("Alert %s %s qualified for Telegram but send failed", alert.symbol, alert.alert_type.value)
                if notification_winner and alert.alert_type != notification_winner.alert_type:
                    logger.info("Alert %s %s stored without Telegram because %s has same-cycle priority", alert.symbol, alert.alert_type.value, notification_winner.alert_type.value)
                elif not should_send:
                    logger.info("Alert %s %s stored without Telegram because level config or cooldown blocked it", alert.symbol, alert.alert_type.value)
                alerts.append(persisted_alert)
        return sorted(alerts, key=lambda item: item.score, reverse=True)

    def _select_notification_winner(self, alerts: list[AlertSignal]) -> AlertSignal | None:
        """Select at most one Telegram candidate for the same symbol in one cycle.
        为同一交易对同一轮扫描最多选择一条 Telegram 候选。
        """

        candidates = [alert for alert in alerts if alert.should_consider_notification]
        if not candidates:
            return None
        return max(candidates, key=lambda alert: (ALERT_NOTIFICATION_PRIORITY[alert.alert_type], alert.score))

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
        return AlertSignal(
            timestamp=int(time.time() * 1000),
            symbol=metrics.symbol,
            alert_type=alert_type,
            level=level_from_score(score),
            score=score,
            price=metrics.price,
            price_change_3m=metrics.stats_3m.change,
            price_change_5m=metrics.stats_5m.change,
            price_change_15m=metrics.stats_15m.change,
            price_change_1h=metrics.stats_1h.change,
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
