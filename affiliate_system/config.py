"""
Affiliate Marketing System — Centralized Configuration
Loads from parent .env, manages API keys, paths, defaults.
"""
import os
import platform
from pathlib import Path
from dotenv import load_dotenv

# ── Path Resolution ──
BASE_DIR = Path(__file__).parent                    # affiliate_system/
PROJECT_DIR = BASE_DIR.parent                       # franchise-db/
load_dotenv(PROJECT_DIR / '.env', override=True)

# ── API Keys ──
GEMINI_API_KEY      = os.getenv('GEMINI_API_KEY', '')
ANTHROPIC_API_KEY   = os.getenv('ANTHROPIC_API_KEY', '')
OPENAI_API_KEY      = os.getenv('OPENAI_API_KEY', '')
DRIVE_CLIENT_ID     = os.getenv('DRIVE_CLIENT_ID', '')
DRIVE_CLIENT_SECRET = os.getenv('DRIVE_CLIENT_SECRET', '')
INSTAGRAM_USERNAME  = os.getenv('INSTAGRAM_USERNAME', '')
INSTAGRAM_PASSWORD  = os.getenv('INSTAGRAM_PASSWORD', '')

# ── Coupang Partners API ──
COUPANG_ACCESS_KEY  = os.getenv('COUPANG_ACCESS_KEY', '')
COUPANG_SECRET_KEY  = os.getenv('COUPANG_SECRET_KEY', '')
COUPANG_PARTNER_ID  = os.getenv('COUPANG_PARTNER_ID', '')

# ── Stock Media API Keys (무료) ──
PEXELS_API_KEY      = os.getenv('PEXELS_API_KEY', '')
PIXABAY_API_KEY     = os.getenv('PIXABAY_API_KEY', '')
UNSPLASH_ACCESS_KEY = os.getenv('UNSPLASH_ACCESS_KEY', '')

# ── AI Model Routing (하이브리드: Gemini 무료 + Claude 고품질) ──
# 전략: 대량/반복 작업은 Gemini(무료), 핵심 창작/정밀 작업은 Claude(유료)
AI_ROUTING = {
    # 핵심 창작 (Claude - 고품질 필수)
    'hook_generation':    {'model': 'claude-3-haiku-20240307',  'provider': 'anthropic'},
    'content_generation': {'model': 'claude-3-haiku-20240307',  'provider': 'anthropic'},
    # 대량/분석 작업 (Gemini - 무료 우선)
    'translation':        {'model': 'gemini-2.5-flash',         'provider': 'gemini'},
    'text_structuring':   {'model': 'gemini-2.5-flash',         'provider': 'gemini'},
    'product_analysis':   {'model': 'gemini-2.5-flash',         'provider': 'gemini'},
    # 검토/분석 (Gemini - 대량 처리 가능)
    'review_legal':       {'model': 'gemini-2.5-flash',         'provider': 'gemini'},
    'review_platform':    {'model': 'gemini-2.5-flash',         'provider': 'gemini'},
    'review_quality':     {'model': 'gemini-2.5-flash',         'provider': 'gemini'},
    'reference_analysis': {'model': 'gemini-2.5-flash',         'provider': 'gemini'},
}

# ── Video Rendering Defaults ──
VIDEO_WIDTH_BASE    = 1080
VIDEO_HEIGHT_BASE   = 1920
VIDEO_FPS           = 60
TTS_SPEED_RATE      = "+15%"
DIMENSION_JITTER    = (10, 30)
OPACITY_JITTER      = (0.92, 1.0)
AUDIO_PAD_JITTER    = (50, 300)

# ── Upload Defaults ──
HUMANIZER_DELAY_MIN = 15 * 60      # 15분 (초)
HUMANIZER_DELAY_MAX = 45 * 60      # 45분 (초)
INSTAGRAM_DM_BATCH  = 20
INSTAGRAM_DM_DELAY  = (3, 8)

# ── Naver Blog ──
NAVER_BLOG_ID       = 'jyjzzj'
CDP_URL             = 'http://127.0.0.1:9222'

# ── Budget ──
BUDGET_LIMIT_KRW    = 50_000
COST_TRACKER_DB     = str(PROJECT_DIR / 'api_usage.db')

# ── Paths ──
WORK_DIR            = BASE_DIR / 'workspace'
RENDER_OUTPUT_DIR   = BASE_DIR / 'renders'
UPLOAD_LOG_DIR      = BASE_DIR / 'logs'

IS_WINDOWS = platform.system() == 'Windows'

# Ensure dirs exist
for d in [WORK_DIR, RENDER_OUTPUT_DIR, UPLOAD_LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)
