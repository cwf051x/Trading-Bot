"""Telegram message formatter for market alerts.
行情雷达 Telegram 消息格式化。
"""

from __future__ import annotations

from app.alerts.signal_models import AlertLevel, AlertSignal, AlertType


ALERT_TYPE_TITLES = {
    AlertType.TOP_GAINER_MOMENTUM: "涨幅榜强势 / Top Gainer Momentum",
    AlertType.SHORT_TERM_SURGE: "短周期异动 / Short-Term Surge",
    AlertType.MULTI_TIMEFRAME_BREAKOUT: "多周期突破 / Multi-Timeframe Breakout",
    AlertType.STRONG_PULLBACK_WATCH: "强势回调观察 / Strong Pullback Watch",
    AlertType.PULLBACK_SECOND_LEG: "回调二启 / Pullback Second Leg",
    AlertType.HIGH_RISK_EXTENSION: "高位风险 / High-Risk Extension",
    AlertType.VOLUME_PRICE_OI_RESONANCE: "量价OI共振拉升 / Volume Price OI Resonance",
    AlertType.HOURLY_TREND_T1: "小时趋势启动 / Hourly Trend T1",
    AlertType.HOURLY_TREND_T2: "小时趋势加速 / Hourly Trend T2",
    AlertType.HOURLY_TREND_T3: "小时回踩接多观察 / Hourly Trend T3",
    AlertType.HOURLY_TREND_T4: "小时高位过热风险 / Hourly Trend T4",
    AlertType.PUMP_PULLBACK_P1: "首波后健康回调 / Pump Pullback P1",
    AlertType.PUMP_PULLBACK_P2: "二波启动预警 / Pump Pullback P2",
    AlertType.PUMP_PULLBACK_P3: "二波确认突破 / Pump Pullback P3",
    AlertType.PUMP_PULLBACK_P4: "二波失败风险 / Pump Pullback P4",
}


def format_pct(value: float) -> str:
    """Format decimal ratio as signed percentage.
    将小数比例格式化为带符号百分比。
    """

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

    prefix = "🚨" if alert.level == AlertLevel.A else "⚠️" if alert.level == AlertLevel.B else "👀"
    reasons = "\n".join(f"- {reason}" for reason in alert.reasons[:5])
    return (
        f"{prefix} {alert.level.value}级信号：{ALERT_TYPE_TITLES[alert.alert_type]}\n\n"
        f"币种：{alert.symbol}\n"
        f"现价：{format_price(alert.price)}\n"
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
