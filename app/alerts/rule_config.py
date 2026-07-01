"""YAML-backed configuration for radar rule thresholds.
基于 YAML 的雷达规则阈值配置。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_RADAR_RULE_CONFIG: dict[str, Any] = {
    "volume_price_oi": {
        "enabled": True,
        "l0": {
            "enabled": True,
            "min_score_to_store": 60,
            "min_score_to_digest": 65,
            "hard_filters": {
                "price_change_5m": 0.015,
                "price_change_15m": 0.025,
                "close_position_min": 0.60,
                "price_above_ma7": True,
                "reject_long_upper_wick": True,
                "btc_15m_drop_min": -0.008,
            },
            "scoring": {
                "base_score": 55,
                "volume_ratio_1_5": 8,
                "volume_ratio_2_0": 14,
                "volume_ratio_3_0": 20,
                "oi_change_15m_1": 6,
                "oi_change_15m_2": 10,
                "oi_change_15m_4": 16,
                "both_volume_and_oi_bonus": 10,
                "price_above_ma25_bonus": 5,
                "top_gainer_rank_bonus": 5,
            },
            "auto_paper": False,
            "send_to_telegram": False,
            "digest": True,
        },
        "l1": {
            "price_change_15m": 0.03,
            "volume_ratio": 1.6,
            "oi_change_15m": 0.03,
        },
        "l2": {
            "price_change_30m": 0.06,
            "price_change_60m": 0.10,
            "bullish_5m_count_6": 4,
            "volume_continuity": 4,
            "oi_change_30m": 0.08,
        },
        "l3": {
            "price_change_60m": 0.20,
            "rsi6": 85.0,
            "ma25_deviation": 0.10,
            "oi_change_60m": 0.20,
        },
    },
    "hourly_trend": {
        "enabled": True,
        "funding_rate_ttl_seconds": 900,
        "t1": {
            "price_change_6h": 0.08,
            "ma7_ma25_min_ratio": 0.995,
            "volume_multiplier": 1.5,
            "oi_change_6h": 0.08,
        },
        "t2": {
            "price_change_12h": 0.20,
            "bullish_count_12": 8,
            "oi_change_12h": 0.15,
            "volume_expansion": 1.5,
        },
        "t3": {
            "price_change_12h": 0.15,
            "oi_change_12h": 0.10,
            "pullback_min": 0.04,
            "pullback_max": 0.10,
            "oi_pullback_max": 0.10,
        },
        "t4": {
            "price_change_24h": 0.50,
            "ma25_deviation": 0.20,
            "rsi6": 85.0,
            "rsi24": 75.0,
            "oi_change_24h": 0.40,
        },
    },
    "pump_pullback_second_wave": {
        "enabled": True,
        "first_pump": {
            "lookback_hours": 24,
            "min_change": 0.15,
            "min_duration_hours": 1,
            "max_duration_hours": 4,
            "volume_multiplier": 2.0,
            "oi_change_min": 0.10,
        },
        "pullback": {
            "min_pullback_from_high": 0.04,
            "max_retracement_ratio": 0.65,
            "max_pullback_volume_ratio": 1.0,
            "max_oi_drawdown_from_peak": 0.15,
        },
        "p2": {
            "cooldown_seconds": 1800,
            "recent_15m_change_3bars": 0.03,
            "volume_ratio_15m": 1.8,
            "oi_change_30m": 0.03,
            "rsi24_min": 45.0,
        },
        "p3": {
            "volume_ratio_15m": 2.5,
            "oi_change_1h": 0.06,
            "near_pump_high_distance": 0.05,
        },
        "p4": {
            "bypass_cooldown": True,
        },
    },
    "minute_runner": {
        "enabled": True,
        "pool": {
            "min_score": 72,
            "high_quality_score": 82,
            "early_confirmed_score": 88,
            "mature_confirmed_score": 93,
            "remove_score": 65,
        },
        "trend_age": {
            "early_confirmed_min_minutes": 60,
            "early_confirmed_max_minutes": 180,
            "sweet_spot_min_minutes": 60,
            "sweet_spot_max_minutes": 120,
        },
        "momentum": {
            "one_hour_change_min": 0.12,
            "one_hour_change_sweet_max": 0.45,
            "one_hour_change_overheat": 0.60,
        },
        "volume": {
            "min_15m_volume_ratio": 1.5,
            "confirmed_15m_volume_ratio": 1.8,
        },
        "oi": {
            "min_30m_change": 0.02,
            "confirmed_30m_change": 0.04,
            "confirmed_45m_change": 0.05,
            "confirmed_1h_change": 0.06,
            "max_negative_1h_change": -0.02,
        },
        "risk": {
            "btc_15m_dump_threshold": -0.008,
            "max_distance_to_ma25_5m_for_email": 0.15,
            "overheat_distance_to_ma25_5m": 0.20,
            "confirmed_pullback_downgrade": 0.12,
            "pool_remove_pullback": 0.15,
        },
        "telegram_digest": {
            "enabled": True,
            "interval_seconds": 300,
            "no_change_interval_seconds": 900,
            "top_n": 8,
            "min_score_to_show": 72,
        },
        "email": {
            "enabled": False,
            "min_score": 88,
            "top_rank": 5,
            "global_cooldown_seconds": 1800,
            "max_per_hour": 2,
        },
    },
}


def load_radar_rule_config(path: Path | str = Path("config/radar_rules.yaml")) -> dict[str, Any]:
    """Load radar rule config and merge it into defaults.
    读取雷达规则配置，并合并到默认值上。
    """

    config = deepcopy(DEFAULT_RADAR_RULE_CONFIG)
    config_path = Path(path)
    if not config_path.exists():
        return config
    loaded = parse_simple_yaml(config_path.read_text(encoding="utf-8"))
    deep_merge(config, loaded)
    return config


def apply_settings_overrides(config: dict[str, Any], settings: Any) -> dict[str, Any]:
    """Apply environment-level rule switches on top of YAML config.
    将环境变量级别的规则开关同步到 YAML 配置之后的最终配置。
    """

    if not bool(getattr(settings, "minute_runner_enabled", True)):
        config.setdefault("minute_runner", {})["enabled"] = False
    return config


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge nested dictionaries.
    递归合并嵌套配置字典。
    """

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by radar rule config.
    解析雷达规则配置使用的小型 YAML 子集。
    """

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        key, separator, raw_value = line_without_comment.strip().partition(":")
        if not separator or not key:
            raise ValueError(f"Invalid radar rule config line: {raw_line}")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value_text = raw_value.strip()
        if value_text == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(value_text)
    return root


def parse_scalar(value: str) -> Any:
    """Parse booleans and numbers from YAML scalar text.
    从 YAML 标量文本解析布尔值和数字。
    """

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("\"'")
