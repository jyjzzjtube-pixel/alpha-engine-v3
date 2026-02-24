# -*- coding: utf-8 -*-
"""
Claude Code CLI 헬퍼 — 커맨드센터 서비스를 CLI로 노출
Usage:
    python -m command_center.claude_helper --status
    python -m command_center.claude_helper --gemini "분석할 내용"
    python -m command_center.claude_helper --telegram "보낼 메시지"
    python -m command_center.claude_helper --health
    python -m command_center.claude_helper --cost
    python -m command_center.claude_helper --search "키워드"
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 설정
_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))

from dotenv import load_dotenv
load_dotenv(_PROJECT / ".env", override=True)

from command_center.config import (
    GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    COST_DB_PATH, BUDGET_LIMIT_KRW,
)


# ── 명령 핸들러 ──

def cmd_status(json_mode=False):
    """전체 시스템 상태 요약"""
    from command_center.services.site_monitor import SiteMonitor
    from command_center.services.cost_service import CostService
    from command_center.database import Database
    from command_center.telegram_bridge import TaskQueue

    # 사이트
    monitor = SiteMonitor()
    results = monitor.check_all()
    up = sum(1 for r in results if r.status.value == "up")
    down_names = [r.name for r in results if r.status.value != "up"]

    # 비용
    cs = CostService()
    s = cs.get_summary()

    # 알림
    db = Database()
    unread = db.get_unread_count()

    # 큐
    queue = TaskQueue()
    pending = queue.get_pending()

    # 서비스 가용성
    gemini_ok = bool(GEMINI_API_KEY)
    telegram_ok = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

    if json_mode:
        print(json.dumps({
            "sites": {"up": up, "total": len(results), "down": down_names},
            "cost": {"today_krw": s["today_krw"], "monthly_krw": s["monthly_krw"],
                     "budget_pct": s["budget_pct"], "budget_limit": BUDGET_LIMIT_KRW},
            "alerts": {"unread": unread},
            "queue": {"pending": len(pending), "tasks": [{"id": t["id"], "message": t["message"][:80]} for t in pending]},
            "services": {"gemini": gemini_ok, "telegram": telegram_ok},
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2))
    else:
        print("=== YJ COMMAND CENTER STATUS ===")
        site_str = f"SITES: {up}/{len(results)} UP"
        if down_names:
            site_str += f" | DOWN: {', '.join(down_names)}"
        else:
            site_str += " (all clear)"
        print(site_str)
        print(f"COST: W{s['today_krw']:,} today | W{s['monthly_krw']:,} month | {s['budget_pct']}% budget (W{BUDGET_LIMIT_KRW:,} limit)")
        print(f"ALERTS: {unread} unread")
        # 큐 상태
        if pending:
            print(f"QUEUE: {len(pending)} pending tasks!")
            for t in pending:
                print(f"  #{t['id']}: {t['message'][:60]}")
        else:
            print("QUEUE: empty")
        print(f"GEMINI: {'available' if gemini_ok else 'not configured'}")
        print(f"TELEGRAM: {'configured' if telegram_ok else 'not configured'}")
        print(f"TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def cmd_gemini(prompt, json_mode=False):
    """Gemini 무료 AI 분석"""
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not configured", file=sys.stderr)
        sys.exit(1)

    from google import genai
    from api_cost_tracker import CostTracker

    client = genai.Client(api_key=GEMINI_API_KEY)
    tracker = CostTracker(project_name="claude_helper")

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = response.text.strip()

        # 비용 기록
        usage = getattr(response, "usage_metadata", None)
        if usage:
            in_tok = getattr(usage, "prompt_token_count", 0) or 0
            out_tok = getattr(usage, "candidates_token_count", 0) or 0
            tracker.record("gemini-2.5-flash", in_tok, out_tok)

        if json_mode:
            sys.stdout.buffer.write(json.dumps({"response": text, "model": "gemini-2.5-flash"}, ensure_ascii=False).encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
        else:
            sys.stdout.buffer.write(text.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
    except Exception as e:
        print(f"ERROR: Gemini failed — {e}", file=sys.stderr)
        sys.exit(1)


def cmd_telegram(message, json_mode=False):
    """텔레그램 메시지 전송"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram not configured", file=sys.stderr)
        sys.exit(1)

    import requests
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
        timeout=10,
    )
    data = resp.json()

    if json_mode:
        print(json.dumps({"ok": data.get("ok", False)}, ensure_ascii=False))
    else:
        if data.get("ok"):
            print("SENT: ok")
        else:
            print(f"ERROR: {data.get('description', 'unknown')}", file=sys.stderr)
            sys.exit(1)


def cmd_health(json_mode=False):
    """사이트 건강검진"""
    from command_center.services.site_monitor import SiteMonitor

    monitor = SiteMonitor()
    results = monitor.check_all()

    if json_mode:
        items = []
        for r in results:
            items.append({
                "name": r.name, "status": r.status.value,
                "response_time": r.response_time, "error": r.error,
            })
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        total_time = 0
        up_count = 0
        for r in results:
            is_up = r.status.value == "up"
            icon = "UP" if is_up else "DOWN"
            detail = f"{r.response_time}s" if r.response_time else (r.error or r.status.value)
            print(f"  [{icon:4s}] {r.name:25s} {detail}")
            if is_up:
                up_count += 1
                total_time += (r.response_time or 0)
        avg = round(total_time / up_count, 2) if up_count else 0
        print(f"TOTAL: {up_count}/{len(results)} UP | avg {avg}s")


def cmd_cost(json_mode=False):
    """API 비용 요약"""
    from command_center.services.cost_service import CostService

    cs = CostService()
    s = cs.get_summary()
    models = cs.get_model_breakdown()

    if json_mode:
        print(json.dumps({
            "summary": s,
            "models": models,
        }, ensure_ascii=False, indent=2, default=str))
    else:
        print("=== API COST REPORT ===")
        print(f"Today:   W{s['today_krw']:,} (${s['today_usd']:.4f})")
        print(f"Month:   W{s['monthly_krw']:,} (${s['monthly_usd']:.4f})")
        print(f"Budget:  {s['budget_pct']}% of W{BUDGET_LIMIT_KRW:,}")
        if models:
            print("---")
            print("Top models:")
            for m in models:
                calls = m.get("calls", m.get("count", 0))
                print(f"  {m['model']:35s} {calls:>5} calls, W{m.get('cost_krw', m.get('total_krw', 0)):,}")


def cmd_search(keyword, json_mode=False):
    """통합 검색"""
    from command_center.services.search_engine import SearchEngine

    engine = SearchEngine()
    results = engine.search(keyword, limit_per_source=5)

    if json_mode:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        if not results:
            print(f"No results for '{keyword}'")
            return
        for source, items in results.items():
            if not items:
                continue
            print(f"--- {source} ---")
            for item in items[:5]:
                if hasattr(item, "file"):
                    print(f"  {item.file}:{item.line} — {item.text[:80]}")
                elif isinstance(item, dict):
                    print(f"  {item}")
                else:
                    text = str(item)
                    print(f"  {text[:100]}")


def cmd_openai(prompt, model="gpt-4o-mini", json_mode=False):
    """OpenAI API 호출"""
    if not OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY not configured in .env", file=sys.stderr)
        sys.exit(1)

    from command_center.services.ai_service import AIService
    svc = AIService()

    try:
        resp = svc.ask_openai(prompt, model=model)
        if json_mode:
            sys.stdout.buffer.write(json.dumps({
                "response": resp.text, "model": resp.model,
                "tokens": {"input": resp.input_tokens, "output": resp.output_tokens},
                "cost_usd": resp.cost_usd, "elapsed_ms": resp.elapsed_ms,
            }, ensure_ascii=False).encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
        else:
            sys.stdout.buffer.write(resp.text.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
    except Exception as e:
        print(f"ERROR: OpenAI failed — {e}", file=sys.stderr)
        sys.exit(1)


def cmd_claude(prompt, model="claude-haiku-4-5-20251001", json_mode=False):
    """Anthropic Claude API 호출"""
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not configured", file=sys.stderr)
        sys.exit(1)

    from command_center.services.ai_service import AIService
    svc = AIService()

    try:
        resp = svc.ask_claude(prompt, model=model)
        if json_mode:
            sys.stdout.buffer.write(json.dumps({
                "response": resp.text, "model": resp.model,
                "tokens": {"input": resp.input_tokens, "output": resp.output_tokens},
                "cost_usd": resp.cost_usd, "elapsed_ms": resp.elapsed_ms,
            }, ensure_ascii=False).encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
        else:
            sys.stdout.buffer.write(resp.text.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
    except Exception as e:
        print(f"ERROR: Claude API failed — {e}", file=sys.stderr)
        sys.exit(1)


def cmd_ollama(prompt, model=None, json_mode=False):
    """Ollama 로컬 AI 호출 (완전 무료, 오프라인)"""
    from command_center.services.ai_service import AIService
    svc = AIService()

    if not svc._check_ollama():
        print("ERROR: Ollama 서버가 꺼져있음. 'ollama serve' 실행 필요", file=sys.stderr)
        sys.exit(1)

    try:
        resp = svc.ask_ollama(prompt, model=model)
        if json_mode:
            sys.stdout.buffer.write(json.dumps({
                "response": resp.text, "model": resp.model,
                "tokens": {"input": resp.input_tokens, "output": resp.output_tokens},
                "cost_usd": 0.0, "elapsed_ms": resp.elapsed_ms,
            }, ensure_ascii=False).encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
        else:
            sys.stdout.buffer.write(resp.text.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
    except Exception as e:
        print(f"ERROR: Ollama failed — {e}", file=sys.stderr)
        sys.exit(1)


def cmd_gemini_pro(prompt, json_mode=False):
    """Gemini Pro 호출 (울트라급, API 무료)"""
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not configured", file=sys.stderr)
        sys.exit(1)

    from command_center.services.ai_service import AIService
    svc = AIService()

    try:
        resp = svc.ask_gemini_pro(prompt)
        if json_mode:
            sys.stdout.buffer.write(json.dumps({
                "response": resp.text, "model": resp.model,
                "tokens": {"input": resp.input_tokens, "output": resp.output_tokens},
                "cost_usd": 0.0, "elapsed_ms": resp.elapsed_ms,
            }, ensure_ascii=False).encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
        else:
            sys.stdout.buffer.write(resp.text.encode("utf-8"))
            sys.stdout.buffer.write(b"\n")
    except Exception as e:
        print(f"ERROR: Gemini Pro failed — {e}", file=sys.stderr)
        sys.exit(1)


def cmd_ai(prompt, provider=None, json_mode=False):
    """통합 AI 호출 (자동 fallback chain)"""
    from command_center.services.ai_service import AIService
    svc = AIService()

    resp = svc.ask(prompt, provider=provider)

    if resp.error:
        print(f"ERROR: {resp.error}", file=sys.stderr)
        sys.exit(1)

    if json_mode:
        sys.stdout.buffer.write(json.dumps({
            "response": resp.text, "provider": resp.provider, "model": resp.model,
            "tokens": {"input": resp.input_tokens, "output": resp.output_tokens},
            "cost_usd": resp.cost_usd, "elapsed_ms": resp.elapsed_ms,
        }, ensure_ascii=False).encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
    else:
        sys.stdout.buffer.write(f"[{resp.provider}|{resp.model}] ".encode("utf-8"))
        sys.stdout.buffer.write(resp.text.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")


def cmd_queue_check(json_mode=False):
    """큐에 대기 중인 작업 확인"""
    from command_center.telegram_bridge import TaskQueue

    queue = TaskQueue()
    pending = queue.get_pending()
    recent = queue.get_all(limit=10)

    if json_mode:
        print(json.dumps({
            "pending": pending,
            "recent": recent,
        }, ensure_ascii=False, indent=2, default=str))
    else:
        if pending:
            print(f"=== PENDING TASKS ({len(pending)}) ===")
            for t in pending:
                print(f"  #{t['id']} [{t['source']}] {t['message'][:80]}")
                print(f"       created: {t['created_at']}")
        else:
            print("No pending tasks in queue.")

        if recent:
            print(f"\n--- Recent ({len(recent)}) ---")
            for t in recent:
                icon = {"pending": "...", "in_progress": ">>", "completed": "OK", "failed": "XX"}.get(t["status"], "??")
                print(f"  [{icon}] #{t['id']} {t['message'][:60]}")


def cmd_queue_add(message, json_mode=False):
    """큐에 작업 추가"""
    from command_center.telegram_bridge import TaskQueue

    queue = TaskQueue()
    task = queue.add(message, source="cli")

    if json_mode:
        print(json.dumps(task, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Task #{task['id']} added to queue: {message[:80]}")


def cmd_ai_providers(json_mode=False):
    """사용 가능한 AI 프로바이더 목록"""
    from command_center.services.ai_service import AIService
    svc = AIService()
    providers = svc.list_providers()

    if json_mode:
        print(json.dumps(providers, ensure_ascii=False, indent=2))
    else:
        print("=== AI PROVIDERS ===")
        for p in providers:
            status = "OK" if p["available"] else "NO KEY"
            print(f"  [{status:6s}] {p['name']:16s} {p['model']:35s} ({p['cost']})")


# ── CLI 엔트리 ──

def main():
    parser = argparse.ArgumentParser(
        description="Claude Code CLI Helper — 커맨드센터 서비스 통합 인터페이스",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="시스템 전체 상태")
    group.add_argument("--ollama", type=str, metavar="PROMPT", help="Ollama 로컬 AI (무료, 오프라인)")
    group.add_argument("--gemini", type=str, metavar="PROMPT", help="Gemini Flash 분석 (무료)")
    group.add_argument("--gemini-pro", type=str, metavar="PROMPT", help="Gemini Pro 분석 (울트라급, 무료)")
    group.add_argument("--openai", type=str, metavar="PROMPT", help="OpenAI GPT 분석")
    group.add_argument("--claude", type=str, metavar="PROMPT", help="Claude API 분석")
    group.add_argument("--ai", type=str, metavar="PROMPT", help="통합 AI (자동 fallback)")
    group.add_argument("--ai-providers", action="store_true", help="AI 프로바이더 목록")
    group.add_argument("--telegram", type=str, metavar="MSG", help="텔레그램 메시지 전송")
    group.add_argument("--health", action="store_true", help="사이트 건강검진")
    group.add_argument("--cost", action="store_true", help="API 비용 요약")
    group.add_argument("--search", type=str, metavar="KEYWORD", help="통합 검색")
    group.add_argument("--queue-check", action="store_true", help="큐 대기 작업 확인")
    group.add_argument("--queue-add", type=str, metavar="TASK", help="큐에 작업 추가")

    parser.add_argument("--json", action="store_true", help="JSON 형식 출력")
    parser.add_argument("--model", type=str, default=None, help="AI 모델 지정 (예: gpt-4o, claude-sonnet-4-6-20250610)")
    parser.add_argument("--provider", type=str, default=None, help="AI 프로바이더 지정 (--ai용)")

    args = parser.parse_args()

    if args.status:
        cmd_status(args.json)
    elif args.ollama:
        cmd_ollama(args.ollama, model=args.model, json_mode=args.json)
    elif args.gemini:
        cmd_gemini(args.gemini, args.json)
    elif getattr(args, "gemini_pro", None):
        cmd_gemini_pro(args.gemini_pro, json_mode=args.json)
    elif args.openai:
        model = args.model or "gpt-4o-mini"
        cmd_openai(args.openai, model=model, json_mode=args.json)
    elif args.claude:
        model = args.model or "claude-haiku-4-5-20251001"
        cmd_claude(args.claude, model=model, json_mode=args.json)
    elif args.ai:
        cmd_ai(args.ai, provider=args.provider, json_mode=args.json)
    elif getattr(args, "ai_providers", False):
        cmd_ai_providers(args.json)
    elif args.telegram is not None:
        cmd_telegram(args.telegram, args.json)
    elif args.health:
        cmd_health(args.json)
    elif args.cost:
        cmd_cost(args.json)
    elif args.search:
        cmd_search(args.search, args.json)
    elif getattr(args, "queue_check", False):
        cmd_queue_check(args.json)
    elif getattr(args, "queue_add", None):
        cmd_queue_add(args.queue_add, args.json)


if __name__ == "__main__":
    main()
