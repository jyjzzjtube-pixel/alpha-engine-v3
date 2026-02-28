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

# ── Telegram ──
TELEGRAM_BOT_TOKEN  = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID    = os.getenv('TELEGRAM_CHAT_ID', '')

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
TTS_SPEED_RATE      = "+5%"           # +15%→+5% 자연스러운 속도
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

# ═══════════════════════════════════════════════════════════════════════════
# V2 — Coupang Partners Profit-Maximizer 설정
# ═══════════════════════════════════════════════════════════════════════════

# ── V2 네이버 블로그 설정 ──
BLOG_CHAR_MIN           = 1500          # 블로그 본문 최소 글자수
BLOG_CHAR_MAX           = 2000          # 블로그 본문 최대 글자수
BLOG_IMAGE_COUNT_MIN    = 5             # 최소 이미지 개수
BLOG_IMAGE_COUNT_MAX    = 7             # 최대 이미지 개수
BLOG_HASHTAG_COUNT      = 7             # 해시태그 개수
BLOG_IMAGE_MIN_WIDTH    = 800           # 이미지 최소 가로 해상도
BLOG_IMAGE_MIN_HEIGHT   = 600           # 이미지 최소 세로 해상도
BLOG_IMAGE_RESIZE_WIDTH = 860           # 네이버 블로그 본문 최적 가로폭

# ── V2 FFmpeg 영상 세탁 설정 ──
LAUNDER_CROP_PCT_MIN    = 0.03          # 최소 크롭 비율 (3%)
LAUNDER_CROP_PCT_MAX    = 0.06          # 최대 크롭 비율 (6%)
LAUNDER_SPEED_MIN       = 1.1           # 최소 배속
LAUNDER_SPEED_MAX       = 1.2           # 최대 배속
LAUNDER_SHARPEN_AMOUNT  = 1.5           # 샤프닝 강도 (luma_amount)
LAUNDER_CONTRAST_BOOST  = 1.08          # 대비 증가 배율
LAUNDER_VIBRANCE_BOOST  = 1.12          # 채도 증가 배율
LAUNDER_BRIGHTNESS_BOOST = 1.03         # 밝기 증가 배율
FFMPEG_HWACCEL          = 'cuda'        # GPU 하드웨어 가속 (cuda/dxva2/d3d11va)
FFMPEG_ENCODER          = 'h264_nvenc'  # GPU 인코더 (h264_nvenc/h264_amf)
FFMPEG_ENCODER_FALLBACK = 'libx264'     # CPU 폴백 인코더
FFMPEG_CRF              = '18'          # 품질 (낮을수록 고화질, 18=거의 무손실)
FFMPEG_PRESET           = 'p4'          # NVENC 프리셋 (p1=최빠름, p7=최고화질)

# ── V2 DM 자동화 / 저작권 방어 ──
DM_KEYWORD_DEFAULT      = "링크"
DM_PROMPT_TEMPLATE      = ("[{keyword}]를 댓글로 남겨주시면 "
                           "구매 링크를 DM으로 즉시 보내드립니다!")
DM_REPLY_TEMPLATE       = ("안녕하세요! 요청하신 구매 링크입니다 :)\n\n"
                           "{affiliate_link}\n\n"
                           "빠른 배송으로 만나보세요!")
COPYRIGHT_DEFENSE_TEXT  = ("저작권 관련 문제가 있을 시 아래 이메일로 연락 주시면 "
                           "즉시 삭제 조치하겠습니다.")
COPYRIGHT_EMAIL         = os.getenv('COPYRIGHT_EMAIL', '')
COUPANG_DISCLAIMER      = ("이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
                           "이에 따른 일정액의 수수료를 제공받습니다.")

# ── V2 Anti-Ban 크롤링 설정 ──
PROXY_URL               = os.getenv('PROXY_URL', '')         # socks5://user:pass@host:port
COOKIES_TXT_PATH        = str(PROJECT_DIR / 'cookies.txt')   # 브라우저 쿠키 파일
CRAWL_MIN_DELAY         = 2.0           # 크롤링 요청 간 최소 딜레이 (초)
CRAWL_MAX_DELAY         = 5.0           # 크롤링 요청 간 최대 딜레이 (초)
CRAWL_MAX_RETRIES       = 3             # 최대 재시도 횟수

# ── V2 Whisper 자막 싱크 설정 ──
WHISPER_MODEL_SIZE      = 'base'        # tiny/base/small/medium/large
WHISPER_LANGUAGE        = 'ko'          # 한국어
WHISPER_DEVICE          = 'cuda'        # cuda 또는 cpu

# ── V2 TTS 감정 프리셋 (Edge-TTS SSML prosody) ──
TTS_EMOTION_PRESETS = {
    'excited':  {'rate': '+20%', 'pitch': '+5Hz',  'volume': '+10%'},
    'friendly': {'rate': '+5%',  'pitch': '+0Hz',  'volume': '+0%'},
    'urgent':   {'rate': '+25%', 'pitch': '+3Hz',  'volume': '+15%'},
    'dramatic': {'rate': '-5%',  'pitch': '-2Hz',  'volume': '+5%'},
    'calm':     {'rate': '+0%',  'pitch': '+0Hz',  'volume': '+0%'},
    'hyped':    {'rate': '+30%', 'pitch': '+8Hz',  'volume': '+20%'},
}

# ── V2 숏폼 영상 스펙 ──
SHORTS_MIN_SCENES       = 5             # 최소 장면 수
SHORTS_MAX_SCENES       = 7             # 최대 장면 수
SHORTS_MAX_DURATION     = 59            # 최대 영상 길이 (초, YouTube Shorts 제한)
SHORTS_RESOLUTION       = (1080, 1920)  # 세로 9:16
SHORTS_FPS              = 30            # 프레임레이트

# ── V2 Google Custom Search (이미지) ──
GOOGLE_CSE_API_KEY      = os.getenv('GOOGLE_CSE_API_KEY', '')
GOOGLE_CSE_CX           = os.getenv('GOOGLE_CSE_CX', '')

# ── V2 경로 ──
V2_WORK_DIR             = WORK_DIR / 'v2_campaigns'
V2_BLOG_DIR             = WORK_DIR / 'v2_blog'
V2_SHORTS_DIR           = WORK_DIR / 'v2_shorts'
V2_LAUNDERED_DIR        = WORK_DIR / 'v2_laundered'
V2_TTS_DIR              = WORK_DIR / 'v2_tts'
V2_SUBTITLE_DIR         = WORK_DIR / 'v2_subtitles'
V2_SFX_DIR              = WORK_DIR / 'v2_sfx'
V2_PLACEHOLDER_DIR      = WORK_DIR / 'v2_placeholders'

# Ensure V2 dirs exist
for d in [WORK_DIR, RENDER_OUTPUT_DIR, UPLOAD_LOG_DIR,
          V2_WORK_DIR, V2_BLOG_DIR, V2_SHORTS_DIR,
          V2_LAUNDERED_DIR, V2_TTS_DIR, V2_SUBTITLE_DIR,
          V2_SFX_DIR, V2_PLACEHOLDER_DIR]:
    d.mkdir(parents=True, exist_ok=True)
