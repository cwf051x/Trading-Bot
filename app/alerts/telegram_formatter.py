"""Telegram message formatter for market alerts.
行情雷达 Telegram 消息格式化。
"""

from __future__ import annotations

from app.alerts.display import display_alert_type, display_reasons_cn, display_signal_code, display_symbol, metadata_from_raw
from app.alerts.signal_models import AlertSignal


def format_pct(value: float | None) -> str:
    """Format decimal ratio as signed percentage.
    将小数比例格式化为带符号百分比。
    """

    if value is None:
        return "-"
    return f"{value * 100:+.2f}%"


def format_price(value: float | None) -> str:
    """Format price with compact precision.
    用紧凑精度格式化价格。
    """

    if value is None:
        return "-"
    if value >= 100:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def format_alert_message(alert: AlertSignal) -> str:
    """Return a concise Telegram alert message.
    返回精简的 Telegram 提醒消息。
    """

    metadata = metadata_from_raw(alert.raw)
    first_line = "｜".join(
        [
            display_symbol(alert.symbol),
            f"{alert.level.value}级",
            display_signal_code(alert.alert_type, metadata),
            format_price(alert.price),
            format_pct(alert.price_change_1h),
        ]
    )
    reasons = "\n".join(f"- {reason}" for reason in display_reasons_cn(alert.reasons, limit=5)) or "-"
    return (
        f"{first_line}\n\n"
        f"{display_alert_type(alert.alert_type)}\n\n"
        f"评分：{alert.score}/100\n"
        f"建议：{alert.suggested_action}\n\n"
        f"短线表现：\n"
        f"3m：{format_pct(alert.price_change_3m)}  5m：{format_pct(alert.price_change_5m)}\n"
        f"15m：{format_pct(alert.price_change_15m)}  1h：{format_pct(alert.price_change_1h)}\n"
        f"24h：{format_pct(alert.price_change_24h)}  BTC15m：{format_pct(alert.btc_15m_change)}\n"
        f"量比：{alert.volume_ratio:.2f}x\n\n"
        f"核心理由：\n{reasons}\n\n"
        f"参考计划：\n"
        f"- 失效位：{format_price(alert.invalidation_price)}\n"
        f"- 第一目标：{format_price(alert.target_1)}\n"
        f"- 第二目标：{format_price(alert.target_2)}\n\n"
        f"风险提示：信号仅用于行情提醒，不是交易指令；若BTC突然跳水或5m放量冲高回落，暂停追入。"
    )
