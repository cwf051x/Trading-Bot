"""Telegram digest for recent market alerts.
最近行情雷达提醒的 Telegram 热榜汇总。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from app.alerts.telegram_formatter import format_pct, format_price
from app.storage.sqlite import SQLiteStorage

DIGEST_STATE_SYMBOL = "__digest__"


@dataclass(frozen=True)
class AlertDigest:
    """Rendered digest text plus source rows.
    已渲染的热榜文本及其来源提醒行。
    """

    text: str
    items: list[dict[str, Any]]


def build_alert_digest(
    storage: SQLiteStorage,
    now_ms: int | None = None,
    lookback_seconds: int = 900,
    top_n: int = 10,
    min_score: int = 60,
) -> AlertDigest | None:
    """Build a ranked digest from recent market alerts.
    从最近窗口内的提醒构建按币种聚合的热榜。
    """

    now_ms = now_ms or int(time.time() * 1000)
    since_ms = now_ms - int(lookback_seconds * 1000)
    rows = [row for row in storage.get_market_alerts_since(since_ms, limit=1000) if int(row.get("score") or 0) >= min_score]
    if not rows:
        return None
    items = sorted((_build_digest_item(symbol, symbol_rows) for symbol, symbol_rows in _group_by_symbol(rows).items()), key=lambda item: item["digest_score"], reverse=True)
    items = items[: max(1, int(top_n))]
    if not items:
        return None
    return AlertDigest(text=_format_digest_text(items, since_ms, now_ms, top_n), items=items)


class AlertDigestManager:
    """Periodically send the alert digest without affecting per-alert storage.
    定时发送热榜汇总，不影响单条 alert 的入库与冷却逻辑。
    """

    def __init__(self, storage: SQLiteStorage, notifier: Any, settings: Any) -> None:
        self.storage = storage
        self.notifier = notifier
        self.settings = settings

    def maybe_send(self, now_ms: int | None = None) -> bool:
        """Send a digest when enabled and interval has elapsed.
        在启用且间隔到达时发送一条热榜。
        """

        if not bool(getattr(self.settings, "alert_digest_enabled", True)):
            return False
        now_ms = now_ms or int(time.time() * 1000)
        interval_ms = int(getattr(self.settings, "alert_digest_interval_seconds", 900)) * 1000
        last_digest_at = self._last_digest_at()
        if last_digest_at and now_ms - last_digest_at < interval_ms:
            return False
        digest = build_alert_digest(
            self.storage,
            now_ms=now_ms,
            lookback_seconds=int(getattr(self.settings, "alert_digest_lookback_seconds", 900)),
            top_n=int(getattr(self.settings, "alert_digest_top_n", 10)),
            min_score=int(getattr(self.settings, "alert_digest_min_score", 60)),
        )
        if digest is None:
            return False
        if not self.storage.claim_alert_digest(now_ms, interval_ms):
            return False
        sent = bool(self.notifier.send_message(digest.text))
        self._record_digest_at(now_ms, sent)
        return sent

    def _last_digest_at(self) -> int:
        state = self.storage.get_alert_state(DIGEST_STATE_SYMBOL)
        if not state:
            return 0
        if isinstance(state.get("metadata_json"), dict):
            return int(state["metadata_json"].get("last_digest_at") or 0)
        try:
            metadata = json.loads(str(state.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            return 0
        return int(metadata.get("last_digest_at") or 0)

    def _record_digest_at(self, timestamp_ms: int, sent: bool) -> None:
        # 失败也记录时间，避免 Telegram 异常时每轮重复刷日志和重试。
        self.storage.upsert_alert_state(
            {
                "symbol": DIGEST_STATE_SYMBOL,
                "state": "digest_sent" if sent else "digest_attempted",
                "last_alert_type": "ALERT_DIGEST",
                "last_alert_score": 0,
                "last_alert_price": 0.0,
                "last_alert_at": timestamp_ms,
                "watch_high": None,
                "watch_low": None,
                "support_price": None,
                "invalidation_price": None,
                "metadata_json": {"last_digest_at": timestamp_ms, "sent": sent},
            }
        )


def _group_by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["symbol"]), []).append(row)
    return grouped


def _build_digest_item(symbol: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: (int(row.get("timestamp") or 0), int(row.get("id") or 0)))
    first = rows[0]
    latest = rows[-1]
    start_price = float(first.get("price") or 0.0)
    latest_price = float(latest.get("price") or 0.0)
    window_change = (latest_price / start_price - 1) if start_price > 0 else 0.0
    max_score = max(int(row.get("score") or 0) for row in rows)
    max_volume_ratio = max(_metric(row, "volume_ratio", float(row.get("volume_ratio") or 0.0)) for row in rows)
    max_oi_change = max(_metric(row, "oi_change_15m", _metric(row, "oi_change_30m", _metric(row, "oi_change_6h", 0.0))) for row in rows)
    quote_volume_rank = min((_metric(row, "quote_volume_rank", _metric(row, "rank_24h", 9999)) for row in rows), default=9999)
    risk_tags = _risk_tags(rows)
    multi_family_bonus = max(0, len({_family_and_stage(row)[0] for row in rows}) - 1) * 8
    upgrade_bonus = _upgrade_bonus(rows)
    digest_score = max_score + min(20, len(rows) * 2) + max(0.0, window_change) * 100 + multi_family_bonus + upgrade_bonus
    if risk_tags:
        digest_score -= 10
    return {
        "symbol": symbol,
        "short_symbol": _short_symbol(symbol),
        "start_price": start_price,
        "latest_price": latest_price,
        "window_change": window_change,
        "signal_text": _format_signal_text(rows),
        "count": len(rows),
        "max_volume_ratio": max_volume_ratio,
        "max_oi_change": max_oi_change,
        "quote_volume_rank": int(quote_volume_rank) if quote_volume_rank != 9999 else None,
        "risk_tags": risk_tags,
        "status_text": _status_text(rows, window_change, risk_tags),
        "digest_score": digest_score,
    }


def _format_digest_text(items: list[dict[str, Any]], since_ms: int, now_ms: int, top_n: int) -> str:
    lines = [f"🔥 15分钟雷达热榜 TOP{top_n}", f"时间：{_format_hhmm(since_ms)} - {_format_hhmm(now_ms)}", ""]
    for index, item in enumerate(items, start=1):
        rank = f"#{item['quote_volume_rank']}" if item["quote_volume_rank"] is not None else "-"
        lines.extend(
            [
                f"{index}. {item['short_symbol']}  {format_pct(item['window_change'])}（{format_price(item['start_price'])} ➜ {format_price(item['latest_price'])}）",
                f"   信号：{item['signal_text']}，共{item['count']}次",
                f"   共振：量比 {item['max_volume_ratio']:.2f}x｜OI {format_pct(item['max_oi_change'])}｜成交额排名 {rank}",
                f"   状态：{item['status_text']}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _format_signal_text(rows: list[dict[str, Any]]) -> str:
    family_order: list[str] = []
    family_stages: dict[str, list[str]] = {}
    for row in rows:
        family, stage = _family_and_stage(row)
        if family not in family_stages:
            family_order.append(family)
            family_stages[family] = []
        family_stages[family].append(stage)
    if len(family_order) == 1 and family_order[0] == "volume_price_oi":
        return _compress_stages(family_stages["volume_price_oi"])
    parts = []
    for family in family_order:
        label = {"volume_price_oi": "量价OI", "hourly_trend": "小时趋势", "pump_pullback_second_wave": "二波"}.get(family, "其他")
        parts.append(f"{label} {_compress_stages(family_stages[family])}")
    return "；".join(parts)


def _compress_stages(stages: list[str]) -> str:
    segments: list[str] = []
    for stage in stages:
        if segments and segments[-1].startswith(f"{stage}×"):
            count = int(segments[-1].split("×", 1)[1]) + 1
            segments[-1] = f"{stage}×{count}"
        else:
            segments.append(f"{stage}×1")
    return " → ".join(segments)


def _family_and_stage(row: dict[str, Any]) -> tuple[str, str]:
    metadata = _metadata(row)
    alert_type = str(row.get("alert_type") or "")
    family = str(metadata.get("rule_family") or "")
    if not family:
        if alert_type.startswith("HOURLY_TREND_"):
            family = "hourly_trend"
        elif alert_type.startswith("PUMP_PULLBACK_"):
            family = "pump_pullback_second_wave"
        elif alert_type.startswith("VOLUME_PRICE_OI"):
            family = "volume_price_oi"
        else:
            family = "other"
    stage = str(metadata.get("signal_stage") or metadata.get("resonance_level") or metadata.get("trend_level") or metadata.get("pump_pullback_level") or alert_type.rsplit("_", 1)[-1])
    return family, stage


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_json") or "{}"
    if isinstance(raw, dict):
        return dict(raw.get("metadata") or {})
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return dict(parsed.get("metadata") or {})


def _metric(row: dict[str, Any], key: str, default: float) -> float:
    metadata = _metadata(row)
    value = metadata.get(key)
    if value is None:
        raw = row.get("raw_json") or "{}"
        try:
            parsed = raw if isinstance(raw, dict) else json.loads(str(raw))
        except json.JSONDecodeError:
            parsed = {}
        value = (parsed.get("metrics") or {}).get(key)
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _risk_tags(rows: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    for row in rows:
        metadata = _metadata(row)
        for tag in metadata.get("risk_tags") or []:
            if tag not in tags:
                tags.append(str(tag))
        if str(row.get("alert_type") or "").endswith(("L3", "T4", "P4")) and "高位过热" not in tags:
            tags.append("高位过热")
    return tags


def _status_text(rows: list[dict[str, Any]], window_change: float, risk_tags: list[str]) -> str:
    stages = [_family_and_stage(row)[1] for row in rows]
    if any(stage in {"L3", "T4", "P4"} for stage in stages) or risk_tags:
        return "高位过热｜禁止追高｜等风险释放"
    if any(stage in {"L2", "T2", "P3"} for stage in stages):
        return "主升确认｜未过热｜重点观察 5m 回踩"
    if any(stage in {"L1", "T1", "P2"} for stage in stages):
        return "早期启动｜未过热｜观察能否升级 L2"
    if window_change > 0.10:
        return "启动加速｜偏高｜只等回踩，不追"
    return "早期启动｜未过热｜观察能否升级 L2"


def _upgrade_bonus(rows: list[dict[str, Any]]) -> int:
    stage_rank = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "T1": 1, "T2": 2, "T3": 3, "T4": 4, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
    ranks = [stage_rank.get(_family_and_stage(row)[1], 0) for row in rows]
    return 8 if ranks and max(ranks) > min(ranks) else 0


def _short_symbol(symbol: str) -> str:
    return symbol.split("/", 1)[0]


def _format_hhmm(timestamp_ms: int) -> str:
    return time.strftime("%H:%M", time.localtime(timestamp_ms / 1000))
