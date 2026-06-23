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
from app.execution.paper import PaperTradingEngine
from app.exchange.binance import BinanceFuturesClient
from app.main import build_telegram_notifiers
from app.risk.manager import RiskManager
from app.storage.sqlite import SQLiteStorage


def main() -> None:
    """Create dependencies and run one alert radar cycle.
    创建依赖并执行一轮行情雷达扫描。
    """

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    storage = SQLiteStorage(settings.database_path)
    client = BinanceFuturesClient(proxy=settings.exchange_proxy)
    notifier, order_notifier = build_telegram_notifiers(settings)
    paper = PaperTradingEngine(storage=storage, notifier=order_notifier, initial_equity=settings.account_equity, leverage=settings.paper_leverage)
    risk_manager = RiskManager(account_equity=settings.account_equity, btc_drop_threshold_15m=settings.btc_drop_threshold_15m)
    radar = MarketAlertRadar(MarketScanner(client, settings), storage, notifier, settings, paper=paper, risk_manager=risk_manager)
    alerts = radar.run_once()
    print(f"Alert radar generated {len(alerts)} alerts.")
    for alert in alerts[:10]:
        print("-" * 80)
        print(format_alert_message(alert))


if __name__ == "__main__":
    main()
