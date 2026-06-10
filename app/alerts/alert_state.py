"""SQLite-backed state manager for market alert radar.
基于 SQLite 的行情雷达状态管理器。
"""

from __future__ import annotations

import time
from typing import Any

from app.alerts.signal_models import AlertLevel, AlertSignal, AlertType
from app.storage.sqlite import SQLiteStorage


class AlertStateManager:
    """Track alert cooldowns and symbol watch states.
    跟踪提醒冷却期和交易对观察状态。
    """

    def __init__(self, storage: SQLiteStorage, settings: Any) -> None:
        self.storage = storage
        self.settings = settings

    def get_state(self, symbol: str) -> dict[str, Any] | None:
        """Return stored state for a symbol.
        返回某个交易对的已存状态。
        """

        return self.storage.get_alert_state(symbol)

    def cooldown_seconds(self, level: AlertLevel) -> int:
        """Return configured cooldown seconds for a level.
        返回某个等级的配置冷却秒数。
        """

        if level == AlertLevel.A:
            return int(self.settings.alert_cooldown_a_seconds)
        if level == AlertLevel.B:
            return int(self.settings.alert_cooldown_b_seconds)
        if level == AlertLevel.C:
            return int(self.settings.alert_cooldown_c_seconds)
        return 3600

    def should_send(self, alert: AlertSignal, now_ms: int | None = None) -> bool:
        """Return whether Telegram should send this alert now.
        判断当前是否应该发送该提醒到 Telegram。
        """

        if alert.level == AlertLevel.IGNORE:
            return False
        if alert.level == AlertLevel.A and not self.settings.alert_send_a_level:
            return False
        if alert.level == AlertLevel.B and not self.settings.alert_send_b_level:
            return False
        if alert.level == AlertLevel.C and not self.settings.alert_send_c_level:
            return False
        last_alert = self.storage.get_last_market_alert(alert.symbol, alert.alert_type.value, sent_only=True)
        if not last_alert:
            return True
        last_alert_at = int(last_alert.get("timestamp") or 0)
        now_ms = now_ms or alert.timestamp or int(time.time() * 1000)
        elapsed_seconds = max(0, (now_ms - last_alert_at) / 1000)
        return elapsed_seconds >= self.cooldown_seconds(alert.level)

    def record_alert(self, alert: AlertSignal, sent_to_telegram: bool) -> None:
        """Persist alert and update state.
        持久化提醒并更新状态。
        """

        payload = {
            "timestamp": alert.timestamp,
            "symbol": alert.symbol,
            "alert_type": alert.alert_type.value,
            "level": alert.level.value,
            "score": alert.score,
            "price": alert.price,
            "price_change_3m": alert.price_change_3m,
            "price_change_5m": alert.price_change_5m,
            "price_change_15m": alert.price_change_15m,
            "price_change_1h": alert.price_change_1h,
            "price_change_24h": alert.price_change_24h,
            "volume_ratio": alert.volume_ratio,
            "btc_15m_change": alert.btc_15m_change,
            "reason": alert.reason_text,
            "suggested_action": alert.suggested_action,
            "invalidation_price": alert.invalidation_price,
            "target_1": alert.target_1,
            "target_2": alert.target_2,
            "sent_to_telegram": sent_to_telegram,
            "raw_json": alert.raw,
        }
        self.storage.save_market_alert(payload)
        existing_state = self.get_state(alert.symbol) or {}
        state_name = self._state_name(alert.alert_type, existing_state)
        self.storage.upsert_alert_state(
            {
                "symbol": alert.symbol,
                "state": state_name,
                "last_alert_type": alert.alert_type.value,
                "last_alert_score": alert.score,
                "last_alert_price": alert.price,
                "last_alert_at": alert.timestamp,
                "watch_high": alert.target_1 if alert.target_1 is not None else existing_state.get("watch_high"),
                "watch_low": alert.invalidation_price if alert.invalidation_price is not None else existing_state.get("watch_low"),
                "support_price": alert.invalidation_price if alert.invalidation_price is not None else existing_state.get("support_price"),
                "invalidation_price": alert.invalidation_price if alert.invalidation_price is not None else existing_state.get("invalidation_price"),
                "metadata_json": alert.raw,
            }
        )

    def mark_pullback_watch(self, alert: AlertSignal) -> None:
        """Persist pullback watch state for later second-leg detection.
        保存回调观察状态，供后续二次启动识别使用。
        """

        self.storage.upsert_alert_state(
            {
                "symbol": alert.symbol,
                "state": "pullback_watch",
                "last_alert_type": alert.alert_type.value,
                "last_alert_score": alert.score,
                "last_alert_price": alert.price,
                "last_alert_at": alert.timestamp,
                "watch_high": alert.target_1,
                "watch_low": alert.invalidation_price,
                "support_price": alert.invalidation_price,
                "invalidation_price": alert.invalidation_price,
                "metadata_json": alert.raw,
            }
        )

    @staticmethod
    def _state_name(alert_type: AlertType, existing_state: dict[str, Any] | None = None) -> str:
        """Map alert type to durable state name.
        将提醒类型映射为可持久化状态名。
        """

        existing_name = (existing_state or {}).get("state")
        if alert_type == AlertType.STRONG_PULLBACK_WATCH:
            return "pullback_watch"
        if alert_type == AlertType.PULLBACK_SECOND_LEG:
            return "second_leg_triggered"
        if alert_type == AlertType.TOP_GAINER_MOMENTUM:
            return "strong_watch"
        if existing_name == "pullback_watch":
            return "pullback_watch"
        return "alerted"
