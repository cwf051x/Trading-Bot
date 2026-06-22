"""Market snapshot utilities for alert radar.
行情雷达使用的市场快照工具。
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from app.alerts.signal_models import HourlyTrendStats, MarketMetrics, ResonanceStats, TimeframeStats
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
) -> MarketMetrics | None:
    """Build derived metrics for one symbol, returning None when data is insufficient.
    为单个交易对构建派生指标；数据不足时返回 None。
    """

    symbol = str(ticker.get("symbol") or "")
    price_value = ticker.get("last") or ticker.get("close")
    if not symbol or price_value is None:
        return None
    required = ["1m", "3m", "5m", "15m", "1h"]
    if any(len(klines_by_timeframe.get(timeframe, [])) < 5 for timeframe in required):
        return None
    return MarketMetrics(
        symbol=symbol,
        price=float(price_value),
        price_change_24h=float(ticker.get("percentage") or ticker.get("price_change_percent") or 0.0) / 100,
        quote_volume_24h=float(ticker.get("quote_volume") or ticker.get("quoteVolume") or 0.0),
        rank_24h=rank_24h,
        high_24h=float(ticker["high"]) if ticker.get("high") is not None else None,
        low_24h=float(ticker["low"]) if ticker.get("low") is not None else None,
        stats_1m=compute_timeframe_stats(klines_by_timeframe["1m"]),
        stats_3m=compute_timeframe_stats(klines_by_timeframe["3m"]),
        stats_5m=compute_timeframe_stats(klines_by_timeframe["5m"]),
        stats_15m=compute_timeframe_stats(klines_by_timeframe["15m"]),
        stats_1h=compute_timeframe_stats(klines_by_timeframe["1h"]),
        btc_15m_change=btc_15m_change,
        funding_rate=funding_rate,
        open_interest=open_interest,
        resonance=build_resonance_stats(klines_by_timeframe["5m"], oi_history or []),
        trend=build_hourly_trend_stats(klines_by_timeframe["1h"], klines_by_timeframe["15m"], trend_oi_history or [], funding_rate=funding_rate),
        raw={"ticker": ticker},
    )
