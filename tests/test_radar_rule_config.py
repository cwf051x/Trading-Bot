"""Radar rule YAML configuration tests.
雷达规则 YAML 配置测试。
"""

from pathlib import Path

from app.alerts.rule_config import load_radar_rule_config


def test_load_radar_rule_config_uses_defaults_when_file_is_missing(tmp_path: Path) -> None:
    config = load_radar_rule_config(tmp_path / "missing.yaml")

    assert config["hourly_trend"]["enabled"] is True
    assert config["pump_pullback_second_wave"]["p2"]["cooldown_seconds"] == 1800


def test_load_radar_rule_config_merges_nested_yaml_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "radar_rules.yaml"
    config_path.write_text(
        """
hourly_trend:
  enabled: false
  t1:
    price_change_6h: 0.12
pump_pullback_second_wave:
  enabled: true
  first_pump:
    min_change: 0.2
  p3:
    volume_ratio_15m: 3.0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_radar_rule_config(config_path)

    assert config["hourly_trend"]["enabled"] is False
    assert config["hourly_trend"]["t1"]["price_change_6h"] == 0.12
    assert config["hourly_trend"]["t2"]["price_change_12h"] == 0.20
    assert config["pump_pullback_second_wave"]["first_pump"]["min_change"] == 0.2
    assert config["pump_pullback_second_wave"]["p3"]["volume_ratio_15m"] == 3.0


def test_legacy_hourly_env_does_not_override_yaml_rule_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALERT_HOURLY_T1_PRICE_CHANGE_6H", "0.99")
    config_path = tmp_path / "radar_rules.yaml"
    config_path.write_text(
        """
hourly_trend:
  t1:
    price_change_6h: 0.11
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_radar_rule_config(config_path)

    assert config["hourly_trend"]["t1"]["price_change_6h"] == 0.11
