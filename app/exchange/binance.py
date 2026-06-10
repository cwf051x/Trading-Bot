"""Binance USDT-M futures market data client.
Binance USDT-M 永续合约行情客户端。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Kline:
    """Normalized OHLCV candle.
    标准化 OHLCV K 线数据。
    """

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class BinanceFuturesClient:
    """Synchronous Binance USDT-M futures client backed by ccxt.
    基于 ccxt 的同步 Binance USDT-M 永续合约客户端。
    """

    def __init__(self, api_key: str = "", api_secret: str = "", proxy: str = "") -> None:
        try:
            import ccxt  # type: ignore
        except ImportError as exc:
            raise RuntimeError("ccxt is required for BinanceFuturesClient") from exc

        config: dict[str, Any] = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
        if proxy:
            config["proxies"] = {"http": proxy, "https": proxy}
        self.exchange = ccxt.binanceusdm(config)

    def get_klines(self, symbol: str, timeframe: str, limit: int, since: int | None = None) -> list[Kline]:
        """Fetch USDT-M futures OHLCV candles.
        获取 USDT-M 永续合约 OHLCV K 线。
        """

        raw = self.exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, since=since, limit=limit)
        return [Kline(timestamp=int(row[0]), open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]), volume=float(row[5])) for row in raw]

    def get_last_price(self, symbol: str) -> float:
        """Fetch the latest traded or last ticker price.
        获取最新成交价或 ticker 最新价。
        """

        ticker = self.exchange.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close")
        if price is None:
            raise ValueError(f"No last price returned for {symbol}")
        return float(price)

    def get_24h_tickers(self) -> list[dict[str, Any]]:
        """Fetch and sort 24h tickers by percentage change descending.
        获取 24 小时 ticker 并按涨跌幅降序排序。
        """

        tickers = self.exchange.fetch_tickers()
        rows: list[dict[str, Any]] = []
        for symbol, ticker in tickers.items():
            if "/USDT" not in symbol:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "last": ticker.get("last"),
                    "close": ticker.get("close"),
                    "percentage": ticker.get("percentage"),
                    "quote_volume": ticker.get("quoteVolume"),
                    "high": ticker.get("high"),
                    "low": ticker.get("low"),
                    "raw": ticker.get("info", {}),
                }
            )
        return sorted(rows, key=lambda row: row["percentage"] if row["percentage"] is not None else -999, reverse=True)

    def get_funding_rate(self, symbol: str) -> float | None:
        """Fetch current funding rate if available.
        获取当前资金费率；不可用时返回 None。
        """

        if not hasattr(self.exchange, "fetch_funding_rate"):
            logger.warning("ccxt exchange does not expose fetch_funding_rate")
            return None
        funding = self.exchange.fetch_funding_rate(symbol)
        value = funding.get("fundingRate") if isinstance(funding, dict) else None
        return float(value) if value is not None else None

    def get_open_interest(self, symbol: str) -> float | None:
        """Fetch open interest if the installed ccxt version supports it.
        在当前 ccxt 版本支持时获取持仓量 OI。
        """

        # TODO: If a deployed ccxt version lacks this unified endpoint, call Binance's
        # `/fapi/v1/openInterest` REST endpoint directly and normalize the response here.
        # TODO（中文）: 如果部署环境的 ccxt 缺少统一 OI 接口，则直接调用 Binance
        # `/fapi/v1/openInterest` REST 接口，并在这里统一响应格式。
        if not hasattr(self.exchange, "fetch_open_interest"):
            logger.warning("ccxt exchange does not expose fetch_open_interest")
            return None
        try:
            payload = self.exchange.fetch_open_interest(symbol)
        except Exception as exc:  # pragma: no cover - exchange dependent
            logger.warning("Failed to fetch open interest for %s: %s", symbol, exc)
            return None
        value = payload.get("openInterestAmount") or payload.get("openInterestValue") or payload.get("openInterest")
        return float(value) if value is not None else None

    def get_long_short_ratio(self, symbol: str) -> float | None:
        """Return long-short ratio when a stable endpoint is added.
        稳定接口接入后返回多空比。
        """

        # TODO: Add Binance futures global/account long-short ratio REST support
        # after rate-limit and response normalization rules are finalized.
        # TODO（中文）: 在确认限频和响应标准化规则后，接入 Binance 合约多空比 REST 接口。
        logger.info("Long-short ratio is not implemented yet for %s", symbol)
        return None
