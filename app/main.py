"""Application entry point for backtest, paper, and guarded live modes.
应用入口，负责回测、模拟盘和受保护 live 模式的调度。
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Any

from app.backtest.engine import BacktestEngine
from app.config import RunMode, get_settings
from app.data.closed_candles import closed_klines
from app.execution.paper import PaperTradingEngine
from app.exchange.binance import BinanceFuturesClient
from app.notify.telegram import TelegramNotifier
from app.risk.manager import RiskManager
from app.storage.sqlite import SQLiteStorage
from app.strategies.momentum_oi import MomentumOIStrategy


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser.
    构建命令行参数解析器。
    """

    parser = argparse.ArgumentParser(description="Crypto USDT-M futures trading system")
    parser.add_argument("--mode", choices=[mode.value for mode in RunMode], help="Override RUN_MODE")
    parser.add_argument("--csv", type=Path, help="Historical kline CSV path for backtest")
    parser.add_argument("--equity-curve-csv", type=Path, help="Optional equity curve export path")
    parser.add_argument("--once", action="store_true", help="Run one paper cycle and exit")
    return parser


def build_telegram_notifiers(settings: Any) -> tuple[TelegramNotifier, TelegramNotifier]:
    """Build separate Telegram clients for radar/system alerts and order flow.
    构建雷达/系统通知与订单流水通知两个 Telegram 客户端，方便降低消息互相干扰。
    """

    alert_proxy = settings.telegram_proxy or settings.exchange_proxy
    alert_notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id, proxy=alert_proxy)
    if not getattr(settings, "telegram_order_enabled", True):
        return alert_notifier, TelegramNotifier()

    # 未配置订单专用通道时回退到原通知通道，避免升级后静默丢失订单通知。
    order_token = getattr(settings, "telegram_order_bot_token", "") or settings.telegram_bot_token
    order_chat_id = getattr(settings, "telegram_order_chat_id", "") or settings.telegram_chat_id
    order_proxy = getattr(settings, "telegram_order_proxy", "") or alert_proxy
    return alert_notifier, TelegramNotifier(order_token, order_chat_id, proxy=order_proxy)


def run_paper_cycle(
    client: BinanceFuturesClient,
    paper: PaperTradingEngine,
    strategy: MomentumOIStrategy,
    risk_manager: RiskManager,
    notifier: TelegramNotifier,
    settings: Any,
) -> None:
    """Run one paper trading market-data and signal cycle for watched symbols.
    对所有监控交易对执行一轮模拟盘行情、信号、风控和模拟执行流程。
    """

    watch_symbols = list(getattr(settings, "active_symbols", [settings.default_symbol]))
    btc_klines = closed_klines(client.get_klines("BTC/USDT:USDT", "15m", limit=2), "15m")
    current_prices: dict[str, float] = {}
    for symbol in watch_symbols:
        klines = closed_klines(client.get_klines(symbol, settings.default_timeframe, limit=settings.kline_limit), settings.default_timeframe)
        if klines:
            current_prices[symbol] = klines[-1].close
            # 使用已完成 K 线的 high/low 做模拟触发，避免只看 close 漏掉盘中止损止盈。
            paper.update_open_positions(symbol, klines[-1].close, klines[-1].timestamp, high=klines[-1].high, low=klines[-1].low)
        signal = strategy.generate_signal({"symbol": symbol, "klines": klines, "btc_klines": btc_klines})
        if signal.is_actionable:
            notifier.notify_signal(signal)
        else:
            logger.info("Signal %s %s: %s", signal.symbol, signal.side, signal.reason)
        decision = risk_manager.evaluate(signal=signal, market_context={"btc_klines": btc_klines, "current_prices": current_prices})
        if decision.allowed:
            paper.process_signal(signal, quantity=decision.position_size)
        elif signal.is_actionable:
            notifier.notify_risk_block(signal, decision.reason)
        else:
            logger.info("Risk ignored non-actionable signal %s: %s", signal.symbol, decision.reason)

    snapshot = paper.get_account_snapshot(current_prices)
    logger.info(
        "Paper account equity=%.2f available=%.2f used_margin=%.2f realized_pnl=%.2f unrealized_pnl=%.2f open_positions=%s",
        snapshot.equity,
        snapshot.available_balance,
        snapshot.used_margin,
        snapshot.realized_pnl,
        snapshot.unrealized_pnl,
        snapshot.open_position_count,
    )


def run() -> None:
    """Run the configured application mode.
    按配置或命令行参数运行指定模式。
    """

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args()
    settings = get_settings()
    mode = RunMode(args.mode) if args.mode else settings.run_mode

    storage = SQLiteStorage(settings.database_path)
    storage.initialize()
    notifier, order_notifier = build_telegram_notifiers(settings)
    notifier.notify_startup(mode.value)

    strategy = MomentumOIStrategy(
        breakout_window=settings.strategy_breakout_window,
        volume_window=settings.strategy_volume_window,
        volume_multiplier=settings.strategy_volume_multiplier,
        btc_drop_threshold=settings.btc_drop_threshold_15m,
        stop_loss_pct=settings.strategy_stop_loss_pct,
        take_profit_pct=settings.strategy_take_profit_pct,
    )
    risk_manager = RiskManager(
        account_equity=settings.account_equity,
        risk_per_trade_pct=getattr(settings, "risk_per_trade_pct", 0.01),
        max_symbol_position_pct=getattr(settings, "risk_max_symbol_position_pct", 0.10),
        max_total_exposure_pct=getattr(settings, "risk_max_total_exposure_pct", 0.50),
        max_open_positions=getattr(settings, "risk_max_open_positions", 5),
        max_consecutive_losses=getattr(settings, "risk_max_consecutive_losses", 3),
        loss_cooldown_seconds=getattr(settings, "risk_loss_cooldown_seconds", 3600),
        btc_drop_threshold_15m=settings.btc_drop_threshold_15m,
        storage=storage,
        fee_rate=getattr(settings, "paper_fee_rate", 0.0),
        slippage_pct=getattr(settings, "paper_slippage_pct", 0.0),
        funding_rate=getattr(settings, "paper_funding_rate", 0.0),
    )

    if mode == RunMode.BACKTEST:
        if not args.csv:
            raise SystemExit("--csv is required when running backtest mode")
        engine = BacktestEngine(strategy=strategy, initial_equity=settings.account_equity)
        result = engine.run_csv(args.csv)
        if args.equity_curve_csv:
            result.export_equity_curve(args.equity_curve_csv)
        logger.info("Backtest metrics: %s", result.metrics)
        return

    if mode == RunMode.PAPER:
        client = BinanceFuturesClient(
            settings.binance_api_key,
            settings.binance_api_secret,
            settings.exchange_proxy,
            settings.exchange_network_mode,
            settings.exchange_request_retries,
            settings.exchange_retry_delay_seconds,
        )
        paper = PaperTradingEngine(
            storage=storage,
            notifier=order_notifier,
            initial_equity=settings.account_equity,
            leverage=settings.paper_leverage,
            fee_rate=getattr(settings, "paper_fee_rate", 0.0),
            slippage_pct=getattr(settings, "paper_slippage_pct", 0.0),
            funding_rate=getattr(settings, "paper_funding_rate", 0.0),
        )
        paper_error_streak = 0
        while True:
            try:
                # Paper 策略信号和风控拦截属于执行链路，和雷达提醒分流到订单通道。
                run_paper_cycle(client, paper, strategy, risk_manager, order_notifier, settings)
                paper_error_streak = 0
            except KeyboardInterrupt:
                logger.info("Paper mode stopped by user")
                return
            except Exception as exc:
                paper_error_streak += 1
                logger.exception("Paper cycle failed: %s", exc)
                notify_threshold = max(1, settings.paper_error_notify_consecutive_failures)
                if paper_error_streak >= notify_threshold:
                    # Paper cycle failures belong to the execution/order channel so
                    # radar alerts stay focused on market signals.
                    order_notifier.notify_error(f"Paper cycle failed {paper_error_streak}x consecutively: {exc}")
                else:
                    logger.warning("Paper cycle failure notification suppressed streak=%s/%s", paper_error_streak, notify_threshold)
            if args.once:
                return
            time.sleep(settings.poll_interval_seconds)

    logger.warning("Live mode is not implemented. Real orders are blocked in v1.")
    raise SystemExit("live mode is reserved and real trading is disabled in this version")


if __name__ == "__main__":
    run()
