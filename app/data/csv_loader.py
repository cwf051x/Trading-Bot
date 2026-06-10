"""CSV loading helpers for OHLCV market data.
OHLCV 行情 CSV 加载工具。
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.exchange.binance import Kline


def load_klines_csv(path: Path) -> list[Kline]:
    """Load `timestamp,open,high,low,close,volume` candles from CSV.
    从 CSV 读取 `timestamp,open,high,low,close,volume` 格式的 K 线。
    """

    rows: list[Kline] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
        for row in reader:
            rows.append(
                Kline(
                    timestamp=int(float(row["timestamp"])),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return rows
