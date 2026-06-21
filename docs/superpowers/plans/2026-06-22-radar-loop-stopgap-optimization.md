# Radar Loop Stopgap Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce alert radar loop runtime by limiting deep market-data fetches to a candidate pool and reusing short-lived K-line/OI caches.

**Architecture:** Keep `MarketAlertRadar` and rule logic unchanged. Add candidate selection and TTL caches inside `MarketScanner`, so existing `MarketMetrics` consumers continue to receive the same shape of data.

**Tech Stack:** Python, pytest, existing Binance/ccxt client, in-memory process caches.

---

### Task 1: Candidate Pool And Cache Tests

**Files:**
- Modify: `tests/test_market_scanner.py`
- Modify: `app/alerts/scanner.py`
- Modify: `app/config.py`

- [x] Add tests proving scanner limits deep K-line fetches to `ALERT_CANDIDATE_TOP_N`.
- [x] Add tests proving `15m`, `1h`, and OI reuse cached data while TTL is valid.
- [x] Add tests proving OI fetches are limited to `ALERT_OI_TOP_N`.

### Task 2: Scanner Stopgap Implementation

**Files:**
- Modify: `app/alerts/scanner.py`

- [x] Add `candle_cache`, `oi_cache`, and `ticker_cache` dictionaries.
- [x] Build `candidate_symbols` from 24h ticker rank, quote volume, positive change, watchlist, hot symbols, and optional open paper positions if available.
- [x] Fetch fast K-lines only for candidate symbols.
- [x] Reuse medium/slow K-line cache by TTL.
- [x] Build `strong_candidate_symbols` from fast K-line derived stats and fetch OI only for that subset.

### Task 3: Settings And Profiling

**Files:**
- Modify: `app/config.py`
- Modify: `app/alerts/scanner.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_alert_profiling.py`

- [x] Add candidate/cache/OI settings with safe defaults.
- [x] Emit profiling metadata for candidate counts, cache hits/misses, fetch counts, and skipped counts.
- [x] Run focused tests and full pytest suite.
