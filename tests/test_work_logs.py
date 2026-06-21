"""Work log parsing tests.
工作日志解析测试。
"""

from pathlib import Path

from app.web.work_logs import build_status_cards, load_work_log_view, parse_log_lines, redact_secrets


def test_parse_log_lines_classifies_common_sources() -> None:
    entries = parse_log_lines(
        [
            "2026-06-21 18:20:02,123 ERROR app.main Paper cycle failed: binanceusdm GET https://fapi.binance.com/fapi/v1/klines",
            "2026-06-21 17:59:31,264 INFO root Alert radar cycle finished with 0 alerts",
            "2026-06-21 17:06:29,666 INFO app.notify.telegram Telegram disabled: B级信号",
        ]
    )

    assert [entry.source for entry in entries] == ["telegram", "radar_loop", "paper_cycle"]
    assert entries[0].status == "disabled"
    assert entries[1].status == "quiet"
    assert entries[2].status == "failed"


def test_parse_log_lines_keeps_multiline_messages() -> None:
    entries = parse_log_lines(
        [
            "2026-06-21 17:06:29,666 INFO app.notify.telegram Telegram disabled: alert",
            "币种：BTC/USDT:USDT",
            "评分：85/100",
        ]
    )

    assert len(entries) == 1
    assert "币种：BTC/USDT:USDT" in entries[0].message
    assert "评分：85/100" in entries[0].raw


def test_redact_secrets_hides_token_like_values() -> None:
    text = "TELEGRAM_BOT_TOKEN=bot123456:abcdefghijklmnopqrstuvwxyz CHAT_ID:1234567890 api_key=abc123"

    redacted = redact_secrets(text)

    assert "abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "1234567890" not in redacted
    assert "abc123" not in redacted
    assert "[redacted" in redacted


def test_load_work_log_view_filters_and_summarizes(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "alert_radar.log").write_text(
        "\n".join(
            [
                "2026-06-21 17:59:31,264 INFO root Alert radar cycle finished with 2 alerts",
                "2026-06-21 18:20:02,123 ERROR app.main Paper cycle failed: binanceusdm GET /fapi/v1/klines",
                "2026-06-21 18:21:02,123 INFO app.notify.telegram Telegram disabled: token=super-secret",
            ]
        ),
        encoding="utf-8",
    )

    view = load_work_log_view(tmp_path, source="telegram", level="all", query="", limit=20)
    cards = view["cards"]

    assert len(view["entries"]) == 1
    assert view["entries"][0].source == "telegram"
    assert "super-secret" not in view["entries"][0].message
    assert [card.value for card in cards] == ["运行中", "2", "未启用", "1"]
    assert view["log_files"] == ["logs/alert_radar.log"]


def test_load_work_log_view_reads_multiple_local_log_files(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "alert_radar.log").write_text("2026-06-21 17:59:31,264 INFO root Alert radar cycle finished with 0 alerts\n", encoding="utf-8")
    (log_dir / "paper.log").write_text("2026-06-21 18:20:02,123 ERROR app.main Paper cycle failed: binanceusdm GET /fapi/v1/klines\n", encoding="utf-8")

    view = load_work_log_view(tmp_path, source="all", level="ERROR", query="", limit=20)

    assert len(view["entries"]) == 1
    assert view["entries"][0].source == "paper_cycle"
    assert view["log_files"] == ["logs/alert_radar.log", "logs/paper.log"]


def test_build_status_cards_handles_empty_logs() -> None:
    cards = build_status_cards([])

    assert [card.value for card in cards] == ["无日志", "-", "无日志", "0"]
