"""Helpers for removing still-forming candles from market data.
过滤未收盘 K 线的公共工具。
"""

from __future__ import annotations

import time

from app.exchange.binance import Kline


def timeframe_seconds(timeframe: str) -> int:
    """Return seconds for common Binance interval strings.
    返回常见 Binance K 线周期对应秒数。
    """

    if len(timeframe) < 2:
        return 0
    try:
        value = int(timeframe[:-1])
    except ValueError:
        return 0
    unit = timeframe[-1]
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 60 * 60
    if unit == "d":
        return value * 24 * 60 * 60
    return 0


def closed_klines(klines: list[Kline], timeframe: str, now_ms: int | None = None) -> list[Kline]:
    """Drop the latest candle when its close time is still in the future.
    当最后一根 K 线尚未收盘时丢弃，避免 paper/replay/radar 使用 repaint 数据。
    """

    if not klines:
        return []
    timeframe_ms = timeframe_seconds(timeframe) * 1000
    if timeframe_ms <= 0:
        return klines
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if klines[-1].timestamp + timeframe_ms > current_ms:
        return klines[:-1]
    return klines
