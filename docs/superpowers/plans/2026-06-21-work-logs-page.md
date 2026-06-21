# Work Logs Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local admin Web page that summarizes radar loop health, system errors, Telegram status, and recent operational log lines.

**Architecture:** Read safe local log files from `logs/` only, parse common Python logging lines into display rows, and keep the UI read-only. The Web server owns routing and template rendering; a small helper module owns log parsing and status summarization so it can be tested without HTTP.

**Tech Stack:** FastAPI, Jinja2 templates, Python standard library, pytest.

---

### Task 1: Log Reader Helper

**Files:**
- Create: `app/web/work_logs.py`
- Test: `tests/test_work_logs.py`

- [ ] Add a `LogEntry` dataclass, a parser for lines shaped like `YYYY-MM-DD HH:MM:SS,mmm LEVEL logger message`, and a `load_work_log_view()` function that reads bounded tail lines from `logs/alert_radar.log`.
- [ ] Classify sources as `radar_loop`, `paper_cycle`, `telegram`, `paper_order`, `exchange`, or `system` from message/logger text.
- [ ] Build status cards for radar loop, latest alerts count, Telegram status, and recent errors.
- [ ] Redact sensitive token-like values from messages before rendering.
- [ ] Cover parsing, redaction, and summary behavior with pytest.

### Task 2: Web Route And Template

**Files:**
- Modify: `app/web/server.py`
- Modify: `app/web/templates/base.html`
- Create: `app/web/templates/logs.html`
- Test: `tests/test_web.py` or existing Web tests if present

- [ ] Add a protected `GET /logs` route that accepts `source`, `level`, `q`, and `limit` query params.
- [ ] Add a sidebar nav item for 工作日志.
- [ ] Create a compact dark trading-terminal page matching the existing design tokens.
- [ ] Render stat cards, filter controls, a responsive log table, and a details panel for the latest/selected row.

### Task 3: Verification

**Files:**
- Existing test suite

- [ ] Run focused tests for the helper and route.
- [ ] Run the full test suite.
- [ ] Start the local Web app if needed and visually inspect `/logs`.
