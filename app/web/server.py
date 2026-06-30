"""FastAPI administration panel for paper trading operations.
用于模拟盘运维的 FastAPI 管理后台。
"""

from __future__ import annotations

import csv
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.alerts.display import display_alert_type, display_reason_cn, display_symbol
from app.alerts.replay import ReplayConfig, ReplayOutcome, replay_symbol
from app.alerts.rule_config import load_radar_rule_config
from app.backtest.engine import BacktestEngine
from app.config import Settings
from app.exchange.binance import BinanceFuturesClient
from app.storage.sqlite import SQLiteStorage
from app.strategies.momentum_oi import MomentumOIStrategy
from app.web.env_editor import update_env_values
from app.web.work_logs import load_work_log_view
from scripts.replay_radar_signals import (
    default_cache_path,
    ensure_klines_csv,
    ensure_oi_csv,
    read_klines_csv,
    read_oi_csv,
    summarize,
    write_outcomes,
    write_summary,
)


BASE_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
CSRF_COOKIE_NAME = "csrf_token"
CSRF_PROTECTED_PATHS = {"/settings", "/backtests/run", "/replay"}


def format_datetime_ms(timestamp_ms: int | float | None) -> str:
    """Format millisecond epoch timestamps for templates.
    为模板格式化毫秒时间戳。
    """

    if not timestamp_ms:
        return "-"
    return datetime.fromtimestamp(float(timestamp_ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")


def format_percent(value: int | float | None) -> str:
    """Format decimal ratios as percentages for templates.
    为模板将小数比例格式化为百分比。
    """

    if value is None:
        return "-"
    return f"{float(value) * 100:+.2f}%"


def format_compact_number(value: int | float | None, decimals: int = 4) -> str:
    """Format table numbers without long floating-point tails.
    压缩表格数字展示，保留数据库精度但避免页面出现浮点长尾。
    """

    if value is None:
        return "-"
    text = f"{float(value):,.{decimals}f}".rstrip("0").rstrip(".")
    return text if text else "0"


def format_compact_price(value: int | float | None) -> str:
    """Format prices with enough precision for small crypto quotes.
    以有效数字展示价格，兼顾小币种价格和页面紧凑性。
    """

    if value is None:
        return "-"
    return f"{float(value):.6g}"


templates.env.filters["datetime_ms"] = format_datetime_ms
templates.env.filters["percent"] = format_percent
templates.env.filters["compact_number"] = format_compact_number
templates.env.filters["compact_price"] = format_compact_price

def display_symbol_base(symbol: str) -> str:
    """Return compact base asset text for web tables.
    返回表格使用的精简币名。
    """

    return display_symbol(symbol)


def alert_type_label(alert_type: str) -> str:
    """Translate stored alert type values for operators.
    将入库的提醒类型翻译成中文运营文案。
    """

    return display_alert_type(alert_type)


def chinese_reason_text(reason: str) -> str:
    """Keep only the Chinese half of bilingual alert reasons.
    只展示双语提醒理由中的中文部分。
    """

    return display_reason_cn(reason)


templates.env.filters["symbol_base"] = display_symbol_base
templates.env.filters["alert_type_label"] = alert_type_label
templates.env.filters["chinese_reason"] = chinese_reason_text


@dataclass(frozen=True)
class TableState:
    """Shared server-side table controls for admin pages.
    后台表格统一使用的服务端分页、排序和搜索状态。
    """

    page: int
    per_page: int
    total: int
    sort: str
    direction: str
    q: str
    path: str
    extra_params: dict[str, str]

    @property
    def total_pages(self) -> int:
        return max(1, ceil(self.total / self.per_page))

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    def page_url(self, page: int) -> str:
        return self.url(page=max(1, min(page, self.total_pages)))

    def sort_url(self, column: str) -> str:
        next_direction = "asc"
        if self.sort == column and self.direction == "asc":
            next_direction = "desc"
        return self.url(page=1, sort=column, direction=next_direction)

    def url(self, **overrides: Any) -> str:
        params: dict[str, Any] = {
            "page": overrides.get("page", self.page),
            "per_page": overrides.get("per_page", self.per_page),
            "sort": overrides.get("sort", self.sort),
            "direction": overrides.get("direction", self.direction),
            **self.extra_params,
        }
        query = overrides.get("q", self.q)
        if query:
            params["q"] = query
        return f"{self.path}?{urlencode(params)}"


@dataclass(frozen=True)
class RadarReplayView:
    """Rendered result for a web-triggered radar replay.
    Web 页面触发雷达回放后用于模板展示的结果。
    """

    symbol: str
    days: int
    detail_path: Path
    summary_path: Path
    signal_count: int
    summary: list[dict[str, Any]]
    details: list[dict[str, Any]]


def table_state(request: Request, *, allowed_sort: set[str], default_sort: str = "id", extra_params: dict[str, str] | None = None) -> TableState:
    """Parse bounded table parameters from a request.
    从请求中解析有边界的表格参数。
    """

    def parse_int(name: str, default: int) -> int:
        try:
            return int(request.query_params.get(name, str(default)))
        except ValueError:
            return default

    per_page = min(max(parse_int("per_page", 25), 1), 100)
    page = max(parse_int("page", 1), 1)
    sort = request.query_params.get("sort", default_sort)
    if sort not in allowed_sort:
        sort = default_sort
    direction = request.query_params.get("direction", "desc").lower()
    if direction not in {"asc", "desc"}:
        direction = "desc"
    return TableState(
        page=page,
        per_page=per_page,
        total=0,
        sort=sort,
        direction=direction,
        q=request.query_params.get("q", "").strip(),
        path=request.url.path,
        extra_params=extra_params or {},
    )


def with_total(state: TableState, total: int) -> TableState:
    """Return table state capped to the available page range.
    根据总数修正页码，避免请求超过最后一页时显示空列表。
    """

    capped = TableState(**{**state.__dict__, "total": total})
    if capped.page <= capped.total_pages:
        return capped
    return TableState(**{**capped.__dict__, "page": capped.total_pages})


def query_table_page(
    storage: SQLiteStorage,
    state: TableState,
    table: str,
    *,
    search_columns: list[str],
    filters: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], TableState]:
    """Query rows for the requested page and re-query when page is capped.
    查询当前页数据；当页码超过最后一页被修正时重新查询。
    """

    rows, total = storage.query_records(
        table,
        search_columns=search_columns,
        filters=filters,
        query=state.q,
        sort_by=state.sort,
        direction=state.direction,
        limit=state.per_page,
        offset=state.offset,
    )
    capped = with_total(state, total)
    if capped.page != state.page:
        rows, _ = storage.query_records(
            table,
            search_columns=search_columns,
            filters=filters,
            query=capped.q,
            sort_by=capped.sort,
            direction=capped.direction,
            limit=capped.per_page,
            offset=capped.offset,
        )
    return rows, capped


def create_app() -> FastAPI:
    """Create and configure the admin web application.
    创建并配置管理后台应用。
    """

    app = FastAPI(title="Trading Bot Admin")

    @app.middleware("http")
    async def csrf_middleware(request: Request, call_next: Any) -> Response:
        """Validate CSRF token for state-changing admin forms.
        对会修改状态的后台表单校验 CSRF，避免反代暴露后被跨站提交。
        """

        if request.method == "POST" and request.url.path in CSRF_PROTECTED_PATHS:
            body = await request.body()
            request._body = body  # type: ignore[attr-defined]
            form_token = parse_qs(body.decode("utf-8", errors="ignore")).get("csrf_token", [""])[0]
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
            if not form_token or not cookie_token or not secrets.compare_digest(form_token, cookie_token):
                return Response("CSRF token invalid", status_code=403)
        response = await call_next(request)
        csrf_token = getattr(request.state, "csrf_token", "")
        if csrf_token:
            response.set_cookie(CSRF_COOKIE_NAME, csrf_token, httponly=True, samesite="lax")
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return a lightweight health check response.
        返回轻量健康检查结果。
        """

        return {"status": "ok"}

    @app.get("/login")
    def login_page(request: Request) -> Response:
        settings = Settings()
        return templates.TemplateResponse(request, "login.html", {"auth_required": bool(settings.web_admin_token)})

    @app.post("/login")
    def login(token: str = Form(default="")) -> RedirectResponse:
        settings = Settings()
        if settings.web_admin_token and token != settings.web_admin_token:
            raise HTTPException(status_code=401, detail="Invalid admin token")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("admin_token", token, httponly=True, samesite="lax")
        return response

    @app.get("/")
    def dashboard(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        storage = build_storage(settings)
        snapshot = {
            "orders": storage.get_orders(limit=5),
            "positions": storage.get_positions(limit=5),
            "trades": storage.get_trades(limit=5),
            "summary": read_backtest_summary(),
        }
        return templates.TemplateResponse(request, "dashboard.html", base_context(request, settings, snapshot=snapshot))

    @app.get("/settings")
    def settings_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        return templates.TemplateResponse(request, "settings.html", base_context(request, settings, message=request.query_params.get("message", "")))

    @app.post("/settings")
    def save_settings(
        watch_symbols: str = Form(...),
        default_symbol: str = Form(...),
        default_timeframe: str = Form(...),
        btc_drop_threshold_15m: str = Form(...),
        account_equity: str = Form(...),
        poll_interval_seconds: str = Form(...),
        kline_limit: str = Form(...),
        paper_leverage: str = Form(...),
        strategy_breakout_window: str = Form(...),
        strategy_volume_window: str = Form(...),
        strategy_volume_multiplier: str = Form(...),
        strategy_stop_loss_pct: str = Form(...),
        strategy_take_profit_pct: str = Form(...),
        alert_radar_enabled: str = Form(...),
        alert_scan_interval_seconds: str = Form(...),
        alert_top_gainers_limit: str = Form(...),
        alert_min_24h_quote_volume_usdt: str = Form(...),
        alert_blacklist: str = Form(""),
        alert_watchlist: str = Form(""),
        alert_send_a_level: str = Form(...),
        alert_send_b_level: str = Form(...),
        alert_send_c_level: str = Form(...),
        alert_cooldown_a_seconds: str = Form(...),
        alert_cooldown_b_seconds: str = Form(...),
        alert_cooldown_c_seconds: str = Form(...),
        alert_surge_3m_threshold: str = Form(...),
        alert_surge_5m_threshold: str = Form(...),
        alert_surge_15m_threshold: str = Form(...),
        alert_volume_ratio_threshold: str = Form(...),
        alert_pullback_min_ratio: str = Form(...),
        alert_pullback_max_ratio: str = Form(...),
        alert_btc_dump_15m_threshold: str = Form(...),
        alert_high_risk_15m_change: str = Form(...),
        alert_high_risk_1h_change: str = Form(...),
        alert_min_breakout_close_position: str = Form(...),
        alert_second_leg_min_close_position: str = Form(...),
        alert_pullback_volume_contraction_max: str = Form(...),
        alert_overheat_rsi: str = Form(...),
        _: None = Depends(require_admin),
    ) -> RedirectResponse:
        """Persist safe runtime and strategy settings to `.env`.
        将安全的运行和策略参数保存到 `.env`。
        """

        try:
            update_env_values(
                BASE_DIR / ".env",
                {
                "WATCH_SYMBOLS": watch_symbols,
                "DEFAULT_SYMBOL": default_symbol,
                "DEFAULT_TIMEFRAME": default_timeframe,
                "BTC_DROP_THRESHOLD_15M": btc_drop_threshold_15m,
                "ACCOUNT_EQUITY": account_equity,
                "POLL_INTERVAL_SECONDS": poll_interval_seconds,
                "KLINE_LIMIT": kline_limit,
                "PAPER_LEVERAGE": paper_leverage,
                "STRATEGY_BREAKOUT_WINDOW": strategy_breakout_window,
                "STRATEGY_VOLUME_WINDOW": strategy_volume_window,
                "STRATEGY_VOLUME_MULTIPLIER": strategy_volume_multiplier,
                "STRATEGY_STOP_LOSS_PCT": strategy_stop_loss_pct,
                "STRATEGY_TAKE_PROFIT_PCT": strategy_take_profit_pct,
                "ALERT_RADAR_ENABLED": alert_radar_enabled,
                "ALERT_SCAN_INTERVAL_SECONDS": alert_scan_interval_seconds,
                "ALERT_TOP_GAINERS_LIMIT": alert_top_gainers_limit,
                "ALERT_MIN_24H_QUOTE_VOLUME_USDT": alert_min_24h_quote_volume_usdt,
                "ALERT_BLACKLIST": alert_blacklist,
                "ALERT_WATCHLIST": alert_watchlist,
                "ALERT_SEND_A_LEVEL": alert_send_a_level,
                "ALERT_SEND_B_LEVEL": alert_send_b_level,
                "ALERT_SEND_C_LEVEL": alert_send_c_level,
                "ALERT_COOLDOWN_A_SECONDS": alert_cooldown_a_seconds,
                "ALERT_COOLDOWN_B_SECONDS": alert_cooldown_b_seconds,
                "ALERT_COOLDOWN_C_SECONDS": alert_cooldown_c_seconds,
                "ALERT_SURGE_3M_THRESHOLD": alert_surge_3m_threshold,
                "ALERT_SURGE_5M_THRESHOLD": alert_surge_5m_threshold,
                "ALERT_SURGE_15M_THRESHOLD": alert_surge_15m_threshold,
                "ALERT_VOLUME_RATIO_THRESHOLD": alert_volume_ratio_threshold,
                "ALERT_PULLBACK_MIN_RATIO": alert_pullback_min_ratio,
                "ALERT_PULLBACK_MAX_RATIO": alert_pullback_max_ratio,
                "ALERT_BTC_DUMP_15M_THRESHOLD": alert_btc_dump_15m_threshold,
                "ALERT_HIGH_RISK_15M_CHANGE": alert_high_risk_15m_change,
                "ALERT_HIGH_RISK_1H_CHANGE": alert_high_risk_1h_change,
                "ALERT_MIN_BREAKOUT_CLOSE_POSITION": alert_min_breakout_close_position,
                "ALERT_SECOND_LEG_MIN_CLOSE_POSITION": alert_second_leg_min_close_position,
                "ALERT_PULLBACK_VOLUME_CONTRACTION_MAX": alert_pullback_volume_contraction_max,
                "ALERT_OVERHEAT_RSI": alert_overheat_rsi,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse("/settings?message=Settings%20saved.%20Restart%20paper%20service%20to%20apply.", status_code=303)

    @app.get("/backtests")
    def backtests_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        return templates.TemplateResponse(
            request,
            "backtests.html",
            base_context(request, settings, csv_files=list_backtest_csvs(), summary=read_backtest_summary()),
        )

    @app.get("/replay")
    def radar_replay_page(request: Request, _: None = Depends(require_admin)) -> Response:
        """Render the radar replay form.
        渲染雷达历史回放页面。
        """

        settings = Settings()
        return templates.TemplateResponse(request, "replay.html", base_context(request, settings, title="Radar Replay", replay=None, error=""))

    @app.post("/replay")
    def run_radar_replay_page(
        request: Request,
        symbol: str = Form(...),
        days: int = Form(30),
        warmup_bars: int = Form(120),
        cooldown_bars: int = Form(6),
        _: None = Depends(require_admin),
    ) -> Response:
        """Run one-symbol radar replay and render the result.
        执行单币种雷达回放并渲染结果。
        """

        settings = Settings()
        try:
            replay = run_radar_replay(symbol=symbol, days=days, warmup_bars=warmup_bars, cooldown_bars=cooldown_bars)
        except Exception as exc:
            return templates.TemplateResponse(
                request,
                "replay.html",
                base_context(request, settings, title="Radar Replay", replay=None, error=str(exc), form={"symbol": symbol, "days": days, "warmup_bars": warmup_bars, "cooldown_bars": cooldown_bars}),
                status_code=400,
            )
        return templates.TemplateResponse(
            request,
            "replay.html",
            base_context(request, settings, title="Radar Replay", replay=replay, error="", form={"symbol": replay.symbol, "days": replay.days, "warmup_bars": warmup_bars, "cooldown_bars": cooldown_bars}),
        )

    @app.post("/backtests/run")
    def run_backtest(csv_file: str = Form(...), _: None = Depends(require_admin)) -> RedirectResponse:
        settings = Settings()
        csv_path = safe_backtest_path(csv_file)
        symbol = infer_symbol_from_file(csv_path.name)
        strategy = MomentumOIStrategy(
            breakout_window=settings.strategy_breakout_window,
            volume_window=settings.strategy_volume_window,
            volume_multiplier=settings.strategy_volume_multiplier,
            btc_drop_threshold=settings.btc_drop_threshold_15m,
            stop_loss_pct=settings.strategy_stop_loss_pct,
            take_profit_pct=settings.strategy_take_profit_pct,
        )
        engine = BacktestEngine(
            strategy=strategy,
            initial_equity=settings.account_equity,
            symbol=symbol,
            btc_drop_threshold_15m=settings.btc_drop_threshold_15m,
        )
        result = engine.run_csv(csv_path)
        equity_path = csv_path.with_name(csv_path.stem + "_equity_curve.csv")
        result.export_equity_curve(equity_path)
        upsert_backtest_summary(symbol, csv_path, result.metrics)
        return RedirectResponse(f"/equity?file={equity_path.name}", status_code=303)

    @app.get("/equity")
    def equity_page(request: Request, file: str = "", _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        equity_files = list_equity_curve_csvs()
        selected = safe_backtest_path(file) if file else equity_files[0] if equity_files else None
        curve = read_equity_curve(selected) if selected else []
        return templates.TemplateResponse(
            request,
            "equity.html",
            base_context(
                request,
                settings,
                equity_files=equity_files,
                selected=selected.name if selected else "",
                curve=curve,
                svg_points=svg_points(curve),
            ),
        )

    @app.get("/orders")
    def orders_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        storage = build_storage(settings)
        state = table_state(request, allowed_sort={"id", "symbol", "side", "quantity", "entry_price", "status", "timestamp"}, default_sort="id")
        rows, state = query_table_page(storage, state, "orders", search_columns=["symbol", "side", "status", "reason"])
        summary = storage.get_paper_performance_summary(leverage=settings.paper_leverage)
        return templates.TemplateResponse(request, "orders.html", base_context(request, settings, rows=rows, table=state, performance=summary, title="Orders"))

    @app.get("/alerts")
    def alerts_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        storage = build_storage(settings)
        alert_filter = request.query_params.get("type", "all")
        alert_type = None if alert_filter == "all" else alert_filter
        extra_params = {"type": alert_filter}
        state = table_state(
            request,
            allowed_sort={"id", "timestamp", "symbol", "alert_type", "level", "score", "price", "price_change_15m", "price_change_1h", "price_change_24h", "volume_ratio"},
            default_sort="timestamp",
            extra_params=extra_params,
        )
        rows, state = query_table_page(
            storage,
            state,
            "market_alerts",
            search_columns=["symbol", "alert_type", "level", "reason", "suggested_action"],
            filters={"alert_type": alert_type},
        )
        return templates.TemplateResponse(
            request,
            "alerts.html",
            base_context(
                request,
                settings,
                rows=rows,
                table=state,
                alert_filter=alert_filter,
                title="行情雷达提醒",
            ),
        )

    @app.get("/logs")
    def logs_page(request: Request, _: None = Depends(require_admin)) -> Response:
        """Render local operation logs for radar and paper-trading diagnostics.
        渲染本地运行日志，辅助排查雷达和模拟盘问题。
        """

        settings = Settings()
        limit_text = request.query_params.get("limit", "200")
        try:
            limit = int(limit_text)
        except ValueError:
            limit = 200
        view = load_work_log_view(
            BASE_DIR,
            source=request.query_params.get("source", "all"),
            level=request.query_params.get("level", "all"),
            query=request.query_params.get("q", ""),
            limit=limit,
        )
        return templates.TemplateResponse(request, "logs.html", base_context(request, settings, title="Work Logs", **view))

    @app.get("/positions")
    def positions_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        storage = build_storage(settings)
        state = table_state(request, allowed_sort={"id", "symbol", "side", "quantity", "entry_price", "status", "pnl", "opened_at", "closed_at"}, default_sort="id")
        rows, state = query_table_page(storage, state, "positions", search_columns=["symbol", "side", "status", "exit_reason"])
        return templates.TemplateResponse(request, "positions.html", base_context(request, settings, rows=rows, table=state, title="Positions"))

    @app.get("/trades")
    def trades_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        storage = build_storage(settings)
        state = table_state(request, allowed_sort={"id", "symbol", "side", "quantity", "entry_price", "exit_price", "pnl", "exit_reason", "closed_at"}, default_sort="id")
        rows, state = query_table_page(storage, state, "trades", search_columns=["symbol", "side", "exit_reason"])
        summary = storage.get_paper_performance_summary(leverage=settings.paper_leverage)
        return templates.TemplateResponse(request, "trades.html", base_context(request, settings, rows=rows, table=state, performance=summary, title="Trades"))

    return app


def require_admin(request: Request) -> None:
    """Require the configured admin token when one is set.
    配置了后台令牌时要求通过令牌验证。
    """

    settings = Settings()
    if not settings.web_admin_token and not is_local_bind(settings.web_host):
        raise HTTPException(status_code=500, detail="WEB_ADMIN_TOKEN is required when WEB_HOST is not local")
    if not settings.web_admin_token:
        return
    token = request.cookies.get("admin_token", "")
    if token != settings.web_admin_token:
        raise HTTPException(status_code=303, headers={"Location": "/login"})


def is_local_bind(host: str) -> bool:
    """Return whether the admin server is bound only to local interfaces.
    判断 Web 后台是否只监听本地地址；非本地监听必须配置后台 token。
    """

    return host.strip().lower() in {"", "127.0.0.1", "localhost", "::1"}


def build_storage(settings: Settings) -> SQLiteStorage:
    """Initialize and return SQLite storage.
    初始化并返回 SQLite 存储。
    """

    storage = SQLiteStorage(settings.database_path)
    storage.initialize()
    return storage


def base_context(request: Request, settings: Settings, **extra: Any) -> dict[str, Any]:
    """Build shared template context.
    构建模板共享上下文。
    """

    context: dict[str, Any] = {
        "request": request,
        "settings": settings,
        "symbols": ", ".join(settings.active_symbols),
        "auth_enabled": bool(settings.web_admin_token),
        "csrf_token": request.cookies.get(CSRF_COOKIE_NAME) or secrets.token_urlsafe(32),
    }
    request.state.csrf_token = context["csrf_token"]
    context.update(extra)
    return context


def list_backtest_csvs() -> list[Path]:
    """Return historical CSV files available for backtesting.
    返回可用于回测的历史 CSV 文件。
    """

    backtests = BASE_DIR / "backtests"
    return sorted(path for path in backtests.glob("*.csv") if "equity_curve" not in path.name and "summary" not in path.name)


def list_equity_curve_csvs() -> list[Path]:
    """Return exported equity curve CSV files.
    返回已导出的收益曲线 CSV 文件。
    """

    return sorted((BASE_DIR / "backtests").glob("*equity_curve.csv"))


def safe_backtest_path(file_name: str) -> Path:
    """Resolve a backtest filename under the backtests directory.
    在 backtests 目录内安全解析回测文件名。
    """

    path = (BASE_DIR / "backtests" / Path(file_name).name).resolve()
    if not str(path).startswith(str((BASE_DIR / "backtests").resolve())) or path.suffix != ".csv":
        raise HTTPException(status_code=400, detail="Invalid CSV file")
    if not path.exists():
        raise HTTPException(status_code=404, detail="CSV file not found")
    return path


def run_radar_replay(symbol: str, days: int, warmup_bars: int, cooldown_bars: int) -> RadarReplayView:
    """Download/cache one symbol and replay all radar rules for the web page.
    为 Web 页面下载/缓存单个币种数据，并回放所有雷达规则。
    """

    normalized_symbol = normalize_replay_symbol(symbol)
    bounded_days = min(max(int(days), 1), 90)
    bounded_warmup = min(max(int(warmup_bars), 20), 500)
    bounded_cooldown = min(max(int(cooldown_bars), 0), 288)
    settings = Settings()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - bounded_days * 24 * 60 * 60 * 1000
    client = BinanceFuturesClient(
        settings.binance_api_key,
        settings.binance_api_secret,
        settings.exchange_proxy,
        settings.exchange_network_mode,
        settings.exchange_request_retries,
        settings.exchange_retry_delay_seconds,
    )
    cache_dir = BASE_DIR / "data" / "replay"
    report_dir = BASE_DIR / "reports"
    safe_name = replay_file_symbol(normalized_symbol)
    run_stamp = datetime.fromtimestamp(end_ms / 1000).strftime("%Y%m%d_%H%M%S")

    klines_path = ensure_klines_csv(client, normalized_symbol, default_cache_path(cache_dir, normalized_symbol, "5m", bounded_days, suffix="klines"), start_ms=start_ms, end_ms=end_ms)
    oi_5m_path = ensure_oi_csv(client, normalized_symbol, "5m", default_cache_path(cache_dir, normalized_symbol, "5m", bounded_days, suffix="oi"), start_ms=start_ms, end_ms=end_ms)
    oi_15m_path = ensure_oi_csv(client, normalized_symbol, "15m", default_cache_path(cache_dir, normalized_symbol, "15m", bounded_days, suffix="oi"), start_ms=start_ms, end_ms=end_ms)
    oi_1h_path = ensure_oi_csv(client, normalized_symbol, "1h", default_cache_path(cache_dir, normalized_symbol, "1h", bounded_days, suffix="oi"), start_ms=start_ms, end_ms=end_ms)

    outcomes = replay_symbol(
        normalized_symbol,
        read_klines_csv(klines_path),
        oi_5m=read_oi_csv(oi_5m_path),
        oi_15m=read_oi_csv(oi_15m_path),
        oi_1h=read_oi_csv(oi_1h_path),
        config=ReplayConfig(min_warmup_bars=bounded_warmup, cooldown_bars=bounded_cooldown),
        radar_rule_config=load_radar_rule_config(),
    )
    summary_rows = summarize(outcomes)
    detail_path = report_dir / f"radar_replay_{safe_name}_{bounded_days}d_{run_stamp}.csv"
    summary_path = report_dir / f"radar_replay_{safe_name}_{bounded_days}d_summary_{run_stamp}.csv"
    write_outcomes(detail_path, outcomes)
    write_summary(summary_path, summary_rows)
    return RadarReplayView(
        symbol=normalized_symbol,
        days=bounded_days,
        detail_path=detail_path,
        summary_path=summary_path,
        signal_count=len(outcomes),
        summary=summary_rows,
        details=replay_details(outcomes, limit=50),
    )


def normalize_replay_symbol(symbol: str) -> str:
    """Normalize flexible user input into a ccxt USDT swap symbol.
    将页面输入的币种统一成 ccxt USDT 永续合约格式。
    """

    text = symbol.strip().upper()
    if not text:
        raise ValueError("Symbol is required")
    if "/" in text:
        return text if ":" in text else f"{text}:USDT"
    base = text.removesuffix("USDT")
    return f"{base}/USDT:USDT"


def replay_file_symbol(symbol: str) -> str:
    """Build a compact symbol slug for report filenames.
    为报告文件名构建紧凑币种标识。
    """

    return symbol.upper().replace(":USDT", "").replace("/", "")


def replay_details(outcomes: list[ReplayOutcome], limit: int = 50) -> list[dict[str, Any]]:
    """Convert replay outcomes into rows for the web table.
    将回放结果转换为页面表格行。
    """

    rows: list[dict[str, Any]] = []
    for outcome in outcomes[:limit]:
        row: dict[str, Any] = {
            "symbol": outcome.symbol,
            "signal_type": outcome.signal_type,
            "level": outcome.level,
            "score": outcome.score,
            "trigger_time": outcome.trigger_time,
            "trigger_price": outcome.trigger_price,
            "mfe": outcome.max_favorable_return,
            "mae": outcome.max_adverse_return,
            "reasons": outcome.reasons,
        }
        row.update(outcome.forward_returns)
        rows.append(row)
    return rows


def read_backtest_summary() -> list[dict[str, str]]:
    """Read the latest backtest summary CSV.
    读取最新回测汇总 CSV。
    """

    path = BASE_DIR / "backtests" / "backtest_90d_summary.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def upsert_backtest_summary(symbol: str, csv_path: Path, metrics: dict[str, float]) -> None:
    """Update the summary CSV after a web-triggered backtest.
    在网页触发回测后更新汇总 CSV。
    """

    path = BASE_DIR / "backtests" / "backtest_90d_summary.csv"
    rows = [row for row in read_backtest_summary() if row.get("symbol") != symbol]
    rows.append(
        {
            "symbol": symbol,
            "csv_path": csv_path.as_posix(),
            "trade_count": f"{metrics['trade_count']:.0f}",
            "win_rate": f"{metrics['win_rate']:.4f}",
            "profit_factor": f"{metrics['profit_factor']:.4f}",
            "max_drawdown": f"{metrics['max_drawdown']:.6f}",
            "final_equity": f"{metrics['final_equity']:.4f}",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["symbol", "csv_path", "trade_count", "win_rate", "profit_factor", "max_drawdown", "final_equity"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_equity_curve(path: Path) -> list[dict[str, float]]:
    """Read an equity curve CSV.
    读取收益曲线 CSV。
    """

    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{"timestamp": float(row["timestamp"]), "equity": float(row["equity"])} for row in csv.DictReader(handle)]


def svg_points(curve: list[dict[str, float]], width: int = 900, height: int = 260) -> str:
    """Convert an equity curve into SVG polyline points.
    将收益曲线转换为 SVG 折线点。
    """

    if len(curve) < 2:
        return ""
    equities = [row["equity"] for row in curve]
    min_equity = min(equities)
    max_equity = max(equities)
    span = max(max_equity - min_equity, 1.0)
    points: list[str] = []
    for index, row in enumerate(curve):
        x = index / (len(curve) - 1) * width
        y = height - ((row["equity"] - min_equity) / span * height)
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def infer_symbol_from_file(file_name: str) -> str:
    """Infer a Binance USDT-M symbol from a generated CSV filename.
    从生成的 CSV 文件名推断 Binance USDT-M 交易对。
    """

    base = file_name.split("_", 1)[0]
    if base.endswith("USDTUSDT"):
        asset = base[: -len("USDTUSDT")]
        return f"{asset}/USDT:USDT"
    return "BTC/USDT:USDT"


app = create_app()
