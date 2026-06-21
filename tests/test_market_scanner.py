"""Market scanner diagnostics tests.
行情扫描器诊断日志测试。
"""

import logging
import threading
import time
from collections import Counter

import pytest

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
        self.kline_limits: list[tuple[str, str, int]] = []
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
        self.kline_limits.append((symbol, timeframe, limit))
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


def test_scanner_limits_oi_refreshes_per_loop() -> None:
    client = CountingMarketClient(ticker_count=8)
    settings = Settings(_env_file=None, ALERT_CANDIDATE_TOP_N=6, ALERT_OI_TOP_N=6, ALERT_OI_MAX_REFRESH_PER_LOOP=2)
    scanner = MarketScanner(client, settings)

    scanner.scan()

    assert sum(client.oi_calls.values()) == 2
    assert scanner.last_profile.meta["strong_candidate_symbols_count"] == 6
    assert scanner.last_profile.meta["oi_refresh_needed_count"] == 6
    assert scanner.last_profile.meta["oi_refresh_skipped_by_limit"] == 4


def test_scanner_does_not_refetch_tiered_oi_cache_when_ttl_is_valid() -> None:
    client = CountingMarketClient(ticker_count=8)
    settings = Settings(
        _env_file=None,
        ALERT_CANDIDATE_TOP_N=6,
        ALERT_OI_TOP_N=6,
        ALERT_OI_MAX_REFRESH_PER_LOOP=2,
        ALERT_OI_HOT_TTL_SECONDS=300,
        ALERT_OI_WARM_TTL_SECONDS=300,
        ALERT_OI_COLD_TTL_SECONDS=300,
    )
    scanner = MarketScanner(client, settings)

    scanner.scan()
    scanner.scan()

    assert sum(client.oi_calls.values()) == 4
    assert max(client.oi_calls.values()) == 1
    assert scanner.last_profile.meta["oi_cache_hits"] == 2
    assert scanner.last_profile.meta["oi_skipped_by_ttl"] == 2


class SlowCountingMarketClient(CountingMarketClient):
    def __init__(self, ticker_count: int = 8, delay_seconds: float = 0.02) -> None:
        super().__init__(ticker_count=ticker_count)
        self.delay_seconds = delay_seconds
        self.active_requests = 0
        self.max_active_requests = 0
        self._lock = threading.Lock()

    def _track_request(self) -> None:
        with self._lock:
            self.active_requests += 1
            self.max_active_requests = max(self.max_active_requests, self.active_requests)
        try:
            time.sleep(self.delay_seconds)
        finally:
            with self._lock:
                self.active_requests -= 1

    def get_klines(self, symbol: str, timeframe: str, limit: int):
        self._track_request()
        return super().get_klines(symbol, timeframe, limit)

    def get_open_interest_history(self, symbol: str, period: str = "5m", limit: int = 30):
        self._track_request()
        return super().get_open_interest_history(symbol, period, limit)


def test_scanner_fetches_market_data_with_bounded_concurrency() -> None:
    client = SlowCountingMarketClient(ticker_count=8, delay_seconds=0.02)
    settings = Settings(_env_file=None, ALERT_CANDIDATE_TOP_N=6, ALERT_OI_TOP_N=3, ALERT_FETCH_CONCURRENCY=3, ALERT_FETCH_MIN_INTERVAL_SECONDS=0)
    scanner = MarketScanner(client, settings)

    scanner.scan()

    assert client.max_active_requests > 1
    assert client.max_active_requests <= 3
    assert scanner.last_profile.meta["fetch_concurrency"] == 3


def test_scanner_throttles_fetch_start_rate(monkeypatch) -> None:
    scanner = MarketScanner(CountingMarketClient(), Settings(_env_file=None, ALERT_FETCH_MIN_INTERVAL_SECONDS=0.5))
    times = iter([10.0, 10.1, 10.2, 10.3, 10.6])
    sleeps: list[float] = []

    monkeypatch.setattr("app.alerts.scanner.time.time", lambda: next(times))
    monkeypatch.setattr("app.alerts.scanner.time.sleep", sleeps.append)

    scanner._throttle_fetch()
    scanner._throttle_fetch()

    assert sleeps == pytest.approx([0.3])


class TailRefreshClient:
    def __init__(self) -> None:
        self.limits: list[int] = []

    def get_klines(self, symbol: str, timeframe: str, limit: int):
        self.limits.append(limit)
        if len(self.limits) == 1:
            return [make_kline(index, close=1 + index / 100) for index in range(limit)]
        return [make_kline(index, close=2 + index / 100) for index in (58, 59, 60)][-limit:]


def test_scanner_incrementally_merges_warm_kline_cache_without_duplicates() -> None:
    client = TailRefreshClient()
    settings = Settings(_env_file=None, ALERT_INCREMENTAL_KLINES_ENABLED=True, ALERT_INCREMENTAL_KLINE_TAIL_LIMIT=3, ALERT_KLINE_CACHE_MAX_LENGTH=60)
    scanner = MarketScanner(client, settings)

    scanner._get_klines_cached("BTC/USDT:USDT", "5m", 60, ttl_seconds=0)
    merged = scanner._get_klines_cached("BTC/USDT:USDT", "5m", 60, ttl_seconds=0)

    timestamps = [item.timestamp for item in merged]
    assert client.limits == [60, 3]
    assert timestamps == sorted(set(timestamps))
    assert len(merged) == 60
    assert timestamps[0] == make_kline(1).timestamp
    assert timestamps[-1] == make_kline(60).timestamp
    assert scanner.candle_cache[("BTC/USDT:USDT", "5m")]["data"] == merged
    assert scanner._cache_stats["kline_incremental_refresh_count"] == 1
    assert scanner._cache_stats["kline_incremental_merge_count"] == 1


def test_scanner_uses_full_refresh_when_kline_cache_has_large_time_gap() -> None:
    client = TailRefreshClient()
    settings = Settings(_env_file=None, ALERT_INCREMENTAL_KLINES_ENABLED=True, ALERT_INCREMENTAL_KLINE_TAIL_LIMIT=3, ALERT_KLINE_CACHE_MAX_LENGTH=60)
    scanner = MarketScanner(client, settings)
    scanner.candle_cache[("BTC/USDT:USDT", "1m")] = {
        "data": [make_kline(0), make_kline(1), make_kline(10)],
        "updated_at": time.time(),
        "full_refresh_at": time.time(),
    }

    refreshed = scanner._get_klines_cached("BTC/USDT:USDT", "1m", 60, ttl_seconds=0)

    assert client.limits == [60]
    assert len(refreshed) == 60
    assert scanner._cache_stats["kline_cache_invalid_count"] == 1
    assert scanner._cache_stats["kline_full_refresh_count"] == 1


class RateLimitedClient:
    def get_klines(self, symbol: str, timeframe: str, limit: int):
        raise RuntimeError("binance -1003 Too Many Requests")


def test_scanner_enters_rate_limit_backoff_after_429(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        ALERT_FETCH_CONCURRENCY=6,
        ALERT_RATE_LIMIT_BACKOFF_CONCURRENCY=2,
        ALERT_FETCH_MIN_INTERVAL_SECONDS=0.15,
        ALERT_RATE_LIMIT_BACKOFF_MIN_INTERVAL_SECONDS=0.5,
        ALERT_RATE_LIMIT_BACKOFF_SECONDS=120,
    )
    scanner = MarketScanner(RateLimitedClient(), settings)
    monkeypatch.setattr("app.alerts.scanner.time.time", lambda: 1000.0)

    assert scanner._get_klines_safe("BTC/USDT:USDT", "5m", 3) == []

    assert scanner._fetch_concurrency() == 2
    assert scanner._rate_limit_backoff_remaining() == pytest.approx(120.0)
    assert scanner._cache_stats["rate_limited_count"] == 1


def test_scanner_uses_backoff_request_spacing(monkeypatch) -> None:
    settings = Settings(_env_file=None, ALERT_FETCH_MIN_INTERVAL_SECONDS=0.15, ALERT_RATE_LIMIT_BACKOFF_MIN_INTERVAL_SECONDS=0.5)
    scanner = MarketScanner(CountingMarketClient(), settings)
    scanner._rate_limit_backoff_until = 20.0
    times = iter([10.0, 10.1, 10.2, 10.3, 10.6])
    sleeps: list[float] = []

    monkeypatch.setattr("app.alerts.scanner.time.time", lambda: next(times))
    monkeypatch.setattr("app.alerts.scanner.time.sleep", sleeps.append)

    scanner._throttle_fetch()
    scanner._throttle_fetch()

    assert sleeps == pytest.approx([0.3])
