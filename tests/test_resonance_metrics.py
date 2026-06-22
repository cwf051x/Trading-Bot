"""Volume-price-OI resonance metric tests.
量价 OI 共振指标测试。
"""

from app.alerts.rule_config import DEFAULT_RADAR_RULE_CONFIG
from app.data.market_snapshot import build_hourly_trend_stats, build_pump_pullback_stats, build_resonance_stats
from app.exchange.binance import Kline, OpenInterestPoint


def make_klines() -> list[Kline]:
    rows: list[Kline] = []
    price = 100.0
    for index in range(110):
        open_price = price
        close = open_price * (1.01 if index >= 98 else 1.001)
        high = close * (1.002 if index != 109 else 1.03)
        low = open_price * 0.998
        volume = 1000.0
        if index >= 104:
            volume = 4000.0
        rows.append(Kline(timestamp=index, open=open_price, high=high, low=low, close=close, volume=volume))
        price = close
    return rows


def make_oi_history() -> list[OpenInterestPoint]:
    return [OpenInterestPoint(timestamp=index, open_interest=1000.0 + index * 25.0) for index in range(20)]


def test_build_resonance_stats_derives_price_volume_oi_and_ma_fields() -> None:
    stats = build_resonance_stats(make_klines(), make_oi_history())

    assert stats is not None
    assert stats.price_change_15m > 0.03
    assert stats.price_change_30m > 0.06
    assert stats.price_change_60m > 0.10
    assert stats.volume_ratio > 2
    assert stats.volume_continuity == 6
    assert stats.oi_change_15m > 0.03
    assert stats.oi_change_30m > 0.08
    assert stats.oi_change_60m > 0.20
    assert stats.ma7 > stats.ma25 > stats.ma99
    assert stats.bullish_5m_count_6 == 6
    assert stats.ma25_deviation > 0


def make_hourly_klines() -> list[Kline]:
    rows: list[Kline] = []
    price = 100.0
    for index in range(120):
        open_price = price
        close = open_price * (1.004 if index < 108 else 1.02)
        high = close * 1.004
        low = open_price * 0.996
        volume = 1000.0 if index < 108 else 2200.0
        if index == 119:
            volume = 4000.0
        rows.append(Kline(timestamp=index * 3_600_000, open=open_price, high=high, low=low, close=close, volume=volume))
        price = close
    return rows


def make_15m_reversal_klines() -> list[Kline]:
    rows: list[Kline] = []
    price = 120.0
    for index in range(80):
        if index < 75:
            close = price * 0.997
        else:
            close = price * 1.006
        high = max(price, close) * 1.002
        low = min(price, close) * 0.998
        rows.append(Kline(timestamp=index * 900_000, open=price, high=high, low=low, close=close, volume=900.0))
        price = close
    return rows


def make_hourly_oi_history() -> list[OpenInterestPoint]:
    return [OpenInterestPoint(timestamp=index * 3_600_000, open_interest=1000.0 + index * 30.0) for index in range(30)]


def test_build_hourly_trend_stats_derives_trend_fields() -> None:
    stats = build_hourly_trend_stats(make_hourly_klines(), make_15m_reversal_klines(), make_hourly_oi_history(), funding_rate=0.0002)

    assert stats is not None
    assert stats.ma7 > stats.ma25 > stats.ma99
    assert stats.price_change_6h > 0.08
    assert stats.price_change_12h > 0.20
    assert stats.volume_ratio > 1.5
    assert stats.oi_change_6h > 0.08
    assert stats.oi_change_12h > 0.15
    assert stats.bullish_1h_count_12 == 12
    assert stats.close_above_high_12h_previous
    assert stats.funding_rate == 0.0002


def make_pump_pullback_15m_klines() -> list[Kline]:
    rows: list[Kline] = []
    price = 1.0
    for index in range(120):
        open_price = price
        if 80 <= index <= 87:
            close = open_price * 1.025
            volume = 5000.0
        elif 88 <= index <= 110:
            close = open_price * 0.995
            volume = 1600.0
        elif index >= 117:
            close = open_price * 1.015
            volume = 5200.0 if index == 119 else 2600.0
        else:
            close = open_price * 1.0005
            volume = 1000.0
        high = max(open_price, close) * 1.003
        low = min(open_price, close) * 0.997
        rows.append(Kline(timestamp=index * 900_000, open=open_price, high=high, low=low, close=close, volume=volume))
        price = close
    return rows


def make_pump_pullback_1h_klines() -> list[Kline]:
    rows: list[Kline] = []
    price = 1.0
    for index in range(120):
        close = price * (1.003 if index < 100 else 1.006)
        rows.append(Kline(timestamp=index * 3_600_000, open=price, high=max(price, close) * 1.002, low=min(price, close) * 0.998, close=close, volume=2000.0))
        price = close
    return rows


def make_pump_pullback_5m_klines(latest_price: float) -> list[Kline]:
    rows: list[Kline] = []
    price = latest_price * 0.98
    for index in range(120):
        close = price * (1.001 if index < 118 else 1.006)
        rows.append(Kline(timestamp=index * 300_000, open=price, high=max(price, close) * 1.002, low=min(price, close) * 0.998, close=close, volume=800.0))
        price = close
    return rows


def make_pump_pullback_oi_history(length: int, step: int) -> list[OpenInterestPoint]:
    rows: list[OpenInterestPoint] = []
    value = 1000.0
    for index in range(length):
        if 80 <= index <= 87:
            value *= 1.016
        elif 88 <= index <= 103:
            value *= 0.997
        elif index >= length - 6:
            value *= 1.007
        else:
            value *= 1.001
        rows.append(OpenInterestPoint(timestamp=index * step, open_interest=value))
    return rows


def test_build_pump_pullback_stats_derives_first_pump_pullback_and_restart_fields() -> None:
    klines_15m = make_pump_pullback_15m_klines()
    latest_price = klines_15m[-1].close
    stats = build_pump_pullback_stats(
        klines_15m=klines_15m,
        klines_1h=make_pump_pullback_1h_klines(),
        klines_5m=make_pump_pullback_5m_klines(latest_price),
        oi_history_15m=make_pump_pullback_oi_history(120, 900_000),
        oi_history_5m=make_pump_pullback_oi_history(120, 300_000),
        config=DEFAULT_RADAR_RULE_CONFIG["pump_pullback_second_wave"],
    )

    assert stats is not None
    assert stats.has_first_pump is True
    assert stats.pump_change > 0.15
    assert stats.pullback_from_high > 0.04
    assert stats.retracement_ratio < 0.65
    assert stats.pullback_volume_ratio < 0.75
    assert stats.oi_drawdown_from_peak < 0.15
    assert stats.price_above_pump_start is True
    assert stats.volume_ratio_15m > 1.8
    assert stats.oi_change_30m > 0.03
    assert stats.range_high > stats.range_low
