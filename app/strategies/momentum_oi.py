"""Example momentum strategy with BTC market filter.
带 BTC 大盘过滤条件的动量策略示例。
"""

from __future__ import annotations

from typing import Any

from app.exchange.binance import Kline
from app.strategies.base import BaseStrategy, Signal
from app.utils.time import utc_ms


class MomentumOIStrategy(BaseStrategy):
    """Long-only breakout strategy with volume and BTC drawdown filters.
    只做多的突破策略，包含成交量放大和 BTC 回撤过滤。
    """

    name = "MomentumOIStrategy"

    def __init__(
        self,
        breakout_window: int = 20,
        volume_window: int = 20,
        volume_multiplier: float = 1.5,
        btc_drop_threshold: float = 0.03,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
    ) -> None:
        self.breakout_window = breakout_window
        self.volume_window = volume_window
        self.volume_multiplier = volume_multiplier
        self.btc_drop_threshold = btc_drop_threshold
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        """Generate long signal when price breaks out with expanded volume.
        当价格突破且成交量放大时生成做多信号。
        """

        symbol = str(market_data.get("symbol", "UNKNOWN"))
        klines: list[Kline] = list(market_data.get("klines", []))
        btc_klines: list[Kline] = list(market_data.get("btc_klines", []))
        timestamp = klines[-1].timestamp if klines else utc_ms()

        if len(klines) <= max(self.breakout_window, self.volume_window):
            return self._none(symbol, "not enough candles", timestamp)

        if self._btc_is_dumping(btc_klines):
            return self._none(symbol, "BTC 15m drawdown filter blocked long", timestamp)

        current = klines[-1]
        prior = klines[-self.breakout_window - 1 : -1]
        volume_prior = klines[-self.volume_window - 1 : -1]
        prior_high = max(candle.high for candle in prior)
        avg_volume = sum(candle.volume for candle in volume_prior) / len(volume_prior)

        price_breakout = current.close > prior_high
        volume_expanded = current.volume > avg_volume * self.volume_multiplier
        if not price_breakout or not volume_expanded:
            return self._none(symbol, "breakout or volume condition not met", timestamp)

        entry = current.close
        return Signal(
            symbol=symbol,
            side="long",
            confidence=0.7,
            entry_price=entry,
            stop_loss=entry * (1 - self.stop_loss_pct),
            take_profit=entry * (1 + self.take_profit_pct),
            reason=f"close {entry:.4f} broke {prior_high:.4f} with volume expansion",
            timestamp=timestamp,
        )

    def _btc_is_dumping(self, btc_klines: list[Kline]) -> bool:
        if len(btc_klines) < 2:
            return False
        previous = btc_klines[-2].close
        current = btc_klines[-1].close
        if previous <= 0:
            return False
        return (previous - current) / previous >= self.btc_drop_threshold

    @staticmethod
    def _none(symbol: str, reason: str, timestamp: int) -> Signal:
        return Signal(symbol=symbol, side="none", confidence=0.0, entry_price=None, stop_loss=None, take_profit=None, reason=reason, timestamp=timestamp)
