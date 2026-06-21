"""Volume-price-OI resonance metric tests.
量价 OI 共振指标测试。
"""

from app.data.market_snapshot import build_resonance_stats
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
