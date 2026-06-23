from collections import Counter
import threading
import time

from app.config import Settings
from app.data.market_data_service import MarketDataService
from app.exchange.binance import Kline, OpenInterestPoint


def make_kline(index: int, close: float = 1.0) -> Kline:
    return Kline(timestamp=index * 60_000, open=close * 0.99, high=close * 1.01, low=close * 0.98, close=close, volume=100 + index)


class TailKlineClient:
    def __init__(self) -> None:
        self.limits: list[int] = []

    def get_klines(self, symbol: str, timeframe: str, limit: int):
        self.limits.append(limit)
        if len(self.limits) == 1:
            return [make_kline(index) for index in range(limit)]
        return [make_kline(index, close=2.0) for index in (58, 59, 60)][-limit:]


class CountingDataClient:
    def __init__(self) -> None:
        self.oi_period_calls: Counter[tuple[str, str]] = Counter()
        self.funding_calls: Counter[str] = Counter()

    def get_open_interest_history(self, symbol: str, period: str = "5m", limit: int = 30):
        self.oi_period_calls[(symbol, period)] += 1
        return [OpenInterestPoint(timestamp=index * 300_000, open_interest=1000 + index) for index in range(limit)]

    def get_funding_rate(self, symbol: str):
        self.funding_calls[symbol] += 1
        return 0.0002


def test_market_data_service_incrementally_merges_kline_cache() -> None:
    client = TailKlineClient()
    service = MarketDataService(client, Settings(_env_file=None, ALERT_INCREMENTAL_KLINE_TAIL_LIMIT=3, ALERT_KLINE_CACHE_MAX_LENGTH=60))

    service.get_klines_cached("BTC/USDT:USDT", "5m", 60, ttl_seconds=0)
    merged = service.get_klines_cached("BTC/USDT:USDT", "5m", 60, ttl_seconds=0)

    assert client.limits == [60, 3]
    assert [item.timestamp for item in merged] == sorted({item.timestamp for item in merged})
    assert len(merged) == 60
    assert service.candle_cache[("BTC/USDT:USDT", "5m")]["data"] == merged
    assert service.cache_stats["kline_incremental_refresh_count"] == 1
    assert service.cache_stats["kline_incremental_merge_count"] == 1


def test_market_data_service_caches_oi_periods_and_funding_independently() -> None:
    client = CountingDataClient()
    service = MarketDataService(client, Settings(_env_file=None, ALERT_OI_TTL_SECONDS=300, ALERT_FUNDING_RATE_TTL_SECONDS=600))

    service.get_open_interest_history_safe("COIN0/USDT:USDT", period="5m")
    service.get_open_interest_history_safe("COIN0/USDT:USDT", period="1h")
    service.get_open_interest_history_safe("COIN0/USDT:USDT", period="5m")
    service.get_open_interest_history_safe("COIN0/USDT:USDT", period="1h")
    service.get_funding_rate_safe("COIN0/USDT:USDT")
    service.get_funding_rate_safe("COIN0/USDT:USDT")

    assert client.oi_period_calls[("COIN0/USDT:USDT", "5m")] == 1
    assert client.oi_period_calls[("COIN0/USDT:USDT", "1h")] == 1
    assert client.funding_calls["COIN0/USDT:USDT"] == 1
    assert service.cache_stats["oi_cache_hits"] == 2
    assert service.cache_stats["funding_cache_hits"] == 1


def test_market_data_service_runs_batch_fetches_with_bounded_concurrency() -> None:
    service = MarketDataService(CountingDataClient(), Settings(_env_file=None, ALERT_FETCH_CONCURRENCY=3))
    active_requests = 0
    max_active_requests = 0
    lock = threading.Lock()

    def worker(value: int) -> int:
        nonlocal active_requests, max_active_requests
        with lock:
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
        try:
            time.sleep(0.01)
            return value * 10
        finally:
            with lock:
                active_requests -= 1

    results = service.run_limited([3, 1, 2, 4], worker)

    assert results == [(3, 30), (1, 10), (2, 20), (4, 40)]
    assert max_active_requests > 1
    assert max_active_requests <= 3
