"""Telegram notification client.
Telegram 通知客户端。
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from app.strategies.base import Signal

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send trading system notifications to Telegram.
    向 Telegram 发送交易系统通知。
    """

    def __init__(self, bot_token: str = "", chat_id: str = "", timeout: float = 10.0, proxy: str = "") -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self.proxy = proxy

    @property
    def enabled(self) -> bool:
        """Return whether Telegram credentials are configured.
        判断 Telegram 凭据是否已配置。
        """

        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str) -> bool:
        """Send a message, or log it when Telegram is not configured.
        发送消息；未配置 Telegram 时写入日志。
        """

        if not self.enabled:
            logger.info("Telegram disabled: %s", text)
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        try:
            response = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=self.timeout, proxies=proxies)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Telegram send failed without blocking runtime: %s", exc.__class__.__name__)
            return False
        return True

    def notify_startup(self, mode: str) -> bool:
        return self.send_message(f"Trading bot started in {mode} mode. Real trading is disabled by default.")

    def notify_signal(self, signal: Signal) -> bool:
        return self.send_message(f"Signal {signal.symbol} {signal.side} confidence={signal.confidence:.2f}: {signal.reason}")

    def notify_paper_order(self, order: Any) -> bool:
        return self.send_message(f"Paper order #{order.id}: {order.side} {order.symbol} qty={order.quantity} entry={order.entry_price}")

    def notify_risk_block(self, signal: Signal, reason: str) -> bool:
        return self.send_message(f"Risk blocked {signal.symbol} {signal.side}: {reason}")

    def notify_error(self, message: str) -> bool:
        return self.send_message(f"Error: {message}")
