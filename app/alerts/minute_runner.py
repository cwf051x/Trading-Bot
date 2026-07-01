"""Stateful Minute Runner Radar pool, digest, and email gating.
分钟级单边上涨池、统一榜单和邮件限频。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import subprocess
import time
from typing import Any, Iterable

from app.alerts.display import display_symbol
from app.alerts.rule_config import load_radar_rule_config
from app.alerts.signal_models import MarketMetrics, MinuteRunnerState, MinuteRunnerStats
from app.alerts.telegram_formatter import format_pct, format_price
from app.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

MINUTE_RUNNER_DIGEST_SYMBOL = "__minute_runner_digest__"
MINUTE_RUNNER_EMAIL_SYMBOL = "__minute_runner_email__"


@dataclass(frozen=True)
class MinuteRunnerDigest:
    """Rendered Minute Runner digest and source rows.
    单边上涨池榜文案及来源行。
    """

    text: str
    main: list[dict[str, Any]]
    risks: list[dict[str, Any]]


@dataclass(frozen=True)
class EmailGateResult:
    """Decision for a Minute Runner email attempt.
    单边上涨邮件发送限频决策。
    """

    allowed: bool
    reason: str


@dataclass(frozen=True)
class EmailSendResult:
    """Result returned by the email adapter.
    邮件适配器返回的发送结果。
    """

    sent: bool
    reason: str


class MinuteRunnerEmailSender:
    """Minimal email adapter, disabled unless settings enable it.
    最小邮件适配器；只有配置开启时才会被调用。
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def send(self, subject: str, body: str) -> EmailSendResult:
        """Send email through the configured provider.
        通过配置的邮件 provider 发送提醒。
        """

        if not bool(getattr(self.settings, "minute_runner_email_enabled", False)):
            return EmailSendResult(False, "email_disabled")
        to_address = str(getattr(self.settings, "minute_runner_email_to", "") or "").strip()
        if not to_address:
            return EmailSendResult(False, "missing_email_to")
        provider = str(getattr(self.settings, "minute_runner_email_provider", "qq_agent") or "qq_agent")
        if provider != "qq_agent":
            return EmailSendResult(False, f"unsupported_provider:{provider}")
        command = ["agently-cli", "mail", "send", "--to", to_address, "--subject", subject, "--body", body]
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            return EmailSendResult(False, "agently_cli_not_found")
        except subprocess.TimeoutExpired:
            return EmailSendResult(False, "email_send_timeout")
        if completed.returncode != 0:
            reason = (completed.stderr or completed.stdout or "email_send_failed").strip()[:200]
            return EmailSendResult(False, reason)
        return EmailSendResult(True, "sent")


class MinuteRunnerEmailGate:
    """Persisted email limiter for M2E signals.
    M2E 邮件的持久化限频器。
    """

    def __init__(self, storage: SQLiteStorage, settings: Any, now_ms: int | None = None) -> None:
        self.storage = storage
        self.settings = settings
        self.now_ms = now_ms or int(time.time() * 1000)

    def claim(self, symbol: str, trend_id: str) -> EmailGateResult:
        """Claim one symbol/trend email slot if limits allow.
        在符号趋势和全局限频允许时占用邮件发送名额。
        """

        if not bool(getattr(self.settings, "minute_runner_email_enabled", False)):
            self._record_skip(symbol, trend_id, "email_disabled")
            return EmailGateResult(False, "email_disabled")
        self._ensure_symbol_row(symbol, trend_id)
        row = self.storage.get_minute_runner_state(symbol)
        if row and row.get("email_sent_for_trend_id") == trend_id:
            self._record_skip(symbol, trend_id, "already_sent_for_trend")
            return EmailGateResult(False, "already_sent_for_trend")

        state = self.storage.get_alert_state(MINUTE_RUNNER_EMAIL_SYMBOL) or {}
        metadata = state.get("metadata_json") if isinstance(state.get("metadata_json"), dict) else {}
        sent_times = [int(item) for item in metadata.get("sent_times", []) if item]
        cooldown_ms = int(getattr(self.settings, "minute_runner_email_global_cooldown_seconds", 1800)) * 1000
        max_per_hour = int(getattr(self.settings, "minute_runner_email_max_per_hour", 2))
        last_sent_at = max(sent_times) if sent_times else 0
        if last_sent_at and self.now_ms - last_sent_at < cooldown_ms:
            self._record_skip(symbol, trend_id, "global_cooldown")
            return EmailGateResult(False, "global_cooldown")
        recent_hour = [item for item in sent_times if self.now_ms - item < 3_600_000]
        if len(recent_hour) >= max_per_hour:
            self._record_skip(symbol, trend_id, "global_hourly_limit")
            return EmailGateResult(False, "global_hourly_limit")
        updated_times = [*recent_hour, self.now_ms]
        self.storage.upsert_alert_state(
            {
                "symbol": MINUTE_RUNNER_EMAIL_SYMBOL,
                "state": "minute_runner_email_claimed",
                "last_alert_type": "MINUTE_RUNNER_EMAIL",
                "last_alert_score": 0,
                "last_alert_price": 0.0,
                "last_alert_at": self.now_ms,
                "watch_high": None,
                "watch_low": None,
                "support_price": None,
                "invalidation_price": None,
                "metadata_json": {"sent_times": updated_times, "last_sent_at": self.now_ms},
            }
        )
        self.storage.update_minute_runner_email_status(
            symbol,
            last_email_sent_at=self.now_ms,
            email_sent_for_trend_id=trend_id,
            email_send_status="claimed",
            email_skip_reason=None,
        )
        return EmailGateResult(True, "claimed")

    def _ensure_symbol_row(self, symbol: str, trend_id: str) -> None:
        if self.storage.get_minute_runner_state(symbol) is not None:
            return
        self.storage.upsert_minute_runner_state(
            {
                "symbol": symbol,
                "state": MinuteRunnerState.EARLY_CONFIRMED.value,
                "runner_score": 0.0,
                "ranking_score": 0.0,
                "trend_id": trend_id,
                "trend_age_minutes": 0,
                "last_score_update_at": self.now_ms,
                "metadata_json": {},
            }
        )

    def _record_skip(self, symbol: str, trend_id: str, reason: str) -> None:
        self._ensure_symbol_row(symbol, trend_id)
        self.storage.update_minute_runner_email_status(
            symbol,
            email_send_status="skipped",
            email_skip_reason=reason,
        )


class MinuteRunnerManager:
    """Update stateful Minute Runner pool after each radar scan.
    每轮雷达扫描后更新单边上涨池。
    """

    def __init__(self, storage: SQLiteStorage, notifier: Any, settings: Any, email_sender: Any | None = None) -> None:
        self.storage = storage
        self.notifier = notifier
        self.settings = settings
        if not hasattr(self.settings, "radar_rule_config"):
            object.__setattr__(self.settings, "radar_rule_config", load_radar_rule_config())
        self.email_sender = email_sender or MinuteRunnerEmailSender(settings)

    def process(self, rows: Iterable[MarketMetrics | tuple[str, float, MinuteRunnerStats | None]], now_ms: int | None = None) -> None:
        """Persist stats, maybe send digest, and maybe send M2E email.
        持久化池状态，并按限频发送池榜和 M2E 邮件。
        """

        if not bool(getattr(self.settings, "minute_runner_enabled", True)):
            return
        now_ms = now_ms or int(time.time() * 1000)
        changed = False
        entries = list(self._normalize_rows(rows))
        for symbol, price, stats in entries:
            if stats is None:
                continue
            previous = self.storage.get_minute_runner_state(symbol)
            changed = self._upsert(symbol, price, stats, previous, now_ms) or changed
        self._maybe_send_emails(entries, now_ms)
        self._maybe_send_digest(changed=changed, now_ms=now_ms)

    def _normalize_rows(self, rows: Iterable[MarketMetrics | tuple[str, float, MinuteRunnerStats | None]]) -> Iterable[tuple[str, float, MinuteRunnerStats | None]]:
        for row in rows:
            if isinstance(row, tuple):
                yield row
            else:
                yield row.symbol, row.price, row.minute_runner

    def _upsert(self, symbol: str, price: float, stats: MinuteRunnerStats, previous: dict[str, Any] | None, now_ms: int) -> bool:
        previous_state = str(previous.get("state")) if previous else ""
        state_changed = previous_state != stats.state
        trend_started_at = _trend_started_at(stats)
        first_pool_at = now_ms if stats.state in {MinuteRunnerState.POOL.value, MinuteRunnerState.EARLY_CONFIRMED.value, MinuteRunnerState.MATURE_CONFIRMED.value} else None
        confirmed_at = now_ms if stats.state in {MinuteRunnerState.EARLY_CONFIRMED.value, MinuteRunnerState.MATURE_CONFIRMED.value} else None
        # entry/highest 只服务池榜展示，不参与任何下单或仓位计算。
        self.storage.upsert_minute_runner_state(
            {
                "symbol": symbol,
                "state": stats.state,
                "runner_score": round(stats.runner_score, 2),
                "ranking_score": round(stats.ranking_score, 2),
                "trend_id": stats.trend_id,
                "trend_started_at": trend_started_at,
                "trend_age_minutes": stats.trend_age_minutes,
                "first_pool_at": first_pool_at,
                "confirmed_at": confirmed_at,
                "last_state_change_at": now_ms if state_changed else (previous or {}).get("last_state_change_at"),
                "last_score_update_at": now_ms,
                "last_price": price,
                "entry_price": price if previous is None else previous.get("entry_price"),
                "highest_price": max(price, float((previous or {}).get("highest_price") or 0.0)),
                "pullback_from_high": stats.pullback_from_high,
                "price_change_1h": stats.price_change_1h,
                "volume_ratio_15m": stats.volume_ratio_15m,
                "oi_change_30m": stats.oi_change_30m,
                "oi_change_45m": stats.oi_change_45m,
                "oi_change_1h": stats.oi_change_1h,
                "distance_to_ma25_5m": stats.distance_to_ma25_5m,
                "risk_tags_json": stats.risk_tags,
                "reasons_json": stats.reasons,
                "metadata_json": {
                    "email_should_send": stats.email_should_send,
                    "broken_reason": stats.broken_reason,
                    "volume_ratio_5m": stats.volume_ratio_5m,
                    "price_change_15m": stats.price_change_15m,
                    "price_change_30m": stats.price_change_30m,
                },
            }
        )
        score_delta = abs(float((previous or {}).get("runner_score") or 0.0) - stats.runner_score)
        return state_changed or score_delta >= 3

    def _maybe_send_digest(self, *, changed: bool, now_ms: int) -> None:
        digest_config = self.settings.radar_rule_config.get("minute_runner", {}).get("telegram_digest", {})
        if not bool(getattr(self.settings, "minute_runner_telegram_enabled", True)) or not bool(digest_config.get("enabled", True)):
            return
        interval_ms = int(getattr(self.settings, "minute_runner_digest_interval_seconds", digest_config.get("interval_seconds", 300))) * 1000
        no_change_interval_ms = int(getattr(self.settings, "minute_runner_digest_no_change_interval_seconds", digest_config.get("no_change_interval_seconds", 900))) * 1000
        state = self.storage.get_alert_state(MINUTE_RUNNER_DIGEST_SYMBOL) or {}
        metadata = state.get("metadata_json") if isinstance(state.get("metadata_json"), dict) else {}
        last_digest_at = int(metadata.get("last_digest_at") or 0)
        required_interval = interval_ms if changed else no_change_interval_ms
        if last_digest_at and now_ms - last_digest_at < required_interval:
            return
        digest = build_minute_runner_digest(
            self.storage,
            now_ms=now_ms,
            top_n=int(getattr(self.settings, "minute_runner_digest_top_n", digest_config.get("top_n", 8))),
            min_score=float(getattr(self.settings, "minute_runner_min_score_to_show", digest_config.get("min_score_to_show", 72))),
        )
        if digest is None:
            return
        sent = bool(self.notifier.send_message(digest.text))
        # 发送失败也记录时间，避免 Telegram 异常导致每轮重复刷屏重试。
        self.storage.upsert_alert_state(
            {
                "symbol": MINUTE_RUNNER_DIGEST_SYMBOL,
                "state": "minute_runner_digest_sent" if sent else "minute_runner_digest_attempted",
                "last_alert_type": "MINUTE_RUNNER_DIGEST",
                "last_alert_score": 0,
                "last_alert_price": 0.0,
                "last_alert_at": now_ms,
                "watch_high": None,
                "watch_low": None,
                "support_price": None,
                "invalidation_price": None,
                "metadata_json": {"last_digest_at": now_ms, "sent": sent},
            }
        )

    def _maybe_send_emails(self, entries: list[tuple[str, float, MinuteRunnerStats | None]], now_ms: int) -> None:
        if not bool(getattr(self.settings, "minute_runner_email_enabled", False)):
            return
        ranked = {row["symbol"]: index for index, row in enumerate(self.storage.list_minute_runner_states(limit=100), start=1)}
        min_score = float(getattr(self.settings, "minute_runner_email_min_score", 88))
        top_rank = int(getattr(self.settings, "minute_runner_email_top_rank", 5))
        gate = MinuteRunnerEmailGate(self.storage, self.settings, now_ms=now_ms)
        for symbol, price, stats in entries:
            if stats is None or not stats.email_should_send:
                continue
            rank = ranked.get(symbol, 999)
            if rank > top_rank and stats.runner_score < min_score:
                self.storage.update_minute_runner_email_status(symbol, email_send_status="skipped", email_skip_reason="rank_and_score_below_email_gate")
                continue
            claim = gate.claim(symbol, stats.trend_id)
            if not claim.allowed:
                continue
            subject = _format_email_subject(symbol, stats, price)
            body = _format_email_body(symbol, stats, price)
            result = self.email_sender.send(subject, body)
            self.storage.update_minute_runner_email_status(
                symbol,
                last_email_sent_at=now_ms if result.sent else None,
                email_sent_for_trend_id=stats.trend_id if result.sent else None,
                email_send_status="sent" if result.sent else "failed",
                email_skip_reason=None if result.sent else result.reason,
            )


def build_minute_runner_digest(storage: SQLiteStorage, now_ms: int | None = None, top_n: int = 8, min_score: float = 72) -> MinuteRunnerDigest | None:
    """Build the Telegram Minute Runner pool board.
    构建 Telegram 单边上涨池榜单。
    """

    rows = storage.list_minute_runner_states(limit=200)
    main = [
        row
        for row in rows
        if row.get("state") in {MinuteRunnerState.EARLY_CONFIRMED.value, MinuteRunnerState.MATURE_CONFIRMED.value, MinuteRunnerState.POOL.value}
        and float(row.get("runner_score") or 0.0) >= min_score
    ]
    risks = [row for row in rows if row.get("state") == MinuteRunnerState.OVERHEAT.value][:3]
    main = sorted(main, key=lambda row: (_state_priority(str(row.get("state"))), float(row.get("ranking_score") or 0.0), float(row.get("runner_score") or 0.0)), reverse=True)[: max(1, int(top_n))]
    if not main and not risks:
        return None
    lines = ["【单边上涨池｜5m更新】", ""]
    for index, row in enumerate(main, start=1):
        lines.extend(
            [
                f"{index}. {display_symbol(str(row['symbol']))}｜{int(round(float(row.get('runner_score') or 0)))}｜{row['state']}｜{format_price(row.get('last_price'))}｜1h {format_pct(row.get('price_change_1h'))}",
                f"   OI30m {format_pct(row.get('oi_change_30m'))}｜Vol15m {float(row.get('volume_ratio_15m') or 0.0):.1f}x｜趋势 {int(row.get('trend_age_minutes') or 0)}m｜{_state_label(str(row.get('state')))}",
                "",
            ]
        )
    if risks:
        lines.append("风险：")
        for row in risks:
            tags = row.get("risk_tags_json") or []
            reason = "｜".join(str(tag) for tag in tags[:2]) if tags else "防追高"
            lines.append(
                f"- {display_symbol(str(row['symbol']))}｜M3过热｜1h {format_pct(row.get('price_change_1h'))}｜距MA25 {format_pct(row.get('distance_to_ma25_5m'))}｜{reason}"
            )
    return MinuteRunnerDigest(text="\n".join(lines).strip(), main=main, risks=risks)


def _state_priority(state: str) -> int:
    return {
        MinuteRunnerState.EARLY_CONFIRMED.value: 4,
        MinuteRunnerState.MATURE_CONFIRMED.value: 3,
        MinuteRunnerState.POOL.value: 2,
        MinuteRunnerState.SPARK.value: 1,
    }.get(state, 0)


def _state_label(state: str) -> str:
    return {
        MinuteRunnerState.EARLY_CONFIRMED.value: "早期确信",
        MinuteRunnerState.MATURE_CONFIRMED.value: "成熟强趋势",
        MinuteRunnerState.POOL.value: "单边池",
        MinuteRunnerState.OVERHEAT.value: "过热防追高",
        MinuteRunnerState.BROKEN.value: "趋势破坏",
    }.get(state, "启动观察")


def _trend_started_at(stats: MinuteRunnerStats) -> int | None:
    try:
        return int(stats.trend_id.removeprefix("trend-"))
    except ValueError:
        return None


def _format_email_subject(symbol: str, stats: MinuteRunnerStats, price: float) -> str:
    return f"【单边确信】{display_symbol(symbol)}｜{int(round(stats.runner_score))}分｜1h {format_pct(stats.price_change_1h)}｜OI30m {format_pct(stats.oi_change_30m)}"


def _format_email_body(symbol: str, stats: MinuteRunnerStats, price: float) -> str:
    reasons = stats.reasons or ["5m结构持续上抬", "15m确认周期站稳", "OI与成交量同步配合", "当前未进入过热状态"]
    reason_lines = "\n".join(f"{index}. {reason}" for index, reason in enumerate(reasons, start=1))
    return (
        f"币种：{display_symbol(symbol)}\n"
        f"状态：早期确信池 M2E\n"
        f"价格：{format_price(price)}\n"
        f"趋势年龄：{stats.trend_age_minutes}分钟\n"
        f"Runner Score：{int(round(stats.runner_score))}\n"
        f"1h涨幅：{format_pct(stats.price_change_1h)}\n"
        f"15m涨幅：{format_pct(stats.price_change_15m)}\n"
        f"OI 30m：{format_pct(stats.oi_change_30m)}\n"
        f"OI 1h：{format_pct(stats.oi_change_1h)}\n"
        f"15m量比：{(stats.volume_ratio_15m or 0):.2f}x\n"
        f"距离5m MA25：{format_pct(stats.distance_to_ma25_5m)}\n\n"
        f"触发原因：\n{reason_lines}\n\n"
        "建议动作：\n"
        "强烈值得打开图表盯盘。优先等待5m回踩MA7/MA25不破后的机会；如果出现放量长上影或跌破5m MA25，不要追。\n\n"
        "风险提示：\n"
        "如果连续2根5m收在MA25下方，或从高点回撤超过12%，应从确信池降级；如果1h涨幅超过60%且距离MA25过远，进入过热状态，不再发邮件。"
    )
