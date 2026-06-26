"""Run market alert radar in a polling loop.
循环运行行情信号雷达。
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.alerts.radar import MarketAlertRadar
from app.alerts.scanner import MarketScanner
from app.alerts.telegram_formatter import format_pct
from app.config import get_settings
from app.execution.paper import PaperTradingEngine
from app.exchange.binance import BinanceFuturesClient
from app.main import build_telegram_notifiers
from app.risk.manager import RiskManager
from app.storage.sqlite import SQLiteStorage


def main() -> None:
    """Run radar cycles until interrupted.
    持续运行雷达扫描直到手动中断。
    """

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    storage = SQLiteStorage(settings.database_path)
    client = BinanceFuturesClient(
        proxy=settings.exchange_proxy,
        network_mode=settings.exchange_network_mode,
        request_retries=settings.exchange_request_retries,
        retry_delay_seconds=settings.exchange_retry_delay_seconds,
    )
    notifier, order_notifier = build_telegram_notifiers(settings)
    paper = PaperTradingEngine(
        storage=storage,
        notifier=order_notifier,
        initial_equity=settings.account_equity,
        leverage=settings.paper_leverage,
        fee_rate=settings.paper_fee_rate,
        slippage_pct=settings.paper_slippage_pct,
        funding_rate=settings.paper_funding_rate,
    )
    risk_manager = RiskManager(
        account_equity=settings.account_equity,
        risk_per_trade_pct=settings.risk_per_trade_pct,
        max_symbol_position_pct=settings.risk_max_symbol_position_pct,
        max_total_exposure_pct=settings.risk_max_total_exposure_pct,
        max_open_positions=settings.risk_max_open_positions,
        max_consecutive_losses=settings.risk_max_consecutive_losses,
        btc_drop_threshold_15m=settings.btc_drop_threshold_15m,
        storage=storage,
        fee_rate=settings.paper_fee_rate,
        slippage_pct=settings.paper_slippage_pct,
        funding_rate=settings.paper_funding_rate,
    )
    if settings.alert_auto_paper_trading_enabled:
        logging.warning("ALERT_AUTO_PAPER_TRADING_ENABLED=true: ensure only one writer service creates paper orders")
    radar = MarketAlertRadar(MarketScanner(client, settings, storage=storage), storage, notifier, settings, paper=paper, risk_manager=risk_manager)
    while True:
        try:
            alerts = radar.run_once()
            logging.info("Alert radar cycle finished with %s alerts", len(alerts))
            for alert in alerts:
                telegram_status = "telegram=sent" if alert.sent_to_telegram else "telegram=stored"
                logging.info(
                    "Alert %s %s level=%s score=%s price=%.8g 15m=%s 1h=%s %s action=%s",
                    alert.symbol,
                    alert.alert_type.value,
                    alert.level.value,
                    alert.score,
                    alert.price,
                    format_pct(alert.price_change_15m),
                    format_pct(alert.price_change_1h),
                    telegram_status,
                    alert.suggested_action,
                )
        except KeyboardInterrupt:
            logging.info("Alert radar loop stopped by user")
            return
        time.sleep(settings.alert_scan_interval_seconds)


if __name__ == "__main__":
    main()
