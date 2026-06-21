"""Market scanner diagnostics tests.
行情扫描器诊断日志测试。
"""

import logging
from collections import Counter

from app.alerts.scanner import MarketScanner
from app.config import Settings
from app.exchange.binance import Kline, OpenInterestPoint


class FailingOIClient:
    def get_open_interest_history(self, symbol: str, period: str = "5m", limit: int = 30):
        raise TimeoutError("read timeout")


def test_oi_history_failures_are_summarized_once(caplog) -> None:
    scanner = MarketScanner(FailingOIClient(), Settings(_env_file=None))

    with caplog.at_level(logging.WARNING):
        assert scanner._get_open_interest_history_safe("OP/USDT:USDT") == []
        assert scanner._get_open_interest_history_safe("ARB/USDT:USDT") == []
        scanner._log_oi_failure_summary(total_symbols=10)

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert "OI history fetch failed for 2/10 symbols" in messages[0]
    assert "OP/USDT:USDT" in messages[0]
    assert "ARB/USDT:USDT" in messages[0]
    assert "Failed to fetch OP/USDT:USDT OI history" not in messages[0]


def make_kline(index: int, close: float = 1.0, volume: float = 100.0) -> Kline:
    return Kline(timestamp=index * 60_000, open=close * 0.99, high=close * 1.01, low=close * 0.98, close=close, volume=volume)


class CountingMarketClient:
    def __init__(self, ticker_count: int = 20) -> None:
        self.klines_calls: Counter[tuple[str, str]] = Counter()
        self.oi_calls: Counter[str] = Counter()
        self.tickers = [
            {
                "symbol": f"COIN{index}/USDT:USDT",
                "last": 1.0 + index / 100,
                "close": 1.0 + index / 100,
                "percentage": float(ticker_count - index),
                "quote_volume": 50_000_000 - index,
                "high": 1.2,
                "low": 0.8,
            }
            for index in range(ticker_count)
        ]

    def get_24h_tickers(self):
        return list(self.tickers)

    def get_klines(self, symbol: str, timeframe: str, limit: int):
        self.klines_calls[(symbol, timeframe)] += 1
        close = 1.0
        if "COIN" in symbol:
            close = 1.0 + int(symbol.split("COIN", 1)[1].split("/", 1)[0]) / 100
        return [make_kline(index, close=close, volume=100 + index) for index in range(limit)]

    def get_open_interest_history(self, symbol: str, period: str = "5m", limit: int = 30):
        self.oi_calls[symbol] += 1
        return [OpenInterestPoint(timestamp=index * 300_000, open_interest=1000 + index) for index in range(limit)]


def test_scanner_fetches_deep_data_only_for_candidate_pool() -> None:
    client = CountingMarketClient(ticker_count=20)
    settings = Settings(_env_file=None, ALERT_CANDIDATE_TOP_N=5, ALERT_OI_TOP_N=2)
    scanner = MarketScanner(client, settings)

    rows = scanner.scan()

    assert len(rows) == 5
    fetched_symbols = {symbol for symbol, _ in client.klines_calls}
    assert fetched_symbols == {"BTC/USDT:USDT", "COIN0/USDT:USDT", "COIN1/USDT:USDT", "COIN2/USDT:USDT", "COIN3/USDT:USDT", "COIN4/USDT:USDT"}
    assert sum(client.oi_calls.values()) == 2
    assert scanner.last_profile.meta["candidate_symbols_count"] == 5
    assert scanner.last_profile.meta["strong_candidate_symbols_count"] == 2
    assert scanner.last_profile.meta["skipped_by_not_candidate"] == 15


def test_scanner_reuses_medium_slow_and_oi_cache_within_ttl() -> None:
    client = CountingMarketClient(ticker_count=5)
    settings = Settings(
        _env_file=None,
        ALERT_CANDIDATE_TOP_N=3,
        ALERT_OI_TOP_N=2,
        ALERT_KLINE_MEDIUM_TTL_SECONDS=180,
        ALERT_KLINE_SLOW_TTL_SECONDS=600,
        ALERT_OI_TTL_SECONDS=60,
    )
    scanner = MarketScanner(client, settings)

    scanner.scan()
    scanner.scan()

    candidate_symbols = {"COIN0/USDT:USDT", "COIN1/USDT:USDT", "COIN2/USDT:USDT"}
    assert sum(client.klines_calls[(symbol, "1m")] for symbol in candidate_symbols) == 6
    assert sum(client.klines_calls[(symbol, "5m")] for symbol in candidate_symbols) == 6
    assert sum(client.klines_calls[(symbol, "15m")] for symbol in candidate_symbols) == 3
    assert sum(client.klines_calls[(symbol, "1h")] for symbol in candidate_symbols) == 3
    assert sum(client.oi_calls.values()) == 2
    assert scanner.last_profile.meta["kline_cache_hits"] >= 6
    assert scanner.last_profile.meta["oi_cache_hits"] == 2
    assert scanner.last_profile.meta["skipped_by_ttl"] >= 8
