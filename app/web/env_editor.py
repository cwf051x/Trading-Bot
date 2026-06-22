"""Safe `.env` editing helpers for the admin panel.
管理后台使用的安全 `.env` 编辑工具。
"""

from __future__ import annotations

from pathlib import Path


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
    "ALERT_RULE_HOURLY_TREND_ENABLED",
    "ALERT_HOURLY_T1_PRICE_CHANGE_6H",
    "ALERT_HOURLY_T1_MA7_MA25_MIN_RATIO",
    "ALERT_HOURLY_T1_VOLUME_MULTIPLIER",
    "ALERT_HOURLY_T1_OI_CHANGE_6H",
    "ALERT_HOURLY_T2_PRICE_CHANGE_12H",
    "ALERT_HOURLY_T2_BULLISH_COUNT_12",
    "ALERT_HOURLY_T2_OI_CHANGE_12H",
    "ALERT_HOURLY_T2_VOLUME_EXPANSION",
    "ALERT_HOURLY_T3_PRICE_CHANGE_12H",
    "ALERT_HOURLY_T3_OI_CHANGE_12H",
    "ALERT_HOURLY_T3_PULLBACK_MIN",
    "ALERT_HOURLY_T3_PULLBACK_MAX",
    "ALERT_HOURLY_T3_OI_PULLBACK_MAX",
    "ALERT_HOURLY_T4_PRICE_CHANGE_24H",
    "ALERT_HOURLY_T4_MA25_DEVIATION",
    "ALERT_HOURLY_T4_RSI6",
    "ALERT_HOURLY_T4_RSI24",
    "ALERT_HOURLY_T4_OI_CHANGE_24H",
}


def update_env_values(env_path: Path, updates: dict[str, str]) -> None:
    """Update an env file using a strict allow-list.
    使用严格白名单更新 env 文件。
    """

    safe_updates = {key: value.strip() for key, value in updates.items() if key in ALLOWED_ENV_KEYS}
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
