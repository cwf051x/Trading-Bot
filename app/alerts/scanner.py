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
        self._oi_failures: list[str] = []

    def scan(self) -> list[Any]:
        """Scan the configured market universe once.
        对配置的市场范围扫描一轮。
        """

        tickers = self.client.get_24h_tickers()
        eligible = filter_symbol_universe(
            tickers=tickers,
            min_quote_volume=self.settings.alert_min_24h_quote_volume_usdt,
            top_gainers_limit=self.settings.alert_top_gainers_limit,
            blacklist=self.settings.alert_blacklist,
            watchlist=self.settings.alert_watchlist,
        )
        self._oi_failures = []
        btc_klines = self._get_klines_safe("BTC/USDT:USDT", "15m", 2)
        btc_15m_change = pct_change(btc_klines[0].open, btc_klines[-1].close) if len(btc_klines) >= 2 else 0.0
        metrics_rows = []
        for ticker in eligible:
            symbol = ticker["symbol"]
            klines = self._collect_klines(symbol)
            oi_history = self._get_open_interest_history_safe(symbol)
            metrics = build_market_metrics(ticker=ticker, klines_by_timeframe=klines, btc_15m_change=btc_15m_change, rank_24h=ticker.get("rank_24h"), oi_history=oi_history)
            if metrics is None:
                logger.info("Skipping %s because market data is insufficient", symbol)
                continue
            metrics_rows.append(metrics)
        self._log_oi_failure_summary(total_symbols=len(eligible))
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

    def _get_open_interest_history_safe(self, symbol: str) -> list[Any]:
        """Fetch OI history without crashing the full scan.
        获取 OI 历史，单个失败不导致整轮扫描崩溃。
        """

        try:
            return self.client.get_open_interest_history(symbol, period="5m", limit=30)
        except Exception as exc:  # pragma: no cover - network dependent
            self._record_oi_failure(symbol, exc)
            return []

    def _record_oi_failure(self, symbol: str, exc: Exception) -> None:
        """Store per-symbol OI failures for one compact cycle summary.
        暂存单币种 OI 失败，用于本轮扫描结束后的汇总日志。
        """

        detail = f"{symbol}: {exc}"
        self._oi_failures.append(detail)
        logger.debug("Failed to fetch %s OI history: %s", symbol, exc)

    def _log_oi_failure_summary(self, total_symbols: int) -> None:
        """Log one OI failure summary instead of flooding warnings per symbol.
        用一条汇总日志替代每个币一条 WARNING，减少日志噪音。
        """

        if not self._oi_failures:
            return
        samples = "; ".join(self._oi_failures[:5])
        logger.warning("OI history fetch failed for %s/%s symbols; samples: %s", len(self._oi_failures), total_symbols, samples)
