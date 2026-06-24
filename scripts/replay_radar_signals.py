"""Replay radar signals on local historical CSV data.
使用本地历史 CSV 回放雷达信号。
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.alerts.replay import ReplayConfig, ReplayOutcome, replay_symbol
from app.alerts.rule_config import load_radar_rule_config
from app.config import Settings
from app.exchange.binance import BinanceFuturesClient, Kline, OpenInterestPoint

FIVE_MINUTES_MS = 300_000
PERIOD_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
}


def build_parser() -> argparse.ArgumentParser:
    """Build command-line parser.
    构建命令行参数解析器。
    """

    parser = argparse.ArgumentParser(description="Replay radar rules against local 5m CSV data")
    parser.add_argument("--symbol", required=True, help="Symbol label, e.g. BTC/USDT:USDT")
    parser.add_argument("--klines-5m", type=Path, help="CSV with timestamp,open,high,low,close,volume. Downloaded when omitted.")
    parser.add_argument("--oi-5m", type=Path, help="Optional OI CSV with timestamp,open_interest")
    parser.add_argument("--oi-15m", type=Path, help="Optional 15m OI CSV with timestamp,open_interest")
    parser.add_argument("--oi-1h", type=Path, help="Optional 1h OI CSV with timestamp,open_interest")
    parser.add_argument("--output", type=Path, default=Path("reports/radar_replay.csv"), help="Output CSV path")
    parser.add_argument("--summary-output", type=Path, default=Path("reports/radar_replay_summary.csv"), help="Summary CSV path")
    parser.add_argument("--days", type=int, default=30, help="Days to download when local CSV is omitted")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/replay"), help="Downloaded CSV cache directory")
    parser.add_argument("--warmup-bars", type=int, default=120, help="5m warmup bars before replay starts")
    parser.add_argument("--cooldown-bars", type=int, default=6, help="Minimum bars between same signal type")
    return parser


def main() -> None:
    """Run replay and write reports.
    执行回放并写出报告。
    """

    args = build_parser().parse_args()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - max(args.days, 1) * 24 * 60 * 60 * 1000
    auto_download = args.klines_5m is None

    if auto_download:
        settings = Settings()
        client = BinanceFuturesClient(settings.binance_api_key, settings.binance_api_secret, settings.exchange_proxy, settings.exchange_network_mode)
        klines_path = ensure_klines_csv(
            client,
            args.symbol,
            default_cache_path(args.cache_dir, args.symbol, "5m", args.days, suffix="klines"),
            start_ms=start_ms,
            end_ms=end_ms,
        )
        oi_5m_path = ensure_oi_csv(client, args.symbol, "5m", default_cache_path(args.cache_dir, args.symbol, "5m", args.days, suffix="oi"), start_ms=start_ms, end_ms=end_ms)
        oi_15m_path = ensure_oi_csv(client, args.symbol, "15m", default_cache_path(args.cache_dir, args.symbol, "15m", args.days, suffix="oi"), start_ms=start_ms, end_ms=end_ms)
        oi_1h_path = ensure_oi_csv(client, args.symbol, "1h", default_cache_path(args.cache_dir, args.symbol, "1h", args.days, suffix="oi"), start_ms=start_ms, end_ms=end_ms)
    else:
        klines_path = args.klines_5m
        oi_5m_path = args.oi_5m
        oi_15m_path = args.oi_15m
        oi_1h_path = args.oi_1h

    outcomes = replay_symbol(
        args.symbol,
        read_klines_csv(klines_path),
        oi_5m=read_oi_csv(oi_5m_path) if oi_5m_path else None,
        oi_15m=read_oi_csv(oi_15m_path) if oi_15m_path else None,
        oi_1h=read_oi_csv(oi_1h_path) if oi_1h_path else None,
        config=ReplayConfig(min_warmup_bars=args.warmup_bars, cooldown_bars=args.cooldown_bars),
        radar_rule_config=load_radar_rule_config(),
    )
    write_outcomes(args.output, outcomes)
    write_summary(args.summary_output, summarize(outcomes))
    print(f"Replay generated {len(outcomes)} signals.")
    print(f"Klines: {klines_path}")
    print(f"OI 5m: {oi_5m_path or '-'}")
    print(f"OI 15m: {oi_15m_path or '-'}")
    print(f"OI 1h: {oi_1h_path or '-'}")
    print(f"Detail: {args.output}")
    print(f"Summary: {args.summary_output}")


def ensure_klines_csv(client: BinanceFuturesClient, symbol: str, path: Path, *, start_ms: int, end_ms: int) -> Path:
    """Return an existing kline cache or download it from Binance.
    返回已有 K 线缓存；不存在时从 Binance 下载并写入 CSV。
    """

    if path.exists():
        return path
    klines = download_klines(client, symbol, start_ms=start_ms, end_ms=end_ms)
    write_klines_csv(path, klines)
    return path


def ensure_oi_csv(client: BinanceFuturesClient, symbol: str, period: str, path: Path, *, start_ms: int, end_ms: int) -> Path:
    """Return an existing OI cache or download it from Binance.
    返回已有 OI 缓存；不存在时从 Binance 下载并写入 CSV。
    """

    if path.exists():
        return path
    history = download_open_interest_history(client, symbol, period=period, start_ms=start_ms, end_ms=end_ms)
    write_oi_csv(path, history)
    return path


def download_klines(client: BinanceFuturesClient, symbol: str, *, start_ms: int, end_ms: int) -> list[Kline]:
    """Download 5m klines by paging through Binance limits.
    按 Binance 单次限制分页下载 5m K 线。
    """

    rows: list[Kline] = []
    since = start_ms
    while since < end_ms:
        batch = client.get_klines(symbol, "5m", limit=1000, since=since)
        batch = [item for item in batch if start_ms <= item.timestamp <= end_ms]
        if not batch:
            break
        rows.extend(item for item in batch if not rows or item.timestamp > rows[-1].timestamp)
        next_since = batch[-1].timestamp + FIVE_MINUTES_MS
        if next_since <= since:
            break
        since = next_since
    return rows


def download_open_interest_history(client: BinanceFuturesClient, symbol: str, *, period: str, start_ms: int, end_ms: int) -> list[OpenInterestPoint]:
    """Download OI history for a period using Binance time windows.
    使用 Binance 时间窗口分页下载指定周期的 OI 历史。
    """

    step_ms = PERIOD_MS.get(period)
    if step_ms is None:
        raise ValueError(f"Unsupported OI period: {period}")

    rows: list[OpenInterestPoint] = []
    since = start_ms
    while since < end_ms:
        # Binance OI history has a small per-request limit, so replay download
        # pages by timestamp instead of asking for a long range in one call.
        batch = client.get_open_interest_history(symbol, period=period, limit=500, start_time=since, end_time=end_ms)
        batch = [item for item in batch if start_ms <= item.timestamp <= end_ms]
        if not batch:
            break
        rows.extend(item for item in batch if not rows or item.timestamp > rows[-1].timestamp)
        next_since = batch[-1].timestamp + step_ms
        if next_since <= since:
            break
        since = next_since
    return rows


def default_cache_path(cache_dir: Path, symbol: str, timeframe: str, days: int, *, suffix: str) -> Path:
    """Build a stable local cache path for downloaded replay data.
    为下载的回放数据构建稳定缓存路径。
    """

    safe_symbol = symbol.upper().replace(":USDT", "").replace("/", "").replace("-", "")
    return cache_dir / f"{safe_symbol}_{suffix}_{timeframe}_{days}d.csv"


def write_klines_csv(path: Path, klines: list[Kline]) -> None:
    """Write OHLCV candles to CSV.
    将 OHLCV K 线写入 CSV。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for item in klines:
            writer.writerow(item.__dict__)


def write_oi_csv(path: Path, history: list[OpenInterestPoint]) -> None:
    """Write open interest history to CSV.
    将持仓量历史写入 CSV。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open_interest"])
        writer.writeheader()
        for item in history:
            writer.writerow(item.__dict__)


def read_klines_csv(path: Path) -> list[Kline]:
    """Read OHLCV candles from CSV.
    从 CSV 读取 OHLCV K 线。
    """

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            Kline(
                timestamp=int(float(row["timestamp"])),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in rows
        ]


def read_oi_csv(path: Path) -> list[OpenInterestPoint]:
    """Read open interest history from CSV.
    从 CSV 读取持仓量历史。
    """

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return [OpenInterestPoint(timestamp=int(float(row["timestamp"])), open_interest=float(row["open_interest"])) for row in rows]


def write_outcomes(path: Path, outcomes: list[ReplayOutcome]) -> None:
    """Write detailed signal outcomes.
    写出逐条信号后验表现。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    horizons = sorted({key for outcome in outcomes for key in outcome.forward_returns})
    fieldnames = ["symbol", "signal_type", "level", "score", "trigger_time", "trigger_price", *horizons, "mfe", "mae", "reasons"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for outcome in outcomes:
            writer.writerow(
                {
                    "symbol": outcome.symbol,
                    "signal_type": outcome.signal_type,
                    "level": outcome.level,
                    "score": outcome.score,
                    "trigger_time": outcome.trigger_time,
                    "trigger_price": outcome.trigger_price,
                    **{key: outcome.forward_returns.get(key, "") for key in horizons},
                    "mfe": outcome.max_favorable_return,
                    "mae": outcome.max_adverse_return,
                    "reasons": outcome.reasons,
                }
            )


def summarize(outcomes: list[ReplayOutcome]) -> list[dict[str, float | int | str]]:
    """Aggregate replay outcomes by signal type.
    按信号类型汇总回放表现。
    """

    rows: list[dict[str, float | int | str]] = []
    for signal_type in sorted({outcome.signal_type for outcome in outcomes}):
        group = [outcome for outcome in outcomes if outcome.signal_type == signal_type]
        return_1h = [outcome.forward_returns.get("1h", 0.0) for outcome in group if "1h" in outcome.forward_returns]
        wins = [value for value in return_1h if value > 0]
        losses = [value for value in return_1h if value < 0]
        gross_loss = abs(sum(losses))
        rows.append(
            {
                "signal_type": signal_type,
                "count": len(group),
                "win_rate_1h": len(wins) / len(return_1h) if return_1h else 0.0,
                "avg_return_1h": sum(return_1h) / len(return_1h) if return_1h else 0.0,
                "profit_factor_1h": sum(wins) / gross_loss if gross_loss else 0.0,
                "avg_mfe": sum(item.max_favorable_return for item in group) / len(group),
                "avg_mae": sum(item.max_adverse_return for item in group) / len(group),
            }
        )
    return rows


def write_summary(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    """Write aggregated summary rows.
    写出聚合汇总 CSV。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["signal_type", "count", "win_rate_1h", "avg_return_1h", "profit_factor_1h", "avg_mfe", "avg_mae"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
