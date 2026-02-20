# -*- coding: utf-8 -*-
"""
통합 커맨드센터 설정
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ── 경로 ──
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
load_dotenv(PROJECT_DIR / ".env")

# ── API 키 ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", ""))
NETLIFY_TOKEN = "nfc_SVmjya7So89j4xPh5n6PB8JcsTGy23jk16d2"
NETLIFY_ACCOUNT = "jyjzzjtube"

# ── 비용 ──
BUDGET_LIMIT_KRW = 50_000
COST_DB_PATH = str(PROJECT_DIR / "api_usage.db")
COMMAND_CENTER_DB = str(BASE_DIR / "command_center.db")

# ── AI 하이브리드 설정 ──
AI_PROVIDERS = {
    "gemini": {"model": "gemini-2.5-flash", "cost": "free", "priority": 1},
    "claude_haiku": {"model": "claude-3-5-haiku-20241022", "cost": "low", "priority": 2},
    "claude_sonnet": {"model": "claude-sonnet-4-20250514", "cost": "high", "priority": 3},
}
AI_FALLBACK_CHAIN = ["gemini", "claude_haiku", "claude_sonnet"]

# ── 관리 사이트 ──
MANAGED_SITES = [
    {"id": "alpha-engine", "name": "Alpha Engine", "url": "https://alpha-engine.netlify.app",
     "type": "netlify", "category": "finance", "source_dir": ""},
    {"id": "yjtax-v8", "name": "YJ Tax v8", "url": "https://yjtax-v8.netlify.app",
     "type": "netlify", "category": "tax", "source_dir": "yjtax_v8_extracted"},
    {"id": "yj-partners", "name": "YJ Partners MCN", "url": "https://yj-partners.netlify.app",
     "type": "netlify", "category": "mcn", "source_dir": ""},
    {"id": "bridgeone", "name": "Bridge One", "url": "https://bridgeone-franchise.netlify.app",
     "type": "netlify", "category": "franchise", "source_dir": ""},
    {"id": "founderone", "name": "Founder One", "url": "https://founderone-site.netlify.app",
     "type": "netlify", "category": "startup", "source_dir": ""},
    {"id": "news-dashboard", "name": "News Dashboard", "url": "https://yj-news-dashboard.netlify.app",
     "type": "netlify", "category": "news", "source_dir": ""},
    {"id": "ai-secretary", "name": "AI Secretary", "url": "https://yj-ai-secretary.netlify.app",
     "type": "netlify", "category": "ai", "source_dir": ""},
    {"id": "shorts-factory", "name": "Shorts Factory", "url": "http://localhost:5000",
     "type": "local", "category": "content", "health_url": "http://localhost:5000/api/health"},
    {"id": "cost-api", "name": "Cost API", "url": "http://localhost:5050",
     "type": "local", "category": "monitoring", "health_url": "http://localhost:5050/"},
    {"id": "naver-blog", "name": "Naver Blog", "url": "https://blog.naver.com/jyjzzj",
     "type": "external", "category": "blog"},
    {"id": "youtube", "name": "YouTube", "url": "https://www.youtube.com/@jjin_deal",
     "type": "external", "category": "social"},
    {"id": "instagram", "name": "Instagram", "url": "https://www.instagram.com/jjin_deal",
     "type": "external", "category": "social"},
]

# ── 관리 봇/서비스 ──
VENV_PYTHON = str(PROJECT_DIR / "AI_Command_Center" / "venv" / "Scripts" / "python.exe")

MANAGED_BOTS = [
    {
        "id": "master-bot",
        "name": "Master Bot",
        "icon": "\U0001F916",
        "cmd": [VENV_PYTHON, str(PROJECT_DIR / "AI_Command_Center" / "master_bot.py")],
        "type": "telegram",
        "cwd": str(PROJECT_DIR / "AI_Command_Center"),
    },
    {
        "id": "kakao-bot",
        "name": "Kakao Bot",
        "icon": "\U0001F916",
        "cmd": [sys.executable, str(PROJECT_DIR / "kakao_local" / "main.py"), "--telegram"],
        "type": "telegram",
        "cwd": str(PROJECT_DIR / "kakao_local"),
    },
    {
        "id": "cost-api",
        "name": "Cost API Server",
        "icon": "\u2699\uFE0F",
        "cmd": [sys.executable, str(PROJECT_DIR / "cost_api.py"), "--port", "5050"],
        "type": "http",
        "health_url": "http://localhost:5050/",
        "cwd": str(PROJECT_DIR),
    },
    {
        "id": "shorts-factory",
        "name": "Shorts Factory",
        "icon": "\U0001F3AC",
        "cmd": [sys.executable, str(PROJECT_DIR / "shorts_factory" / "server.py")],
        "type": "http",
        "health_url": "http://localhost:5000/api/health",
        "cwd": str(PROJECT_DIR / "shorts_factory"),
    },
]

# ── 타이머 간격 ──
HEALTH_CHECK_INTERVAL_MS = 30_000   # 30초
COST_REFRESH_INTERVAL_MS = 15_000   # 15초
BOT_STATUS_INTERVAL_MS = 5_000      # 5초
ALERT_CHECK_INTERVAL_MS = 60_000    # 60초

# ── 알림 설정 ──
ALERT_COST_THRESHOLD_KRW = 1_000
ALERT_DESKTOP_ENABLED = True
ALERT_TELEGRAM_ENABLED = True
