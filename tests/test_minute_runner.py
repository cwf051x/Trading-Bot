"""Minute Runner Radar tests.
分钟级单边上涨池测试。
"""

from __future__ import annotations

from dataclasses import replace

from app.alerts.minute_runner import (
    MinuteRunnerEmailGate,
    MinuteRunnerManager,
    MinuteRunnerState,
    build_minute_runner_digest,
)
from app.alerts.rule_config import DEFAULT_RADAR_RULE_CONFIG
from app.alerts.rules.minute_runner import MinuteRunnerRule
from app.alerts.signal_models import MinuteRunnerStats
from app.config import Settings
from app.data.minute_runner_snapshot import build_minute_runner_stats
from app.exchange.binance import Kline, OpenInterestPoint
from app.storage.sqlite import SQLiteStorage


class CapturingNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, text: str) -> bool:
        self.messages.append(text)
        return True


class CapturingEmailSender:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send(self, subject: str, body: str):
        self.messages.append((subject, body))
        return type("EmailResult", (), {"sent": True, "reason": "sent"})()


def make_stats(**overrides) -> MinuteRunnerStats:
    """Create a compact MinuteRunnerStats row for manager persistence tests.
    为状态持久化测试构造最小的单边上涨指标。
    """

    defaults = {
        "trend_age_minutes": 75,
        "runner_score": 90,
        "ranking_score": 108,
        "state": MinuteRunnerState.EARLY_CONFIRMED.value,
        "email_should_send": True,
        "price_change_15m": 0.08,
        "price_change_30m": 0.15,
        "price_change_1h": 0.28,
        "volume_ratio_15m": 2.4,
        "volume_ratio_5m": 2.0,
        "oi_change_30m": 0.06,
        "oi_change_45m": 0.07,
        "oi_change_1h": 0.10,
        "distance_to_ma25_5m": 0.08,
        "pullback_from_high": 0.02,
        "trend_id": "trend-old",
        "reasons": ["测试趋势"],
    }
    defaults.update(overrides)
    return MinuteRunnerStats(**defaults)


def make_runner_5m_klines(
    *,
    bars: int = 120,
    start_price: float = 1.0,
    trend_start_index: int = 96,
    per_bar_change: float = 0.018,
    last_distance: float = 0.0,
) -> list[Kline]:
    """Build a late-stage 5m uptrend with enough history for MA99.
    构造有足够均线历史的 5m 单边上涨 K 线。
    """

    rows: list[Kline] = []
    price = start_price
    for index in range(bars):
        if index < trend_start_index:
            close = price * 1.0002
            volume = 1000.0
        else:
            close = price * (1 + per_bar_change)
            volume = 2600.0
        if index == bars - 1 and last_distance:
            close *= 1 + last_distance
        open_price = price
        high = max(open_price, close) * 1.004
        low = min(open_price, close) * 0.996
        rows.append(Kline(timestamp=index * 300_000, open=open_price, high=high, low=low, close=close, volume=volume))
        price = close
    return rows


def make_15m_from_5m(klines_5m: list[Kline]) -> list[Kline]:
    rows: list[Kline] = []
    for index in range(0, len(klines_5m), 3):
        chunk = klines_5m[index : index + 3]
        if len(chunk) < 3:
            continue
        rows.append(
            Kline(
                timestamp=chunk[0].timestamp,
                open=chunk[0].open,
                high=max(item.high for item in chunk),
                low=min(item.low for item in chunk),
                close=chunk[-1].close,
                volume=sum(item.volume for item in chunk),
            )
        )
    return rows


def make_1h_klines(*, change_1h: float = 0.28, bars: int = 120) -> list[Kline]:
    rows: list[Kline] = []
    price = 1.0
    normal_step = 1.001
    final_step = (1 + change_1h) ** (1 / 2)
    for index in range(bars):
        step = final_step if index >= bars - 2 else normal_step
        close = price * step
        rows.append(Kline(timestamp=index * 3_600_000, open=price, high=close * 1.002, low=price * 0.998, close=close, volume=2000.0))
        price = close
    return rows


def make_oi_history(*, total_change: float = 0.08, bars: int = 30) -> list[OpenInterestPoint]:
    rows: list[OpenInterestPoint] = []
    value = 1000.0
    step = (1 + total_change) ** (1 / 12)
    for index in range(bars):
        if index >= bars - 12:
            value *= step
        rows.append(OpenInterestPoint(timestamp=index * 300_000, open_interest=value))
    return rows


def test_minute_runner_rule_does_not_request_unused_3m_timeframe() -> None:
    rule = MinuteRunnerRule(Settings(_env_file=None))

    assert rule.required_timeframes() == {"5m", "15m", "1h"}


def test_minute_runner_stats_identifies_early_confirmed_and_email_candidate() -> None:
    klines_5m = make_runner_5m_klines(trend_start_index=102, per_bar_change=0.012)
    stats = build_minute_runner_stats(
        klines_5m=klines_5m,
        klines_15m=make_15m_from_5m(klines_5m),
        klines_1h=make_1h_klines(change_1h=0.28),
        oi_history_5m=make_oi_history(total_change=0.10),
        funding_rate=0.0002,
        btc_15m_change=-0.001,
        config=DEFAULT_RADAR_RULE_CONFIG["minute_runner"],
    )

    assert stats is not None
    assert stats.runner_score >= 88
    assert stats.state == MinuteRunnerState.EARLY_CONFIRMED.value
    assert stats.email_should_send is True
    assert 60 <= stats.trend_age_minutes <= 120


def test_minute_runner_overheat_does_not_allow_email() -> None:
    klines_5m = make_runner_5m_klines(trend_start_index=96, per_bar_change=0.025, last_distance=0.10)
    stats = build_minute_runner_stats(
        klines_5m=klines_5m,
        klines_15m=make_15m_from_5m(klines_5m),
        klines_1h=make_1h_klines(change_1h=0.68),
        oi_history_5m=make_oi_history(total_change=0.12),
        funding_rate=0.0002,
        btc_15m_change=0.0,
        config=DEFAULT_RADAR_RULE_CONFIG["minute_runner"],
    )

    assert stats is not None
    assert stats.state == MinuteRunnerState.OVERHEAT.value
    assert stats.email_should_send is False
    assert stats.is_overheated is True


def test_minute_runner_broken_when_price_loses_ma25_twice() -> None:
    klines_5m = make_runner_5m_klines(trend_start_index=96, per_bar_change=0.012)
    ma25_anchor = sum(item.close for item in klines_5m[-27:-2]) / 25
    klines_5m[-2] = replace(klines_5m[-2], open=ma25_anchor * 0.995, close=ma25_anchor * 0.985, high=ma25_anchor, low=ma25_anchor * 0.970, volume=5000)
    klines_5m[-1] = replace(klines_5m[-1], open=ma25_anchor * 0.984, close=ma25_anchor * 0.975, high=ma25_anchor * 0.990, low=ma25_anchor * 0.960, volume=5200)

    stats = build_minute_runner_stats(
        klines_5m=klines_5m,
        klines_15m=make_15m_from_5m(klines_5m),
        klines_1h=make_1h_klines(change_1h=0.20),
        oi_history_5m=make_oi_history(total_change=0.06),
        funding_rate=0.0002,
        btc_15m_change=0.0,
        config=DEFAULT_RADAR_RULE_CONFIG["minute_runner"],
    )

    assert stats is not None
    assert stats.state == MinuteRunnerState.BROKEN.value
    assert "5m连续跌破MA25" in (stats.broken_reason or "")


def test_minute_runner_email_gate_limits_symbol_trend_and_global_cooldown(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "runner.sqlite")
    storage.initialize()
    gate = MinuteRunnerEmailGate(storage, Settings(_env_file=None, MINUTE_RUNNER_EMAIL_ENABLED=True), now_ms=1_000_000)

    first = gate.claim("IN/USDT:USDT", "IN-1")
    gate.mark_sent("IN/USDT:USDT", "IN-1")
    same_trend = gate.claim("IN/USDT:USDT", "IN-1")
    global_limited = gate.claim("AAA/USDT:USDT", "AAA-1")

    assert first.allowed is True
    assert same_trend.allowed is False
    assert same_trend.reason == "already_sent_for_trend"
    assert global_limited.allowed is False
    assert global_limited.reason == "global_cooldown"
    assert storage.get_minute_runner_state("AAA/USDT:USDT")["email_skip_reason"] == "global_cooldown"


def test_minute_runner_email_failure_does_not_consume_global_or_trend_limit(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "runner.sqlite")
    storage.initialize()
    gate = MinuteRunnerEmailGate(storage, Settings(_env_file=None, MINUTE_RUNNER_EMAIL_ENABLED=True), now_ms=1_000_000)

    first = gate.claim("IN/USDT:USDT", "IN-1")
    gate.mark_failed("IN/USDT:USDT", "email_send_failed")
    retry_same_trend = gate.claim("IN/USDT:USDT", "IN-1")
    other_symbol = gate.claim("AAA/USDT:USDT", "AAA-1")

    assert first.allowed is True
    assert retry_same_trend.allowed is True
    assert other_symbol.allowed is True
    row = storage.get_minute_runner_state("IN/USDT:USDT")
    assert row["last_email_sent_at"] is None
    assert row["email_sent_for_trend_id"] is None
    assert row["email_send_status"] == "claimed"


def test_minute_runner_digest_sorts_confirmed_before_pool_and_risk_section(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "runner.sqlite")
    storage.initialize()
    base = 1_700_000_000_000
    for row in [
        {"symbol": "POOL/USDT:USDT", "state": "M1", "runner_score": 82, "ranking_score": 85, "last_price": 1.2, "price_change_1h": 0.18, "trend_age_minutes": 45, "oi_change_30m": 0.03, "oi_change_1h": 0.05, "volume_ratio_15m": 2.0, "distance_to_ma25_5m": 0.06, "pullback_from_high": 0.02},
        {"symbol": "HOT/USDT:USDT", "state": "M3", "runner_score": 94, "ranking_score": 60, "last_price": 2.0, "price_change_1h": 0.66, "trend_age_minutes": 160, "oi_change_30m": 0.12, "oi_change_1h": 0.16, "volume_ratio_15m": 3.0, "distance_to_ma25_5m": 0.24, "pullback_from_high": 0.01, "risk_tags_json": ["过热"]},
        {"symbol": "BROKEN/USDT:USDT", "state": "M4", "runner_score": 50, "ranking_score": 20, "last_price": 0.9, "price_change_1h": -0.02, "trend_age_minutes": 30, "oi_change_30m": -0.03, "oi_change_1h": -0.04, "volume_ratio_15m": 0.8, "distance_to_ma25_5m": -0.04, "pullback_from_high": 0.18},
        {"symbol": "IN/USDT:USDT", "state": "M2E", "runner_score": 89, "ranking_score": 110, "last_price": 0.123, "price_change_1h": 0.28, "trend_age_minutes": 85, "oi_change_30m": 0.052, "oi_change_1h": 0.068, "volume_ratio_15m": 2.6, "distance_to_ma25_5m": 0.084, "pullback_from_high": 0.02},
    ]:
        storage.upsert_minute_runner_state({**row, "trend_id": f"{row['symbol']}-1", "last_score_update_at": base, "metadata_json": {}})

    digest = build_minute_runner_digest(storage, now_ms=base, top_n=8, min_score=72)

    assert digest is not None
    assert "【单边上涨池｜5m更新】" in digest.text
    assert digest.text.index("1. IN｜89｜M2E") < digest.text.index("2. POOL｜82｜M1")
    assert "风险：" in digest.text
    assert "HOT｜M3过热" in digest.text
    assert "BROKEN" not in digest.text.split("风险：", 1)[0]


def test_minute_runner_manager_sends_digest_and_m2e_email(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "runner.sqlite")
    storage.initialize()
    notifier = CapturingNotifier()
    email_sender = CapturingEmailSender()
    settings = Settings(
        _env_file=None,
        MINUTE_RUNNER_EMAIL_ENABLED=True,
        MINUTE_RUNNER_DIGEST_INTERVAL_SECONDS=300,
        MINUTE_RUNNER_EMAIL_GLOBAL_COOLDOWN_SECONDS=1800,
    )
    manager = MinuteRunnerManager(storage, notifier, settings, email_sender=email_sender)
    klines_5m = make_runner_5m_klines(trend_start_index=102, per_bar_change=0.012)
    stats = build_minute_runner_stats(
        klines_5m=klines_5m,
        klines_15m=make_15m_from_5m(klines_5m),
        klines_1h=make_1h_klines(change_1h=0.28),
        oi_history_5m=make_oi_history(total_change=0.10),
        funding_rate=0.0002,
        btc_15m_change=0.0,
        config=DEFAULT_RADAR_RULE_CONFIG["minute_runner"],
    )

    manager.process([("IN/USDT:USDT", 0.123, stats)], now_ms=1_700_000_000_000)

    assert notifier.messages
    assert email_sender.messages
    assert "【单边确信】IN｜" in email_sender.messages[0][0]
    row = storage.get_minute_runner_state("IN/USDT:USDT")
    assert row["state"] == "M2E"
    assert row["email_sent_for_trend_id"] == row["trend_id"]


def test_minute_runner_manager_resets_trend_scoped_fields_when_trend_changes(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "runner.sqlite")
    storage.initialize()
    manager = MinuteRunnerManager(
        storage,
        CapturingNotifier(),
        Settings(_env_file=None, MINUTE_RUNNER_EMAIL_ENABLED=True),
        email_sender=CapturingEmailSender(),
    )

    manager.process([("IN/USDT:USDT", 10.0, make_stats(trend_id="trend-old"))], now_ms=1_000_000)
    old_row = storage.get_minute_runner_state("IN/USDT:USDT")
    assert old_row["email_sent_for_trend_id"] == "trend-old"
    assert old_row["highest_price"] == 10.0

    manager.process(
        [
            (
                "IN/USDT:USDT",
                7.0,
                make_stats(
                    trend_id="trend-new",
                    state=MinuteRunnerState.POOL.value,
                    runner_score=76,
                    ranking_score=82,
                    email_should_send=False,
                ),
            )
        ],
        now_ms=2_000_000,
    )

    row = storage.get_minute_runner_state("IN/USDT:USDT")
    assert row["trend_id"] == "trend-new"
    assert row["entry_price"] == 7.0
    assert row["highest_price"] == 7.0
    assert row["first_pool_at"] == 2_000_000
    assert row["confirmed_at"] is None
    assert row["last_state_change_at"] == 2_000_000
    assert row["last_email_sent_at"] is None
    assert row["email_sent_for_trend_id"] is None
    assert row["email_send_status"] is None
    assert row["email_skip_reason"] is None
