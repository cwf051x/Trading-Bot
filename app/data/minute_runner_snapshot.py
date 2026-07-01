"""Minute Runner Radar snapshot scoring.
分钟级单边上涨池的快照评分和状态机。
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from app.alerts.signal_models import MinuteRunnerState, MinuteRunnerStats
from app.exchange.binance import Kline, OpenInterestPoint


def pct_change(start: float, end: float) -> float:
    """Return percentage change as a decimal ratio.
    返回小数形式的涨跌幅比例。
    """

    if start == 0:
        return 0.0
    return (end - start) / start


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


def build_minute_runner_stats(
    klines_5m: list[Kline],
    klines_15m: list[Kline],
    klines_1h: list[Kline],
    oi_history_5m: list[OpenInterestPoint],
    funding_rate: float | None,
    btc_15m_change: float,
    config: dict[str, Any],
) -> MinuteRunnerStats | None:
    """Build minute-level one-way runner metrics without extra exchange calls.
    基于 scanner 已有 K 线/OI/funding 构建分钟级单边上涨指标。
    """

    if not bool(config.get("enabled", True)):
        return None
    if len(klines_5m) < 100 or len(klines_15m) < 25 or len(klines_1h) < 3 or len(oi_history_5m) < 13:
        return None

    current = klines_5m[-1]
    closes_5m = [item.close for item in klines_5m]
    closes_15m = [item.close for item in klines_15m]
    ma7_5m = moving_average(closes_5m, 7)
    ma25_5m = moving_average(closes_5m, 25)
    ma99_5m = moving_average(closes_5m, 99)
    ma7_15m = moving_average(closes_15m, 7)
    ma25_15m = moving_average(closes_15m, 25)
    previous_ma7_5m = moving_average(closes_5m[:-1], 7)
    previous_ma25_5m = moving_average(closes_5m[:-1], 25)
    previous_ma7_15m = moving_average(closes_15m[:-1], 7)
    previous_ma25_15m = moving_average(closes_15m[:-1], 25)
    recent_12 = klines_5m[-12:]
    recent_6 = klines_5m[-6:]
    volume_ratio_5m = _volume_ratio(klines_5m, 20)
    volume_ratio_15m = _volume_ratio(klines_15m, 20)
    oi_change_30m = oi_change(oi_history_5m, 6)
    oi_change_45m = oi_change(oi_history_5m, 9)
    oi_change_1h = oi_change(oi_history_5m, 12)
    price_change_15m = _window_change(klines_5m, 3)
    price_change_30m = _window_change(klines_5m, 6)
    price_change_1h = _window_change(klines_1h, 1)
    high_1h = max(item.high for item in klines_5m[-12:])
    pullback_from_high = (high_1h - current.close) / high_1h if high_1h and high_1h > current.close else 0.0
    distance_to_ma25_5m = (current.close / ma25_5m - 1) if ma25_5m else 0.0
    close_above_ma7_count = _rolling_close_above_ma_count(klines_5m, 7, 12)
    close_above_ma25_count = _rolling_close_above_ma_count(klines_5m, 25, 12)
    bullish_count = sum(1 for item in recent_12 if item.close > item.open)
    higher_low_count = sum(1 for previous, item in zip(recent_12, recent_12[1:]) if item.low > previous.low)
    long_upper_wick_count = sum(1 for item in recent_6[-3:] if _is_long_upper_wick(item, moving_average([row.volume for row in klines_5m[:-1]], 20)))
    consecutive_below_ma25 = sum(1 for item in recent_6[-2:] if ma25_5m and item.close < ma25_5m)
    volume_stall = _volume_stall(klines_5m)
    oi_price_divergence = oi_change_30m >= 0.04 and price_change_30m <= 0.005
    trend_start_index = _minute_runner_trend_start_index(klines_5m, ma25_15m)
    trend_age_minutes = max(0, (len(klines_5m) - 1 - trend_start_index) * 5) if trend_start_index is not None else 0
    trend_id = f"trend-{klines_5m[trend_start_index].timestamp}" if trend_start_index is not None else f"trend-{current.timestamp}"
    reasons: list[str] = []
    risk_tags: list[str] = []
    score = 0.0

    # 趋势结构只奖励中前段结构质量，不让末端涨幅无限加分。
    if ma7_5m > ma25_5m:
        score += 6
        reasons.append("5m MA7 > MA25，短线多头结构成立")
    if ma25_5m > ma99_5m:
        score += 5
    if current.close > ma7_5m:
        score += 5
    if klines_15m[-1].close > ma25_15m:
        score += 5
    if ma7_5m > previous_ma7_5m and ma25_5m >= previous_ma25_5m and ma7_15m >= previous_ma7_15m and ma25_15m >= previous_ma25_15m:
        score += 4

    if close_above_ma7_count >= 8:
        score += 5
    if close_above_ma25_count >= 10:
        score += 5
        reasons.append("最近12根5m中至少10根收在MA25上方")
    if higher_low_count >= 7:
        score += 5
    if pullback_from_high <= 0.04:
        score += 5

    if 30 <= trend_age_minutes < 45:
        score += 3
    elif 45 <= trend_age_minutes < 60:
        score += 6
    elif 60 <= trend_age_minutes <= 120:
        score += 10
        reasons.append(f"趋势已持续{trend_age_minutes}分钟，处于60-120分钟甜蜜区间")
    elif 120 < trend_age_minutes <= 180:
        score += 8
    elif trend_age_minutes > 180:
        score += 3

    if 0.08 <= price_change_1h < 0.12:
        score += 4
    elif 0.12 <= price_change_1h <= 0.30:
        score += 8
    elif 0.30 < price_change_1h <= 0.45:
        score += 6
    elif 0.45 < price_change_1h <= 0.60:
        score += 2

    if volume_ratio_15m >= 1.8:
        score += 4
        reasons.append("15m成交量放大，趋势确认周期有量能配合")
    if sum(1 for item in klines_5m[-3:] if item.volume > moving_average([row.volume for row in klines_5m[:-1]], 20)) >= 3:
        score += 3
    if _up_volume_down_volume_quality(klines_5m):
        score += 3

    if oi_change_30m >= 0.04:
        score += 4
        reasons.append("OI 30m同步回升")
    if oi_change_45m >= 0.05:
        score += 3
    if oi_change_1h >= 0.06:
        score += 3
    if btc_15m_change > float(config["risk"]["btc_15m_dump_threshold"]):
        score += 3
    if not _funding_extreme(funding_rate):
        score += 2

    if current.close < ma7_5m:
        score -= 5
    if len(recent_6) >= 2 and recent_6[-1].close < recent_6[-1].open and recent_6[-2].close < recent_6[-2].open:
        score -= 5
    if volume_stall:
        score -= 5
        risk_tags.append("量能衰减")
    if current.close < ma25_5m:
        score -= 15
    if oi_price_divergence:
        score -= 12
        risk_tags.append("OI增价滞")
    if distance_to_ma25_5m > 0.15:
        score -= 8
    if price_change_1h > float(config["momentum"]["one_hour_change_overheat"]):
        score -= 12
    if consecutive_below_ma25 >= 2:
        score -= 25
    if klines_15m[-1].close < ma25_15m:
        score -= 35
    if pullback_from_high >= float(config["risk"]["confirmed_pullback_downgrade"]):
        score -= 20
    if pullback_from_high >= float(config["risk"]["pool_remove_pullback"]):
        score -= 10

    is_overheated = (
        price_change_1h >= float(config["momentum"]["one_hour_change_overheat"])
        or price_change_15m >= 0.25
        or distance_to_ma25_5m >= float(config["risk"]["overheat_distance_to_ma25_5m"])
        or long_upper_wick_count >= 2
        or oi_price_divergence
        or _funding_extreme(funding_rate)
    )
    if is_overheated:
        risk_tags.append("过热/防追高")
    broken_reason = _minute_runner_broken_reason(consecutive_below_ma25, klines_15m[-1].close < ma25_15m, pullback_from_high, volume_stall, oi_change_30m, price_change_30m, config)
    state = _minute_runner_state(
        score=score,
        trend_age_minutes=trend_age_minutes,
        current=current,
        ma7_5m=ma7_5m,
        ma25_5m=ma25_5m,
        ma25_15m=ma25_15m,
        close_above_ma7_count=close_above_ma7_count,
        close_above_ma25_count=close_above_ma25_count,
        volume_ratio_15m=volume_ratio_15m,
        oi_change_30m=oi_change_30m,
        oi_change_45m=oi_change_45m,
        oi_change_1h=oi_change_1h,
        price_change_1h=price_change_1h,
        distance_to_ma25_5m=distance_to_ma25_5m,
        btc_15m_change=btc_15m_change,
        is_overheated=is_overheated,
        broken_reason=broken_reason,
        config=config,
    )
    ranking_score = _minute_runner_ranking_score(score, state, oi_change_30m, close_above_ma25_count, pullback_from_high)
    email_should_send = state == MinuteRunnerState.EARLY_CONFIRMED.value and not is_overheated and broken_reason is None
    return MinuteRunnerStats(
        trend_age_minutes=trend_age_minutes,
        runner_score=max(0.0, min(100.0, score)),
        ranking_score=ranking_score,
        state=state,
        email_should_send=email_should_send,
        price_change_15m=price_change_15m,
        price_change_30m=price_change_30m,
        price_change_1h=price_change_1h,
        volume_ratio_15m=volume_ratio_15m,
        volume_ratio_5m=volume_ratio_5m,
        oi_change_30m=oi_change_30m,
        oi_change_45m=oi_change_45m,
        oi_change_1h=oi_change_1h,
        ma7_5m=ma7_5m,
        ma25_5m=ma25_5m,
        ma99_5m=ma99_5m,
        ma7_15m=ma7_15m,
        ma25_15m=ma25_15m,
        close_above_ma7_5m_count_12=close_above_ma7_count,
        close_above_ma25_5m_count_12=close_above_ma25_count,
        bullish_5m_count_12=bullish_count,
        higher_low_count_5m=higher_low_count,
        pullback_from_high=pullback_from_high,
        distance_to_ma25_5m=distance_to_ma25_5m,
        long_upper_wick_count_5m=long_upper_wick_count,
        volume_stall=volume_stall,
        oi_price_divergence=oi_price_divergence,
        is_overheated=is_overheated,
        broken_reason=broken_reason,
        risk_tags=risk_tags,
        reasons=reasons,
        trend_id=trend_id,
    )


def _window_change(klines: list[Kline], intervals: int) -> float:
    """Return close-to-close change over a recent candle interval.
    返回指定最近 K 线间隔的收盘价涨跌幅。
    """

    if len(klines) <= intervals:
        return 0.0
    return pct_change(klines[-(intervals + 1)].close, klines[-1].close)


def _volume_ratio(klines: list[Kline], window: int) -> float:
    """Return latest volume divided by the previous average volume.
    返回最新成交量相对前序均量的倍数。
    """

    if len(klines) <= window:
        return 0.0
    base = [item.volume for item in klines[-(window + 1) : -1]]
    average_volume = mean(base) if base else 0.0
    return klines[-1].volume / average_volume if average_volume else 0.0


def _rolling_close_above_ma_count(klines: list[Kline], window: int, lookback: int) -> int:
    """Count recent closes above their own rolling moving average.
    统计最近 K 线收盘价是否站上各自对应的滚动均线。
    """

    if len(klines) < window:
        return 0
    closes = [item.close for item in klines]
    count = 0
    start = max(window - 1, len(klines) - lookback)
    for index in range(start, len(klines)):
        average = moving_average(closes[: index + 1], window)
        if average and klines[index].close > average:
            count += 1
    return count


def _minute_runner_trend_start_index(klines_5m: list[Kline], ma25_15m: float) -> int | None:
    """Find the first recent candle that starts the one-way trend clock.
    查找最近一段单边趋势开始计时的 5m K 线。
    """

    closes = [item.close for item in klines_5m]
    floor = max(25, len(klines_5m) - 48)
    for index in range(floor, len(klines_5m)):
        ma7 = moving_average(closes[: index + 1], 7)
        ma25 = moving_average(closes[: index + 1], 25)
        previous_ma7 = moving_average(closes[:index], 7)
        recent = klines_5m[max(0, index - 2) : index + 1]
        bullish_recent = sum(1 for item in recent if item.close > item.open)
        if ma25 and klines_5m[index].close > ma25 and ma7 > previous_ma7 and bullish_recent >= 2 and (ma25_15m <= 0 or klines_5m[index].close > ma25_15m * 0.98):
            return index
    return None


def _volume_stall(klines_5m: list[Kline]) -> bool:
    """Detect price stall with fading volume after a runner advance.
    识别上涨后价格滞涨且量能衰减的情况。
    """

    if len(klines_5m) < 12:
        return False
    recent_volume = mean(item.volume for item in klines_5m[-3:])
    previous_volume = mean(item.volume for item in klines_5m[-9:-3])
    recent_change = pct_change(klines_5m[-4].close, klines_5m[-1].close)
    return previous_volume > 0 and recent_volume < previous_volume * 0.65 and recent_change <= 0.005


def _up_volume_down_volume_quality(klines_5m: list[Kline]) -> bool:
    """Return whether up candles carry more volume than pullbacks.
    判断上涨放量、回调缩量的量能结构。
    """

    recent = klines_5m[-12:]
    up = [item.volume for item in recent if item.close >= item.open]
    down = [item.volume for item in recent if item.close < item.open]
    if not up:
        return False
    return not down or mean(up) >= mean(down)


def _funding_extreme(funding_rate: float | None) -> bool:
    """Treat very high positive funding as a chase-risk filter.
    将极高正资金费率视为追高风险过滤项。
    """

    return funding_rate is not None and funding_rate >= 0.002


def _minute_runner_broken_reason(
    consecutive_below_ma25: int,
    close_15m_below_ma25: bool,
    pullback_from_high: float,
    volume_stall: bool,
    oi_change_30m: float,
    price_change_30m: float,
    config: dict[str, Any],
) -> str | None:
    """Return the durable remove/downgrade reason for broken runner trends.
    返回单边上涨池移出或降级的持久化原因。
    """

    if consecutive_below_ma25 >= 2:
        return "5m连续跌破MA25"
    if close_15m_below_ma25:
        return "15m跌破MA25"
    if pullback_from_high >= float(config["risk"]["pool_remove_pullback"]):
        return "高点回撤过大"
    if volume_stall and price_change_30m < 0:
        return "放量破位"
    if oi_change_30m < -0.04 and price_change_30m < 0:
        return "OI流出"
    return None


def _minute_runner_state(
    *,
    score: float,
    trend_age_minutes: int,
    current: Kline,
    ma7_5m: float,
    ma25_5m: float,
    ma25_15m: float,
    close_above_ma7_count: int,
    close_above_ma25_count: int,
    volume_ratio_15m: float,
    oi_change_30m: float,
    oi_change_45m: float,
    oi_change_1h: float,
    price_change_1h: float,
    distance_to_ma25_5m: float,
    btc_15m_change: float,
    is_overheated: bool,
    broken_reason: str | None,
    config: dict[str, Any],
) -> str:
    """Classify the current minute-runner state from stats and hard gates.
    根据评分和硬闸口分类 M0-M4 状态。
    """

    pool = config["pool"]
    risk = config["risk"]
    trend_age = config["trend_age"]
    momentum = config["momentum"]
    volume = config["volume"]
    oi = config["oi"]
    if broken_reason is not None:
        return MinuteRunnerState.BROKEN.value
    if is_overheated:
        return MinuteRunnerState.OVERHEAT.value
    if score < float(pool["remove_score"]):
        return MinuteRunnerState.BROKEN.value
    early_confirmed = (
        score >= float(pool["early_confirmed_score"])
        and int(trend_age["early_confirmed_min_minutes"]) <= trend_age_minutes <= int(trend_age["early_confirmed_max_minutes"])
        and ma7_5m > ma25_5m
        and current.close > ma25_5m
        and current.close > ma25_15m
        and close_above_ma7_count >= 8
        and close_above_ma25_count >= 10
        and volume_ratio_15m >= float(volume["confirmed_15m_volume_ratio"])
        and (oi_change_30m >= float(oi["confirmed_30m_change"]) or oi_change_45m >= float(oi["confirmed_45m_change"]) or oi_change_1h >= float(oi["confirmed_1h_change"]))
        and oi_change_1h > float(oi["max_negative_1h_change"])
        and float(momentum["one_hour_change_min"]) <= price_change_1h <= float(momentum["one_hour_change_sweet_max"])
        and distance_to_ma25_5m <= float(risk["max_distance_to_ma25_5m_for_email"])
        and btc_15m_change > float(risk["btc_15m_dump_threshold"])
    )
    if early_confirmed:
        return MinuteRunnerState.EARLY_CONFIRMED.value
    if score >= float(pool["mature_confirmed_score"]) and trend_age_minutes >= 90 and ma7_5m > ma25_5m and oi_change_1h >= 0.08:
        return MinuteRunnerState.MATURE_CONFIRMED.value
    pool_matched = (
        score >= float(pool["min_score"])
        and (ma7_5m > ma25_5m or ma7_5m > 0)
        and current.close > ma25_5m
        and close_above_ma25_count >= 8
        and current.close > ma25_15m
        and volume_ratio_15m >= float(volume["min_15m_volume_ratio"])
        and (oi_change_30m >= float(oi["min_30m_change"]) or oi_change_1h >= 0.03)
    )
    if pool_matched:
        return MinuteRunnerState.POOL.value
    return MinuteRunnerState.SPARK.value


def _minute_runner_ranking_score(score: float, state: str, oi_change_30m: float, close_above_ma25_count: int, pullback_from_high: float) -> float:
    """Rank pool entries by quality rather than raw price change.
    按趋势质量而不是单纯涨幅计算池榜排序分。
    """

    ranking = score
    if state == MinuteRunnerState.EARLY_CONFIRMED.value:
        ranking += 18
    elif state == MinuteRunnerState.MATURE_CONFIRMED.value:
        ranking += 10
    elif state == MinuteRunnerState.OVERHEAT.value:
        ranking -= 30
    ranking += min(8.0, max(0.0, oi_change_30m) * 100)
    ranking += 5 if close_above_ma25_count >= 10 else 0
    ranking -= min(15.0, max(0.0, pullback_from_high) * 100)
    return max(0.0, ranking)


def _is_long_upper_wick(kline: Kline, average_volume: float) -> bool:
    """Return whether a candle has a meaningful high-volume upper wick.
    判断 K 线是否出现带量长上影。
    """

    upper_wick = kline.high - max(kline.open, kline.close)
    body = abs(kline.close - kline.open)
    volume_ok = average_volume > 0 and kline.volume > average_volume * 1.5
    return volume_ok and upper_wick > max(body * 1.5, kline.close * 0.004)
