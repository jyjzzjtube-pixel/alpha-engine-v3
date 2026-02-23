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
load_dotenv(PROJECT_DIR / ".env", override=True)

# ── API 키 ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", ""))
NETLIFY_TOKEN = "nfc_SVmjya7So89j4xPh5n6PB8JcsTGy23jk16d2"
NETLIFY_ACCOUNT = "jyjzzjtube"

# ── 비용 ──
BUDGET_LIMIT_KRW = 50_000
COST_DB_PATH = str(PROJECT_DIR / "api_usage.db")
COMMAND_CENTER_DB = str(BASE_DIR / "command_center.db")

# ── Ollama 로컬 설정 ──
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# ── AI 하이브리드 설정 ──
# 비용 순서: 로컬(무료) → Gemini(무료) → API(유료)
AI_PROVIDERS = {
    "ollama": {"model": OLLAMA_MODEL, "cost": "free-local", "priority": 0},
    "gemini": {"model": "gemini-2.5-flash", "cost": "free", "priority": 1},
    "gemini_pro": {"model": "gemini-2.5-pro", "cost": "free", "priority": 1},
    "claude_haiku": {"model": "claude-haiku-4-5-20251001", "cost": "low", "priority": 2},
    "openai_mini": {"model": "gpt-4o-mini", "cost": "low", "priority": 2},
    "openai": {"model": "gpt-4o", "cost": "medium", "priority": 3},
    "claude_sonnet": {"model": "claude-sonnet-4-6-20250610", "cost": "high", "priority": 4},
    "openai_o1": {"model": "o1", "cost": "high", "priority": 5},
}
# 폴백 체인: 로컬 무료 → 클라우드 무료 → 저가 → 고가
AI_FALLBACK_CHAIN = ["gemini", "ollama", "claude_haiku", "openai_mini", "openai", "claude_sonnet"]

# ── 관리 사이트 ──
MANAGED_SITES = [
    # ── GitHub Pages (배포 완료) ──
    {"id": "alpha-engine", "name": "Alpha Engine v5.7", "url": "https://jyjzzjtube-pixel.github.io/alpha-engine-v3/",
     "type": "github", "category": "finance"},
    {"id": "yjtax-v8", "name": "YJ Tax Master v9.2", "url": "https://jyjzzjtube-pixel.github.io/yjtax-v8/",
     "type": "github", "category": "tax"},
    {"id": "founderone", "name": "Founder One", "url": "https://jyjzzjtube-pixel.github.io/founderone-site/",
     "type": "github", "category": "startup"},
    {"id": "wonwill-app", "name": "제안서 시뮬레이터", "url": "https://jyjzzjtube-pixel.github.io/wonwill-app/",
     "type": "github", "category": "proposal"},
    {"id": "lotto", "name": "YJ 행운의 번호", "url": "https://jyjzzjtube-pixel.github.io/lotto-generator/",
     "type": "github", "category": "utility"},
    {"id": "coupang-blog", "name": "YJ 추천템 블로그", "url": "https://jyjzzjtube-pixel.github.io/coupang-blog/",
     "type": "github", "category": "affiliate"},
    {"id": "coupang-autoblog", "name": "쿠팡 오토블로그 Pro", "url": "https://jyjzzjtube-pixel.github.io/coupang-autoblog/",
     "type": "github", "category": "affiliate"},
    {"id": "yj-db-automation", "name": "YJ DB 자동화", "url": "https://jyjzzjtube-pixel.github.io/yj-db-automation/",
     "type": "github", "category": "automation"},
    {"id": "naver-blog-master", "name": "네이버 블로그 마스터", "url": "https://jyjzzjtube-pixel.github.io/naver-blog-master/",
     "type": "github", "category": "blog"},
    {"id": "yj-partners-mcn", "name": "YJ Partners MCN", "url": "https://jyjzzjtube-pixel.github.io/yj-partners-mcn/",
     "type": "github", "category": "mcn"},
    # ── Google Apps Script ──
    {"id": "yj-drive-manager", "name": "YJ Drive Manager", "url": "https://script.google.com/macros/s/AKfycbyG5607pBRS1tMZZXjmQQNcrLVBUVtr9SBPNzgm2llXI9XH2nzVm8Bg5OfepfDObfM0/exec",
     "type": "external", "category": "drive"},
    # ── 로컬 서비스 ──
    {"id": "shorts-factory", "name": "Shorts Factory", "url": "http://localhost:5000",
     "type": "local", "category": "content", "health_url": "http://localhost:5000/api/health", "enabled": False},
    {"id": "cost-api", "name": "Cost API", "url": "http://localhost:5050",
     "type": "local", "category": "monitoring", "health_url": "http://localhost:5050/", "enabled": False},
    # ── 외부 사이트 (항상 모니터링) ──
    {"id": "naver-blog", "name": "Naver Blog", "url": "https://blog.naver.com/jyjzzj",
     "type": "external", "category": "blog"},
    {"id": "youtube", "name": "YouTube", "url": "https://www.youtube.com/@jjin_deal",
     "type": "external", "category": "social"},
    {"id": "instagram", "name": "Instagram", "url": "https://www.instagram.com/jjin_deal",
     "type": "external", "category": "social"},
    {"id": "naver-blog-ezsbiz", "name": "Naver Blog (쿠팡)", "url": "https://blog.naver.com/ezsbizteam",
     "type": "external", "category": "affiliate"},
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
