"""Safe `.env` editing helpers for the admin panel.
管理后台使用的安全 `.env` 编辑工具。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable


ALLOWED_ENV_KEYS = {
    "WATCH_SYMBOLS",
    "DEFAULT_SYMBOL",
    "DEFAULT_TIMEFRAME",
    "BTC_DROP_THRESHOLD_15M",
    "ACCOUNT_EQUITY",
    "POLL_INTERVAL_SECONDS",
    "KLINE_LIMIT",
    "PAPER_LEVERAGE",
    "STRATEGY_BREAKOUT_WINDOW",
    "STRATEGY_VOLUME_WINDOW",
    "STRATEGY_VOLUME_MULTIPLIER",
    "STRATEGY_STOP_LOSS_PCT",
    "STRATEGY_TAKE_PROFIT_PCT",
    "ALERT_RADAR_ENABLED",
    "ALERT_SCAN_INTERVAL_SECONDS",
    "ALERT_TOP_GAINERS_LIMIT",
    "ALERT_MIN_24H_QUOTE_VOLUME_USDT",
    "ALERT_BLACKLIST",
    "ALERT_WATCHLIST",
    "ALERT_SEND_A_LEVEL",
    "ALERT_SEND_B_LEVEL",
    "ALERT_SEND_C_LEVEL",
    "ALERT_COOLDOWN_A_SECONDS",
    "ALERT_COOLDOWN_B_SECONDS",
    "ALERT_COOLDOWN_C_SECONDS",
    "ALERT_SURGE_3M_THRESHOLD",
    "ALERT_SURGE_5M_THRESHOLD",
    "ALERT_SURGE_15M_THRESHOLD",
    "ALERT_VOLUME_RATIO_THRESHOLD",
    "ALERT_PULLBACK_MIN_RATIO",
    "ALERT_PULLBACK_MAX_RATIO",
    "ALERT_BTC_DUMP_15M_THRESHOLD",
    "ALERT_HIGH_RISK_15M_CHANGE",
    "ALERT_HIGH_RISK_1H_CHANGE",
    "ALERT_MIN_BREAKOUT_CLOSE_POSITION",
    "ALERT_SECOND_LEG_MIN_CLOSE_POSITION",
    "ALERT_PULLBACK_VOLUME_CONTRACTION_MAX",
    "ALERT_OVERHEAT_RSI",
    "ALERT_FUNDING_RATE_TTL_SECONDS",
}

BOOL_KEYS = {"ALERT_RADAR_ENABLED", "ALERT_SEND_A_LEVEL", "ALERT_SEND_B_LEVEL", "ALERT_SEND_C_LEVEL"}
INT_MIN = {
    "POLL_INTERVAL_SECONDS": 1,
    "KLINE_LIMIT": 2,
    "STRATEGY_BREAKOUT_WINDOW": 2,
    "STRATEGY_VOLUME_WINDOW": 2,
    "ALERT_SCAN_INTERVAL_SECONDS": 5,
    "ALERT_TOP_GAINERS_LIMIT": 1,
    "ALERT_COOLDOWN_A_SECONDS": 0,
    "ALERT_COOLDOWN_B_SECONDS": 0,
    "ALERT_COOLDOWN_C_SECONDS": 0,
}
FLOAT_MIN = {
    "ACCOUNT_EQUITY": 1.0,
    "BTC_DROP_THRESHOLD_15M": -1.0,
    "PAPER_LEVERAGE": 1.0,
    "STRATEGY_VOLUME_MULTIPLIER": 0.0,
    "STRATEGY_STOP_LOSS_PCT": 0.0,
    "STRATEGY_TAKE_PROFIT_PCT": 0.0,
    "ALERT_MIN_24H_QUOTE_VOLUME_USDT": 0.0,
    "ALERT_SURGE_3M_THRESHOLD": -1.0,
    "ALERT_SURGE_5M_THRESHOLD": -1.0,
    "ALERT_SURGE_15M_THRESHOLD": -1.0,
    "ALERT_VOLUME_RATIO_THRESHOLD": 0.0,
    "ALERT_PULLBACK_MIN_RATIO": 0.0,
    "ALERT_PULLBACK_MAX_RATIO": 0.0,
    "ALERT_BTC_DUMP_15M_THRESHOLD": -1.0,
    "ALERT_HIGH_RISK_15M_CHANGE": 0.0,
    "ALERT_HIGH_RISK_1H_CHANGE": 0.0,
    "ALERT_MIN_BREAKOUT_CLOSE_POSITION": 0.0,
    "ALERT_SECOND_LEG_MIN_CLOSE_POSITION": 0.0,
    "ALERT_PULLBACK_VOLUME_CONTRACTION_MAX": 0.0,
    "ALERT_OVERHEAT_RSI": 0.0,
}


def update_env_values(env_path: Path, updates: dict[str, str]) -> None:
    """Update an env file using a strict allow-list.
    使用严格白名单更新 env 文件。
    """

    safe_updates = validate_env_updates({key: value.strip() for key, value in updates.items() if key in ALLOWED_ENV_KEYS})
    if not safe_updates:
        return

    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in safe_updates:
            output.append(f"{key}={safe_updates[key]}")
            seen.add(key)
        else:
            output.append(line)

    for key, value in safe_updates.items():
        if key not in seen:
            output.append(f"{key}={value}")

    env_path.write_text("\n".join(output) + "\n", encoding="utf-8")


def validate_env_updates(updates: dict[str, str]) -> dict[str, str]:
    """Validate editable env values before writing them to disk.
    写入 `.env` 前做基础类型和范围校验，避免无效参数导致服务重启失败。
    """

    validators: dict[str, Callable[[str], None]] = {}
    for key in BOOL_KEYS:
        validators[key] = _validate_bool
    for key, minimum in INT_MIN.items():
        validators[key] = lambda value, min_value=minimum: _validate_int_min(value, min_value)
    for key, minimum in FLOAT_MIN.items():
        validators[key] = lambda value, min_value=minimum: _validate_float_min(value, min_value)
    for key, value in updates.items():
        validator = validators.get(key)
        if validator:
            validator(value)
    return updates


def _validate_bool(value: str) -> None:
    if value.lower() not in {"true", "false"}:
        raise ValueError("Boolean env values must be true or false")


def _validate_int_min(value: str, minimum: int) -> None:
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"Integer env value must be >= {minimum}")


def _validate_float_min(value: str, minimum: float) -> None:
    parsed = float(value)
    if parsed < minimum:
        raise ValueError(f"Float env value must be >= {minimum}")
