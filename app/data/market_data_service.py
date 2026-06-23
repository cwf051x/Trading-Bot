"""Cached market data access for radar scans.
雷达扫描使用的行情数据缓存访问层。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from threading import Lock
import time
from typing import Any, Callable, Iterable, TypeVar

from app.alerts.rule_config import load_radar_rule_config
from app.exchange.binance import Kline

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class MarketDataService:
    """Fetch and cache exchange data independently from radar orchestration.
    独立于雷达编排的行情请求与缓存服务。
    """

    def __init__(self, client: Any, settings: Any) -> None:
        self.client = client
        self.settings = settings
        if not hasattr(self.settings, "radar_rule_config"):
            object.__setattr__(self.settings, "radar_rule_config", load_radar_rule_config())
        self.profiler: Any | None = None
        self.cache_stats: dict[str, int] = {}
        self.candle_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.oi_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.funding_cache: dict[str, dict[str, Any]] = {}
        self.oi_failures: list[str] = []
        self._cache_lock = Lock()
        self._stats_lock = Lock()
        self._throttle_lock = Lock()
        self._last_fetch_started_at = 0.0
        self._rate_limit_backoff_until = 0.0

    def start_cycle(self, profiler: Any | None, cache_stats: dict[str, int]) -> None:
        """Attach per-cycle profiling counters without clearing long-lived caches.
        挂接本轮 profiling 计数器，同时保留跨轮缓存。
        """

        self.profiler = profiler
        self.cache_stats = cache_stats
        self.oi_failures = []

    def fetch_concurrency(self) -> int:
        """Return bounded fetch concurrency for exchange calls.
        返回交易所请求并发上限，避免并发过高触发限流。
        """

        if self.rate_limit_backoff_active():
            return max(1, int(getattr(self.settings, "alert_rate_limit_backoff_concurrency", 2)))
        return max(1, int(getattr(self.settings, "alert_fetch_concurrency", 8)))

    def run_limited(self, items: Iterable[T], worker: Callable[[T], R]) -> list[tuple[T, R]]:
        """Run independent market-data tasks with bounded concurrency.
        用受限线程池执行独立行情请求，并保持输入顺序返回。
        """

        item_list = list(items)
        if not item_list:
            return []
        max_workers = min(self.fetch_concurrency(), len(item_list))
        if max_workers <= 1:
            return [(item, worker(item)) for item in item_list]
        results: list[tuple[int, T, R]] = []
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="market-data") as executor:
            futures = {executor.submit(worker, item): (index, item) for index, item in enumerate(item_list)}
            for future in as_completed(futures):
                index, item = futures[future]
                results.append((index, item, future.result()))
        return [(item, result) for index, item, result in sorted(results, key=lambda row: row[0])]

    def increment_cache_stat(self, key: str, amount: int = 1) -> None:
        """Increment profiling counters safely across fetch worker threads.
        在线程池请求中安全累加 profiling 计数器。
        """

        with self._stats_lock:
            self.cache_stats[key] = self.cache_stats.get(key, 0) + amount

    def get_klines_cached(self, symbol: str, timeframe: str, limit: int, ttl_seconds: int) -> list[Kline]:
        """Return cached candles, refreshing only the tail when possible.
        缓存可用时只刷新最近几根 K 线，减少重复拉取完整历史。
        """

        cache_key = (symbol, timeframe)
        now = time.time()
        cached = self.candle_cache.get(cache_key)
        if cached and ttl_seconds > 0 and now - float(cached["updated_at"]) < ttl_seconds:
            self.increment_cache_stat("kline_cache_hits")
            self.increment_cache_stat("skipped_by_ttl")
            self.increment_cache_stat("kline_cache_reused_count")
            return list(cached["data"])
        self.increment_cache_stat("kline_cache_misses")
        data, full_refresh = self._refresh_klines(symbol, timeframe, limit, now, cached)
        if data:
            with self._cache_lock:
                if full_refresh or cached is None:
                    full_refresh_at = now
                else:
                    full_refresh_at = float(cached.get("full_refresh_at") or cached.get("updated_at") or now)
                self.candle_cache[cache_key] = {"data": list(data), "updated_at": now, "full_refresh_at": full_refresh_at}
        return data

    def get_klines_safe(self, symbol: str, timeframe: str, limit: int) -> list[Kline]:
        """Fetch klines without crashing the full scan.
        获取 K 线，单个失败不导致整轮扫描崩溃。
        """

        try:
            if self.profiler:
                with self.profiler.measure(f"fetch_klines_{timeframe}"):
                    self.increment_cache_stat("kline_fetch_count")
                    self.throttle_fetch()
                    return self._closed_klines(self.client.get_klines(symbol, timeframe, limit=limit), timeframe)
            self.increment_cache_stat("kline_fetch_count")
            self.throttle_fetch()
            return self._closed_klines(self.client.get_klines(symbol, timeframe, limit=limit), timeframe)
        except Exception as exc:  # pragma: no cover - network dependent
            self.handle_rate_limit_error(exc)
            logger.warning("Failed to fetch %s %s klines: %s", symbol, timeframe, exc)
            return []

    def get_open_interest_history_safe(self, symbol: str, period: str = "5m", force_refresh: bool = False, limit: int = 30) -> list[Any]:
        """Fetch OI history without crashing the full scan.
        获取 OI 历史，单个失败不导致整轮扫描崩溃。
        """

        try:
            now = time.time()
            ttl_seconds = int(getattr(self.settings, "alert_oi_ttl_seconds", 60))
            cache_key = (symbol, period)
            cached = self.oi_cache.get(cache_key)
            if not force_refresh and cached and ttl_seconds > 0 and now - float(cached["updated_at"]) < ttl_seconds:
                self.increment_cache_stat("oi_cache_hits")
                self.increment_cache_stat("skipped_by_ttl")
                return list(cached["data"])
            self.increment_cache_stat("oi_cache_misses")
            if self.profiler:
                with self.profiler.measure("fetch_open_interest"):
                    self.increment_cache_stat("oi_fetch_count")
                    self.throttle_fetch()
                    data = self.client.get_open_interest_history(symbol, period=period, limit=limit)
            else:
                self.increment_cache_stat("oi_fetch_count")
                self.throttle_fetch()
                data = self.client.get_open_interest_history(symbol, period=period, limit=limit)
            with self._cache_lock:
                self.oi_cache[cache_key] = {"data": list(data), "updated_at": now}
            return data
        except Exception as exc:  # pragma: no cover - network dependent
            self.handle_rate_limit_error(exc)
            self.record_oi_failure(symbol, exc)
            return []

    def get_funding_rate_safe(self, symbol: str) -> float | None:
        """Fetch funding rate with a TTL cache.
        带 TTL 缓存获取资金费率，避免每轮重复请求。
        """

        try:
            now = time.time()
            ttl_seconds = int(self.settings.radar_rule_config["hourly_trend"].get("funding_rate_ttl_seconds", getattr(self.settings, "alert_funding_rate_ttl_seconds", 900)))
            cached = self.funding_cache.get(symbol)
            if cached and ttl_seconds > 0 and now - float(cached["updated_at"]) < ttl_seconds:
                self.increment_cache_stat("funding_cache_hits")
                self.increment_cache_stat("skipped_by_ttl")
                return cached["data"]
            self.increment_cache_stat("funding_cache_misses")
            if self.profiler:
                with self.profiler.measure("fetch_funding_rate"):
                    self.increment_cache_stat("funding_fetch_count")
                    self.throttle_fetch()
                    data = self.client.get_funding_rate(symbol)
            else:
                self.increment_cache_stat("funding_fetch_count")
                self.throttle_fetch()
                data = self.client.get_funding_rate(symbol)
            with self._cache_lock:
                self.funding_cache[symbol] = {"data": data, "updated_at": now}
            return data
        except Exception as exc:  # pragma: no cover - network dependent
            self.handle_rate_limit_error(exc)
            logger.debug("Failed to fetch %s funding rate: %s", symbol, exc)
            return None

    def throttle_fetch(self) -> None:
        """Pace exchange request starts across worker threads.
        控制多线程请求的启动间隔，避免并发瞬间触发交易所限流。
        """

        if self.rate_limit_backoff_active():
            min_interval = max(0.0, float(getattr(self.settings, "alert_rate_limit_backoff_min_interval_seconds", 0.5)))
        else:
            min_interval = max(0.0, float(getattr(self.settings, "alert_fetch_min_interval_seconds", 0.08)))
        if min_interval <= 0:
            return
        with self._throttle_lock:
            now = time.time()
            wait_seconds = self._last_fetch_started_at + min_interval - now
            if wait_seconds > 0:
                time.sleep(wait_seconds)
                now = time.time()
            self._last_fetch_started_at = now

    def handle_rate_limit_error(self, exc: Exception) -> None:
        """Enter temporary backoff when Binance reports rate limiting.
        检测到 Binance 限流后临时降速，避免下一轮继续打满请求。
        """

        if not self.is_rate_limit_error(exc):
            return
        backoff_seconds = max(1, int(getattr(self.settings, "alert_rate_limit_backoff_seconds", 120)))
        self.increment_cache_stat("rate_limited_count")
        self._rate_limit_backoff_until = max(self._rate_limit_backoff_until, time.time() + backoff_seconds)

    @staticmethod
    def is_rate_limit_error(exc: Exception) -> bool:
        """Return whether an exception looks like Binance request throttling.
        用字符串兼容 ccxt 与 requests 抛出的不同限流异常。
        """

        message = str(exc).lower()
        return "429" in message or "-1003" in message or "too many requests" in message

    def rate_limit_backoff_active(self) -> bool:
        """Return whether rate-limit backoff is currently active.
        判断当前是否处于限流退避窗口。
        """

        return self.rate_limit_backoff_remaining() > 0

    def rate_limit_backoff_remaining(self) -> float:
        """Return remaining backoff seconds.
        返回限流退避剩余秒数，便于日志和测试观察。
        """

        return max(0.0, self._rate_limit_backoff_until - time.time())

    def record_oi_failure(self, symbol: str, exc: Exception) -> None:
        """Store per-symbol OI failures for one compact cycle summary.
        暂存单币种 OI 失败，用于本轮扫描结束后的汇总日志。
        """

        detail = f"{symbol}: {exc}"
        with self._stats_lock:
            self.oi_failures.append(detail)
        logger.debug("Failed to fetch %s OI history: %s", symbol, exc)

    def log_oi_failure_summary(self, total_symbols: int) -> None:
        """Log one OI failure summary instead of flooding warnings per symbol.
        用一条汇总日志替代每个币一条 WARNING，减少日志噪音。
        """

        if not self.oi_failures:
            return
        samples = "; ".join(self.oi_failures[:5])
        logger.warning("OI history fetch failed for %s/%s symbols; samples: %s", len(self.oi_failures), total_symbols, samples)

    def _refresh_klines(self, symbol: str, timeframe: str, limit: int, now: float, cached: dict[str, Any] | None) -> tuple[list[Kline], bool]:
        """Choose full or incremental refresh for one K-line cache entry.
        根据缓存状态决定完整刷新还是只刷新尾部 K 线。
        """

        incremental_enabled = bool(getattr(self.settings, "alert_incremental_klines_enabled", True))
        if not incremental_enabled or cached is None:
            self.increment_cache_stat("kline_full_refresh_count")
            return self.get_klines_safe(symbol, timeframe, limit), True
        cached_data = list(cached.get("data") or [])
        if self._kline_cache_invalid(cached_data, timeframe):
            self.increment_cache_stat("kline_cache_invalid_count")
            self.increment_cache_stat("kline_full_refresh_count")
            return self.get_klines_safe(symbol, timeframe, limit), True
        if self._kline_full_refresh_due(cached, now):
            self.increment_cache_stat("kline_full_refresh_due_count")
            self.increment_cache_stat("kline_full_refresh_count")
            return self.get_klines_safe(symbol, timeframe, limit), True

        tail_limit = max(1, int(getattr(self.settings, "alert_incremental_kline_tail_limit", 3)))
        self.increment_cache_stat("kline_incremental_refresh_count")
        fresh_tail = self.get_klines_safe(symbol, timeframe, tail_limit)
        if not fresh_tail:
            self.increment_cache_stat("kline_cache_reused_count")
            return cached_data[-self._kline_cache_max_length(limit) :], False
        self.increment_cache_stat("kline_incremental_merge_count")
        return self._merge_klines(cached_data, fresh_tail, self._kline_cache_max_length(limit)), False

    def _closed_klines(self, klines: list[Kline], timeframe: str) -> list[Kline]:
        """Drop Binance's still-forming latest candle before metrics use it.
        在计算指标前丢弃 Binance 返回的未收盘最新 K 线。
        """

        if not klines:
            return []
        timeframe_ms = self.get_timeframe_seconds(timeframe) * 1000
        if timeframe_ms <= 0:
            return klines
        now_ms = int(time.time() * 1000)
        if klines[-1].timestamp + timeframe_ms > now_ms:
            return klines[:-1]
        return klines

    def _merge_klines(self, cached: list[Kline], fresh: list[Kline], max_length: int) -> list[Kline]:
        """Merge K-lines by Binance candle open timestamp.
        使用 K 线 open timestamp 去重，保持 build_metrics 输入结构不变。
        """

        by_timestamp = {item.timestamp: item for item in cached}
        for item in fresh:
            by_timestamp[item.timestamp] = item
        merged = [by_timestamp[timestamp] for timestamp in sorted(by_timestamp)]
        return merged[-max(1, max_length) :]

    def _kline_cache_invalid(self, data: list[Kline], timeframe: str) -> bool:
        """Detect missing or obviously broken candle sequences.
        发现缓存为空、乱序或大时间断层时退回完整刷新。
        """

        if not data:
            return True
        timestamps = [item.timestamp for item in data]
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            return True
        expected_gap = self.get_timeframe_seconds(timeframe) * 1000
        if expected_gap <= 0:
            return False
        return any(current - previous > expected_gap * 2 for previous, current in zip(timestamps, timestamps[1:]))

    def _kline_full_refresh_due(self, cached: dict[str, Any], now: float) -> bool:
        """Return whether the periodic full refresh interval has elapsed.
        定期完整刷新用于校正增量合并可能遗漏的历史修正。
        """

        refresh_seconds = max(0, int(getattr(self.settings, "alert_full_kline_refresh_seconds", 1800)))
        if refresh_seconds == 0:
            return True
        refreshed_at = float(cached.get("full_refresh_at") or cached.get("updated_at") or 0.0)
        return now - refreshed_at >= refresh_seconds

    def _kline_cache_max_length(self, requested_limit: int) -> int:
        """Return bounded cache length while preserving enough indicator history.
        限制缓存长度，避免增量合并后内存无限增长。
        """

        configured = int(getattr(self.settings, "alert_kline_cache_max_length", 200))
        return max(requested_limit, configured)

    @staticmethod
    def get_timeframe_seconds(timeframe: str) -> int:
        """Return timeframe length in seconds for supported Binance intervals.
        将 Binance 周期字符串转换为秒数，用于检测缓存时间断层。
        """

        unit = timeframe[-1]
        value = int(timeframe[:-1])
        if unit == "m":
            return value * 60
        if unit == "h":
            return value * 60 * 60
        if unit == "d":
            return value * 24 * 60 * 60
        return 0
