"""Read and summarize local operation logs for the admin panel.
为后台工作日志页读取并汇总本地运行日志。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


LOG_PATTERN = re.compile(r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+(?P<level>[A-Z]+)\s+(?P<logger>\S+)\s+(?P<message>.*)$")
SECRET_PATTERNS = [
    re.compile(r"(?i)(bot\d+:[A-Za-z0-9_-]{20,})"),
    re.compile(r"(?i)(token|secret|api[_-]?key|chat[_-]?id)(=|:)\s*([^\s,&]+)"),
]


@dataclass(frozen=True)
class LogEntry:
    """One parsed log row ready for safe template rendering.
    一条已经解析并可安全渲染的日志。
    """

    timestamp: str
    level: str
    logger: str
    source: str
    status: str
    message: str
    raw: str


@dataclass(frozen=True)
class StatusCard:
    """Compact status card shown above the log table.
    日志表上方的紧凑状态卡。
    """

    title: str
    value: str
    detail: str
    tone: str = ""


def load_work_log_view(
    base_dir: Path,
    *,
    source: str = "all",
    level: str = "all",
    query: str = "",
    limit: int = 200,
) -> dict[str, object]:
    """Load a bounded, filterable view of local operation logs.
    读取有限数量的本地运行日志，并按页面筛选条件组织视图数据。
    """

    safe_limit = max(20, min(limit, 1000))
    log_files = discover_log_files(base_dir / "logs")
    entries = parse_log_lines(read_log_tail_lines(log_files, max_lines_per_file=1000))
    filtered = filter_entries(entries, source=source, level=level, query=query)
    if source == "all" and not query.strip():
        filtered = [entry for entry in filtered if not is_routine_noise(entry)]
    filtered = filtered[:safe_limit]
    return {
        "entries": filtered,
        "cards": build_status_cards(entries),
        "selected": filtered[0] if filtered else None,
        "filters": {"source": source, "level": level, "q": query, "limit": safe_limit},
        "log_files": [f"logs/{path.name}" for path in log_files],
    }


def discover_log_files(log_dir: Path) -> list[Path]:
    """Return local log files under the project log directory only.
    只发现项目 logs 目录下的本地日志文件。
    """

    if not log_dir.exists() or not log_dir.is_dir():
        return []
    return sorted(path for path in log_dir.glob("*.log") if path.is_file())


def read_log_tail_lines(paths: list[Path], max_lines_per_file: int = 1000) -> list[str]:
    """Read tail lines from all known log files.
    从所有已知日志文件读取尾部行。
    """

    lines: list[str] = []
    for path in paths:
        lines.extend(read_tail_lines(path, max_lines=max_lines_per_file))
    return lines


def read_tail_lines(path: Path, max_lines: int = 1000) -> list[str]:
    """Read only the last N lines so a growing log file cannot slow the page down.
    只读取日志尾部，避免日志文件变大后拖慢 Web 页面。
    """

    if not path.exists() or not path.is_file():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return [line.rstrip("\n") for line in lines[-max_lines:]]


def parse_log_lines(lines: list[str]) -> list[LogEntry]:
    """Parse Python logging output and attach continuation lines to the prior row.
    解析 Python logging 输出，并把多行消息续接到上一条日志。
    """

    entries: list[LogEntry] = []
    current: LogEntry | None = None
    for line in lines:
        match = LOG_PATTERN.match(line)
        if match:
            if current:
                entries.append(current)
            current = build_entry(
                timestamp=match.group("time"),
                level=match.group("level"),
                logger=match.group("logger"),
                message=match.group("message"),
                raw=line,
            )
            continue
        if current and line.strip():
            message = f"{current.message}\n{redact_secrets(line)}"
            raw = f"{current.raw}\n{redact_secrets(line)}"
            current = LogEntry(current.timestamp, current.level, current.logger, current.source, current.status, message, raw)
    if current:
        entries.append(current)
    return list(reversed(entries))


def build_entry(timestamp: str, level: str, logger: str, message: str, raw: str) -> LogEntry:
    """Normalize one parsed row into the fields the template needs.
    将一条原始日志归一化为模板需要展示的字段。
    """

    safe_message = redact_secrets(message)
    safe_raw = redact_secrets(raw)
    return LogEntry(
        timestamp=timestamp,
        level=level,
        logger=logger,
        source=classify_source(logger, safe_message),
        status=classify_status(level, safe_message),
        message=safe_message,
        raw=safe_raw,
    )


def classify_source(logger: str, message: str) -> str:
    """Map noisy logger/message text to operator-friendly sources.
    将 logger 和消息归类成运维更容易筛选的来源。
    """

    text = f"{logger} {message}".lower()
    if "telegram" in text:
        return "telegram"
    if "paper order" in text or "created paper order" in text:
        return "paper_order"
    if "paper cycle" in text or "paper account equity" in text or "risk ignored non-actionable signal" in text or re.search(r"\bsignal\s+\S+\s+none:", text):
        return "paper_cycle"
    if "binance" in text or "open interest" in text or "fetch" in text:
        return "exchange"
    if "alert radar" in text or "app.alerts" in text:
        return "radar_loop"
    return "system"


def classify_status(level: str, message: str) -> str:
    """Provide a short status word for scanning the table.
    为表格扫描提供简短状态词。
    """

    lowered = message.lower()
    if level in {"ERROR", "CRITICAL"} or "failed" in lowered:
        return "failed"
    if "disabled" in lowered:
        return "disabled"
    if "created paper order" in lowered:
        return "created"
    if "with 0 alerts" in lowered:
        return "quiet"
    if "with " in lowered and " alerts" in lowered:
        return "alert"
    if "sent" in lowered:
        return "sent"
    return "ok"


def is_routine_noise(entry: LogEntry) -> bool:
    """Return whether a log line is a high-frequency non-actionable paper trace.
    默认视图隐藏逐币无信号/忽略日志，保留页面对异常和关键事件的扫描价值。
    """

    if entry.source != "paper_cycle" or entry.level not in {"INFO", "DEBUG"}:
        return False
    lowered = entry.message.lower()
    return "risk ignored non-actionable signal" in lowered or bool(re.search(r"\bsignal\s+\S+\s+none:", lowered))


def filter_entries(entries: list[LogEntry], *, source: str, level: str, query: str) -> list[LogEntry]:
    """Apply page filters without mutating the parsed log list.
    应用页面筛选条件，同时保持原始解析结果不变。
    """

    query_text = query.strip().lower()
    result = entries
    if source and source != "all":
        result = [entry for entry in result if entry.source == source]
    if level and level != "all":
        allowed = {"WARN": {"WARNING", "ERROR", "CRITICAL"}, "ERROR": {"ERROR", "CRITICAL"}}.get(level, {level})
        result = [entry for entry in result if entry.level in allowed]
    if query_text:
        result = [entry for entry in result if query_text in f"{entry.source} {entry.level} {entry.message}".lower()]
    return result


def build_status_cards(entries: list[LogEntry]) -> list[StatusCard]:
    """Summarize the latest parsed logs into four operational cards.
    将最近日志汇总为四张运维状态卡。
    """

    radar_entry = next((entry for entry in entries if entry.source == "radar_loop" and "cycle finished" in entry.message.lower()), None)
    alert_count = extract_alert_count(radar_entry.message) if radar_entry else None
    telegram_entry = next((entry for entry in entries if entry.source == "telegram"), None)
    error_count = sum(1 for entry in entries if entry.level in {"ERROR", "CRITICAL"} or entry.status == "failed")

    return [
        StatusCard(
            title="Radar Loop",
            value="运行中" if radar_entry else "无日志",
            detail=f"上一轮 {radar_entry.timestamp}" if radar_entry else "未找到 radar_loop 完成记录",
            tone="ok" if radar_entry else "warn",
        ),
        StatusCard(
            title="Last Cycle Alerts",
            value=str(alert_count) if alert_count is not None else "-",
            detail="上一轮产生的提醒数量" if alert_count is not None else "等待下一轮扫描完成",
        ),
        StatusCard(
            title="Telegram",
            value=telegram_status_label(telegram_entry),
            detail=telegram_entry.timestamp if telegram_entry else "未找到 Telegram 日志",
            tone=telegram_status_tone(telegram_entry),
        ),
        StatusCard(
            title="Errors",
            value=str(error_count),
            detail="最近日志窗口内失败/异常数量",
            tone="bad" if error_count else "ok",
        ),
    ]


def extract_alert_count(message: str) -> int | None:
    """Extract alert count from the radar completion line.
    从雷达完成日志中提取本轮提醒数量。
    """

    match = re.search(r"with\s+(\d+)\s+alerts?", message)
    return int(match.group(1)) if match else None


def telegram_status_label(entry: LogEntry | None) -> str:
    """Return a short human label for the latest Telegram state.
    返回最近 Telegram 状态的中文短标签。
    """

    if entry is None:
        return "无日志"
    if entry.status == "disabled":
        return "未启用"
    if entry.status == "failed":
        return "失败"
    return "有记录"


def telegram_status_tone(entry: LogEntry | None) -> str:
    """Color Telegram status by operational severity.
    按运维严重程度给 Telegram 状态上色。
    """

    if entry is None or entry.status == "disabled":
        return "warn"
    if entry.status == "failed":
        return "bad"
    return "ok"


def redact_secrets(text: str) -> str:
    """Hide token-like values before any log text reaches the browser.
    日志进入浏览器前先隐藏疑似密钥内容。
    """

    redacted = text
    redacted = SECRET_PATTERNS[0].sub("[redacted-token]", redacted)
    redacted = SECRET_PATTERNS[1].sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", redacted)
    return redacted
