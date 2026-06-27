"""Alert digest aggregation tests.
雷达热榜汇总测试。
"""

from __future__ import annotations

from app.alerts.digest import AlertDigestManager, build_alert_digest
from app.storage.sqlite import SQLiteStorage


class FakeNotifier:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.messages: list[str] = []

    def send_message(self, text: str) -> bool:
        self.messages.append(text)
        return self.enabled


class DigestSettings:
    alert_digest_enabled = True
    alert_digest_interval_seconds = 900
    alert_digest_top_n = 10
    alert_digest_lookback_seconds = 900
    alert_digest_min_score = 60


def save_alert(storage: SQLiteStorage, *, symbol: str, alert_type: str, timestamp: int, price: float, score: int = 70, raw: dict | None = None) -> None:
    storage.save_market_alert(
        {
            "timestamp": timestamp,
            "symbol": symbol,
            "alert_type": alert_type,
            "level": "B" if score >= 70 else "C",
            "score": score,
            "price": price,
            "price_change_3m": 0.01,
            "price_change_5m": 0.02,
            "price_change_15m": 0.03,
            "price_change_1h": 0.08,
            "price_change_24h": 0.20,
            "volume_ratio": (raw or {}).get("metadata", {}).get("volume_ratio", 2.0),
            "btc_15m_change": 0.0,
            "reason": "test",
            "suggested_action": "观察",
            "invalidation_price": None,
            "target_1": None,
            "target_2": None,
            "sent_to_telegram": False,
            "raw_json": raw or {},
        }
    )


def test_digest_aggregates_same_symbol_and_compresses_stages(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "digest.sqlite")
    storage.initialize()
    base = 1_800_000
    for offset, stage, price in [(0, "L0", 1.0), (10, "L0", 1.02), (20, "L1", 1.05), (30, "L2", 1.12)]:
        save_alert(
            storage,
            symbol="AIN/USDT:USDT",
            alert_type="VOLUME_PRICE_OI_L0" if stage == "L0" else "VOLUME_PRICE_OI_RESONANCE",
            timestamp=base + offset,
            price=price,
            score=65 if stage == "L0" else 75,
            raw={"metadata": {"rule_family": "volume_price_oi", "signal_stage": stage, "volume_ratio": 3.0, "oi_change_15m": 0.062, "quote_volume_rank": 5}},
        )

    digest = build_alert_digest(storage, now_ms=base + 60, lookback_seconds=900, top_n=10, min_score=60)

    assert digest is not None
    assert "15分钟雷达热榜 TOP10" in digest.text
    assert "AIN" in digest.text
    assert "+12.00%" in digest.text
    assert "L0×2 → L1×1 → L2×1" in digest.text
    assert "量比 3.00x" in digest.text
    assert "OI +6.20%" in digest.text
    assert "成交额排名 #5" in digest.text
    assert "T0" not in digest.text


def test_digest_supports_multiple_rule_families_for_one_symbol(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "digest.sqlite")
    storage.initialize()
    base = 1_800_000
    save_alert(storage, symbol="TSJ/USDT:USDT", alert_type="VOLUME_PRICE_OI_RESONANCE", timestamp=base, price=1.0, raw={"metadata": {"rule_family": "volume_price_oi", "signal_stage": "L2", "volume_ratio": 2.5, "oi_change_15m": 0.052}})
    save_alert(storage, symbol="TSJ/USDT:USDT", alert_type="HOURLY_TREND_T1", timestamp=base + 1, price=1.1, raw={"metadata": {"rule_family": "hourly_trend", "trend_level": "T1", "volume_ratio": 1.8, "oi_change_6h": 0.09}})
    save_alert(storage, symbol="TSJ/USDT:USDT", alert_type="PUMP_PULLBACK_P2", timestamp=base + 2, price=1.12, raw={"metadata": {"rule_family": "pump_pullback_second_wave", "pump_pullback_level": "P2", "volume_ratio_15m": 2.0, "oi_change_30m": 0.04}})

    digest = build_alert_digest(storage, now_ms=base + 60, lookback_seconds=900, top_n=10, min_score=60)

    assert digest is not None
    assert "量价OI L2×1" in digest.text
    assert "小时趋势 T1×1" in digest.text
    assert "二波 P2×1" in digest.text


def test_digest_top_n_and_empty_window(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "digest.sqlite")
    storage.initialize()
    base = 1_800_000
    save_alert(storage, symbol="AAA/USDT:USDT", alert_type="VOLUME_PRICE_OI_L0", timestamp=base, price=1.0, score=65, raw={"metadata": {"rule_family": "volume_price_oi", "signal_stage": "L0"}})
    save_alert(storage, symbol="BBB/USDT:USDT", alert_type="VOLUME_PRICE_OI_RESONANCE", timestamp=base + 1, price=1.2, score=85, raw={"metadata": {"rule_family": "volume_price_oi", "signal_stage": "L2"}})

    digest = build_alert_digest(storage, now_ms=base + 60, lookback_seconds=900, top_n=1, min_score=60)
    empty = build_alert_digest(storage, now_ms=base + 2_000_000, lookback_seconds=900, top_n=10, min_score=60)

    assert digest is not None
    assert "BBB" in digest.text
    assert "AAA" not in digest.text
    assert empty is None


def test_digest_manager_respects_interval_and_disabled_telegram(tmp_path) -> None:
    storage = SQLiteStorage(tmp_path / "digest.sqlite")
    storage.initialize()
    base = 1_800_000
    save_alert(storage, symbol="AIN/USDT:USDT", alert_type="VOLUME_PRICE_OI_L0", timestamp=base, price=1.0, score=65, raw={"metadata": {"rule_family": "volume_price_oi", "signal_stage": "L0"}})
    notifier = FakeNotifier(enabled=False)
    manager = AlertDigestManager(storage, notifier, DigestSettings())

    assert manager.maybe_send(now_ms=base + 60) is False
    assert len(notifier.messages) == 1
    state = storage.get_alert_state("__digest__")
    assert state["metadata_json"]["last_digest_at"] == base + 60
    assert manager.maybe_send(now_ms=base + 120) is False
    assert len(notifier.messages) == 1
