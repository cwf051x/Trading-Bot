"""Run one market alert radar scan.
运行一轮行情信号雷达扫描。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.alerts.radar import MarketAlertRadar
from app.alerts.scanner import MarketScanner
from app.alerts.telegram_formatter import format_alert_message
from app.config import get_settings
from app.exchange.binance import BinanceFuturesClient
from app.notify.telegram import TelegramNotifier
from app.storage.sqlite import SQLiteStorage


def main() -> None:
    """Create dependencies and run one alert radar cycle.
    创建依赖并执行一轮行情雷达扫描。
    """

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    storage = SQLiteStorage(settings.database_path)
    client = BinanceFuturesClient(proxy=settings.exchange_proxy)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id, proxy=settings.telegram_proxy or settings.exchange_proxy)
    radar = MarketAlertRadar(MarketScanner(client, settings), storage, notifier, settings)
    alerts = radar.run_once()
    print(f"Alert radar generated {len(alerts)} alerts.")
    for alert in alerts[:10]:
        print("-" * 80)
        print(format_alert_message(alert))


if __name__ == "__main__":
    main()
