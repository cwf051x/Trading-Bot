"""Shared display helpers for alert surfaces.
行情提醒展示层共用工具。
"""

from __future__ import annotations

import re
from typing import Any

from app.alerts.signal_models import AlertType
from app.data.symbol_universe import symbol_base


ALERT_TYPE_LABELS = {
    AlertType.TOP_GAINER_MOMENTUM.value: "涨幅榜强势",
    AlertType.SHORT_TERM_SURGE.value: "短周期异动",
    AlertType.MULTI_TIMEFRAME_BREAKOUT.value: "多周期突破",
    AlertType.STRONG_PULLBACK_WATCH.value: "强势回调观察",
    AlertType.PULLBACK_SECOND_LEG.value: "回调二启",
    AlertType.HIGH_RISK_EXTENSION.value: "高位风险",
    AlertType.VOLUME_PRICE_OI_L0.value: "量价OI早期异动",
    AlertType.VOLUME_PRICE_OI_RESONANCE.value: "量价OI共振拉升",
    AlertType.HOURLY_TREND_T1.value: "小时趋势启动",
    AlertType.HOURLY_TREND_T2.value: "小时趋势加速",
    AlertType.HOURLY_TREND_T3.value: "小时回踩接多",
    AlertType.HOURLY_TREND_T4.value: "小时高位过热",
    AlertType.PUMP_PULLBACK_P1.value: "首波健康回调",
    AlertType.PUMP_PULLBACK_P2.value: "二波启动预警",
    AlertType.PUMP_PULLBACK_P3.value: "二波确认突破",
    AlertType.PUMP_PULLBACK_P4.value: "二波失败风险",
}

SIGNAL_CODE_LABELS = {
    AlertType.VOLUME_PRICE_OI_L0.value: "L0",
    AlertType.HOURLY_TREND_T1.value: "T1",
    AlertType.HOURLY_TREND_T2.value: "T2",
    AlertType.HOURLY_TREND_T3.value: "T3",
    AlertType.HOURLY_TREND_T4.value: "T4",
    AlertType.PUMP_PULLBACK_P1.value: "P1",
    AlertType.PUMP_PULLBACK_P2.value: "P2",
    AlertType.PUMP_PULLBACK_P3.value: "P3",
    AlertType.PUMP_PULLBACK_P4.value: "P4",
    AlertType.TOP_GAINER_MOMENTUM.value: "G",
    AlertType.SHORT_TERM_SURGE.value: "Sg",
    AlertType.MULTI_TIMEFRAME_BREAKOUT.value: "Bk",
    AlertType.STRONG_PULLBACK_WATCH.value: "Pb",
    AlertType.PULLBACK_SECOND_LEG.value: "P2",
    AlertType.HIGH_RISK_EXTENSION.value: "Risk",
}


def _alert_type_value(alert_type: AlertType | str) -> str:
    """Normalize enum and stored string values before display mapping.
    统一枚举和入库字符串，避免展示层因未知类型报错。
    """

    return alert_type.value if isinstance(alert_type, AlertType) else str(alert_type or "")


def display_symbol(symbol: str) -> str:
    """Return base asset for display only, e.g. BTC/USDT:USDT -> BTC."""

    if not symbol:
        return ""
    return symbol_base(symbol)


def display_alert_type(alert_type: AlertType | str) -> str:
    """Return Chinese-only alert type label."""

    value = _alert_type_value(alert_type)
    return ALERT_TYPE_LABELS.get(value, value)


def display_signal_code(alert_type: AlertType | str, metadata: dict | None = None) -> str:
    """Return compact signal code for Telegram first line."""

    value = _alert_type_value(alert_type)
    metadata = metadata or {}
    if value == AlertType.VOLUME_PRICE_OI_RESONANCE.value:
        # 共振信号的 L1/L2/L3 由规则 metadata 决定，展示层只读取不改写数据。
        level = metadata.get("resonance_level") or metadata.get("signal_stage")
        return str(level) if level else "L?"
    return SIGNAL_CODE_LABELS.get(value, value or "?")


def display_reason_cn(reason: str) -> str:
    """Return Chinese-only reason text from bilingual reason strings."""

    if not reason:
        return ""
    parts: list[str] = []
    for item in re.split(r"[;；]", reason):
        text = item.strip()
        if not text:
            continue
        if "/" in text:
            text = text.rsplit("/", 1)[-1].strip()
        parts.append(text)
    return "；".join(parts)


def display_reasons_cn(reasons: list[str], limit: int = 5) -> list[str]:
    """Return Chinese-only reason list."""

    return [text for text in (display_reason_cn(str(reason)) for reason in reasons[:limit]) if text]


def metadata_from_raw(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Extract alert metadata from raw payloads without assuming full schema.
    从 raw 中安全提取规则 metadata，供展示层识别 L/T/P 级别。
    """

    if not isinstance(raw, dict):
        return {}
    metadata = raw.get("metadata") or {}
    return dict(metadata) if isinstance(metadata, dict) else {}
