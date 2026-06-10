"""Smoke-test alert radar formatting without real network or trading.
在不访问真实网络、不交易的情况下冒烟测试行情雷达格式。
"""

from __future__ import annotations

import time
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.alerts.signal_models import AlertLevel, AlertSignal, AlertType
from app.alerts.telegram_formatter import format_alert_message


def main() -> None:
    """Print a sample alert message for local inspection.
    打印示例提醒消息用于本地检查。
    """

    alert = AlertSignal(
        timestamp=int(time.time() * 1000),
        symbol="ALLO/USDT:USDT",
        alert_type=AlertType.PULLBACK_SECOND_LEG,
        level=AlertLevel.A,
        score=88,
        price=0.1842,
        price_change_3m=0.012,
        price_change_5m=0.021,
        price_change_15m=0.038,
        price_change_1h=0.095,
        price_change_24h=0.386,
        volume_ratio=2.4,
        btc_15m_change=-0.001,
        reasons=[
            "24h gainer rank top 20 / 24小时涨幅榜前20",
            "pullback volume contraction / 回调缩量",
            "pullback second leg restart / 回调后二次启动",
            "BTC 15m is stable / BTC 15分钟未急跌",
        ],
        suggested_action="回调二启，观察5m收稳后的低风险入场区",
        invalidation_price=0.1720,
        target_1=0.1950,
        target_2=0.2100,
    )
    print(format_alert_message(alert))


if __name__ == "__main__":
    main()
