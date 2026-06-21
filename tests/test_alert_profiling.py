"""Alert radar profiling log tests.
行情雷达 profiling 日志测试。
"""

import logging

from app.alerts.profiling import CycleProfiler


def test_cycle_profiler_aggregates_repeated_steps_and_logs_summary(caplog) -> None:
    profiler = CycleProfiler(clock=lambda: 10.0)
    profiler.add("fetch_klines_5m", 1.25)
    profiler.add("fetch_klines_5m", 2.75)
    profiler.add("fetch_open_interest", 0.5)
    profiler.set_meta(symbols=42, alerts=3)

    with caplog.at_level(logging.INFO):
        profiler.log(logging.getLogger("test.radar"), total_seconds=5.5)

    message = caplog.records[0].getMessage()
    assert "[radar-loop] total=5.5s symbols=42 alerts=3" in message
    assert "fetch_klines_5m=4.0s count=2" in message
    assert "fetch_open_interest=0.5s count=1" in message
