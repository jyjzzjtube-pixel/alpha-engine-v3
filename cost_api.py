# -*- coding: utf-8 -*-
"""
API 비용 통합 REST API 서버
============================
모든 배포 사이트(Netlify, Telegram, PyQt6)에서 실시간 API 비용을
조회할 수 있는 경량 Flask 서버.

사용법:
    python cost_api.py              # 서버 시작 (port 5050)
    python cost_api.py --port 8080  # 포트 지정

엔드포인트:
    GET /api/cost/summary   전체 요약 (오늘/이번달/전체/예산)
    GET /api/cost/today     오늘 비용 상세
    GET /api/cost/monthly   이번달 비용 상세
    GET /api/cost/history   최근 50건 사용 내역
    GET /api/cost/models    모델별 비용 분류
    GET /api/cost/projects  프로젝트별 비용 분류
"""
import sys
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify
from flask_cors import CORS

# ── 기존 CostTracker 재사용 ──
sys.path.insert(0, str(Path(__file__).parent))
from api_cost_tracker import CostTracker, BUDGET_LIMIT_KRW, BUDGET_WARN_RATIO

app = Flask(__name__)
CORS(app)  # 모든 도메인에서 접근 허용

tracker = CostTracker(project_name="cost_api")


def _format_krw(usd: float, rate: float) -> str:
    """USD를 원화 문자열로 변환."""
    krw = usd * rate
    if krw >= 1000:
        return f"{krw:,.0f}원"
    return f"{krw:.1f}원"


# ══════════════════════════════════════════════════════════
#  API 엔드포인트
# ══════════════════════════════════════════════════════════

@app.route("/api/cost/summary")
def cost_summary():
    """전체 비용 요약 — 모든 사이트의 메인 데이터 소스."""
    rate = tracker.get_exchange_rate()
    today_usd = tracker.get_today_total()
    monthly_usd = tracker.get_monthly_total()
    alltime_usd = tracker.get_all_time_total()

    monthly_krw = monthly_usd * rate
    budget_pct = round((monthly_krw / BUDGET_LIMIT_KRW) * 100, 1) if BUDGET_LIMIT_KRW > 0 else 0

    # 경고 레벨
    if budget_pct >= 100:
        budget_status = "over"
    elif budget_pct >= BUDGET_WARN_RATIO * 100:
        budget_status = "warn"
    else:
        budget_status = "ok"

    return jsonify({
        "today": {
            "usd": round(today_usd, 6),
            "krw": round(today_usd * rate, 0),
            "krw_fmt": _format_krw(today_usd, rate),
        },
        "monthly": {
            "usd": round(monthly_usd, 6),
            "krw": round(monthly_usd * rate, 0),
            "krw_fmt": _format_krw(monthly_usd, rate),
        },
        "alltime": {
            "usd": round(alltime_usd, 6),
            "krw": round(alltime_usd * rate, 0),
            "krw_fmt": _format_krw(alltime_usd, rate),
        },
        "budget": {
            "limit_krw": BUDGET_LIMIT_KRW,
            "used_pct": budget_pct,
            "status": budget_status,
        },
        "exchange_rate": round(rate, 2),
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/cost/today")
def cost_today():
    """오늘 비용 상세 (모델별 분류 포함)."""
    rate = tracker.get_exchange_rate()
    today_usd = tracker.get_today_total()
    today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")

    # 오늘 모델별 분류
    conn = sqlite3.connect(tracker.db_path)
    c = conn.cursor()
    c.execute(
        "SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) "
        "FROM api_usage WHERE timestamp >= ? GROUP BY model ORDER BY SUM(cost_usd) DESC",
        (today_start,),
    )
    models = []
    for model, calls, in_tok, out_tok, cost in c.fetchall():
        models.append({
            "model": model,
            "calls": calls,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": round(cost, 6),
            "cost_krw": round(cost * rate, 0),
        })
    conn.close()

    return jsonify({
        "total_usd": round(today_usd, 6),
        "total_krw": round(today_usd * rate, 0),
        "total_krw_fmt": _format_krw(today_usd, rate),
        "models": models,
        "exchange_rate": round(rate, 2),
    })


@app.route("/api/cost/monthly")
def cost_monthly():
    """이번달 비용 상세 (모델별 분류 포함)."""
    rate = tracker.get_exchange_rate()
    monthly_usd = tracker.get_monthly_total()
    month_start = datetime.now().strftime("%Y-%m-01 00:00:00")

    conn = sqlite3.connect(tracker.db_path)
    c = conn.cursor()
    c.execute(
        "SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) "
        "FROM api_usage WHERE timestamp >= ? GROUP BY model ORDER BY SUM(cost_usd) DESC",
        (month_start,),
    )
    models = []
    for model, calls, in_tok, out_tok, cost in c.fetchall():
        models.append({
            "model": model,
            "calls": calls,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": round(cost, 6),
            "cost_krw": round(cost * rate, 0),
        })

    # 일별 추이
    c.execute(
        "SELECT DATE(timestamp), COUNT(*), SUM(cost_usd) "
        "FROM api_usage WHERE timestamp >= ? GROUP BY DATE(timestamp) ORDER BY DATE(timestamp)",
        (month_start,),
    )
    daily = []
    for date, calls, cost in c.fetchall():
        daily.append({
            "date": date,
            "calls": calls,
            "cost_usd": round(cost, 6),
            "cost_krw": round(cost * rate, 0),
        })
    conn.close()

    monthly_krw = monthly_usd * rate
    return jsonify({
        "total_usd": round(monthly_usd, 6),
        "total_krw": round(monthly_krw, 0),
        "total_krw_fmt": _format_krw(monthly_usd, rate),
        "budget_limit_krw": BUDGET_LIMIT_KRW,
        "budget_pct": round((monthly_krw / BUDGET_LIMIT_KRW) * 100, 1),
        "models": models,
        "daily": daily,
        "exchange_rate": round(rate, 2),
    })


@app.route("/api/cost/history")
def cost_history():
    """최근 50건 사용 내역."""
    rate = tracker.get_exchange_rate()

    conn = sqlite3.connect(tracker.db_path)
    c = conn.cursor()
    c.execute(
        "SELECT timestamp, project, model, input_tokens, output_tokens, cost_usd "
        "FROM api_usage ORDER BY id DESC LIMIT 50"
    )
    records = []
    for ts, proj, model, in_tok, out_tok, cost in c.fetchall():
        records.append({
            "timestamp": ts,
            "project": proj,
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": round(cost, 6),
            "cost_krw": round(cost * rate, 0),
        })
    conn.close()

    return jsonify({
        "count": len(records),
        "records": records,
        "exchange_rate": round(rate, 2),
    })


@app.route("/api/cost/models")
def cost_models():
    """모델별 비용 분류."""
    rate = tracker.get_exchange_rate()
    rows = tracker.get_model_breakdown()

    models = []
    for model, in_tok, out_tok, cost in rows:
        models.append({
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": round(cost, 6),
            "cost_krw": round(cost * rate, 0),
            "cost_krw_fmt": _format_krw(cost, rate),
        })

    return jsonify({"models": models, "exchange_rate": round(rate, 2)})


@app.route("/api/cost/projects")
def cost_projects():
    """프로젝트별 비용 분류."""
    rate = tracker.get_exchange_rate()
    rows = tracker.get_project_breakdown()

    projects = []
    for proj, cost in rows:
        projects.append({
            "project": proj,
            "cost_usd": round(cost, 6),
            "cost_krw": round(cost * rate, 0),
            "cost_krw_fmt": _format_krw(cost, rate),
        })

    return jsonify({"projects": projects, "exchange_rate": round(rate, 2)})


@app.route("/")
def index():
    """루트 — API 안내."""
    return jsonify({
        "service": "YJ Partners API Cost Monitor",
        "version": "1.0",
        "endpoints": [
            "/api/cost/summary",
            "/api/cost/today",
            "/api/cost/monthly",
            "/api/cost/history",
            "/api/cost/models",
            "/api/cost/projects",
        ],
    })


# ══════════════════════════════════════════════════════════
#  서버 시작
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="API Cost Monitor Server")
    parser.add_argument("--port", type=int, default=5050, help="서버 포트 (기본: 5050)")
    parser.add_argument("--host", default="0.0.0.0", help="바인딩 호스트")
    args = parser.parse_args()

    print(f"{'='*50}")
    print(f"  YJ Partners API Cost Monitor")
    print(f"  http://localhost:{args.port}/api/cost/summary")
    print(f"{'='*50}")

    app.run(host=args.host, port=args.port, debug=False)
