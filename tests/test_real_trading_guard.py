"""Real trading CI guard tests.
真实交易调用 CI 防线测试。
"""

from __future__ import annotations

from pathlib import Path

from scripts import check_no_real_trading_calls as guard


def write_case(tmp_path: Path, source: str) -> Path:
    """Write one temporary Python file for guard scanning.
    将测试代码写入临时文件，避免禁用调用出现在仓库源码中。
    """

    path = tmp_path / "case.py"
    path.write_text(source, encoding="utf-8")
    return path


def assert_blocked(tmp_path: Path, source: str) -> None:
    violations = guard.scan_file_paths([write_case(tmp_path, source)], root=tmp_path)
    assert violations


def assert_allowed(tmp_path: Path, source: str) -> None:
    violations = guard.scan_file_paths([write_case(tmp_path, source)], root=tmp_path)
    assert violations == []


def test_guard_blocks_exchange_create_order(tmp_path) -> None:
    assert_blocked(tmp_path, "def run(exchange):\n    exchange.create_" + "order({})\n")


def test_guard_blocks_create_order_with_allowlist_comment(tmp_path) -> None:
    assert_blocked(tmp_path, "def run(exchange):\n    exchange.create_" + "order({})  # create_open_order_position\n")


def test_guard_allows_internal_storage_create_order(tmp_path) -> None:
    assert_allowed(tmp_path, "def run(storage):\n    storage.create_" + "order('BTC', 'long')\n")


def test_guard_allows_create_open_order_position(tmp_path) -> None:
    assert_allowed(tmp_path, "def run(storage):\n    storage.create_open_order_position('BTC', 'long')\n")


def test_guard_blocks_exchange_control_and_private_api_calls(tmp_path) -> None:
    blocked_sources = [
        "def run(exchange):\n    exchange.set_" + "leverage(3)\n",
        "def run(exchange):\n    exchange.set_" + "margin_mode('isolated')\n",
        "def run(exchange):\n    exchange.fapi" + "PrivateGetAccount()\n",
        "def run(exchange):\n    exchange.private_" + "post_order({})\n",
        "URL = '/fapi/v1/' + 'order'\n",
    ]
    for source in blocked_sources:
        assert_blocked(tmp_path, source)
