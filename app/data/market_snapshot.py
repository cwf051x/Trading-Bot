"""Market snapshot utilities for alert radar.
行情雷达使用的市场快照工具。
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from app.alerts.signal_models import HourlyTrendStats, MarketMetrics, PumpPullbackStats, ResonanceStats, TimeframeStats
from app.exchange.binance import Kline, OpenInterestPoint


def pct_change(start: float, end: float) -> float:
    """Return percentage change as a decimal ratio.
    返回小数形式的涨跌幅比例。
    """

    if start == 0:
        return 0.0
    return (end - start) / start


def aggregate_klines(klines: list[Kline], group_size: int) -> list[Kline]:
    """Aggregate lower timeframe candles into larger candles.
    将低周期 K 线聚合为更高周期 K 线。
    """

    if group_size <= 1:
        return list(klines)
    grouped: list[Kline] = []
    for index in range(0, len(klines), group_size):
        chunk = klines[index : index + group_size]
        if len(chunk) < group_size:
            continue
        grouped.append(
            Kline(
                timestamp=chunk[0].timestamp,
                open=chunk[0].open,
                high=max(item.high for item in chunk),
                low=min(item.low for item in chunk),
                close=chunk[-1].close,
                volume=sum(item.volume for item in chunk),
            )
        )
    return grouped


def compute_rsi(klines: list[Kline], period: int = 14) -> float | None:
    """Compute a simple RSI value from candle closes.
    根据 K 线收盘价计算简化 RSI。
    """

    if len(klines) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    closes = [item.close for item in klines[-(period + 1) :]]
    for previous, current in zip(closes, closes[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = mean(gains)
    average_loss = mean(losses)
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def compute_atr_ratio(klines: list[Kline], period: int = 14) -> float:
    """Compute ATR divided by latest close as a volatility ratio.
    计算 ATR 占最新收盘价的比例，用于衡量波动率。
    """

    if len(klines) <= period:
        return 0.0
    true_ranges: list[float] = []
    recent = klines[-(period + 1) :]
    for previous, current in zip(recent, recent[1:]):
        true_ranges.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    latest_close = klines[-1].close
    return mean(true_ranges) / latest_close if latest_close else 0.0


def moving_average(values: list[float], window: int) -> float:
    """Return simple moving average for the latest window.
    返回最近窗口的简单均线。
    """

    if len(values) < window:
        return 0.0
    return mean(values[-window:])


def oi_change(history: list[OpenInterestPoint], intervals: int) -> float:
    """Return OI change over a number of history intervals.
    返回指定历史间隔数的持仓量变化。
    """

    if len(history) <= intervals:
        return 0.0
    return pct_change(history[-(intervals + 1)].open_interest, history[-1].open_interest)


def previous_rsi(klines: list[Kline], period: int) -> float | None:
    """Return RSI for the previous completed candle window.
    返回上一根完成 K 线窗口的 RSI，用于判断上穿。
    """

    if len(klines) <= period + 1:
        return None
    return compute_rsi(klines[:-1], period)


def build_resonance_stats(klines_5m: list[Kline], oi_history: list[OpenInterestPoint]) -> ResonanceStats | None:
    """Build volume-price-OI resonance metrics from 5m candles and OI history.
    根据 5m K 线和 OI 历史构建量价 OI 共振指标。
    """

    if len(klines_5m) < 100 or len(oi_history) < 13:
        return None
    current = klines_5m[-1]
    closes = [item.close for item in klines_5m]
    volume_base = [item.volume for item in klines_5m[-21:-1]]
    volume_ma20 = mean(volume_base) if volume_base else 0.0
    recent_six = klines_5m[-6:]
    volume_ratio = current.volume / volume_ma20 if volume_ma20 else 0.0
    volume_continuity = sum(1 for item in recent_six if volume_ma20 and item.volume > 2 * volume_ma20)
    upper_wick = current.high - max(current.open, current.close)
    body = abs(current.close - current.open)
    ma25 = moving_average(closes, 25)
    return ResonanceStats(
        price_change_15m=pct_change(klines_5m[-4].close, current.close),
        price_change_30m=pct_change(klines_5m[-7].close, current.close),
        price_change_60m=pct_change(klines_5m[-13].close, current.close),
        volume_ratio=volume_ratio,
        volume_continuity=volume_continuity,
        oi_change_15m=oi_change(oi_history, 3),
        oi_change_30m=oi_change(oi_history, 6),
        oi_change_60m=oi_change(oi_history, 12),
        ma7=moving_average(closes, 7),
        ma25=ma25,
        ma99=moving_average(closes, 99),
        rsi6=compute_rsi(klines_5m, 6),
        rsi24=compute_rsi(klines_5m, 24),
        bullish_5m_count_6=sum(1 for item in recent_six if item.close > item.open),
        ma25_deviation=(current.close / ma25 - 1) if ma25 else 0.0,
        long_upper_wick=upper_wick > max(body * 1.5, current.close * 0.004) and volume_ratio > 2,
        consecutive_red_5m=len(recent_six) >= 2 and recent_six[-1].close < recent_six[-1].open and recent_six[-2].close < recent_six[-2].open,
    )


def build_hourly_trend_stats(
    klines_1h: list[Kline],
    klines_15m: list[Kline],
    oi_history_1h: list[OpenInterestPoint],
    funding_rate: float | None = None,
) -> HourlyTrendStats | None:
    """Build hour-level trend metrics from 1h candles, 15m candles, and 1h OI.
    根据 1h K 线、15m K 线和 1h OI 构建小时级趋势指标。
    """

    if len(klines_1h) < 100 or len(klines_15m) < 30 or len(oi_history_1h) < 25:
        return None
    current = klines_1h[-1]
    closes = [item.close for item in klines_1h]
    volumes = [item.volume for item in klines_1h]
    ma7 = moving_average(closes, 7)
    ma25 = moving_average(closes, 25)
    ma99 = moving_average(closes, 99)
    previous_ma7 = moving_average(closes[:-1], 7)
    previous_ma25 = moving_average(closes[:-1], 25)
    volume_avg_6h = moving_average(volumes, 6)
    volume_avg_12h = moving_average(volumes, 12)
    volume_avg_20h = moving_average(volumes, 20)
    volume_avg_24h = moving_average(volumes, 24)
    volume_avg_48h = moving_average(volumes, 48)
    recent_12h_previous = klines_1h[-13:-1]
    high_12h_previous = max(item.high for item in recent_12h_previous) if recent_12h_previous else current.high
    recent_24h = klines_1h[-24:]
    recent_high = max(item.high for item in recent_24h) if recent_24h else current.high
    recent_15m_base = klines_15m[-21:-1]
    volume_15m_avg20 = mean(item.volume for item in recent_15m_base) if recent_15m_base else 0.0
    pullback_15m = klines_15m[-8:]
    rsi15m = compute_rsi(klines_15m, 6)
    prior_rsi15m = previous_rsi(klines_15m, 6)
    current_15m = klines_15m[-1]
    previous_15m = klines_15m[-2]
    latest_oi = oi_history_1h[-1].open_interest
    max_oi = max(item.open_interest for item in oi_history_1h)
    ma_structure = "多头排列" if ma7 > ma25 > ma99 else "偏多" if current.close > ma25 else "震荡"
    return HourlyTrendStats(
        ma7=ma7,
        ma25=ma25,
        ma99=ma99,
        rsi6=compute_rsi(klines_1h, 6),
        rsi24=compute_rsi(klines_1h, 24),
        price_change_6h=pct_change(klines_1h[-7].close, current.close),
        price_change_12h=pct_change(klines_1h[-13].close, current.close),
        price_change_24h=pct_change(klines_1h[-25].close, current.close),
        current_1h_volume=current.volume,
        volume_avg_6h=volume_avg_6h,
        volume_avg_12h=volume_avg_12h,
        volume_avg_20h=volume_avg_20h,
        volume_avg_24h=volume_avg_24h,
        volume_avg_48h=volume_avg_48h,
        volume_ratio=current.volume / volume_avg_20h if volume_avg_20h else 0.0,
        oi_change_6h=oi_change(oi_history_1h, 6),
        oi_change_12h=oi_change(oi_history_1h, 12),
        oi_change_24h=oi_change(oi_history_1h, 24),
        distance_to_ma7=(current.close / ma7 - 1) if ma7 else 0.0,
        distance_to_ma25=(current.close / ma25 - 1) if ma25 else 0.0,
        bullish_1h_count_12=sum(1 for item in klines_1h[-12:] if item.close > item.open),
        long_upper_wick_1h=is_long_upper_wick(current, volume_avg_20h),
        long_upper_wick_2h=any(is_long_upper_wick(item, volume_avg_20h) for item in klines_1h[-2:]),
        consecutive_red_1h=len(klines_1h) >= 2 and klines_1h[-1].close < klines_1h[-1].open and klines_1h[-2].close < klines_1h[-2].open,
        close_above_high_12h_previous=current.close > high_12h_previous,
        ma7_slope=ma7 - previous_ma7 if previous_ma7 else 0.0,
        ma25_slope=ma25 - previous_ma25 if previous_ma25 else 0.0,
        recent_3h_holds_ma25=ma25 > 0 and all(item.low >= ma25 * 0.995 for item in klines_1h[-3:]),
        pullback_from_recent_high=(recent_high - current.close) / recent_high if recent_high and recent_high > current.close else 0.0,
        near_ma7_or_ma25=near_any_ma(current.close, [ma7, ma25], max_distance=0.02),
        rsi15m_crossed_up=rsi_crossed_up(prior_rsi15m, rsi15m),
        reversal_15m=current_15m.close > current_15m.open and current_15m.close > previous_15m.close,
        pullback_volume_safe=not any(volume_15m_avg20 and item.volume > volume_15m_avg20 * 2.5 for item in pullback_15m),
        oi_pullback_from_high=(max_oi - latest_oi) / max_oi if max_oi else 0.0,
        funding_rate=funding_rate,
        ma_structure=ma_structure,
    )


def build_pump_pullback_stats(
    klines_15m: list[Kline],
    klines_1h: list[Kline],
    klines_5m: list[Kline],
    oi_history_15m: list[OpenInterestPoint],
    oi_history_5m: list[OpenInterestPoint],
    config: dict[str, Any],
) -> PumpPullbackStats | None:
    """Build first-pump pullback and second-wave metrics.
    构建首波爆拉、健康回调和二波启动指标。
    """

    if len(klines_15m) < 100 or len(klines_1h) < 100 or len(klines_5m) < 20 or len(oi_history_15m) < 20 or len(oi_history_5m) < 13:
        return None
    pump = find_first_pump(klines_15m, oi_history_15m, config["first_pump"])
    if pump is None:
        return PumpPullbackStats()
    start_index, high_index, pump_volume_avg = pump
    current = klines_15m[-1]
    pump_start = klines_15m[start_index]
    pump_high = max(item.high for item in klines_15m[start_index : high_index + 1])
    pump_high_candle = max(klines_15m[start_index : high_index + 1], key=lambda item: item.high)
    pump_change = pct_change(pump_start.open, pump_high)
    pullback_candles = klines_15m[high_index + 1 :]
    pullback_body = pullback_candles[:-3] if len(pullback_candles) > 6 else pullback_candles
    range_source = pullback_body or pullback_candles or [current]
    range_high = max(item.high for item in range_source)
    range_low = min(item.low for item in range_source)
    pullback_volume_avg = mean(item.volume for item in pullback_candles) if pullback_candles else current.volume
    oi_after_start = oi_history_15m[start_index:] if len(oi_history_15m) > start_index else oi_history_15m
    peak_oi = max((item.open_interest for item in oi_after_start), default=oi_history_15m[-1].open_interest)
    current_oi = oi_history_15m[-1].open_interest
    closes_15m = [item.close for item in klines_15m]
    closes_1h = [item.close for item in klines_1h]
    ma7_15m = moving_average(closes_15m, 7)
    ma25_15m = moving_average(closes_15m, 25)
    prior_ma7_15m = moving_average(closes_15m[:-1], 7)
    prior_ma25_15m = moving_average(closes_15m[:-1], 25)
    ma7_1h = moving_average(closes_1h, 7)
    prior_close_1h = klines_1h[-2].close
    prior_ma7_1h = moving_average(closes_1h[:-1], 7)
    ma25_1h = moving_average(closes_1h, 25)
    ma99_1h = moving_average(closes_1h, 99)
    rsi6_15m = compute_rsi(klines_15m, 6)
    rsi24_15m = compute_rsi(klines_15m, 24)
    prior_rsi6_15m = previous_rsi(klines_15m, 6)
    prior_rsi24_15m = previous_rsi(klines_15m, 24)
    volume_base = [item.volume for item in klines_15m[-21:-1]]
    volume_avg20 = mean(volume_base) if volume_base else 0.0
    price_30m_ago = klines_15m[-3].close if len(klines_15m) >= 3 else current.open
    return PumpPullbackStats(
        has_first_pump=True,
        pump_start_time=pump_start.timestamp,
        pump_high_time=pump_high_candle.timestamp,
        pump_start_price=pump_start.open,
        pump_high=pump_high,
        pump_change=pump_change,
        pullback_from_high=(pump_high - current.close) / pump_high if pump_high else 0.0,
        retracement_ratio=(pump_high - current.close) / (pump_high - pump_start.open) if pump_high > pump_start.open else 0.0,
        pullback_volume_ratio=pullback_volume_avg / pump_volume_avg if pump_volume_avg else 0.0,
        oi_drawdown_from_peak=(peak_oi - current_oi) / peak_oi if peak_oi else 0.0,
        price_above_pump_start=current.close > pump_start.open,
        price_above_1h_ma25=ma25_1h > 0 and klines_1h[-1].close > ma25_1h,
        price_above_1h_ma99=ma99_1h > 0 and klines_1h[-1].close > ma99_1h,
        ma7_15m=ma7_15m,
        ma25_15m=ma25_15m,
        ma7_crossed_above_ma25_15m=prior_ma7_15m <= prior_ma25_15m and ma7_15m > ma25_15m if prior_ma7_15m and prior_ma25_15m else False,
        rsi6_15m=rsi6_15m,
        rsi24_15m=rsi24_15m,
        rsi6_crossed_above_rsi24_15m=prior_rsi6_15m is not None and prior_rsi24_15m is not None and rsi6_15m is not None and rsi24_15m is not None and prior_rsi6_15m <= prior_rsi24_15m and rsi6_15m > rsi24_15m,
        recent_15m_change_3bars=pct_change(klines_15m[-4].close, current.close),
        volume_ratio_15m=current.volume / volume_avg20 if volume_avg20 else 0.0,
        oi_change_30m=oi_change(oi_history_5m, 6),
        oi_change_1h=oi_change(oi_history_5m, 12),
        range_high=range_high,
        range_low=range_low,
        price_breaks_range_high=current.close > range_high,
        price_near_or_above_pump_high=current.close >= pump_high * (1 - config["p3"]["near_pump_high_distance"]),
        one_hour_close_above_ma7=ma7_1h > 0 and klines_1h[-1].close > ma7_1h,
        one_hour_reclaimed_ma7=prior_ma7_1h > 0 and prior_close_1h < prior_ma7_1h and klines_1h[-1].close > ma7_1h,
        fell_back_into_range=current.close < range_high,
        oi_up_price_down=oi_change(oi_history_5m, 6) > 0 and pct_change(price_30m_ago, current.close) <= 0,
        long_upper_wick_15m=is_long_upper_wick(current, volume_avg20),
        broke_pullback_low=current.close < range_low,
        ma_structure_15m="多头排列" if ma7_15m > ma25_15m else "修复中" if current.close > ma25_15m else "转弱",
        ma_structure_1h="多头排列" if klines_1h[-1].close > ma7_1h > ma25_1h > ma99_1h else "偏多" if klines_1h[-1].close > ma25_1h else "转弱",
    )


def find_first_pump(klines_15m: list[Kline], oi_history_15m: list[OpenInterestPoint], config: dict[str, Any]) -> tuple[int, int, float] | None:
    """Find the strongest valid first-pump window in recent 24h.
    在最近 24 小时内查找最强的首波爆拉窗口。
    """

    lookback = int(config["lookback_hours"] * 4)
    min_window = int(config["min_duration_hours"] * 4)
    max_window = int(config["max_duration_hours"] * 4)
    start_floor = max(1, len(klines_15m) - lookback)
    best: tuple[float, int, int, float] | None = None
    for start in range(start_floor, len(klines_15m) - min_window):
        prior = klines_15m[max(0, start - lookback) : start]
        if not prior:
            continue
        prior_high = max(item.high for item in prior)
        prior_volume_avg = mean(item.volume for item in prior)
        for window in range(min_window, max_window + 1):
            end = start + window - 1
            if end >= len(klines_15m):
                continue
            segment = klines_15m[start : end + 1]
            segment_high = max(item.high for item in segment)
            change = pct_change(klines_15m[start].open, segment_high)
            volume_avg = mean(item.volume for item in segment)
            if end >= len(oi_history_15m) or start >= len(oi_history_15m):
                continue
            oi_move = pct_change(oi_history_15m[start].open_interest, oi_history_15m[end].open_interest)
            matched = (
                change > config["min_change"]
                and volume_avg > prior_volume_avg * config["volume_multiplier"]
                and oi_move > config["oi_change_min"]
                and segment_high > prior_high
            )
            if matched and (best is None or change > best[0]):
                best = (change, start, end, volume_avg)
    if best is None:
        return None
    _, start, end, volume_avg = best
    return start, end, volume_avg


def is_long_upper_wick(kline: Kline, average_volume: float) -> bool:
    """Return whether a candle has a meaningful high-volume upper wick.
    判断 K 线是否出现带量长上影。
    """

    upper_wick = kline.high - max(kline.open, kline.close)
    body = abs(kline.close - kline.open)
    volume_ok = average_volume > 0 and kline.volume > average_volume * 1.5
    return volume_ok and upper_wick > max(body * 1.5, kline.close * 0.004)


def near_any_ma(price: float, averages: list[float], max_distance: float) -> bool:
    """Return whether price is close enough to any moving average.
    判断价格是否足够靠近任一均线。
    """

    return any(average > 0 and abs(price / average - 1) <= max_distance for average in averages)


def rsi_crossed_up(previous: float | None, current: float | None) -> bool:
    """Return whether RSI6 crossed back above a watched low threshold.
    判断 RSI6 是否从低位重新上穿 30 或 50。
    """

    if previous is None or current is None:
        return False
    return (previous < 30 <= current) or (previous < 50 <= current)


def compute_timeframe_stats(klines: list[Kline], breakout_window: int = 20, volume_window: int = 20, ma_window: int = 20) -> TimeframeStats:
    """Compute compact technical statistics from candles.
    根据 K 线计算紧凑技术指标。
    """

    if len(klines) < max(3, min(breakout_window, 5)):
        return TimeframeStats()
    current = klines[-1]
    start = klines[0]
    previous = klines[:-1]
    recent = previous[-breakout_window:] if len(previous) >= breakout_window else previous
    volume_base = previous[-volume_window:] if len(previous) >= volume_window else previous
    ma_base = klines[-ma_window:] if len(klines) >= ma_window else klines
    recent_high = max(item.high for item in recent) if recent else current.high
    recent_low = min(item.low for item in recent) if recent else current.low
    avg_volume = mean(item.volume for item in volume_base) if volume_base else current.volume
    volume_ratio = current.volume / avg_volume if avg_volume else 0.0
    lows = [item.low for item in klines[-6:]]
    higher_lows = len(lows) >= 4 and lows[-1] > lows[-3] > lows[-5]
    ma = mean(item.close for item in ma_base) if ma_base else current.close
    distance_to_ma = (current.close - ma) / ma if ma else 0.0
    upper_wick = current.high - max(current.open, current.close)
    body = abs(current.close - current.open)
    rejection = current.high > 0 and upper_wick > max(body * 1.5, current.close * 0.004) and current.close < current.high * 0.99 and volume_ratio >= 1.5
    large_green_count = sum(1 for item in klines[-5:] if item.close > item.open and pct_change(item.open, item.close) >= 0.01)
    pullback_ratio = pct_change(current.close, recent_high) if current.close and recent_high > current.close else 0.0
    candle_range = current.high - current.low
    close_position = (current.close - current.low) / candle_range if candle_range > 0 else 0.5
    return TimeframeStats(
        change=pct_change(start.open, current.close),
        volume_ratio=volume_ratio,
        recent_high=recent_high,
        recent_low=recent_low,
        higher_lows=higher_lows,
        breakout=current.close > recent_high,
        pullback_ratio=pullback_ratio,
        closes_above_ma=current.close >= ma,
        rejection=rejection,
        large_green_count=large_green_count,
        distance_to_ma=distance_to_ma,
        close_position=close_position,
        rsi=compute_rsi(klines),
        atr_ratio=compute_atr_ratio(klines),
    )


def build_market_metrics(
    ticker: dict[str, Any],
    klines_by_timeframe: dict[str, list[Kline]],
    btc_15m_change: float,
    rank_24h: int | None = None,
    funding_rate: float | None = None,
    open_interest: float | None = None,
    oi_history: list[OpenInterestPoint] | None = None,
    trend_oi_history: list[OpenInterestPoint] | None = None,
    pump_oi_history_15m: list[OpenInterestPoint] | None = None,
    radar_rule_config: dict[str, Any] | None = None,
    required_timeframes: set[str] | None = None,
) -> MarketMetrics | None:
    """Build derived metrics for one symbol, returning None when data is insufficient.
    为单个交易对构建派生指标；数据不足时返回 None。
    """

    symbol = str(ticker.get("symbol") or "")
    price_value = ticker.get("last") or ticker.get("close")
    if not symbol or price_value is None:
        return None
    required = required_timeframes or {"1m", "3m", "5m", "15m", "1h"}
    if any(len(klines_by_timeframe.get(timeframe, [])) < 5 for timeframe in required):
        return None
    klines_1m = klines_by_timeframe.get("1m", [])
    klines_3m = klines_by_timeframe.get("3m", [])
    klines_5m = klines_by_timeframe.get("5m", [])
    klines_15m = klines_by_timeframe.get("15m", [])
    klines_1h = klines_by_timeframe.get("1h", [])
    rule_config = radar_rule_config or {}
    volume_price_oi_enabled = bool(rule_config.get("volume_price_oi", {}).get("enabled", True))
    hourly_trend_enabled = bool(rule_config.get("hourly_trend", {}).get("enabled"))
    pump_pullback_enabled = bool(rule_config.get("pump_pullback_second_wave", {}).get("enabled"))
    return MarketMetrics(
        symbol=symbol,
        price=float(price_value),
        price_change_24h=float(ticker.get("percentage") or ticker.get("price_change_percent") or 0.0) / 100,
        quote_volume_24h=float(ticker.get("quote_volume") or ticker.get("quoteVolume") or 0.0),
        rank_24h=rank_24h,
        high_24h=float(ticker["high"]) if ticker.get("high") is not None else None,
        low_24h=float(ticker["low"]) if ticker.get("low") is not None else None,
        stats_1m=compute_timeframe_stats(klines_1m),
        stats_3m=compute_timeframe_stats(klines_3m),
        stats_5m=compute_timeframe_stats(klines_5m),
        stats_15m=compute_timeframe_stats(klines_15m),
        stats_1h=compute_timeframe_stats(klines_1h),
        btc_15m_change=btc_15m_change,
        funding_rate=funding_rate,
        open_interest=open_interest,
        resonance=build_resonance_stats(klines_5m, oi_history or []) if volume_price_oi_enabled else None,
        trend=build_hourly_trend_stats(klines_1h, klines_15m, trend_oi_history or [], funding_rate=funding_rate) if hourly_trend_enabled else None,
        pump_pullback=build_pump_pullback_stats(klines_15m, klines_1h, klines_5m, pump_oi_history_15m or [], oi_history or [], rule_config.get("pump_pullback_second_wave", {})) if pump_pullback_enabled else None,
        raw={"ticker": ticker},
    )
