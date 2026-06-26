"""SQLite persistence for paper trading records.
模拟盘交易记录的 SQLite 持久化实现。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteStorage:
    """Small SQLite repository for orders and positions.
    用于订单、持仓和交易记录的小型 SQLite 仓储。
    """

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)

    def connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with dict-like rows.
        打开 SQLite 连接，并启用类字典行对象。
        """

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        # WAL + busy_timeout 降低 trading-bot / admin-web / radar 并发访问时的锁冲突概率。
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        """Create storage tables.
        创建存储所需的数据表。
        """

        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL,
                    status TEXT NOT NULL,
                    exit_price REAL,
                    pnl REAL,
                    exit_reason TEXT,
                    opened_at INTEGER NOT NULL DEFAULT 0,
                    closed_at INTEGER,
                    FOREIGN KEY(order_id) REFERENCES orders(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    pnl REAL NOT NULL,
                    exit_reason TEXT NOT NULL,
                    opened_at INTEGER NOT NULL,
                    closed_at INTEGER NOT NULL,
                    FOREIGN KEY(position_id) REFERENCES positions(id)
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_one_open_symbol_side
                ON positions(symbol, side)
                WHERE status = 'open'
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    level TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    price REAL NOT NULL,
                    price_change_3m REAL NOT NULL,
                    price_change_5m REAL NOT NULL,
                    price_change_15m REAL NOT NULL,
                    price_change_1h REAL NOT NULL,
                    price_change_24h REAL NOT NULL,
                    volume_ratio REAL NOT NULL,
                    btc_15m_change REAL NOT NULL,
                    reason TEXT NOT NULL,
                    suggested_action TEXT NOT NULL,
                    invalidation_price REAL,
                    target_1 REAL,
                    target_2 REAL,
                    sent_to_telegram INTEGER NOT NULL,
                    raw_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_states (
                    symbol TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    last_alert_type TEXT,
                    last_alert_score INTEGER,
                    last_alert_price REAL,
                    last_alert_at INTEGER,
                    watch_high REAL,
                    watch_low REAL,
                    support_price REAL,
                    invalidation_price REAL,
                    metadata_json TEXT NOT NULL
                )
                """
            )

    def create_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float | None,
        status: str,
        reason: str,
        timestamp: int,
    ) -> int:
        """Insert an order and return its id.
        插入订单并返回订单 ID。
        """

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO orders(symbol, side, quantity, entry_price, stop_loss, take_profit, status, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (symbol, side, quantity, entry_price, stop_loss, take_profit, status, reason, timestamp),
            )
            return int(cursor.lastrowid)

    def create_position(
        self,
        order_id: int,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float | None,
        opened_at: int,
    ) -> int:
        """Insert an open position and return its id.
        插入开仓持仓并返回持仓 ID。
        """

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO positions(order_id, symbol, side, quantity, entry_price, stop_loss, take_profit, status, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (order_id, symbol, side, quantity, entry_price, stop_loss, take_profit, opened_at),
            )
            return int(cursor.lastrowid)

    def create_open_order_position(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float | None,
        reason: str,
        timestamp: int,
    ) -> dict[str, int] | None:
        """Atomically create an open order and its position when no duplicate exists.
        在同一个写事务里检查并创建订单/持仓，避免先查后插导致重复开仓。
        """

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM positions WHERE status = 'open' AND symbol = ? AND side = ? LIMIT 1",
                (symbol, side),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return None
            order_cursor = connection.execute(
                """
                INSERT INTO orders(symbol, side, quantity, entry_price, stop_loss, take_profit, status, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)
                """,
                (symbol, side, quantity, entry_price, stop_loss, take_profit, reason, timestamp),
            )
            order_id = int(order_cursor.lastrowid)
            position_cursor = connection.execute(
                """
                INSERT INTO positions(order_id, symbol, side, quantity, entry_price, stop_loss, take_profit, status, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (order_id, symbol, side, quantity, entry_price, stop_loss, take_profit, timestamp),
            )
            connection.commit()
            return {"order_id": order_id, "position_id": int(position_cursor.lastrowid)}

    def get_open_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return open positions.
        返回当前未平仓持仓。
        """

        with self.connect() as connection:
            if symbol:
                rows = connection.execute("SELECT * FROM positions WHERE status = 'open' AND symbol = ?", (symbol,)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM positions WHERE status = 'open'").fetchall()
        return [dict(row) for row in rows]

    def get_orders(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent simulated orders.
        返回最近的模拟订单。
        """

        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def query_records(
        self,
        table: str,
        *,
        search_columns: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        query: str = "",
        sort_by: str = "id",
        direction: str = "desc",
        limit: int = 25,
        offset: int = 0,
        allowed_tables: dict[str, set[str]] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return filtered rows and total count for admin tables.
        用白名单控制表名和排序列，避免把页面参数直接拼成危险 SQL。
        """

        allowed = allowed_tables or self._admin_table_columns()
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        columns = allowed[table]
        if sort_by not in columns:
            sort_by = "id"
        direction_sql = "ASC" if direction.lower() == "asc" else "DESC"
        where_sql, params = self._build_table_where(columns, search_columns or [], filters or {}, query)
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, int(offset))
        with self.connect() as connection:
            total_row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}{where_sql}", params).fetchone()
            rows = connection.execute(
                f"SELECT * FROM {table}{where_sql} ORDER BY {sort_by} {direction_sql}, id DESC LIMIT ? OFFSET ?",
                [*params, safe_limit, safe_offset],
            ).fetchall()
        return [dict(row) for row in rows], int(total_row["count"] if total_row else 0)

    @staticmethod
    def _admin_table_columns() -> dict[str, set[str]]:
        """Columns that the admin UI is allowed to query dynamically.
        后台动态表格允许访问的列白名单。
        """

        return {
            "orders": {"id", "symbol", "side", "quantity", "entry_price", "stop_loss", "take_profit", "status", "reason", "timestamp"},
            "positions": {
                "id",
                "order_id",
                "symbol",
                "side",
                "quantity",
                "entry_price",
                "stop_loss",
                "take_profit",
                "status",
                "exit_price",
                "pnl",
                "exit_reason",
                "opened_at",
                "closed_at",
            },
            "trades": {"id", "position_id", "symbol", "side", "quantity", "entry_price", "exit_price", "pnl", "exit_reason", "opened_at", "closed_at"},
            "market_alerts": {
                "id",
                "timestamp",
                "symbol",
                "alert_type",
                "level",
                "score",
                "price",
                "price_change_3m",
                "price_change_5m",
                "price_change_15m",
                "price_change_1h",
                "price_change_24h",
                "volume_ratio",
                "btc_15m_change",
                "reason",
                "suggested_action",
                "invalidation_price",
                "target_1",
                "target_2",
                "sent_to_telegram",
                "raw_json",
            },
        }

    @staticmethod
    def _build_table_where(columns: set[str], search_columns: list[str], filters: dict[str, Any], query: str) -> tuple[str, list[Any]]:
        """Build a parameterized WHERE clause for simple admin filters.
        构建后台列表筛选条件，所有值都使用参数绑定。
        """

        clauses: list[str] = []
        params: list[Any] = []
        for column, value in filters.items():
            if column not in columns or value in (None, "", "all"):
                continue
            clauses.append(f"{column} = ?")
            params.append(value)
        clean_query = query.strip()
        searchable = [column for column in search_columns if column in columns]
        if clean_query and searchable:
            clauses.append("(" + " OR ".join(f"{column} LIKE ?" for column in searchable) + ")")
            params.extend([f"%{clean_query}%"] * len(searchable))
        return (" WHERE " + " AND ".join(clauses), params) if clauses else ("", params)

    def get_positions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent positions regardless of status.
        返回最近的全部持仓记录，不区分状态。
        """

        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM positions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def has_open_position(self, symbol: str, side: str | None = None) -> bool:
        """Return whether an open position already exists.
        判断是否已经存在未平仓持仓。
        """

        with self.connect() as connection:
            if side:
                row = connection.execute("SELECT 1 FROM positions WHERE status = 'open' AND symbol = ? AND side = ? LIMIT 1", (symbol, side)).fetchone()
            else:
                row = connection.execute("SELECT 1 FROM positions WHERE status = 'open' AND symbol = ? LIMIT 1", (symbol,)).fetchone()
        return row is not None

    def close_position(self, position_id: int, exit_price: float, pnl: float, exit_reason: str, timestamp: int) -> bool:
        """Mark an open position as closed.
        将未平仓持仓标记为已平仓，并写入交易记录。
        """

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
            if row is None:
                raise ValueError(f"Position {position_id} does not exist")
            if row["status"] != "open":
                connection.rollback()
                return False
            connection.execute(
                """
                UPDATE positions
                SET status = 'closed', exit_price = ?, pnl = ?, exit_reason = ?, closed_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (exit_price, pnl, exit_reason, timestamp, position_id),
            )
            connection.execute(
                """
                INSERT INTO trades(position_id, symbol, side, quantity, entry_price, exit_price, pnl, exit_reason, opened_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position_id,
                    row["symbol"],
                    row["side"],
                    row["quantity"],
                    row["entry_price"],
                    exit_price,
                    pnl,
                    exit_reason,
                    row["opened_at"],
                    timestamp,
                ),
            )
            connection.commit()
            return True

    def get_trades(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return closed trade records.
        返回已平仓交易记录。
        """

        with self.connect() as connection:
            if limit is None:
                rows = connection.execute("SELECT * FROM trades ORDER BY id").fetchall()
            else:
                rows = connection.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_realized_pnl(self) -> float:
        """Return total realized PnL from closed trades.
        返回已平仓交易的累计已实现盈亏。
        """

        with self.connect() as connection:
            row = connection.execute("SELECT COALESCE(SUM(pnl), 0) AS realized_pnl FROM trades").fetchone()
        return float(row["realized_pnl"])

    def get_recent_closed_trades(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return latest closed trades for runtime risk checks.
        返回最近平仓交易，用于运行时连续亏损风控。
        """

        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM trades ORDER BY closed_at DESC, id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
        return [dict(row) for row in rows]

    def get_paper_performance_summary(self, leverage: float = 1.0) -> dict[str, float | int]:
        """Return paper trading performance and open-risk aggregates.
        汇总模拟盘收益、胜率、退出分布和当前未平仓风险。
        """

        safe_leverage = max(float(leverage or 1.0), 1.0)
        with self.connect() as connection:
            order_row = connection.execute("SELECT COUNT(*) AS total_orders FROM orders").fetchone()
            trade_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS closed_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                    SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losing_trades,
                    COALESCE(SUM(pnl), 0) AS realized_pnl,
                    COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) AS gross_profit,
                    COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) AS gross_loss,
                    AVG(CASE WHEN pnl > 0 THEN pnl END) AS avg_win,
                    AVG(CASE WHEN pnl < 0 THEN pnl END) AS avg_loss,
                    MAX(pnl) AS max_win,
                    MIN(pnl) AS max_loss,
                    SUM(CASE WHEN exit_reason = 'take_profit' THEN 1 ELSE 0 END) AS take_profit_count,
                    SUM(CASE WHEN exit_reason = 'stop_loss' THEN 1 ELSE 0 END) AS stop_loss_count
                FROM trades
                """
            ).fetchone()
            open_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS open_positions,
                    COALESCE(SUM(entry_price * quantity), 0) AS open_notional
                FROM positions
                WHERE status = 'open'
                """
            ).fetchone()

        total_orders = int(order_row["total_orders"] or 0)
        closed_trades = int(trade_row["closed_trades"] or 0)
        winning_trades = int(trade_row["winning_trades"] or 0)
        losing_trades = int(trade_row["losing_trades"] or 0)
        gross_loss = float(trade_row["gross_loss"] or 0.0)
        open_notional = float(open_row["open_notional"] or 0.0)
        return {
            "total_orders": total_orders,
            "open_positions": int(open_row["open_positions"] or 0),
            "closed_trades": closed_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": winning_trades / closed_trades if closed_trades else 0.0,
            "realized_pnl": float(trade_row["realized_pnl"] or 0.0),
            "gross_profit": float(trade_row["gross_profit"] or 0.0),
            "gross_loss": gross_loss,
            "profit_factor": float(trade_row["gross_profit"] or 0.0) / gross_loss if gross_loss else 0.0,
            "avg_win": float(trade_row["avg_win"] or 0.0),
            "avg_loss": float(trade_row["avg_loss"] or 0.0),
            "max_win": float(trade_row["max_win"] or 0.0),
            "max_loss": float(trade_row["max_loss"] or 0.0),
            "take_profit_count": int(trade_row["take_profit_count"] or 0),
            "stop_loss_count": int(trade_row["stop_loss_count"] or 0),
            "other_exit_count": max(0, closed_trades - int(trade_row["take_profit_count"] or 0) - int(trade_row["stop_loss_count"] or 0)),
            "open_notional": open_notional,
            "open_margin": open_notional / safe_leverage,
        }

    def save_market_alert(self, alert: dict[str, Any]) -> int:
        """Insert a market alert and return its id.
        插入行情提醒并返回提醒 ID。
        """

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO market_alerts(
                    timestamp, symbol, alert_type, level, score, price,
                    price_change_3m, price_change_5m, price_change_15m, price_change_1h, price_change_24h,
                    volume_ratio, btc_15m_change, reason, suggested_action, invalidation_price, target_1, target_2,
                    sent_to_telegram, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert["timestamp"],
                    alert["symbol"],
                    alert["alert_type"],
                    alert["level"],
                    alert["score"],
                    alert["price"],
                    alert["price_change_3m"],
                    alert["price_change_5m"],
                    alert["price_change_15m"],
                    alert["price_change_1h"],
                    alert["price_change_24h"],
                    alert["volume_ratio"],
                    alert["btc_15m_change"],
                    alert["reason"],
                    alert["suggested_action"],
                    alert.get("invalidation_price"),
                    alert.get("target_1"),
                    alert.get("target_2"),
                    1 if alert.get("sent_to_telegram") else 0,
                    json.dumps(alert.get("raw_json") or {}, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def get_market_alerts(self, limit: int = 100, alert_type: str | None = None) -> list[dict[str, Any]]:
        """Return recent market alerts.
        返回最近的行情提醒。
        """

        with self.connect() as connection:
            if alert_type:
                rows = connection.execute("SELECT * FROM market_alerts WHERE alert_type = ? ORDER BY id DESC LIMIT ?", (alert_type, limit)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM market_alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_last_market_alert(self, symbol: str, alert_type: str, sent_only: bool = False) -> dict[str, Any] | None:
        """Return the latest alert for one symbol and alert type.
        返回某交易对某提醒类型的最近一条记录。
        """

        with self.connect() as connection:
            if sent_only:
                row = connection.execute(
                    """
                    SELECT * FROM market_alerts
                    WHERE symbol = ? AND alert_type = ? AND sent_to_telegram = 1
                    ORDER BY timestamp DESC, id DESC
                    LIMIT 1
                    """,
                    (symbol, alert_type),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM market_alerts
                    WHERE symbol = ? AND alert_type = ?
                    ORDER BY timestamp DESC, id DESC
                    LIMIT 1
                    """,
                    (symbol, alert_type),
                ).fetchone()
        return dict(row) if row else None

    def upsert_alert_state(self, state: dict[str, Any]) -> None:
        """Insert or update durable alert state for one symbol.
        插入或更新单个交易对的持久化提醒状态。
        """

        metadata_json = json.dumps(state.get("metadata_json") or {}, ensure_ascii=False)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO alert_states(
                    symbol, state, last_alert_type, last_alert_score, last_alert_price, last_alert_at,
                    watch_high, watch_low, support_price, invalidation_price, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    state = excluded.state,
                    last_alert_type = excluded.last_alert_type,
                    last_alert_score = excluded.last_alert_score,
                    last_alert_price = excluded.last_alert_price,
                    last_alert_at = excluded.last_alert_at,
                    watch_high = excluded.watch_high,
                    watch_low = excluded.watch_low,
                    support_price = excluded.support_price,
                    invalidation_price = excluded.invalidation_price,
                    metadata_json = excluded.metadata_json
                """,
                (
                    state["symbol"],
                    state["state"],
                    state.get("last_alert_type"),
                    state.get("last_alert_score"),
                    state.get("last_alert_price"),
                    state.get("last_alert_at"),
                    state.get("watch_high"),
                    state.get("watch_low"),
                    state.get("support_price"),
                    state.get("invalidation_price"),
                    metadata_json,
                ),
            )

    def get_alert_state(self, symbol: str) -> dict[str, Any] | None:
        """Return durable alert state for one symbol.
        返回单个交易对的持久化提醒状态。
        """

        with self.connect() as connection:
            row = connection.execute("SELECT * FROM alert_states WHERE symbol = ?", (symbol,)).fetchone()
        if row is None:
            return None
        payload = dict(row)
        try:
            payload["metadata_json"] = json.loads(payload.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            payload["metadata_json"] = {}
        return payload
