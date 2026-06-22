"""FastAPI administration panel for paper trading operations.
用于模拟盘运维的 FastAPI 管理后台。
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.backtest.engine import BacktestEngine
from app.config import Settings
from app.data.symbol_universe import symbol_base
from app.storage.sqlite import SQLiteStorage
from app.strategies.momentum_oi import MomentumOIStrategy
from app.web.env_editor import update_env_values
from app.web.work_logs import load_work_log_view


BASE_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


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


templates.env.filters["datetime_ms"] = format_datetime_ms
templates.env.filters["percent"] = format_percent

ALERT_TYPE_LABELS = {
    "TOP_GAINER_MOMENTUM": "涨幅榜强势",
    "SHORT_TERM_SURGE": "短周期异动",
    "MULTI_TIMEFRAME_BREAKOUT": "多周期突破",
    "STRONG_PULLBACK_WATCH": "强势回调观察",
    "PULLBACK_SECOND_LEG": "回调二启",
    "HIGH_RISK_EXTENSION": "高位风险延伸",
    "VOLUME_PRICE_OI_RESONANCE": "量价OI共振",
    "HOURLY_TREND_T1": "小时趋势启动",
    "HOURLY_TREND_T2": "小时趋势加速",
    "HOURLY_TREND_T3": "小时回踩接多",
    "HOURLY_TREND_T4": "小时过热风险",
    "PUMP_PULLBACK_P1": "首波健康回调",
    "PUMP_PULLBACK_P2": "二波启动预警",
    "PUMP_PULLBACK_P3": "二波确认突破",
    "PUMP_PULLBACK_P4": "二波失败风险",
}


def display_symbol_base(symbol: str) -> str:
    """Return compact base asset text for web tables.
    返回表格使用的精简币名。
    """

    return symbol_base(symbol)


def alert_type_label(alert_type: str) -> str:
    """Translate stored alert type values for operators.
    将入库的提醒类型翻译成中文运营文案。
    """

    return ALERT_TYPE_LABELS.get(alert_type, alert_type)


def chinese_reason_text(reason: str) -> str:
    """Keep only the Chinese half of bilingual alert reasons.
    只展示双语提醒理由中的中文部分。
    """

    parts = []
    for item in reason.split(";"):
        text = item.strip()
        if not text:
            continue
        if "/" in text:
            text = text.rsplit("/", 1)[-1].strip()
        parts.append(text)
    return "；".join(parts)


templates.env.filters["symbol_base"] = display_symbol_base
templates.env.filters["alert_type_label"] = alert_type_label
templates.env.filters["chinese_reason"] = chinese_reason_text


def create_app() -> FastAPI:
    """Create and configure the admin web application.
    创建并配置管理后台应用。
    """

    app = FastAPI(title="Trading Bot Admin")

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
        return RedirectResponse("/settings?message=Settings%20saved.%20Restart%20paper%20service%20to%20apply.", status_code=303)

    @app.get("/backtests")
    def backtests_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        return templates.TemplateResponse(
            request,
            "backtests.html",
            base_context(request, settings, csv_files=list_backtest_csvs(), summary=read_backtest_summary()),
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
        return templates.TemplateResponse(request, "orders.html", base_context(request, settings, rows=storage.get_orders(limit=200), title="Orders"))

    @app.get("/alerts")
    def alerts_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        storage = build_storage(settings)
        alert_filter = request.query_params.get("type", "VOLUME_PRICE_OI_RESONANCE")
        alert_type = None if alert_filter == "all" else alert_filter
        return templates.TemplateResponse(
            request,
            "alerts.html",
            base_context(
                request,
                settings,
                rows=storage.get_market_alerts(limit=300, alert_type=alert_type),
                alert_filter=alert_filter,
                title="Market Alerts",
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
        return templates.TemplateResponse(request, "positions.html", base_context(request, settings, rows=storage.get_positions(limit=200), title="Positions"))

    @app.get("/trades")
    def trades_page(request: Request, _: None = Depends(require_admin)) -> Response:
        settings = Settings()
        storage = build_storage(settings)
        return templates.TemplateResponse(request, "trades.html", base_context(request, settings, rows=storage.get_trades(limit=200), title="Trades"))

    return app


def require_admin(request: Request) -> None:
    """Require the configured admin token when one is set.
    配置了后台令牌时要求通过令牌验证。
    """

    settings = Settings()
    if not settings.web_admin_token:
        return
    token = request.cookies.get("admin_token") or request.query_params.get("token", "")
    if token != settings.web_admin_token:
        raise HTTPException(status_code=303, headers={"Location": "/login"})


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
    }
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
