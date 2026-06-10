"""Market data scanner for alert radar.
行情雷达市场数据扫描器。
"""

from __future__ import annotations

import logging
from typing import Any

from app.data.market_snapshot import aggregate_klines, build_market_metrics, pct_change
from app.data.symbol_universe import filter_symbol_universe
from app.exchange.binance import BinanceFuturesClient, Kline

logger = logging.getLogger(__name__)


class MarketScanner:
    """Collect Binance futures data and derive radar metrics.
    采集 Binance 合约行情并生成雷达指标。
    """

    def __init__(self, client: BinanceFuturesClient, settings: Any) -> None:
        self.client = client
        self.settings = settings

    def scan(self) -> list[Any]:
        """Scan the configured market universe once.
        对配置的市场范围扫描一轮。
        """

        tickers = self.client.get_24h_tickers()
        eligible = filter_symbol_universe(
            tickers=tickers,
            min_quote_volume=self.settings.alert_min_24h_quote_volume_usdt,
            blacklist=self.settings.alert_blacklist,
            watchlist=self.settings.alert_watchlist,
        )
        top_rank = {ticker["symbol"]: index + 1 for index, ticker in enumerate(eligible)}
        btc_klines = self._get_klines_safe("BTC/USDT:USDT", "15m", 2)
        btc_15m_change = pct_change(btc_klines[0].open, btc_klines[-1].close) if len(btc_klines) >= 2 else 0.0
        metrics_rows = []
        for ticker in eligible:
            symbol = ticker["symbol"]
            klines = self._collect_klines(symbol)
            # TODO: Enrich top candidates with funding, OI, and long-short ratio after
            # adding rate-limit aware batching.
            # TODO（中文）: 后续增加限频友好的候选币二次增强，再接资金费率、OI 和多空比。
            metrics = build_market_metrics(ticker=ticker, klines_by_timeframe=klines, btc_15m_change=btc_15m_change, rank_24h=top_rank.get(symbol))
            if metrics is None:
                logger.info("Skipping %s because market data is insufficient", symbol)
                continue
            metrics_rows.append(metrics)
        return metrics_rows

    def _collect_klines(self, symbol: str) -> dict[str, list[Kline]]:
        """Collect required timeframes for one symbol.
        采集单个交易对所需的全部周期 K 线。
        """

        one_minute = self._get_klines_safe(symbol, "1m", 120)
        three_minute = self._get_klines_safe(symbol, "3m", 120)
        if not three_minute and one_minute:
            three_minute = aggregate_klines(one_minute, 3)[-120:]
        return {
            "1m": one_minute,
            "3m": three_minute,
            "5m": self._get_klines_safe(symbol, "5m", 120),
            "15m": self._get_klines_safe(symbol, "15m", 120),
            "1h": self._get_klines_safe(symbol, "1h", 120),
        }

    def _get_klines_safe(self, symbol: str, timeframe: str, limit: int) -> list[Kline]:
        """Fetch klines without crashing the full scan.
        获取 K 线，单个失败不导致整轮扫描崩溃。
        """

        try:
            return self.client.get_klines(symbol, timeframe, limit=limit)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Failed to fetch %s %s klines: %s", symbol, timeframe, exc)
            return []
