"""Strategy tests.
策略测试。
"""

from __future__ import annotations

from app.exchange.binance import Kline
from app.strategies.momentum_oi import MomentumOIStrategy


def candle(index: int, close: float, volume: float = 100.0, high: float | None = None, low: float | None = None) -> Kline:
    return Kline(timestamp=index, open=close, high=high or close, low=low or close, close=close, volume=volume)


def test_momentum_strategy_generates_long_on_breakout_and_volume() -> None:
    klines = [candle(i, 100 + i * 0.1, 100, high=101) for i in range(21)]
    klines.append(candle(22, 105, 300, high=105))
    btc = [candle(1, 100), candle(2, 99)]
    strategy = MomentumOIStrategy()

    signal = strategy.generate_signal({"symbol": "ETH/USDT:USDT", "klines": klines, "btc_klines": btc})

    assert signal.side == "long"
    assert signal.stop_loss is not None
    assert signal.take_profit is not None


def test_momentum_strategy_blocks_when_btc_dumps() -> None:
    klines = [candle(i, 100 + i * 0.1, 100, high=101) for i in range(21)]
    klines.append(candle(22, 105, 300, high=105))
    btc = [candle(1, 100), candle(2, 95)]
    strategy = MomentumOIStrategy(btc_drop_threshold=0.03)

    signal = strategy.generate_signal({"symbol": "ETH/USDT:USDT", "klines": klines, "btc_klines": btc})

    assert signal.side == "none"
