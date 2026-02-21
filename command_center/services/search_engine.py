# -*- coding: utf-8 -*-
"""
통합 검색 엔진 — 코드, DB, 로그 통합 검색
"""
import os
import subprocess
import sqlite3
from pathlib import Path
from typing import List

from ..config import PROJECT_DIR, COST_DB_PATH, COMMAND_CENTER_DB
from ..models import SearchResult


class SearchEngine:
    """프로젝트 전체 통합 검색"""

    SEARCH_EXTENSIONS = {".py", ".html", ".js", ".json", ".bat", ".css", ".md"}
    EXCLUDE_DIRS = {"venv", "node_modules", "__pycache__", ".git", ".claude", "logs", "renders"}

    def search(self, keyword: str, sources: List[str] = None,
               limit_per_source: int = 10) -> dict:
        """통합 검색 — sources: ['code', 'api_usage', 'alerts', 'orders', 'deploys']"""
        if not keyword or len(keyword) < 2:
            return {}

        all_sources = sources or ["code", "api_usage", "alerts", "orders", "deploys"]
        results = {}

        if "code" in all_sources:
            results["code"] = self._search_code(keyword, limit_per_source)
        if "api_usage" in all_sources:
            results["api_usage"] = self._search_api_usage(keyword, limit_per_source)
        if "alerts" in all_sources:
            results["alerts"] = self._search_db_table(
                COMMAND_CENTER_DB, "alerts",
                ["title", "message", "source"], keyword, limit_per_source
            )
        if "orders" in all_sources:
            results["orders"] = self._search_db_table(
                COMMAND_CENTER_DB, "orders",
                ["command", "result"], keyword, limit_per_source
            )
        if "deploys" in all_sources:
            results["deploys"] = self._search_db_table(
                COMMAND_CENTER_DB, "deploys",
                ["site_name", "status", "deploy_id"], keyword, limit_per_source
            )

        return results

    def _search_code(self, keyword: str, limit: int) -> List[SearchResult]:
        """프로젝트 코드 파일 검색 (findstr/grep)"""
        results = []
        try:
            for root, dirs, files in os.walk(str(PROJECT_DIR)):
                # 제외 디렉토리
                dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]
                for f in files:
                    ext = Path(f).suffix.lower()
                    if ext not in self.SEARCH_EXTENSIONS:
                        continue
                    fp = Path(root) / f
                    try:
                        text = fp.read_text(encoding="utf-8", errors="ignore")
                        for i, line in enumerate(text.splitlines(), 1):
                            if keyword.lower() in line.lower():
                                rel = fp.relative_to(PROJECT_DIR)
                                results.append(SearchResult(
                                    source="code", icon="\U0001F4C1",
                                    title=f"{rel}:{i}",
                                    detail=line.strip()[:120],
                                    file_path=str(fp),
                                    line_number=i,
                                ))
                                if len(results) >= limit:
                                    return results
                    except Exception:
                        continue
        except Exception:
            pass
        return results

    def _search_api_usage(self, keyword: str, limit: int) -> List[SearchResult]:
        """API 사용 내역 검색"""
        if not Path(COST_DB_PATH).exists():
            return []
        try:
            conn = sqlite3.connect(COST_DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, project, model, cost_usd FROM api_usage "
                "WHERE project LIKE ? OR model LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (f"%{keyword}%", f"%{keyword}%", limit),
            ).fetchall()
            conn.close()
            return [SearchResult(
                source="api_usage", icon="\U0001F4CA",
                title=f"{r['timestamp'][:16]} — {r['model']}",
                detail=f"프로젝트: {r['project']} | ${r['cost_usd']:.4f}",
                timestamp=r["timestamp"],
            ) for r in rows]
        except Exception:
            return []

    def _search_db_table(self, db_path: str, table: str, columns: list,
                         keyword: str, limit: int) -> List[SearchResult]:
        """일반 SQLite 테이블 검색"""
        if not Path(db_path).exists():
            return []
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            where_clauses = " OR ".join(f"{col} LIKE ?" for col in columns)
            params = [f"%{keyword}%"] * len(columns) + [limit]
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE {where_clauses} "
                f"ORDER BY id DESC LIMIT ?", params,
            ).fetchall()
            conn.close()

            icons = {"alerts": "\U0001F514", "orders": "\U0001F4CB", "deploys": "\U0001F680"}
            results = []
            for r in rows:
                r_dict = dict(r)
                title = r_dict.get("title") or r_dict.get("command") or r_dict.get("site_name") or ""
                detail = r_dict.get("message") or r_dict.get("result") or r_dict.get("status") or ""
                ts = r_dict.get("timestamp", "")
                results.append(SearchResult(
                    source=table, icon=icons.get(table, ""),
                    title=title[:80], detail=detail[:120],
                    timestamp=ts,
                ))
            return results
        except Exception:
            return []

    def get_total_count(self, results: dict) -> int:
        return sum(len(v) for v in results.values())
