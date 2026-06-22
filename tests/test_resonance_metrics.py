"""Volume-price-OI resonance metric tests.
量价 OI 共振指标测试。
"""

from app.data.market_snapshot import build_hourly_trend_stats, build_resonance_stats
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
