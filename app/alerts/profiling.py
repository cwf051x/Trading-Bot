"""Lightweight profiling helpers for alert radar cycles.
行情雷达轮询的轻量耗时统计工具。
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import logging
from threading import Lock
import time
from typing import Callable, Iterator


class CycleProfiler:
    """Aggregate named timings for one radar loop.
    汇总单轮雷达循环内各阶段的耗时。
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self.clock = clock or time.perf_counter
        self._steps: OrderedDict[str, dict[str, float | int]] = OrderedDict()
        self._meta: OrderedDict[str, int | float | str] = OrderedDict()
        self._lock = Lock()

    def add(self, name: str, seconds: float) -> None:
        """Add elapsed seconds for a named step.
        累加某个阶段的耗时，重复阶段会合并统计。
        """

        with self._lock:
            step = self._steps.setdefault(name, {"seconds": 0.0, "count": 0})
            step["seconds"] = float(step["seconds"]) + max(0.0, seconds)
            step["count"] = int(step["count"]) + 1

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        """Measure a block and aggregate it under the given name.
        统计代码块耗时并归入指定阶段。
        """

        started_at = self.clock()
        try:
            yield
        finally:
            self.add(name, self.clock() - started_at)

    def merge(self, other: "CycleProfiler") -> None:
        """Merge another profiler into this cycle summary.
        将子模块 profiling 数据合并到当前循环汇总。
        """

        for name, step in other.steps.items():
            for _ in range(int(step["count"])):
                self.add(name, float(step["seconds"]) / max(1, int(step["count"])))
        with self._lock:
            self._meta.update(other.meta)

    def set_meta(self, **values: int | float | str) -> None:
        """Attach compact cycle metadata to the headline.
        为日志首行附加交易对数、提醒数等元信息。
        """

        with self._lock:
            for key, value in values.items():
                self._meta[key] = value

    @property
    def steps(self) -> OrderedDict[str, dict[str, float | int]]:
        """Return recorded steps in first-seen order.
        按首次出现顺序返回已记录阶段。
        """

        with self._lock:
            return OrderedDict((name, dict(step)) for name, step in self._steps.items())

    @property
    def meta(self) -> OrderedDict[str, int | float | str]:
        """Return cycle metadata.
        返回本轮循环的元信息。
        """

        with self._lock:
            return OrderedDict(self._meta)

    def log(self, logger: logging.Logger, total_seconds: float) -> None:
        """Emit a multi-line profiling summary.
        输出多行 profiling 摘要，便于在日志页直接定位瓶颈。
        """

        with self._lock:
            meta = OrderedDict(self._meta)
            steps = OrderedDict((name, dict(step)) for name, step in self._steps.items())
        meta_text = " ".join(f"{key}={value}" for key, value in meta.items())
        headline = f"[radar-loop] total={total_seconds:.1f}s"
        if meta_text:
            headline = f"{headline} {meta_text}"
        lines = [headline]
        for name, step in steps.items():
            lines.append(f"  {name}={float(step['seconds']):.1f}s count={int(step['count'])}")
        logger.info("\n".join(lines))
