"""Market data scanner for alert radar.
行情雷达市场数据扫描器。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from threading import Lock
import time
from typing import Any, Callable, Iterable, TypeVar

from app.alerts.profiling import CycleProfiler
from app.data.market_snapshot import aggregate_klines, build_market_metrics, compute_timeframe_stats, pct_change
from app.data.symbol_universe import filter_symbol_universe, normalize_symbol, parse_symbol_list
from app.exchange.binance import BinanceFuturesClient, Kline

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class MarketScanner:
    """Collect Binance futures data and derive radar metrics.
    采集 Binance 合约行情并生成雷达指标。
    """

    def __init__(self, client: BinanceFuturesClient, settings: Any, storage: Any | None = None) -> None:
        self.client = client
        self.settings = settings
        self.storage = storage
        self._oi_failures: list[str] = []
        self._profiler: CycleProfiler | None = None
        self.last_profile = CycleProfiler()
        self.candle_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.oi_cache: dict[str, dict[str, Any]] = {}
        self.ticker_cache: dict[str, dict[str, Any]] = {}
        self.hot_symbols: dict[str, float] = {}
        self._cache_stats: dict[str, int] = {}
        self._cache_lock = Lock()
        self._stats_lock = Lock()
        self._throttle_lock = Lock()
        self._last_fetch_started_at = 0.0
        self._rate_limit_backoff_until = 0.0

    def scan(self) -> list[Any]:
        """Scan the configured market universe once.
        对配置的市场范围扫描一轮。
        """

        profiler = CycleProfiler()
        self._profiler = profiler
        self.last_profile = profiler
        self._cache_stats = {
            "kline_cache_hits": 0,
            "kline_cache_misses": 0,
            "oi_cache_hits": 0,
            "oi_cache_misses": 0,
            "skipped_by_ttl": 0,
            "skipped_by_not_candidate": 0,
            "kline_fetch_count": 0,
            "oi_fetch_count": 0,
            "kline_full_refresh_count": 0,
            "kline_incremental_refresh_count": 0,
            "kline_incremental_merge_count": 0,
            "kline_cache_reused_count": 0,
            "kline_cache_invalid_count": 0,
            "kline_full_refresh_due_count": 0,
            "kline_tail_limit": int(getattr(self.settings, "alert_incremental_kline_tail_limit", 3)),
            "rate_limited_count": 0,
            "oi_hot_count": 0,
            "oi_warm_count": 0,
            "oi_cold_count": 0,
            "oi_refresh_needed_count": 0,
            "oi_refresh_skipped_by_limit": 0,
            "oi_skipped_by_ttl": 0,
            "oi_stale_used_count": 0,
        }
        now = time.time()
        fetch_concurrency = self._fetch_concurrency()
        forced_symbols = parse_symbol_list(getattr(self.settings, "alert_watchlist", [])) | self._open_position_symbols() | self._active_hot_symbols(now)
        with profiler.measure("fetch_24h_tickers"):
            tickers = self.client.get_24h_tickers()
        with profiler.measure("load_symbols"):
            eligible = filter_symbol_universe(
                tickers=tickers,
                min_quote_volume=self.settings.alert_min_24h_quote_volume_usdt,
                top_gainers_limit=self.settings.alert_top_gainers_limit,
                blacklist=self.settings.alert_blacklist,
                watchlist=list(forced_symbols),
            )
            candidate_rows = self._select_candidate_rows(eligible, now=now)
            self._cache_stats["skipped_by_not_candidate"] = max(0, len(eligible) - len(candidate_rows))
            profiler.set_meta(symbols=len(eligible), candidate_symbols_count=len(candidate_rows), skipped_by_not_candidate=self._cache_stats["skipped_by_not_candidate"], fetch_concurrency=fetch_concurrency)
            self._update_ticker_cache(eligible, now=now)
        self._oi_failures = []
        btc_klines = self._get_klines_safe("BTC/USDT:USDT", "15m", 2)
        btc_15m_change = pct_change(btc_klines[0].open, btc_klines[-1].close) if len(btc_klines) >= 2 else 0.0
        fast_pairs = self._run_limited((ticker["symbol"] for ticker in candidate_rows), self._collect_fast_klines)
        fast_klines_by_symbol = {symbol: klines for symbol, klines in fast_pairs}
        strong_symbols = self._select_strong_candidate_symbols(candidate_rows, fast_klines_by_symbol)
        candidate_klines_pairs = self._run_limited((ticker["symbol"] for ticker in candidate_rows), lambda symbol: self._collect_candidate_klines(symbol, fast_klines_by_symbol.get(symbol, {})))
        candidate_klines_by_symbol = {symbol: klines for symbol, klines in candidate_klines_pairs}
        oi_refresh_symbols = self._select_oi_refresh_symbols(strong_symbols, fast_klines_by_symbol, now=now)
        oi_history_by_symbol = self._cached_oi_histories(strong_symbols)
        oi_pairs = self._run_limited(sorted(oi_refresh_symbols), lambda symbol: self._get_open_interest_history_safe(symbol, force_refresh=True))
        oi_history_by_symbol.update({symbol: history for symbol, history in oi_pairs})
        metrics_rows = []
        for ticker in candidate_rows:
            symbol = ticker["symbol"]
            klines = candidate_klines_by_symbol.get(symbol, {})
            oi_history = oi_history_by_symbol.get(symbol, [])
            with profiler.measure("build_metrics"):
                metrics = build_market_metrics(ticker=ticker, klines_by_timeframe=klines, btc_15m_change=btc_15m_change, rank_24h=ticker.get("rank_24h"), oi_history=oi_history)
            if metrics is None:
                logger.info("Skipping %s because market data is insufficient", symbol)
                continue
            metrics_rows.append(metrics)
        self._remember_hot_symbols(strong_symbols, now=now)
        profiler.set_meta(
            metrics=len(metrics_rows),
            strong_candidate_symbols_count=len(strong_symbols),
            oi_failures=len(self._oi_failures),
            **self._cache_stats,
            rate_limit_backoff_active=int(self._rate_limit_backoff_active()),
            backoff_remaining_seconds=round(self._rate_limit_backoff_remaining(), 1),
        )
        self._log_oi_failure_summary(total_symbols=len(strong_symbols))
        return metrics_rows

    def _fetch_concurrency(self) -> int:
        """Return bounded fetch concurrency for exchange calls.
        返回交易所请求并发上限，避免无限并发触发限流。
        """

        if self._rate_limit_backoff_active():
            return max(1, int(getattr(self.settings, "alert_rate_limit_backoff_concurrency", 2)))
        return max(1, int(getattr(self.settings, "alert_fetch_concurrency", 8)))

    def _run_limited(self, items: Iterable[T], worker: Callable[[T], R]) -> list[tuple[T, R]]:
        """Run independent fetch tasks with a conservative worker limit.
        用受限线程池运行互相独立的行情请求。
        """

        item_list = list(items)
        if not item_list:
            return []
        max_workers = min(self._fetch_concurrency(), len(item_list))
        if max_workers <= 1:
            return [(item, worker(item)) for item in item_list]
        results: list[tuple[int, T, R]] = []
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="radar-fetch") as executor:
            futures = {executor.submit(worker, item): (index, item) for index, item in enumerate(item_list)}
            for future in as_completed(futures):
                index, item = futures[future]
                results.append((index, item, future.result()))
        return [(item, result) for _, item, result in sorted(results, key=lambda row: row[0])]

    def _throttle_fetch(self) -> None:
        """Pace exchange request starts across worker threads.
        控制多线程请求的启动间隔，避免并发瞬间触发交易所限流。
        """

        if self._rate_limit_backoff_active():
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

    def _select_candidate_rows(self, eligible: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
        """Return rows that deserve deep K-line scanning this cycle.
        生成本轮需要深度拉取 K 线的候选池。
        """

        candidate_top_n = max(1, int(getattr(self.settings, "alert_candidate_top_n", 50)))
        forced_symbols = parse_symbol_list(getattr(self.settings, "alert_watchlist", []))
        forced_symbols |= self._open_position_symbols()
        forced_symbols |= self._active_hot_symbols(now)
        scored = sorted(eligible, key=self._candidate_rank, reverse=True)
        selected: dict[str, dict[str, Any]] = {}
        for ticker in scored[:candidate_top_n]:
            selected[ticker["symbol"]] = ticker
        for ticker in eligible:
            if ticker["symbol"] in forced_symbols:
                selected[ticker["symbol"]] = ticker
        return sorted(selected.values(), key=self._candidate_rank, reverse=True)

    def _candidate_rank(self, ticker: dict[str, Any]) -> tuple[float, float, float]:
        """Rank symbols before expensive K-line scans.
        在昂贵 K 线请求之前，用 ticker 信息给候选币排序。
        """

        symbol = str(ticker.get("symbol") or "")
        quote_volume = float(ticker.get("quote_volume") or ticker.get("quoteVolume") or 0.0)
        percentage = float(ticker.get("percentage") or 0.0)
        last = float(ticker.get("last") or ticker.get("close") or 0.0)
        previous = self.ticker_cache.get(symbol, {}).get("data", {})
        previous_price = float(previous.get("last") or previous.get("close") or 0.0) if previous else 0.0
        recent_change = pct_change(previous_price, last) if previous_price and last else 0.0
        return (percentage + recent_change * 100, quote_volume, last)

    def _update_ticker_cache(self, tickers: list[dict[str, Any]], now: float) -> None:
        """Store latest ticker rows for next-cycle recent change scoring.
        缓存 ticker，用于下一轮计算最近价格变化。
        """

        for ticker in tickers:
            symbol = str(ticker.get("symbol") or "")
            if symbol:
                with self._cache_lock:
                    self.ticker_cache[symbol] = {"data": dict(ticker), "updated_at": now}

    def _open_position_symbols(self) -> set[str]:
        """Return open position symbols when storage is available.
        storage 可用时把已有持仓纳入候选池。
        """

        if self.storage is None or not hasattr(self.storage, "get_open_positions"):
            return set()
        try:
            return {normalize_symbol(str(row.get("symbol") or "")) for row in self.storage.get_open_positions() if row.get("symbol")}
        except Exception as exc:  # pragma: no cover - storage errors should not stop scanning
            logger.warning("Failed to load open position symbols for radar candidates: %s", exc)
            return set()

    def _active_hot_symbols(self, now: float) -> set[str]:
        """Return hot symbols whose TTL has not expired.
        返回仍在热度 TTL 内的交易对。
        """

        ttl = max(0, int(getattr(self.settings, "alert_hot_symbol_ttl_seconds", 900)))
        if ttl == 0:
            self.hot_symbols.clear()
            return set()
        expired = [symbol for symbol, updated_at in self.hot_symbols.items() if now - updated_at > ttl]
        for symbol in expired:
            self.hot_symbols.pop(symbol, None)
        return set(self.hot_symbols)

    def _remember_hot_symbols(self, symbols: set[str], now: float) -> None:
        """Keep strong candidates hot for a few later cycles.
        将强候选短暂保温，避免刚启动的币下一轮被候选池挤出。
        """

        for symbol in symbols:
            self.hot_symbols[symbol] = now

    def _collect_fast_klines(self, symbol: str) -> dict[str, list[Kline]]:
        """Fetch fast timeframes used for candidate strengthening.
        拉取用于强候选初筛的快周期 K 线。
        """

        return {
            "1m": self._get_klines_cached(symbol, "1m", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_fast_ttl_seconds", 0))),
            "3m": self._get_klines_cached(symbol, "3m", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_fast_ttl_seconds", 0))),
            "5m": self._get_klines_cached(symbol, "5m", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_fast_ttl_seconds", 0))),
        }

    def _collect_candidate_klines(self, symbol: str, fast_klines: dict[str, list[Kline]]) -> dict[str, list[Kline]]:
        """Collect all timeframes for one selected candidate.
        为候选币收集构建指标所需的全部周期。
        """

        one_minute = fast_klines.get("1m", [])
        three_minute = fast_klines.get("3m", [])
        if not three_minute and one_minute:
            three_minute = aggregate_klines(one_minute, 3)[-120:]
        return {
            "1m": one_minute,
            "3m": three_minute,
            "5m": fast_klines.get("5m", []),
            "15m": self._get_klines_cached(symbol, "15m", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_medium_ttl_seconds", 180))),
            "1h": self._get_klines_cached(symbol, "1h", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_slow_ttl_seconds", 600))),
        }

    def _select_strong_candidate_symbols(self, candidate_rows: list[dict[str, Any]], fast_klines_by_symbol: dict[str, dict[str, list[Kline]]]) -> set[str]:
        """Pick the smaller OI fetch set from fast K-line behavior.
        用快周期行为筛出更小的 OI 请求集合。
        """

        oi_top_n = max(0, int(getattr(self.settings, "alert_oi_top_n", 30)))
        if oi_top_n == 0:
            return set()
        scores: list[tuple[float, str]] = []
        rank_by_symbol = {row["symbol"]: float(row.get("rank_24h") or len(candidate_rows) + 1) for row in candidate_rows}
        for symbol, klines_by_timeframe in fast_klines_by_symbol.items():
            klines_5m = klines_by_timeframe.get("5m", [])
            stats_5m = compute_timeframe_stats(klines_5m)
            recent = klines_5m[-6:]
            bullish_count = sum(1 for item in recent if item.close > item.open)
            rank_bonus = max(0.0, len(candidate_rows) + 1 - rank_by_symbol.get(symbol, len(candidate_rows) + 1))
            score = rank_bonus + stats_5m.change * 100 + stats_5m.volume_ratio * 5 + bullish_count
            if stats_5m.breakout:
                score += 10
            scores.append((score, symbol))
        return {symbol for _, symbol in sorted(scores, reverse=True)[:oi_top_n]}

    def _select_oi_refresh_symbols(self, symbols: set[str], fast_klines_by_symbol: dict[str, dict[str, list[Kline]]], now: float) -> set[str]:
        """Choose a limited OI refresh set by tier and cache freshness.
        按热度分层和 TTL 选择本轮真正请求 OI 的币种。
        """

        refresh_candidates: list[tuple[float, str]] = []
        for symbol in symbols:
            tier, score = self._oi_refresh_tier(symbol, fast_klines_by_symbol.get(symbol, {}))
            self._increment_cache_stat(f"oi_{tier}_count")
            cached = self.oi_cache.get(symbol)
            ttl = self._oi_ttl_seconds(tier)
            if cached and ttl > 0 and now - float(cached["updated_at"]) < ttl:
                self._increment_cache_stat("oi_cache_hits")
                self._increment_cache_stat("oi_skipped_by_ttl")
                self._increment_cache_stat("skipped_by_ttl")
                continue
            refresh_candidates.append((score, symbol))
        self._increment_cache_stat("oi_refresh_needed_count", len(refresh_candidates))
        max_refresh = max(0, int(getattr(self.settings, "alert_oi_max_refresh_per_loop", 15)))
        selected = {symbol for _, symbol in sorted(refresh_candidates, reverse=True)[:max_refresh]}
        skipped = max(0, len(refresh_candidates) - len(selected))
        if skipped:
            self._increment_cache_stat("oi_refresh_skipped_by_limit", skipped)
            for _, symbol in sorted(refresh_candidates, reverse=True)[max_refresh:]:
                if symbol in self.oi_cache:
                    self._increment_cache_stat("oi_stale_used_count")
        return selected

    def _oi_refresh_tier(self, symbol: str, klines_by_timeframe: dict[str, list[Kline]]) -> tuple[str, float]:
        """Classify OI refresh urgency from fast 5m behavior.
        用快周期表现给 OI 请求分层，优先刷新真正异动的币。
        """

        klines_5m = klines_by_timeframe.get("5m", [])
        stats_5m = compute_timeframe_stats(klines_5m)
        score = stats_5m.change * 100 + stats_5m.volume_ratio * 5
        if stats_5m.breakout:
            score += 10
        if stats_5m.change >= 0.03 or stats_5m.volume_ratio >= 2 or stats_5m.breakout:
            return "hot", score + 100
        if symbol in self.hot_symbols:
            return "warm", score + 50
        return "warm", score

    def _oi_ttl_seconds(self, tier: str) -> int:
        """Return tier-specific OI cache TTL.
        返回不同热度分层对应的 OI 缓存 TTL。
        """

        if tier == "hot":
            return int(getattr(self.settings, "alert_oi_hot_ttl_seconds", 30))
        if tier == "warm":
            return int(getattr(self.settings, "alert_oi_warm_ttl_seconds", 90))
        return int(getattr(self.settings, "alert_oi_cold_ttl_seconds", 600))

    def _cached_oi_histories(self, symbols: set[str]) -> dict[str, list[Any]]:
        """Return cached OI histories for symbols that are not refreshed.
        未刷新 OI 的币种优先沿用缓存，避免信号输入直接断档。
        """

        histories: dict[str, list[Any]] = {}
        for symbol in symbols:
            cached = self.oi_cache.get(symbol)
            if cached:
                histories[symbol] = list(cached["data"])
        return histories

    def _collect_klines(self, symbol: str) -> dict[str, list[Kline]]:
        """Collect required timeframes for one symbol.
        采集单个交易对所需的全部周期 K 线。
        """

        one_minute = self._get_klines_cached(symbol, "1m", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_fast_ttl_seconds", 0)))
        three_minute = self._get_klines_cached(symbol, "3m", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_fast_ttl_seconds", 0)))
        if not three_minute and one_minute:
            three_minute = aggregate_klines(one_minute, 3)[-120:]
        return {
            "1m": one_minute,
            "3m": three_minute,
            "5m": self._get_klines_cached(symbol, "5m", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_fast_ttl_seconds", 0))),
            "15m": self._get_klines_cached(symbol, "15m", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_medium_ttl_seconds", 180))),
            "1h": self._get_klines_cached(symbol, "1h", 120, ttl_seconds=int(getattr(self.settings, "alert_kline_slow_ttl_seconds", 600))),
        }

    def _get_klines_cached(self, symbol: str, timeframe: str, limit: int, ttl_seconds: int) -> list[Kline]:
        """Return cached candles, refreshing only the tail when possible.
        缓存可用时只刷新最近几根 K 线，减少重复拉取完整历史。
        """

        cache_key = (symbol, timeframe)
        now = time.time()
        cached = self.candle_cache.get(cache_key)
        if cached and ttl_seconds > 0 and now - float(cached["updated_at"]) < ttl_seconds:
            self._increment_cache_stat("kline_cache_hits")
            self._increment_cache_stat("skipped_by_ttl")
            self._increment_cache_stat("kline_cache_reused_count")
            return list(cached["data"])
        self._increment_cache_stat("kline_cache_misses")
        data, full_refresh = self._refresh_klines(symbol, timeframe, limit, now, cached)
        if data:
            with self._cache_lock:
                if full_refresh or cached is None:
                    full_refresh_at = now
                else:
                    full_refresh_at = float(cached.get("full_refresh_at") or cached.get("updated_at") or now)
                self.candle_cache[cache_key] = {"data": list(data), "updated_at": now, "full_refresh_at": full_refresh_at}
        return data

    def _refresh_klines(self, symbol: str, timeframe: str, limit: int, now: float, cached: dict[str, Any] | None) -> tuple[list[Kline], bool]:
        """Choose full or incremental refresh for one K-line cache entry.
        根据缓存状态决定完整刷新还是只刷新尾部 K 线。
        """

        incremental_enabled = bool(getattr(self.settings, "alert_incremental_klines_enabled", True))
        if not incremental_enabled or cached is None:
            self._increment_cache_stat("kline_full_refresh_count")
            return self._get_klines_safe(symbol, timeframe, limit), True
        cached_data = list(cached.get("data") or [])
        if self._kline_cache_invalid(cached_data, timeframe):
            self._increment_cache_stat("kline_cache_invalid_count")
            self._increment_cache_stat("kline_full_refresh_count")
            return self._get_klines_safe(symbol, timeframe, limit), True
        if self._kline_full_refresh_due(cached, now):
            self._increment_cache_stat("kline_full_refresh_due_count")
            self._increment_cache_stat("kline_full_refresh_count")
            return self._get_klines_safe(symbol, timeframe, limit), True

        tail_limit = max(1, int(getattr(self.settings, "alert_incremental_kline_tail_limit", 3)))
        self._increment_cache_stat("kline_incremental_refresh_count")
        fresh_tail = self._get_klines_safe(symbol, timeframe, tail_limit)
        if not fresh_tail:
            self._increment_cache_stat("kline_cache_reused_count")
            return cached_data[-self._kline_cache_max_length(limit) :], False
        self._increment_cache_stat("kline_incremental_merge_count")
        return self._merge_klines(cached_data, fresh_tail, self._kline_cache_max_length(limit)), False

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

    def _get_klines_safe(self, symbol: str, timeframe: str, limit: int) -> list[Kline]:
        """Fetch klines without crashing the full scan.
        获取 K 线，单个失败不导致整轮扫描崩溃。
        """

        try:
            if self._profiler:
                with self._profiler.measure(f"fetch_klines_{timeframe}"):
                    self._increment_cache_stat("kline_fetch_count")
                    self._throttle_fetch()
                    return self.client.get_klines(symbol, timeframe, limit=limit)
            self._increment_cache_stat("kline_fetch_count")
            self._throttle_fetch()
            return self.client.get_klines(symbol, timeframe, limit=limit)
        except Exception as exc:  # pragma: no cover - network dependent
            self._handle_rate_limit_error(exc)
            logger.warning("Failed to fetch %s %s klines: %s", symbol, timeframe, exc)
            return []

    def _get_open_interest_history_safe(self, symbol: str, force_refresh: bool = False) -> list[Any]:
        """Fetch OI history without crashing the full scan.
        获取 OI 历史，单个失败不导致整轮扫描崩溃。
        """

        try:
            now = time.time()
            ttl_seconds = int(getattr(self.settings, "alert_oi_ttl_seconds", 60))
            cached = self.oi_cache.get(symbol)
            if not force_refresh and cached and ttl_seconds > 0 and now - float(cached["updated_at"]) < ttl_seconds:
                self._increment_cache_stat("oi_cache_hits")
                self._increment_cache_stat("skipped_by_ttl")
                return list(cached["data"])
            self._increment_cache_stat("oi_cache_misses")
            if self._profiler:
                with self._profiler.measure("fetch_open_interest"):
                    self._increment_cache_stat("oi_fetch_count")
                    self._throttle_fetch()
                    data = self.client.get_open_interest_history(symbol, period="5m", limit=30)
            else:
                self._increment_cache_stat("oi_fetch_count")
                self._throttle_fetch()
                data = self.client.get_open_interest_history(symbol, period="5m", limit=30)
            with self._cache_lock:
                self.oi_cache[symbol] = {"data": list(data), "updated_at": now}
            return data
        except Exception as exc:  # pragma: no cover - network dependent
            self._handle_rate_limit_error(exc)
            self._record_oi_failure(symbol, exc)
            return []

    def _handle_rate_limit_error(self, exc: Exception) -> None:
        """Enter temporary backoff when Binance reports rate limiting.
        检测到 Binance 限流后临时降速，避免下一轮继续打满请求。
        """

        if not self._is_rate_limit_error(exc):
            return
        backoff_seconds = max(1, int(getattr(self.settings, "alert_rate_limit_backoff_seconds", 120)))
        with self._stats_lock:
            self._cache_stats["rate_limited_count"] = self._cache_stats.get("rate_limited_count", 0) + 1
        self._rate_limit_backoff_until = max(self._rate_limit_backoff_until, time.time() + backoff_seconds)

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        """Return whether an exception looks like Binance request throttling.
        用字符串兼容 ccxt 与 requests 抛出的不同限流异常。
        """

        message = str(exc).lower()
        return "429" in message or "-1003" in message or "too many requests" in message

    def _rate_limit_backoff_active(self) -> bool:
        """Return whether rate-limit backoff is currently active.
        判断当前是否处于限流退避窗口。
        """

        return self._rate_limit_backoff_remaining() > 0

    def _rate_limit_backoff_remaining(self) -> float:
        """Return remaining backoff seconds.
        返回限流退避剩余秒数，便于日志和测试观察。
        """

        return max(0.0, self._rate_limit_backoff_until - time.time())

    def _record_oi_failure(self, symbol: str, exc: Exception) -> None:
        """Store per-symbol OI failures for one compact cycle summary.
        暂存单币种 OI 失败，用于本轮扫描结束后的汇总日志。
        """

        detail = f"{symbol}: {exc}"
        with self._stats_lock:
            self._oi_failures.append(detail)
        logger.debug("Failed to fetch %s OI history: %s", symbol, exc)

    def _increment_cache_stat(self, key: str, amount: int = 1) -> None:
        """Increment profiling counters safely across fetch worker threads.
        在线程池请求中安全累加 profiling 计数器。
        """

        with self._stats_lock:
            self._cache_stats[key] = self._cache_stats.get(key, 0) + amount

    def _log_oi_failure_summary(self, total_symbols: int) -> None:
        """Log one OI failure summary instead of flooding warnings per symbol.
        用一条汇总日志替代每个币一条 WARNING，减少日志噪音。
        """

        if not self._oi_failures:
            return
        samples = "; ".join(self._oi_failures[:5])
        logger.warning("OI history fetch failed for %s/%s symbols; samples: %s", len(self._oi_failures), total_symbols, samples)
