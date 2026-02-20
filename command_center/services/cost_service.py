# -*- coding: utf-8 -*-
"""
API 비용 추적 서비스 — 기존 CostTracker 래퍼
"""
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

from ..config import PROJECT_DIR, COST_DB_PATH, BUDGET_LIMIT_KRW

# 기존 CostTracker 임포트
sys.path.insert(0, str(PROJECT_DIR))
try:
    from api_cost_tracker import CostTracker, BUDGET_WARN_RATIO
except ImportError:
    CostTracker = None
    BUDGET_WARN_RATIO = 0.8


class CostService:
    """API 비용 조회 서비스"""

    def __init__(self):
        self.tracker = None
        if CostTracker:
            try:
                self.tracker = CostTracker(
                    db_path=COST_DB_PATH,
                    project_name="command_center",
                )
            except Exception:
                pass

    @property
    def available(self) -> bool:
        return self.tracker is not None

    def get_exchange_rate(self) -> float:
        if self.tracker:
            return self.tracker.get_exchange_rate()
        return 1400.0

    def get_summary(self) -> dict:
        """전체 비용 요약"""
        if not self.tracker:
            return self._empty_summary()

        rate = self.tracker.get_exchange_rate()
        today_usd = self.tracker.get_today_total()
        monthly_usd = self.tracker.get_monthly_total()
        alltime_usd = self.tracker.get_all_time_total()

        monthly_krw = monthly_usd * rate
        budget_pct = round((monthly_krw / BUDGET_LIMIT_KRW) * 100, 1) if BUDGET_LIMIT_KRW > 0 else 0

        if budget_pct >= 100:
            budget_status = "over"
        elif budget_pct >= BUDGET_WARN_RATIO * 100:
            budget_status = "warn"
        else:
            budget_status = "ok"

        return {
            "today_usd": round(today_usd, 6),
            "today_krw": round(today_usd * rate),
            "monthly_usd": round(monthly_usd, 6),
            "monthly_krw": round(monthly_usd * rate),
            "alltime_usd": round(alltime_usd, 6),
            "alltime_krw": round(alltime_usd * rate),
            "budget_pct": budget_pct,
            "budget_status": budget_status,
            "budget_limit": BUDGET_LIMIT_KRW,
            "exchange_rate": round(rate, 2),
        }

    def get_model_breakdown(self, period: str = "monthly") -> list:
        """모델별 비용 분류"""
        if not self.tracker:
            return []

        conn = sqlite3.connect(COST_DB_PATH)
        c = conn.cursor()
        if period == "today":
            start = datetime.now().strftime("%Y-%m-%d 00:00:00")
        else:
            start = datetime.now().strftime("%Y-%m-01 00:00:00")

        c.execute(
            "SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) "
            "FROM api_usage WHERE timestamp >= ? GROUP BY model ORDER BY SUM(cost_usd) DESC",
            (start,),
        )
        rate = self.get_exchange_rate()
        models = []
        for model, calls, in_tok, out_tok, cost in c.fetchall():
            models.append({
                "model": model, "calls": calls,
                "input_tokens": in_tok or 0, "output_tokens": out_tok or 0,
                "cost_usd": round(cost, 6), "cost_krw": round(cost * rate),
            })
        conn.close()
        return models

    def get_daily_trend(self, days: int = 30) -> list:
        """일별 비용 추이"""
        try:
            conn = sqlite3.connect(COST_DB_PATH)
            c = conn.cursor()
            c.execute(
                "SELECT DATE(timestamp), COUNT(*), SUM(cost_usd) "
                "FROM api_usage GROUP BY DATE(timestamp) "
                "ORDER BY DATE(timestamp) DESC LIMIT ?",
                (days,),
            )
            rate = self.get_exchange_rate()
            daily = []
            for date, calls, cost in c.fetchall():
                daily.append({
                    "date": date, "calls": calls,
                    "cost_usd": round(cost, 6), "cost_krw": round(cost * rate),
                })
            conn.close()
            return list(reversed(daily))
        except Exception:
            return []

    def get_recent_records(self, limit: int = 50) -> list:
        """최근 사용 내역"""
        try:
            conn = sqlite3.connect(COST_DB_PATH)
            c = conn.cursor()
            c.execute(
                "SELECT timestamp, project, model, input_tokens, output_tokens, cost_usd "
                "FROM api_usage ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rate = self.get_exchange_rate()
            records = []
            for ts, proj, model, in_tok, out_tok, cost in c.fetchall():
                records.append({
                    "timestamp": ts, "project": proj, "model": model,
                    "input_tokens": in_tok, "output_tokens": out_tok,
                    "cost_usd": round(cost, 6), "cost_krw": round(cost * rate),
                })
            conn.close()
            return records
        except Exception:
            return []

    def _empty_summary(self) -> dict:
        return {
            "today_usd": 0, "today_krw": 0,
            "monthly_usd": 0, "monthly_krw": 0,
            "alltime_usd": 0, "alltime_krw": 0,
            "budget_pct": 0, "budget_status": "ok",
            "budget_limit": BUDGET_LIMIT_KRW,
            "exchange_rate": 1400,
        }
