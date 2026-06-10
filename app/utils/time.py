"""Time helpers.
时间工具函数。
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_ms() -> int:
    """Return current UTC timestamp in milliseconds.
    返回当前 UTC 毫秒时间戳。
    """

    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)
