# -*- coding: utf-8 -*-
"""
통합 API 과금 감지 및 원화(KRW) 환산 시스템
모든 LLM API 호출의 토큰 사용량/비용을 추적, SQLite 영구기록, 실시간 환율 환산
"""
import os
import sys
import json
import sqlite3
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests

log = logging.getLogger("cost_tracker")

# ============================================================
# 모델별 1,000토큰 당 USD 단가표
# ============================================================
PRICE_TABLE: dict[str, dict[str, float]] = {
    # Google Gemini
    "gemini-2.5-pro":           {"input": 0.00125, "output": 0.0100},
    "gemini-2.5-flash":         {"input": 0.00015, "output": 0.0035},
    "gemini-2.0-flash":         {"input": 0.00010, "output": 0.0004},
    "gemini-2.0-flash-lite":    {"input": 0.00000, "output": 0.0000},
    "gemini-1.5-pro":           {"input": 0.00125, "output": 0.00500},
    "gemini-1.5-flash":         {"input": 0.000075,"output": 0.00030},
    # Anthropic Claude
    "claude-sonnet-4-20250514":      {"input": 0.003, "output": 0.015},
    "claude-3-7-sonnet-20250219":    {"input": 0.003, "output": 0.015},
    "claude-3-5-sonnet-20241022":    {"input": 0.003, "output": 0.015},
    "claude-3-5-sonnet-20240620":    {"input": 0.003, "output": 0.015},
    "claude-3-5-haiku-20241022":     {"input": 0.0008,"output": 0.004},
    "claude-3-opus-20240229":        {"input": 0.015, "output": 0.075},
    "claude-3-sonnet-20240229":      {"input": 0.003, "output": 0.015},
    "claude-3-haiku-20240307":       {"input": 0.00025,"output":0.00125},
    # OpenAI (참고용)
    "gpt-4o":                   {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini":              {"input": 0.00015,"output": 0.0006},
    "gpt-4-turbo":              {"input": 0.010,  "output": 0.030},
    "gpt-4":                    {"input": 0.030,  "output": 0.060},
    "gpt-3.5-turbo":            {"input": 0.0005, "output": 0.0015},
}

# 예산 한도 (KRW)
BUDGET_LIMIT_KRW = 50_000
BUDGET_WARN_RATIO = 0.8

# 환율 캐시 파일
EXCHANGE_CACHE_FILE = "exchange_rate_cache.json"
EXCHANGE_API_URL = "https://open.er-api.com/v6/latest/USD"

# DB 파일
DB_FILE = "api_usage.db"


class CostTracker:
    """LLM API 과금 추적기"""

    def __init__(self, db_path: str | None = None, project_name: str = "default"):
        self.project_name = project_name
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = db_path or os.path.join(base_dir, DB_FILE)
        self.cache_path = os.path.join(base_dir, EXCHANGE_CACHE_FILE)
        self._init_db()
        self._session_cost_usd = 0.0
        self._session_input_tokens = 0
        self._session_output_tokens = 0

    # --------------------------------------------------------
    # SQLite 초기화
    # --------------------------------------------------------
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                project TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    # --------------------------------------------------------
    # 비용 계산
    # --------------------------------------------------------
    @staticmethod
    def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        prices = PRICE_TABLE.get(model)
        if not prices:
            for key in PRICE_TABLE:
                if key in model or model in key:
                    prices = PRICE_TABLE[key]
                    break
        if not prices:
            log.warning(f"Unknown model '{model}', using zero cost.")
            return 0.0

        cost = (input_tokens / 1000) * prices["input"] + \
               (output_tokens / 1000) * prices["output"]
        return round(cost, 8)

    # --------------------------------------------------------
    # 사용량 기록
    # --------------------------------------------------------
    def record(self, model: str, input_tokens: int, output_tokens: int,
               project: str | None = None) -> float:
        cost = self.calc_cost(model, input_tokens, output_tokens)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        proj = project or self.project_name

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "INSERT INTO api_usage (timestamp, project, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, proj, model, input_tokens, output_tokens, cost),
        )
        conn.commit()
        conn.close()

        self._session_cost_usd += cost
        self._session_input_tokens += input_tokens
        self._session_output_tokens += output_tokens

        log.info(
            f"[COST] {model} | in={input_tokens} out={output_tokens} | "
            f"${cost:.6f} | session=${self._session_cost_usd:.6f}"
        )
        return cost

    # --------------------------------------------------------
    # 환율 조회 (캐싱: 1일 1회)
    # --------------------------------------------------------
    def get_exchange_rate(self) -> float:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                cached_time = datetime.fromisoformat(cache["timestamp"])
                if datetime.now() - cached_time < timedelta(hours=24):
                    return float(cache["rate"])
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        try:
            resp = requests.get(EXCHANGE_API_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            rate = float(data["rates"]["KRW"])
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump({"timestamp": datetime.now().isoformat(), "rate": rate}, f)
            log.info(f"Exchange rate updated: 1 USD = {rate:,.2f} KRW")
            return rate
        except Exception as e:
            log.warning(f"Exchange rate fetch failed: {e}, using fallback 1,380")
            return 1380.0

    # --------------------------------------------------------
    # 이달 누적 비용 조회
    # --------------------------------------------------------
    def get_monthly_total(self) -> float:
        now = datetime.now()
        month_start = now.strftime("%Y-%m-01 00:00:00")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE timestamp >= ?",
            (month_start,),
        )
        total = c.fetchone()[0]
        conn.close()
        return float(total)

    # --------------------------------------------------------
    # 오늘 비용 조회
    # --------------------------------------------------------
    def get_today_total(self) -> float:
        today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE timestamp >= ?",
            (today_start,),
        )
        total = c.fetchone()[0]
        conn.close()
        return float(total)

    # --------------------------------------------------------
    # 전체 누적 비용
    # --------------------------------------------------------
    def get_all_time_total(self) -> float:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage")
        total = c.fetchone()[0]
        conn.close()
        return float(total)

    # --------------------------------------------------------
    # 프로젝트별 비용
    # --------------------------------------------------------
    def get_project_breakdown(self) -> list[tuple[str, float]]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT project, SUM(cost_usd) FROM api_usage GROUP BY project ORDER BY SUM(cost_usd) DESC"
        )
        rows = c.fetchall()
        conn.close()
        return rows

    # --------------------------------------------------------
    # 모델별 비용
    # --------------------------------------------------------
    def get_model_breakdown(self) -> list[tuple[str, int, int, float]]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT model, SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) "
            "FROM api_usage GROUP BY model ORDER BY SUM(cost_usd) DESC"
        )
        rows = c.fetchall()
        conn.close()
        return rows

    # --------------------------------------------------------
    # 대시보드 출력
    # --------------------------------------------------------
    def print_dashboard(self):
        rate = self.get_exchange_rate()
        session_usd = self._session_cost_usd
        session_krw = session_usd * rate
        monthly_usd = self.get_monthly_total()
        monthly_krw = monthly_usd * rate

        RED = "\033[91m"
        YELLOW = "\033[93m"
        GREEN = "\033[92m"
        CYAN = "\033[96m"
        BOLD = "\033[1m"
        RESET = "\033[0m"

        print(f"\n{CYAN}{'=' * 50}{RESET}")
        print(f"{CYAN}{BOLD}  [실시간 API 비용 감지]{RESET}")
        print(f"{CYAN}{'=' * 50}{RESET}")
        print(
            f"  - 방금 사용한 비용: {GREEN}${session_usd:.4f}{RESET} "
            f"(약 {GREEN}{session_krw:,.0f}원{RESET})"
        )
        print(
            f"  - 이달의 누적 비용: {BOLD}${monthly_usd:.4f}{RESET} "
            f"(약 {BOLD}{monthly_krw:,.0f}원{RESET})"
        )
        print(
            f"  - 환율: 1 USD = {rate:,.2f} KRW"
        )

        if monthly_krw >= BUDGET_LIMIT_KRW:
            print(f"\n  {RED}{BOLD}[🚨 경고: 예산 한도 100% 초과! "
                  f"({monthly_krw:,.0f}원 / {BUDGET_LIMIT_KRW:,}원)]{RESET}")
        elif monthly_krw >= BUDGET_LIMIT_KRW * BUDGET_WARN_RATIO:
            pct = int((monthly_krw / BUDGET_LIMIT_KRW) * 100)
            print(f"\n  {YELLOW}{BOLD}[⚠️  경고: 예산 한도 {pct}% 도달! "
                  f"({monthly_krw:,.0f}원 / {BUDGET_LIMIT_KRW:,}원)]{RESET}")

        print(f"{CYAN}{'=' * 50}{RESET}\n")

    # --------------------------------------------------------
    # 세션 리셋
    # --------------------------------------------------------
    def reset_session(self):
        self._session_cost_usd = 0.0
        self._session_input_tokens = 0
        self._session_output_tokens = 0

    # --------------------------------------------------------
    # 상세 리포트 (CLI용)
    # --------------------------------------------------------
    def print_full_report(self):
        rate = self.get_exchange_rate()

        CYAN = "\033[96m"
        BOLD = "\033[1m"
        RESET = "\033[0m"

        print(f"\n{CYAN}{'=' * 60}{RESET}")
        print(f"{CYAN}{BOLD}  [API 비용 상세 리포트]{RESET}")
        print(f"{CYAN}{'=' * 60}{RESET}")

        today_usd = self.get_today_total()
        monthly_usd = self.get_monthly_total()
        total_usd = self.get_all_time_total()

        print(f"  오늘:   ${today_usd:.4f} ({today_usd * rate:,.0f}원)")
        print(f"  이달:   ${monthly_usd:.4f} ({monthly_usd * rate:,.0f}원)")
        print(f"  전체:   ${total_usd:.4f} ({total_usd * rate:,.0f}원)")

        models = self.get_model_breakdown()
        if models:
            print(f"\n  {BOLD}[모델별 사용량]{RESET}")
            for model, in_tok, out_tok, cost in models:
                print(f"    {model}: in={in_tok:,} out={out_tok:,} ${cost:.4f}")

        projects = self.get_project_breakdown()
        if projects:
            print(f"\n  {BOLD}[프로젝트별 비용]{RESET}")
            for proj, cost in projects:
                print(f"    {proj}: ${cost:.4f} ({cost * rate:,.0f}원)")

        print(f"{CYAN}{'=' * 60}{RESET}\n")


# ============================================================
# CLI 단독 실행: 리포트 출력
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    tracker = CostTracker(project_name="cli_report")

    if len(sys.argv) > 1 and sys.argv[1] == "report":
        tracker.print_full_report()
    else:
        print("Usage: python api_cost_tracker.py report")
        print("       - 전체 API 비용 리포트 출력")
        tracker.print_dashboard()
