"""Display-only alert formatting tests.
行情提醒展示层格式测试。
"""

from app.alerts.display import display_alert_type, display_reason_cn, display_signal_code, display_symbol
from app.alerts.signal_models import AlertLevel, AlertSignal, AlertType
from app.alerts.telegram_formatter import format_alert_message
from app.web.server import alert_type_label, chinese_reason_text, display_symbol_base


def test_display_symbol_returns_base_asset_only() -> None:
    assert display_symbol("BTC/USDT:USDT") == "BTC"
    assert display_symbol("IN/USDT:USDT") == "IN"
    assert display_symbol("VELVETUSDT") == "VELVET"
    assert display_symbol("") == ""


def test_display_alert_type_returns_chinese_label_or_raw_value() -> None:
    assert display_alert_type(AlertType.HOURLY_TREND_T1) == "小时趋势启动"
    assert display_alert_type("PUMP_PULLBACK_P3") == "二波确认突破"
    assert display_alert_type("UNKNOWN_ALERT") == "UNKNOWN_ALERT"


def test_display_signal_code_returns_compact_code() -> None:
    assert display_signal_code(AlertType.HOURLY_TREND_T1) == "T1"
    assert display_signal_code("HOURLY_TREND_T4") == "T4"
    assert display_signal_code("PUMP_PULLBACK_P3") == "P3"
    assert display_signal_code("VOLUME_PRICE_OI_L0") == "L0"
    assert display_signal_code("VOLUME_PRICE_OI_RESONANCE", {"resonance_level": "L2"}) == "L2"
    assert display_signal_code("VOLUME_PRICE_OI_RESONANCE", {}) == "L?"
    assert display_signal_code("UNKNOWN_ALERT") == "UNKNOWN_ALERT"


def test_display_reason_cn_keeps_only_chinese_text() -> None:
    assert display_reason_cn("T1 trend start / T1 趋势启动") == "T1 趋势启动"
    assert display_reason_cn("price broke above prior 12h high / 价格突破前12小时高点") == "价格突破前12小时高点"
    assert display_reason_cn("已经是中文的理由") == "已经是中文的理由"
    assert display_reason_cn("first / 第一; second / 第二") == "第一；第二"
    assert display_reason_cn("") == ""


def test_format_alert_message_first_line_is_mobile_summary() -> None:
    alert = AlertSignal(
        timestamp=1,
        symbol="IN/USDT:USDT",
        alert_type=AlertType.HOURLY_TREND_T1,
        level=AlertLevel.A,
        score=88,
        price=0.12345,
        price_change_3m=0.012,
        price_change_5m=0.021,
        price_change_15m=0.038,
        price_change_1h=0.23115,
        price_change_24h=0.386,
        volume_ratio=2.4,
        btc_15m_change=-0.001,
        reasons=[
            "price broke above prior 12h high / 价格突破前12小时高点",
            "hourly trend structure starts / 小时级趋势结构开始启动",
        ],
        suggested_action="T1 趋势启动，先观察能否放量站稳",
        invalidation_price=0.118,
        target_1=0.132,
        target_2=0.145,
    )

    message = format_alert_message(alert)
    first_line = message.splitlines()[0]

    assert first_line == "IN｜A级｜T1｜0.123450｜+23.11%"
    assert "/USDT:USDT" not in first_line
    assert "Hourly" not in message
    assert "price broke above" not in message
    assert "价格突破前12小时高点" in message


def test_format_alert_message_keeps_readable_body_after_summary() -> None:
    alert = AlertSignal(
        timestamp=1,
        symbol="NFP/USDT:USDT",
        alert_type=AlertType.VOLUME_PRICE_OI_RESONANCE,
        level=AlertLevel.B,
        score=70,
        price=0.004495,
        price_change_3m=0.0,
        price_change_5m=0.0883,
        price_change_15m=0.0728,
        price_change_1h=0.0584,
        price_change_24h=-0.2269,
        volume_ratio=29.41,
        btc_15m_change=0.0,
        reasons=[
            "L1 unusual move watch / L1 异动观察",
            "price, volume and OI expanded together / 价格、成交量、持仓量同步扩张",
        ],
        suggested_action="L1 异动观察，等待是否升级为主升确认",
        raw={"metadata": {"signal_stage": "L1"}},
    )

    message = format_alert_message(alert)
    lines = message.splitlines()

    assert lines[0] == "NFP｜B级｜L1｜0.004495｜+5.84%"
    assert lines[1] == "--------------------"
    assert "⚠️ B级信号：量价OI共振拉升\n\n币种：NFP\n现价：0.004495\n评分：70/100\n建议：L1 异动观察，等待是否升级为主升确认" in message
    assert "/ Volume Price OI Resonance" not in message
    assert "NFP/USDT:USDT" not in message


def test_format_alert_message_missing_one_hour_change_uses_dash() -> None:
    alert = AlertSignal(
        timestamp=1,
        symbol="BTC/USDT:USDT",
        alert_type=AlertType.VOLUME_PRICE_OI_RESONANCE,
        level=AlertLevel.B,
        score=75,
        price=100.0,
        price_change_3m=0.0,
        price_change_5m=0.0,
        price_change_15m=0.0,
        price_change_1h=None,  # type: ignore[arg-type]
        price_change_24h=0.0,
        volume_ratio=1.0,
        btc_15m_change=0.0,
        reasons=[],
        suggested_action="观察",
        raw={"metadata": {"resonance_level": "L2"}},
    )

    assert format_alert_message(alert).splitlines()[0] == "BTC｜B级｜L2｜100.00｜-"


def test_format_alert_message_resonance_without_metadata_uses_unknown_level() -> None:
    alert = AlertSignal(
        timestamp=1,
        symbol="BTC/USDT:USDT",
        alert_type=AlertType.VOLUME_PRICE_OI_RESONANCE,
        level=AlertLevel.B,
        score=75,
        price=100.0,
        price_change_3m=0.0,
        price_change_5m=0.0,
        price_change_15m=0.0,
        price_change_1h=None,  # type: ignore[arg-type]
        price_change_24h=0.0,
        volume_ratio=1.0,
        btc_15m_change=0.0,
        reasons=[],
        suggested_action="观察",
        raw={"metadata": {}},
    )

    message = format_alert_message(alert)

    assert message.splitlines()[0] == "BTC｜B级｜L?｜100.00｜-"
    assert "\n核心理由：\n-\n" in message


def test_web_display_filters_are_shared_and_tolerant() -> None:
    assert display_symbol_base("IN/USDT:USDT") == "IN"
    assert alert_type_label("HOURLY_TREND_T1") == "小时趋势启动"
    assert alert_type_label("UNKNOWN_ALERT") == "UNKNOWN_ALERT"
    assert chinese_reason_text("english / 中文") == "中文"
    assert chinese_reason_text("") == ""
