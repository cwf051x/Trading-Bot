# Radar Loop Next Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing radar signal behavior unchanged while reducing each `radar-loop` round from roughly 50-60 seconds toward 15-30 seconds.

**Architecture:** The completed stopgap version reduced scan scope with candidate pools and caches. The completed concurrent version overlaps independent network requests with bounded concurrency and request pacing. The next optimization should reduce request volume itself by incrementally updating cached candles and open interest, then only add WebSocket if REST polling still cannot meet the target.

**Tech Stack:** Python, FastAPI app codebase, ccxt/Binance futures REST APIs, pytest, existing `CycleProfiler` logging.

---

## Completed Version Summary

### Baseline Before Optimization

The original radar loop scanned roughly 140 symbols every round and fetched 5 timeframes plus open interest for each symbol.

Observed profiling:

```text
[radar-loop] total=210.5s symbols=140 metrics=140 oi_failures=0 alerts=0
fetch_24h_tickers=0.6s
fetch_klines_15m=28.7s count=141
fetch_klines_1m=29.5s count=140
fetch_klines_3m=29.3s count=140
fetch_klines_5m=30.0s count=140
fetch_klines_1h=31.3s count=140
fetch_open_interest=60.8s count=140
build_metrics=0.3s
calculate_signals=0.1s
```

Conclusion: calculation is not the bottleneck. REST calls for K-lines and open interest dominate the loop.

### Stopgap Candidate/Cache Version

Modified files:

- `app/alerts/scanner.py`
- `app/config.py`
- `scripts/run_alert_radar_loop.py`
- `tests/test_market_scanner.py`
- `tests/test_config.py`

Main changes:

- Added candidate pool selection from 24h tickers.
- Default `candidate_top_n = 50`.
- Deep K-line scan now only runs on candidate symbols, plus watchlist/hot/open-position symbols.
- Added `strong_candidate_symbols` for open interest fetching.
- Default `oi_top_n = 30`.
- Added in-memory caches:
  - `candle_cache[(symbol, timeframe)]`
  - `oi_cache[symbol]`
  - `ticker_cache[symbol]`
- Added TTL controls:
  - fast K-lines: default `0s`
  - 15m K-lines: default `180s`
  - 1h K-lines: default `600s`
  - OI: default `60s`
  - hot symbols: default `900s`
- Added profiling counters:
  - `candidate_symbols_count`
  - `strong_candidate_symbols_count`
  - `kline_cache_hits`
  - `kline_cache_misses`
  - `oi_cache_hits`
  - `oi_cache_misses`
  - `skipped_by_ttl`
  - `skipped_by_not_candidate`

Observed result:

```text
[radar-loop] total=47.8s symbols=140 candidate_symbols_count=59 skipped_by_not_candidate=81 metrics=59 strong_candidate_symbols_count=30 ...
```

Tradeoff:

Non-candidate symbols are no longer deeply scanned every round. They enter the deep scan through 24h ticker rank, quote volume, recent price movement, watchlist, hot symbols, or open positions.

### Concurrent Fetch Version

Modified files:

- `app/alerts/profiling.py`
- `app/alerts/scanner.py`
- `app/config.py`
- `tests/test_market_scanner.py`
- `tests/test_config.py`

Main changes:

- Made `CycleProfiler` thread-safe with a lock.
- Added bounded concurrency for independent REST fetches.
- Added global request start pacing to avoid Binance 429.
- Added config:
  - `ALERT_FETCH_CONCURRENCY=6`
  - `ALERT_FETCH_MIN_INTERVAL_SECONDS=0.15`
- Added tests for:
  - concurrency never exceeding configured limit
  - request start throttling being applied
  - config defaults

Observed safe result:

```text
[radar-loop] total=52.8s symbols=139 candidate_symbols_count=59 skipped_by_not_candidate=80 fetch_concurrency=6 metrics=59 strong_candidate_symbols_count=30 oi_failures=0 kline_cache_hits=0 kline_cache_misses=295 oi_cache_hits=0 oi_cache_misses=30 skipped_by_ttl=0 kline_fetch_count=296 oi_fetch_count=30 alerts=0
fetch_24h_tickers=2.2s
fetch_klines_15m=52.3s count=60
fetch_klines_1m=51.9s count=59
fetch_klines_3m=53.4s count=59
fetch_klines_5m=53.9s count=59
fetch_klines_1h=53.2s count=59
fetch_open_interest=27.8s count=30
```

Important note:

After concurrency was introduced, individual step durations overlap. The sum of `fetch_klines_*` durations is no longer equal to total wall-clock time.

An aggressive setting of `concurrency=8` and `min_interval=0.08` briefly reduced runtime to about 12 seconds, but triggered Binance `429 Too Many Requests`. The safe default was adjusted back to `6 / 0.15`.

## Next Optimization Direction

The next useful step is not simply increasing concurrency. The safer direction is to reduce REST request count.

Priority order:

1. Incremental candle refresh.
2. Shared request budget and adaptive backoff.
3. Better candidate prefiltering from 24h ticker data.
4. Open interest batching/frequency separation where API support allows.
5. WebSocket only after REST volume has been reduced as much as practical.

## Files To Touch

- Modify: `app/alerts/scanner.py`
  - Add incremental cache merge for K-lines.
  - Avoid full `limit=N` fetch when cache already has enough historical candles.
  - Add per-timeframe freshness checks based on candle close time.
- Modify: `app/alerts/profiling.py`
  - Add request volume counters for full refresh vs incremental refresh.
- Modify: `app/config.py`
  - Add incremental refresh config flags and limits.
- Modify: `tests/test_market_scanner.py`
  - Add unit tests for incremental candle merge, stale cache refresh, and 429 backoff behavior.
- Optional modify: `README.md`
  - Document radar loop performance controls and Binance rate-limit notes.

## Proposed Config

Add these fields to `app/config.py`:

```python
alert_incremental_klines_enabled: bool = Field(default=True, alias="ALERT_INCREMENTAL_KLINES_ENABLED")
alert_incremental_kline_tail_limit: int = Field(default=3, alias="ALERT_INCREMENTAL_KLINE_TAIL_LIMIT")
alert_full_kline_refresh_seconds: int = Field(default=1800, alias="ALERT_FULL_KLINE_REFRESH_SECONDS")
alert_rate_limit_backoff_seconds: int = Field(default=120, alias="ALERT_RATE_LIMIT_BACKOFF_SECONDS")
alert_candidate_top_n: int = Field(default=50, alias="ALERT_CANDIDATE_TOP_N")
alert_oi_top_n: int = Field(default=30, alias="ALERT_OI_TOP_N")
```

## Task 1: Add Incremental K-line Cache Refresh

**Files:**

- Modify: `app/alerts/scanner.py`
- Test: `tests/test_market_scanner.py`

- [ ] **Step 1: Write failing tests for candle merge behavior**

Test cases:

```python
def test_scanner_merges_incremental_klines_without_duplicates(monkeypatch):
    # Given cached candles ending at t=1000
    # And Binance returns tail candles [1000, 1300]
    # Expect scanner to keep one t=1000 candle and append t=1300.
    ...

def test_scanner_keeps_required_history_window_after_incremental_merge(monkeypatch):
    # Given a cache larger than the required indicator history
    # Expect old rows to be trimmed so memory does not grow forever.
    ...
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_market_scanner.py -q
```

Expected:

```text
FAILED test_scanner_merges_incremental_klines_without_duplicates
FAILED test_scanner_keeps_required_history_window_after_incremental_merge
```

- [ ] **Step 3: Implement incremental refresh**

Implementation rule:

- If no cache exists, fetch the current full `limit`.
- If cache exists and full refresh TTL has not expired, fetch only `alert_incremental_kline_tail_limit` latest candles.
- Merge by candle timestamp.
- Sort by timestamp.
- Keep only the max historical window required by active signal logic.

Suggested helper inside `MarketScanner`:

```python
def _merge_candles(self, cached: list[dict], fresh: list[dict], limit: int) -> list[dict]:
    by_timestamp = {row["timestamp"]: row for row in cached}
    for row in fresh:
        by_timestamp[row["timestamp"]] = row
    merged = [by_timestamp[key] for key in sorted(by_timestamp)]
    return merged[-limit:]
```

- [ ] **Step 4: Verify tests pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_market_scanner.py -q
```

Expected:

```text
passed
```

## Task 2: Separate Full Refresh From Tail Refresh In Profiling

**Files:**

- Modify: `app/alerts/profiling.py`
- Modify: `app/alerts/scanner.py`
- Test: `tests/test_market_scanner.py`

- [ ] **Step 1: Add failing test for profiling counters**

```python
def test_scanner_profiles_full_and_incremental_kline_fetches(monkeypatch):
    # First scan should record full_kline_fetch_count > 0.
    # Second scan with warm cache should record incremental_kline_fetch_count > 0.
    ...
```

- [ ] **Step 2: Add profiler meta counters**

Counters:

```text
full_kline_fetch_count
incremental_kline_fetch_count
incremental_kline_merged_count
full_refresh_due_count
```

- [ ] **Step 3: Verify profiling log readability**

Run local loop and inspect:

```bash
tail -f logs/alert_radar.log
```

Expected warm-cache log shape:

```text
[radar-loop] total=... full_kline_fetch_count=0 incremental_kline_fetch_count=...
```

## Task 3: Add Adaptive Backoff For Binance 429

**Files:**

- Modify: `app/alerts/scanner.py`
- Modify: `app/config.py`
- Test: `tests/test_market_scanner.py`

- [ ] **Step 1: Write failing test for 429 backoff**

```python
def test_scanner_enters_rate_limit_backoff_after_binance_429(monkeypatch):
    # Given market client raises a Binance rate-limit exception
    # Expect scanner to set a temporary backoff timestamp and skip optional fetches.
    ...
```

- [ ] **Step 2: Implement backoff state**

Rules:

- Detect Binance `429`, `-1003`, or "Too Many Requests".
- Set `self._rate_limit_backoff_until`.
- During backoff:
  - still fetch 24h tickers if allowed
  - skip optional full K-line refresh
  - use existing cache for 15m/1h/OI when possible
  - log `rate_limit_backoff_active=1`

- [ ] **Step 3: Verify no alert crash on rate limit**

Run:

```bash
.venv/bin/python -m pytest tests/test_market_scanner.py -q
```

Expected:

```text
passed
```

## Task 4: Improve Candidate Prefiltering Without Changing Signals

**Files:**

- Modify: `app/alerts/scanner.py`
- Test: `tests/test_market_scanner.py`

- [ ] **Step 1: Add test for candidate score composition**

Candidate score should include:

- 24h percent change
- quote volume
- short ticker movement if available
- watchlist bonus
- hot symbol bonus
- open position bonus

- [ ] **Step 2: Normalize candidate scoring**

Keep the existing `candidate_top_n`, but make the score explicit and profile:

```text
candidate_reason_counts=volume:20,gainer:15,watchlist:4,hot:8,position:1
```

- [ ] **Step 3: Verify candidate count remains stable**

Expected:

```text
candidate_symbols_count <= candidate_top_n + watchlist + hot + positions
```

## Task 5: Document Performance Controls

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Add radar performance section**

Include:

```text
ALERT_CANDIDATE_TOP_N
ALERT_OI_TOP_N
ALERT_FETCH_CONCURRENCY
ALERT_FETCH_MIN_INTERVAL_SECONDS
ALERT_INCREMENTAL_KLINES_ENABLED
ALERT_INCREMENTAL_KLINE_TAIL_LIMIT
ALERT_FULL_KLINE_REFRESH_SECONDS
ALERT_RATE_LIMIT_BACKOFF_SECONDS
```

- [ ] **Step 2: Add network/proxy note**

Document that Binance/API calls may need proxy in local environments and should follow existing `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY` conventions.

## Verification Commands

Run unit tests:

```bash
.venv/bin/python -m pytest -q
```

Run radar loop locally:

```bash
.venv/bin/python -u scripts/run_alert_radar_loop.py
```

Inspect profiling:

```bash
tail -f logs/alert_radar.log
```

Expected target after incremental refresh:

```text
[radar-loop] total=15-30s
candidate_symbols_count=40-60
strong_candidate_symbols_count=20-30
full_kline_fetch_count=0 on warm-cache rounds
incremental_kline_fetch_count > 0 on warm-cache rounds
rate_limit_backoff_active=0 during healthy operation
```

## Acceptance Criteria

- Existing radar signals produce the same logical results from equivalent candle/OI data.
- Warm-cache loop normally completes within 15-30 seconds.
- Cold-start loop may still take around 45-60 seconds.
- Binance 429 no longer causes a noisy failed cycle; scanner backs off and keeps using valid cached data.
- Full test suite passes.
- Profiling logs clearly separate cold full refresh, warm incremental refresh, cache hits, skips, and rate-limit backoff.

