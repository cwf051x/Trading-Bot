"""Binance USDT-M futures market data client.
Binance USDT-M 永续合约行情客户端。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import requests
from requests import RequestException

logger = logging.getLogger(__name__)
T = TypeVar("T")
EXCHANGE_NETWORK_MODES = {"direct", "proxy", "direct_fallback", "proxy_fallback"}


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


@dataclass(frozen=True)
class OpenInterestPoint:
    """Open interest history point.
    持仓量历史点。
    """

    timestamp: int
    open_interest: float


class BinanceFuturesClient:
    """Synchronous Binance USDT-M futures client backed by ccxt.
    基于 ccxt 的同步 Binance USDT-M 永续合约客户端。
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        proxy: str = "",
        network_mode: str = "direct",
        request_retries: int = 2,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        try:
            import ccxt  # type: ignore
        except ImportError as exc:
            raise RuntimeError("ccxt is required for BinanceFuturesClient") from exc

        self.proxy = proxy
        self.network_mode = self._normalize_network_mode(network_mode)
        self.request_retries = max(0, request_retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        base_config: dict[str, Any] = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
        self._direct_exchange = ccxt.binanceusdm(dict(base_config))
        self._proxy_exchange = ccxt.binanceusdm(self._proxy_config(base_config, proxy)) if proxy else None
        self.exchange = self._primary_exchange()
        proxy_state = "configured" if proxy else "disabled"
        logger.info("[network] exchange mode=%s proxy=%s", self.network_mode, proxy_state)

    def get_klines(self, symbol: str, timeframe: str, limit: int, since: int | None = None) -> list[Kline]:
        """Fetch USDT-M futures OHLCV candles.
        获取 USDT-M 永续合约 OHLCV K 线。
        """

        raw = self._call_exchange(lambda exchange: exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe, since=since, limit=limit), f"klines {symbol} {timeframe}")
        return [Kline(timestamp=int(row[0]), open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]), volume=float(row[5])) for row in raw]

    def get_last_price(self, symbol: str) -> float:
        """Fetch the latest traded or last ticker price.
        获取最新成交价或 ticker 最新价。
        """

        ticker = self._call_exchange(lambda exchange: exchange.fetch_ticker(symbol), f"ticker {symbol}")
        price = ticker.get("last") or ticker.get("close")
        if price is None:
            raise ValueError(f"No last price returned for {symbol}")
        return float(price)

    def get_24h_tickers(self) -> list[dict[str, Any]]:
        """Fetch and sort 24h tickers by percentage change descending.
        获取 24 小时 ticker 并按涨跌幅降序排序。
        """

        tickers = self._call_exchange(lambda exchange: exchange.fetch_tickers(), "24h tickers")
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

        exchange = self._primary_exchange()
        if not hasattr(exchange, "fetch_funding_rate"):
            logger.warning("ccxt exchange does not expose fetch_funding_rate")
            return None
        funding = self._call_exchange(lambda selected: selected.fetch_funding_rate(symbol), f"funding rate {symbol}")
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
        exchange = self._primary_exchange()
        if not hasattr(exchange, "fetch_open_interest"):
            logger.warning("ccxt exchange does not expose fetch_open_interest")
            return None
        try:
            payload = self._call_exchange(lambda selected: selected.fetch_open_interest(symbol), f"open interest {symbol}")
        except Exception as exc:  # pragma: no cover - exchange dependent
            logger.warning("Failed to fetch open interest for %s: %s", symbol, exc)
            return None
        value = payload.get("openInterestAmount") or payload.get("openInterestValue") or payload.get("openInterest")
        return float(value) if value is not None else None

    def get_open_interest_history(self, symbol: str, period: str = "5m", limit: int = 30, start_time: int | None = None, end_time: int | None = None) -> list[OpenInterestPoint]:
        """Fetch Binance futures open interest history.
        获取 Binance 合约持仓量历史。
        """

        pair = self._binance_pair(symbol)
        response = self._get_open_interest_history_response(pair, period=period, limit=limit, start_time=start_time, end_time=end_time)
        response.raise_for_status()
        rows = response.json()
        points: list[OpenInterestPoint] = []
        for row in rows:
            value = row.get("sumOpenInterest") or row.get("sumOpenInterestValue")
            timestamp = row.get("timestamp")
            if value is None or timestamp is None:
                continue
            points.append(OpenInterestPoint(timestamp=int(timestamp), open_interest=float(value)))
        return points

    def _get_open_interest_history_response(self, pair: str, period: str, limit: int, start_time: int | None = None, end_time: int | None = None) -> requests.Response:
        """Request OI history with direct-first and proxy fallback.
        先直连请求 OI 历史，失败后按配置使用代理重试。
        """

        url = "https://fapi.binance.com/futures/data/openInterestHist"
        params = {"symbol": pair, "period": period, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._request_get_with_policy(url, params=params, direct_timeout=8, proxy_timeout=12, description=f"OI history {pair}")

    def _call_exchange(self, operation: Callable[[Any], T], description: str) -> T:
        """Run a ccxt call according to the configured direct/proxy policy.
        按配置的直连/代理策略执行 ccxt 请求，避免本地反复直连超时。
        """

        if self.network_mode == "proxy":
            return self._call_exchange_with_retries(self._require_proxy_exchange(description), operation, description, "proxy")
        if self.network_mode == "proxy_fallback":
            try:
                return self._call_exchange_with_retries(self._require_proxy_exchange(description), operation, description, "proxy")
            except Exception as proxy_exc:
                logger.info("[network] proxy exchange request failed for %s: %s, retrying direct", description, proxy_exc)
                return self._call_exchange_with_retries(self._direct_exchange, operation, description, "direct")
        if self.network_mode == "direct_fallback":
            try:
                return self._call_exchange_with_retries(self._direct_exchange, operation, description, "direct")
            except Exception as direct_exc:
                if not self._proxy_exchange:
                    raise
                logger.info("[network] direct exchange request failed for %s: %s, retrying proxy", description, direct_exc)
                return self._call_exchange_with_retries(self._proxy_exchange, operation, description, "proxy")
        return self._call_exchange_with_retries(self._direct_exchange, operation, description, "direct")

    def _call_exchange_with_retries(self, exchange: Any, operation: Callable[[Any], T], description: str, route: str) -> T:
        """Retry transient ccxt failures before surfacing an exchange error.
        对 ccxt 请求做短重试，减少偶发 Binance K 线请求失败导致整轮 paper cycle 失败。
        """

        attempts = self.request_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return operation(exchange)
            except Exception as exc:
                if attempt >= attempts:
                    raise
                logger.info(
                    "[network] %s exchange request failed for %s attempt=%s/%s: %s; retrying",
                    route,
                    description,
                    attempt,
                    attempts,
                    exc.__class__.__name__,
                )
                if self.retry_delay_seconds > 0:
                    time.sleep(self.retry_delay_seconds)
        raise RuntimeError("unreachable exchange retry state")

    def _request_get_with_policy(self, url: str, *, params: dict[str, Any], direct_timeout: int, proxy_timeout: int, description: str) -> requests.Response:
        """Run REST requests with the same network policy as ccxt calls.
        让 REST 请求与 ccxt 请求使用一致的交易所网络策略。
        """

        if self.network_mode == "proxy":
            proxy_map = self._proxy_map()
            return self._request_get(url, params=params, timeout=proxy_timeout, proxies=proxy_map)
        if self.network_mode == "proxy_fallback":
            proxy_map = self._proxy_map()
            try:
                return self._request_get(url, params=params, timeout=proxy_timeout, proxies=proxy_map)
            except RequestException as proxy_exc:
                logger.info("[network] proxy %s request failed: %s, retrying direct", description, proxy_exc)
                return self._request_get(url, params=params, timeout=direct_timeout, proxies=None)
        if self.network_mode == "direct_fallback":
            try:
                return self._request_get(url, params=params, timeout=direct_timeout, proxies=None)
            except RequestException as direct_exc:
                if not self.proxy:
                    raise
                logger.info("[network] direct %s request failed: %s, retrying proxy", description, direct_exc)
                proxy_map = self._proxy_map()
                return self._request_get(url, params=params, timeout=proxy_timeout, proxies=proxy_map)
        return self._request_get(url, params=params, timeout=direct_timeout, proxies=None)

    def _primary_exchange(self) -> Any:
        """Return the exchange object that matches the first network attempt.
        返回当前网络策略下首选的 ccxt exchange 实例。
        """

        if self.network_mode in {"proxy", "proxy_fallback"} and self._proxy_exchange:
            return self._proxy_exchange
        return self._direct_exchange

    def _require_proxy_exchange(self, description: str) -> Any:
        """Return the proxy exchange or fail clearly when proxy mode is misconfigured.
        代理模式下要求显式配置代理，避免悄悄退回直连。
        """

        if not self._proxy_exchange:
            raise RuntimeError(f"Exchange network mode {self.network_mode} requires EXCHANGE_PROXY for {description}")
        return self._proxy_exchange

    def _proxy_map(self) -> dict[str, str]:
        """Return requests proxy mapping for exchange REST endpoints.
        返回交易所 REST 请求使用的 requests 代理映射。
        """

        if not self.proxy:
            raise RuntimeError(f"Exchange network mode {self.network_mode} requires EXCHANGE_PROXY")
        return {"http": self.proxy, "https": self.proxy}

    @staticmethod
    def _proxy_config(base_config: dict[str, Any], proxy: str) -> dict[str, Any]:
        """Copy ccxt config and attach proxy settings.
        复制 ccxt 配置并附加代理设置。
        """

        config = dict(base_config)
        config["proxies"] = {"http": proxy, "https": proxy}
        return config

    @staticmethod
    def _normalize_network_mode(mode: str) -> str:
        """Validate network mode used by exchange requests.
        校验交易所请求的网络模式。
        """

        normalized = mode.strip().lower()
        if normalized not in EXCHANGE_NETWORK_MODES:
            raise ValueError(f"network_mode must be one of {', '.join(sorted(EXCHANGE_NETWORK_MODES))}")
        return normalized

    @staticmethod
    def _request_get(url: str, *, params: dict[str, Any], timeout: int, proxies: dict[str, str] | None) -> requests.Response:
        """Run a requests GET without inheriting ambient proxy variables.
        执行 GET 请求时关闭环境代理继承，保证直连/代理兜底路径可控。
        """

        session = requests.Session()
        session.trust_env = False
        return session.get(url, params=params, timeout=timeout, proxies=proxies)

    @staticmethod
    def _binance_pair(symbol: str) -> str:
        """Convert a ccxt swap symbol to Binance pair text.
        将 ccxt 合约交易对转换为 Binance pair 文本。
        """

        normalized = symbol.upper().replace(":USDT", "")
        if "/" in normalized:
            base, quote = normalized.split("/", 1)
            return f"{base}{quote}"
        return normalized

    def get_long_short_ratio(self, symbol: str) -> float | None:
        """Return long-short ratio when a stable endpoint is added.
        稳定接口接入后返回多空比。
        """

        # TODO: Add Binance futures global/account long-short ratio REST support
        # after rate-limit and response normalization rules are finalized.
        # TODO（中文）: 在确认限频和响应标准化规则后，接入 Binance 合约多空比 REST 接口。
        logger.info("Long-short ratio is not implemented yet for %s", symbol)
        return None
