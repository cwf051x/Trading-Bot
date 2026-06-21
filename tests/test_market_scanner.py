"""Market scanner diagnostics tests.
行情扫描器诊断日志测试。
"""

import logging

from app.alerts.scanner import MarketScanner
from app.config import Settings


class FailingOIClient:
    def get_open_interest_history(self, symbol: str, period: str = "5m", limit: int = 30):
        raise TimeoutError("read timeout")


def test_oi_history_failures_are_summarized_once(caplog) -> None:
    scanner = MarketScanner(FailingOIClient(), Settings(_env_file=None))

    with caplog.at_level(logging.WARNING):
        assert scanner._get_open_interest_history_safe("OP/USDT:USDT") == []
        assert scanner._get_open_interest_history_safe("ARB/USDT:USDT") == []
        scanner._log_oi_failure_summary(total_symbols=10)

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert "OI history fetch failed for 2/10 symbols" in messages[0]
    assert "OP/USDT:USDT" in messages[0]
    assert "ARB/USDT:USDT" in messages[0]
    assert "Failed to fetch OP/USDT:USDT OI history" not in messages[0]
