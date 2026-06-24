"""Radar historical replay tests.
雷达历史回放测试。
"""

import csv

from app.alerts.replay import ReplayConfig, replay_symbol
from app.alerts.rule_config import DEFAULT_RADAR_RULE_CONFIG
from app.exchange.binance import Kline, OpenInterestPoint
from scripts.replay_radar_signals import ensure_klines_csv, ensure_oi_csv, main as replay_main


def make_replay_klines() -> list[Kline]:
    rows: list[Kline] = []
    price = 100.0
    for index in range(150):
        open_price = price
        close = open_price * (1.012 if index >= 120 else 1.001)
        high = close * 1.002
        low = open_price * 0.998
        volume = 4000.0 if index >= 126 else 1000.0
        rows.append(Kline(timestamp=index * 300_000, open=open_price, high=high, low=low, close=close, volume=volume))
        price = close
    return rows


def make_replay_oi(length: int) -> list[OpenInterestPoint]:
    return [OpenInterestPoint(timestamp=index * 300_000, open_interest=1000 * (1.011**index)) for index in range(length)]


def replay_config() -> ReplayConfig:
    return ReplayConfig(min_warmup_bars=120, outcome_horizons=(3, 6, 12), cooldown_bars=0)


def test_replay_symbol_records_alert_and_forward_outcomes() -> None:
    outcomes = replay_symbol(
        "ALLO/USDT:USDT",
        make_replay_klines(),
        oi_5m=make_replay_oi(150),
        config=replay_config(),
        radar_rule_config=DEFAULT_RADAR_RULE_CONFIG,
    )

    assert outcomes
    first = outcomes[0]
    assert first.symbol == "ALLO/USDT:USDT"
    assert first.signal_type == "VOLUME_PRICE_OI_RESONANCE"
    assert first.trigger_price > 0
    assert first.forward_returns["15m"] != 0
    assert first.max_favorable_return > 0
    assert first.max_adverse_return <= first.max_favorable_return


def test_replay_symbol_does_not_look_ahead_before_signal_exists() -> None:
    klines = make_replay_klines()
    early_slice = klines[:119]

    outcomes = replay_symbol(
        "ALLO/USDT:USDT",
        early_slice,
        oi_5m=make_replay_oi(len(early_slice)),
        config=replay_config(),
        radar_rule_config=DEFAULT_RADAR_RULE_CONFIG,
    )

    assert outcomes == []


def test_replay_script_writes_detail_and_summary_csv(monkeypatch, tmp_path) -> None:
    kline_path = tmp_path / "klines.csv"
    oi_path = tmp_path / "oi.csv"
    output_path = tmp_path / "detail.csv"
    summary_path = tmp_path / "summary.csv"
    write_klines_csv(kline_path, make_replay_klines())
    write_oi_csv(oi_path, make_replay_oi(150))
    monkeypatch.setattr(
        "sys.argv",
        [
            "replay_radar_signals.py",
            "--symbol",
            "ALLO/USDT:USDT",
            "--klines-5m",
            str(kline_path),
            "--oi-5m",
            str(oi_path),
            "--output",
            str(output_path),
            "--summary-output",
            str(summary_path),
            "--warmup-bars",
            "120",
        ],
    )

    replay_main()

    assert output_path.exists()
    assert summary_path.exists()
    assert "VOLUME_PRICE_OI_RESONANCE" in output_path.read_text(encoding="utf-8")
    assert "win_rate_1h" in summary_path.read_text(encoding="utf-8")


def test_ensure_klines_csv_downloads_missing_cache(tmp_path) -> None:
    cache_path = tmp_path / "ALLOUSDT_5m_1d.csv"
    client = FakeReplayClient(make_replay_klines()[:3])

    result = ensure_klines_csv(client, "ALLO/USDT:USDT", cache_path, start_ms=0, end_ms=900_000)

    assert result == cache_path
    assert cache_path.exists()
    assert client.calls == [("ALLO/USDT:USDT", "5m", 1000, 0)]
    assert "timestamp,open,high,low,close,volume" in cache_path.read_text(encoding="utf-8")


def test_ensure_klines_csv_reuses_existing_cache(tmp_path) -> None:
    cache_path = tmp_path / "ALLOUSDT_5m_1d.csv"
    write_klines_csv(cache_path, make_replay_klines()[:3])
    client = FakeReplayClient(make_replay_klines()[3:6])

    result = ensure_klines_csv(client, "ALLO/USDT:USDT", cache_path, start_ms=0, end_ms=900_000)

    assert result == cache_path
    assert client.calls == []


def test_ensure_oi_csv_downloads_missing_cache(tmp_path) -> None:
    cache_path = tmp_path / "ALLOUSDT_oi_5m_1d.csv"
    client = FakeReplayClient(make_replay_klines()[:3], oi=make_replay_oi(3))

    result = ensure_oi_csv(client, "ALLO/USDT:USDT", "5m", cache_path, start_ms=0, end_ms=900_000)

    assert result == cache_path
    assert cache_path.exists()
    assert client.oi_calls == [("ALLO/USDT:USDT", "5m", 500, 0, 900_000)]
    assert "timestamp,open_interest" in cache_path.read_text(encoding="utf-8")


def write_klines_csv(path, klines: list[Kline]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for item in klines:
            writer.writerow(item.__dict__)


def write_oi_csv(path, history: list[OpenInterestPoint]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open_interest"])
        writer.writeheader()
        for item in history:
            writer.writerow(item.__dict__)


class FakeReplayClient:
    def __init__(self, klines: list[Kline], oi: list[OpenInterestPoint] | None = None) -> None:
        self.klines = klines
        self.oi = oi or []
        self.calls: list[tuple[str, str, int, int | None]] = []
        self.oi_calls: list[tuple[str, str, int, int | None, int | None]] = []

    def get_klines(self, symbol: str, timeframe: str, limit: int, since: int | None = None) -> list[Kline]:
        self.calls.append((symbol, timeframe, limit, since))
        return [item for item in self.klines if since is None or item.timestamp >= since][:limit]

    def get_open_interest_history(self, symbol: str, period: str = "5m", limit: int = 30, start_time: int | None = None, end_time: int | None = None) -> list[OpenInterestPoint]:
        self.oi_calls.append((symbol, period, limit, start_time, end_time))
        return [item for item in self.oi if (start_time is None or item.timestamp >= start_time) and (end_time is None or item.timestamp <= end_time)][:limit]
