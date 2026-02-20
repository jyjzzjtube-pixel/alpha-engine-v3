# -*- coding: utf-8 -*-
"""
커맨드센터 전용 SQLite 데이터베이스
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .config import COMMAND_CENTER_DB
from .models import Alert, AlertType, Severity, OrderRecord, DeployRecord


class Database:
    """커맨드센터 DB 관리자"""

    def __init__(self, db_path: str = COMMAND_CENTER_DB):
        self.db_path = db_path
        self._init_tables()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_tables(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                message TEXT DEFAULT '',
                source TEXT DEFAULT '',
                timestamp TEXT NOT NULL,
                read INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                result TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                source TEXT DEFAULT 'manual',
                timestamp TEXT NOT NULL,
                duration_ms REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS deploys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                site_name TEXT NOT NULL,
                deploy_id TEXT DEFAULT '',
                status TEXT DEFAULT '',
                file_count INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL,
                duration_ms REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS uptime_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                status TEXT NOT NULL,
                status_code INTEGER DEFAULT 0,
                response_time REAL DEFAULT 0,
                error TEXT DEFAULT '',
                checked_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(timestamp);
            CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
            CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(timestamp);
            CREATE INDEX IF NOT EXISTS idx_uptime_site ON uptime_log(site_id, checked_at);
        """)
        conn.commit()
        conn.close()

    # ── Alerts ──
    def add_alert(self, alert: Alert) -> int:
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO alerts (alert_type, severity, title, message, source, timestamp, read) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (alert.alert_type.value, alert.severity.value, alert.title,
             alert.message, alert.source, alert.timestamp.isoformat(), 0),
        )
        alert_id = cur.lastrowid
        conn.commit()
        conn.close()
        return alert_id

    def get_alerts(self, limit: int = 50, alert_type: str = None,
                   unread_only: bool = False) -> List[Alert]:
        conn = self._conn()
        sql = "SELECT * FROM alerts WHERE 1=1"
        params = []
        if alert_type:
            sql += " AND alert_type = ?"
            params.append(alert_type)
        if unread_only:
            sql += " AND read = 0"
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [self._row_to_alert(r) for r in rows]

    def get_unread_count(self) -> int:
        conn = self._conn()
        count = conn.execute("SELECT COUNT(*) FROM alerts WHERE read = 0").fetchone()[0]
        conn.close()
        return count

    def mark_all_read(self):
        conn = self._conn()
        conn.execute("UPDATE alerts SET read = 1 WHERE read = 0")
        conn.commit()
        conn.close()

    def _row_to_alert(self, row) -> Alert:
        return Alert(
            id=row["id"],
            alert_type=AlertType(row["alert_type"]),
            severity=Severity(row["severity"]),
            title=row["title"],
            message=row["message"],
            source=row["source"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            read=bool(row["read"]),
        )

    # ── Orders ──
    def add_order(self, order: OrderRecord) -> int:
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO orders (command, result, status, source, timestamp, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (order.command, order.result, order.status, order.source,
             order.timestamp.isoformat(), order.duration_ms),
        )
        oid = cur.lastrowid
        conn.commit()
        conn.close()
        return oid

    def update_order(self, order_id: int, result: str, status: str, duration_ms: float):
        conn = self._conn()
        conn.execute(
            "UPDATE orders SET result = ?, status = ?, duration_ms = ? WHERE id = ?",
            (result, status, duration_ms, order_id),
        )
        conn.commit()
        conn.close()

    def get_orders(self, limit: int = 30) -> List[OrderRecord]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [OrderRecord(
            id=r["id"], command=r["command"], result=r["result"],
            status=r["status"], source=r["source"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            duration_ms=r["duration_ms"],
        ) for r in rows]

    # ── Deploys ──
    def add_deploy(self, deploy: DeployRecord) -> int:
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO deploys (site_id, site_name, deploy_id, status, file_count, timestamp, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (deploy.site_id, deploy.site_name, deploy.deploy_id,
             deploy.status, deploy.file_count,
             deploy.timestamp.isoformat(), deploy.duration_ms),
        )
        did = cur.lastrowid
        conn.commit()
        conn.close()
        return did

    def get_deploys(self, site_id: str = None, limit: int = 20) -> List[DeployRecord]:
        conn = self._conn()
        if site_id:
            rows = conn.execute(
                "SELECT * FROM deploys WHERE site_id = ? ORDER BY timestamp DESC LIMIT ?",
                (site_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM deploys ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        conn.close()
        return [DeployRecord(
            id=r["id"], site_id=r["site_id"], site_name=r["site_name"],
            deploy_id=r["deploy_id"], status=r["status"],
            file_count=r["file_count"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            duration_ms=r["duration_ms"],
        ) for r in rows]

    # ── Uptime ──
    def log_uptime(self, site_id: str, status: str, status_code: int,
                   response_time: float, error: str = ""):
        conn = self._conn()
        conn.execute(
            "INSERT INTO uptime_log (site_id, status, status_code, response_time, error, checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (site_id, status, status_code, response_time, error,
             datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    # ── Search ──
    def search_all(self, keyword: str, limit: int = 20) -> dict:
        """모든 테이블에서 키워드 검색"""
        conn = self._conn()
        results = {}

        # Alerts
        results["alerts"] = conn.execute(
            "SELECT * FROM alerts WHERE title LIKE ? OR message LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()

        # Orders
        results["orders"] = conn.execute(
            "SELECT * FROM orders WHERE command LIKE ? OR result LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()

        # Deploys
        results["deploys"] = conn.execute(
            "SELECT * FROM deploys WHERE site_name LIKE ? OR status LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()

        conn.close()
        return results
