"""
Affiliate Marketing System — Data Models V2
=============================================
플랫폼별 프리셋, 브랜딩 템플릿, BGM 장르, 전환 효과,
V2 블로그/숏폼/대화형 파이프라인 데이터 모델.
"""
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional, Callable


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════

class CampaignStatus(Enum):
    DRAFT       = "draft"
    SCRAPING    = "scraping"
    GENERATING  = "generating"
    RENDERING   = "rendering"
    UPLOADING   = "uploading"
    COMPLETE    = "complete"
    ERROR       = "error"


class Platform(Enum):
    YOUTUBE     = "youtube"         # YouTube Shorts
    NAVER_BLOG  = "naver_blog"      # 네이버 블로그 (영상+글)
    INSTAGRAM   = "instagram"       # Instagram Reels


class TransitionType(Enum):
    """영상 전환 효과 타입"""
    CROSSFADE    = "crossfade"      # 크로스디졸브 (기본)
    SLIDE_LEFT   = "slide_left"     # 좌측 슬라이드
    SLIDE_RIGHT  = "slide_right"    # 우측 슬라이드
    SLIDE_UP     = "slide_up"       # 상단 슬라이드
    ZOOM_IN      = "zoom_in"        # 줌인 전환
    ZOOM_OUT     = "zoom_out"       # 줌아웃 전환
    WIPE_LEFT    = "wipe_left"      # 좌측 와이프
    WIPE_RIGHT   = "wipe_right"     # 우측 와이프
    FLASH        = "flash"          # 화이트 플래시
    BLUR         = "blur"           # 블러 전환
    GLITCH       = "glitch"         # 글리치 효과


class BGMGenre(Enum):
    """BGM 장르 프리셋"""
    LOFI         = "lofi"           # Lo-Fi 힙합 (기존)
    UPBEAT       = "upbeat"         # 업비트 팝
    CINEMATIC    = "cinematic"      # 시네마틱 엠비언트
    ENERGETIC    = "energetic"      # 에너제틱 일렉트로닉
    CHILL        = "chill"          # 칠 어쿠스틱
    DRAMATIC     = "dramatic"       # 드라마틱 오케스트라
    TRENDY       = "trendy"         # 트렌디 K-Pop 스타일


class TextAnimation(Enum):
    """모션 텍스트 애니메이션 타입"""
    FADE_IN      = "fade_in"        # 페이드인
    SLIDE_UP     = "slide_up"       # 아래→위 슬라이드
    TYPEWRITER   = "typewriter"     # 타자기 효과
    BOUNCE       = "bounce"         # 바운스
    SCALE_UP     = "scale_up"       # 작은→큰 스케일
    GLOW         = "glow"           # 글로우 효과
    SHAKE        = "shake"          # 흔들림 (임팩트)
    SPLIT        = "split"          # 좌우 분리 → 합치기


# ═══════════════════════════════════════════════════════════════════════════
# 플랫폼별 프리셋 — 각 플랫폼의 최적 스펙 정의
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PlatformPreset:
    """플랫폼별 콘텐츠 규격 프리셋"""
    platform: Platform

    # 영상 스펙
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 60
    max_duration_sec: int = 60       # 최대 영상 길이 (초)
    min_duration_sec: int = 15       # 최소 영상 길이 (초)
    ideal_duration_sec: int = 30     # 이상적 영상 길이 (초)
    video_bitrate: str = "10M"       # 영상 비트레이트

    # 텍스트 스펙
    title_max_chars: int = 100       # 제목 최대 글자수
    body_max_chars: int = 2200       # 본문 최대 글자수
    hashtag_count: int = 15          # 권장 해시태그 수

    # 썸네일 스펙
    thumb_width: int = 1080
    thumb_height: int = 1920
    thumb_format: str = "JPEG"

    # TTS/오디오
    tts_speed: str = "+15%"
    bgm_volume: float = 0.08        # BGM 볼륨 (TTS 있을 때)
    bgm_genre: BGMGenre = BGMGenre.LOFI

    # 자막 스펙
    subtitle_fontsize: int = 65
    subtitle_position: str = "bottom"  # bottom, center, top
    subtitle_style: str = "modern"   # modern, classic, minimal, bold, framed, pro
    subtitle_animation: str = "fade"   # fade / typing / none

    # 캔버스 레이아웃
    canvas_layout: str = "framed"    # framed(상단설명+중앙이미지+하단자막) / fullscreen / auto

    # 전환 효과
    transition_type: TransitionType = TransitionType.CROSSFADE
    transition_duration: float = 0.4  # 전환 길이 (초)

    # 텍스트 애니메이션
    text_animation: TextAnimation = TextAnimation.FADE_IN

    # 브랜딩
    watermark_enabled: bool = False
    intro_enabled: bool = False
    outro_enabled: bool = False
    intro_duration: float = 2.0      # 인트로 길이 (초)
    outro_duration: float = 3.0      # 아웃트로 길이 (초)

    # CTA
    cta_text: str = ""               # 행동 유도 텍스트
    cta_position: str = "end"        # end, overlay, both


# ── 플랫폼 프리셋 사전 정의 ──

PLATFORM_PRESETS: dict[Platform, PlatformPreset] = {
    Platform.YOUTUBE: PlatformPreset(
        platform=Platform.YOUTUBE,
        # YouTube Shorts: 9:16, 최대 60초 — HQ 최적화
        video_width=1080,
        video_height=1920,
        video_fps=60,
        max_duration_sec=60,
        min_duration_sec=15,
        ideal_duration_sec=45,
        video_bitrate="18M",        # 10M→18M HQ
        # 제목 100자, 설명 5000자 (첫 2줄이 중요)
        title_max_chars=100,
        body_max_chars=5000,
        hashtag_count=10,
        # 썸네일
        thumb_width=1080,
        thumb_height=1920,
        thumb_format="JPEG",
        # TTS/오디오 — 자연스러운 속도 + 잔잔한 BGM
        tts_speed="+0%",            # +5%→+0% 더 자연어 속도
        bgm_volume=0.10,            # 잔잔하게
        bgm_genre=BGMGenre.LOFI,    # UPBEAT→LOFI 잔잔한 배경음
        # 자막 — pro 스타일 (굵은 텍스트+아웃라인+컬러강조, 레퍼런스 수준)
        subtitle_fontsize=62,
        subtitle_position="bottom",
        subtitle_style="pro",       # 세련된 볼드+아웃라인+컬러 강조
        subtitle_animation="typing", # 타이핑 효과
        # 캔버스 — framed 레이아웃 (상단 설명 + 중앙 이미지 + 하단 자막)
        canvas_layout="framed",
        # 전환
        transition_type=TransitionType.CROSSFADE,
        transition_duration=0.3,
        # 텍스트 애니메이션
        text_animation=TextAnimation.SCALE_UP,
        # 브랜딩
        watermark_enabled=True,
        intro_enabled=True,
        outro_enabled=True,
        intro_duration=1.5,
        outro_duration=3.0,
        # CTA
        cta_text="구독 & 좋아요 부탁드려요!",
        cta_position="end",
    ),
    Platform.INSTAGRAM: PlatformPreset(
        platform=Platform.INSTAGRAM,
        # Instagram Reels: 9:16, 최대 90초
        video_width=1080,
        video_height=1920,
        video_fps=30,                # 인스타는 30fps 권장
        max_duration_sec=90,
        min_duration_sec=15,
        ideal_duration_sec=30,
        video_bitrate="10M",
        # 캡션 2200자, 해시태그 최대 30개
        title_max_chars=100,         # 릴스 제목은 짧게
        body_max_chars=2200,
        hashtag_count=20,            # 인스타는 15~25개 권장
        # 썸네일
        thumb_width=1080,
        thumb_height=1920,
        thumb_format="JPEG",
        # TTS/오디오
        tts_speed="+10%",
        bgm_volume=0.10,
        bgm_genre=BGMGenre.TRENDY,
        # 자막
        subtitle_fontsize=60,
        subtitle_position="center",
        subtitle_style="modern",
        # 전환
        transition_type=TransitionType.SLIDE_LEFT,
        transition_duration=0.35,
        # 텍스트 애니메이션
        text_animation=TextAnimation.BOUNCE,
        # 브랜딩
        watermark_enabled=True,
        intro_enabled=False,         # 릴스는 인트로 없이 바로 시작
        outro_enabled=True,
        intro_duration=0.0,
        outro_duration=2.5,
        # CTA
        cta_text="저장📌 & 팔로우 해주세요!",
        cta_position="overlay",
    ),
    Platform.NAVER_BLOG: PlatformPreset(
        platform=Platform.NAVER_BLOG,
        # 네이버 블로그: 가로형 or 세로형, 글+영상 혼합
        video_width=1080,
        video_height=1920,           # 영상은 세로형 유지
        video_fps=30,
        max_duration_sec=180,        # 블로그 영상은 길어도 됨
        min_duration_sec=30,
        ideal_duration_sec=60,
        video_bitrate="8M",
        # 블로그: 제목 100자, 본문 제한 없음 (3000~5000자 권장)
        title_max_chars=100,
        body_max_chars=5000,
        hashtag_count=10,            # 네이버는 10개 이하 권장
        # 블로그 대표 이미지 (가로형)
        thumb_width=900,
        thumb_height=600,
        thumb_format="JPEG",
        # TTS/오디오
        tts_speed="+5%",             # 블로그는 느린 속도
        bgm_volume=0.12,
        bgm_genre=BGMGenre.CHILL,
        # 자막
        subtitle_fontsize=55,
        subtitle_position="bottom",
        subtitle_style="classic",
        # 전환
        transition_type=TransitionType.CROSSFADE,
        transition_duration=0.5,
        # 텍스트 애니메이션
        text_animation=TextAnimation.FADE_IN,
        # 브랜딩
        watermark_enabled=True,
        intro_enabled=True,
        outro_enabled=True,
        intro_duration=2.0,
        outro_duration=3.5,
        # CTA
        cta_text="더 많은 정보는 블로그에서 확인하세요! 👆",
        cta_position="both",
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# 브랜딩 설정
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BrandingConfig:
    """인트로/아웃트로/워터마크 브랜딩 설정"""
    # 인트로
    intro_text: str = ""             # 인트로 텍스트 (예: "YJ Partners MCN")
    intro_subtitle: str = ""         # 인트로 부제
    intro_bg_color: str = "#1a1a2e"  # 인트로 배경색
    intro_text_color: str = "#ffffff"
    intro_accent_color: str = "#e94560"
    intro_logo_path: str = ""        # 로고 이미지 경로

    # 아웃트로
    outro_text: str = ""             # 아웃트로 메인 텍스트
    outro_cta: str = ""              # 아웃트로 CTA
    outro_bg_color: str = "#0f3460"
    outro_text_color: str = "#ffffff"

    # 워터마크
    watermark_text: str = ""         # 텍스트 워터마크
    watermark_logo_path: str = ""    # 로고 워터마크
    watermark_opacity: float = 0.3   # 워터마크 불투명도
    watermark_position: str = "bottom_right"  # 위치
    watermark_size: int = 30         # 폰트 크기


# ── 브랜드별 브랜딩 프리셋 ──

BRAND_BRANDING: dict[str, BrandingConfig] = {
    "오레노카츠": BrandingConfig(
        intro_text="오레노카츠",
        intro_subtitle="일본 정통 돈카츠",
        intro_bg_color="#2d1b0e",
        intro_accent_color="#d4a574",
        outro_text="오레노카츠",
        outro_cta="매장 방문 예약하기",
        outro_bg_color="#1a0f05",
        watermark_text="오레노카츠",
        watermark_opacity=0.25,
    ),
    "무사짬뽕": BrandingConfig(
        intro_text="무사짬뽕",
        intro_subtitle="정통 중화풍 짬뽕",
        intro_bg_color="#8b0000",
        intro_accent_color="#ff4444",
        outro_text="무사짬뽕",
        outro_cta="가까운 매장 찾기",
        outro_bg_color="#4a0000",
        watermark_text="무사짬뽕",
        watermark_opacity=0.25,
    ),
    "브릿지원": BrandingConfig(
        intro_text="BRIDGE ONE",
        intro_subtitle="프랜차이즈 창업 컨설팅",
        intro_bg_color="#1a1a2e",
        intro_accent_color="#e94560",
        outro_text="BRIDGE ONE",
        outro_cta="무료 창업 상담 신청",
        outro_bg_color="#0f3460",
        watermark_text="BRIDGE ONE",
        watermark_opacity=0.3,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# 핵심 데이터 모델
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Product:
    url: str = ""
    title: str = ""
    price: str = ""
    image_urls: list[str] = field(default_factory=list)
    description: str = ""
    affiliate_link: str = ""
    scraped_at: Optional[datetime] = None


@dataclass
class AIContent:
    hook_text: str = ""
    body_text: str = ""
    translated_text: str = ""
    hashtags: list[str] = field(default_factory=list)
    narration_scripts: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    models_used: list[str] = field(default_factory=list)
    # 플랫폼별 최적화 콘텐츠
    platform_contents: dict[str, dict] = field(default_factory=dict)
    # 썸네일 텍스트
    thumbnail_text: str = ""
    thumbnail_subtitle: str = ""


@dataclass
class RenderConfig:
    width: int = 1080
    height: int = 1920
    fps: int = 60
    tts_speed: str = "+15%"
    tts_voice: str = "ko-female"
    effect_mode: str = "dynamic"
    # Anti-ban (HQ 모드에서는 전부 False)
    anti_ban_enabled: bool = True      # False면 노이즈/지터 전부 스킵
    dimension_jitter: bool = True
    opacity_jitter: bool = True
    audio_pad_jitter: bool = True
    subtitle_enabled: bool = True
    subtitle_fontsize: int = 65
    subtitle_style: str = "modern"
    subtitle_position: str = "bottom"    # top / center / bottom
    subtitle_animation: str = "fade"     # fade / typing / none
    # 캔버스 레이아웃
    canvas_layout: str = "auto"          # auto / framed / fullscreen / legacy
    # 인코딩
    video_bitrate: str = "10M"
    audio_bitrate: str = "192k"
    encode_preset: str = "medium"      # slow=고품질, medium=균형, fast=속도
    # 향상된 렌더링 옵션
    transition_type: str = "crossfade"
    transition_duration: float = 0.4
    text_animation: str = "fade_in"
    bgm_genre: str = "lofi"
    bgm_volume: float = 0.08
    # 브랜딩
    branding_config: Optional[BrandingConfig] = None
    watermark_enabled: bool = False
    intro_enabled: bool = False
    outro_enabled: bool = False

    @classmethod
    def from_platform_preset(cls, preset: PlatformPreset,
                             brand: str = "") -> "RenderConfig":
        """플랫폼 프리셋으로부터 RenderConfig를 생성한다."""
        branding = BRAND_BRANDING.get(brand)
        # YouTube는 HQ 모드 (안티밴 OFF, 고비트레이트)
        is_hq = preset.platform == Platform.YOUTUBE
        return cls(
            width=preset.video_width,
            height=preset.video_height,
            fps=preset.video_fps,
            tts_speed=preset.tts_speed,
            tts_voice="ko-female",
            effect_mode="cinematic" if is_hq else "dynamic",
            anti_ban_enabled=not is_hq,
            dimension_jitter=not is_hq,
            opacity_jitter=not is_hq,
            audio_pad_jitter=not is_hq,
            subtitle_enabled=True,
            subtitle_fontsize=preset.subtitle_fontsize,
            subtitle_style=preset.subtitle_style,
            subtitle_animation=preset.subtitle_animation,
            canvas_layout=preset.canvas_layout,
            video_bitrate=preset.video_bitrate,
            audio_bitrate="256k" if is_hq else "192k",
            encode_preset="slow" if is_hq else "medium",
            transition_type=preset.transition_type.value,
            transition_duration=preset.transition_duration,
            text_animation=preset.text_animation.value,
            bgm_genre=preset.bgm_genre.value,
            bgm_volume=preset.bgm_volume,
            branding_config=branding,
            watermark_enabled=preset.watermark_enabled,
            intro_enabled=preset.intro_enabled,
            outro_enabled=preset.outro_enabled,
        )


@dataclass
class Campaign:
    id: str = ""
    product: Product = field(default_factory=Product)
    ai_content: AIContent = field(default_factory=AIContent)
    render_config: RenderConfig = field(default_factory=RenderConfig)
    status: CampaignStatus = CampaignStatus.DRAFT
    target_platforms: list[Platform] = field(default_factory=list)
    video_path: str = ""
    # 플랫폼별 렌더링 결과
    platform_videos: dict[str, str] = field(default_factory=dict)
    platform_thumbnails: dict[str, str] = field(default_factory=dict)
    upload_results: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    total_cost_usd: float = 0.0
    persona: str = ""
    hook_directive: str = ""
    error_message: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# V2 — Coupang Partners Profit-Maximizer 확장 모델
# ═══════════════════════════════════════════════════════════════════════════

class ContentMode(Enum):
    """V2 콘텐츠 생성 모드"""
    BLOG_ONLY   = "blog_only"       # 네이버 블로그만
    SHORTS_ONLY = "shorts_only"     # 숏폼 영상만 (유튜브/인스타/틱톡)
    FULL_V2     = "full_v2"         # 블로그 + 숏폼 동시 (기본)


class PipelineStateV2(Enum):
    """V2 대화형 파이프라인 상태"""
    IDLE              = "idle"
    AWAITING_LINK     = "awaiting_link"       # Step 1: 쿠팡 링크 대기
    ANALYZING         = "analyzing"            # Step 2: 링크 분석 중
    AWAITING_CONFIRM  = "awaiting_confirm"     # Step 2: 사용자 확인 대기
    EXECUTING         = "executing"            # Steps 3-10: 풀 실행 중
    PAUSED            = "paused"               # 사용자 확인 대기 (input)
    COMPLETE          = "complete"
    ERROR             = "error"


class EmotionTag(Enum):
    """숏폼 대본 장면별 감정 태그"""
    EXCITED   = "excited"     # 흥분/놀람 — rate:+20%, pitch:+5Hz
    FRIENDLY  = "friendly"    # 친근/설명 — rate:+5%, pitch:0
    URGENT    = "urgent"      # 긴급/강조 — rate:+25%, pitch:+3Hz
    DRAMATIC  = "dramatic"    # 드라마틱 — rate:-5%, pitch:-2Hz
    CALM      = "calm"        # 차분/신뢰 — rate:0%, pitch:0
    HYPED     = "hyped"       # 최고조 흥분 — rate:+30%, pitch:+8Hz


class VideoSource(Enum):
    """비디오 소스 유형"""
    PEXELS_STOCK    = "pexels_stock"      # Pexels 무료 스톡 영상
    PIXABAY_STOCK   = "pixabay_stock"     # Pixabay 무료 스톡 영상
    YOUTUBE_CC      = "youtube_cc"        # YouTube Creative Commons
    TIKTOK          = "tiktok"            # TikTok 크롤링
    INSTAGRAM       = "instagram"         # Instagram 크롤링
    AI_GENERATED    = "ai_generated"      # AI 생성 (Veo 3.1 등)
    PLACEHOLDER     = "placeholder"       # 플레이스홀더 (사용자 수동)


class ImageSource(Enum):
    """이미지 소스 유형"""
    PRODUCT_OWN     = "product_own"       # 상품 자체 이미지
    PEXELS          = "pexels"
    PIXABAY         = "pixabay"
    UNSPLASH        = "unsplash"
    GOOGLE          = "google"
    PINTEREST       = "pinterest"


# ── V2 데이터클래스 ──

@dataclass
class BlogContent:
    """V2 네이버 블로그 콘텐츠 — 자연스러운 설명/추천 스타일"""
    title: str = ""                                          # SEO 최적화 제목
    intro: str = ""                                          # 도입부 (2-3줄)
    body_sections: list[str] = field(default_factory=list)   # 본문 4개 섹션
    image_keywords: list[str] = field(default_factory=list)  # 이미지 검색 키워드 5개 (영어)
    image_paths: list[str] = field(default_factory=list)     # 다운로드된 이미지 경로
    hashtags: list[str] = field(default_factory=list)        # 해시태그 5-7개
    seo_keywords: list[str] = field(default_factory=list)    # 메인+서브 키워드 4개
    cta_text: str = ""                                       # 구매 유도 텍스트
    coupang_link: str = ""                                   # 쿠팡 어필리에이트 링크
    disclaimer: str = ("이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
                       "이에 따른 일정액의 수수료를 제공받습니다.")
    blog_html: str = ""                                      # 최종 생성된 HTML


@dataclass
class ShortsScene:
    """숏폼 영상 1개 장면 데이터"""
    scene_num: int = 0
    text: str = ""                    # 자막/대본 텍스트
    duration: float = 3.0             # 장면 길이 (초)
    emotion: EmotionTag = EmotionTag.FRIENDLY  # 감정 태그
    tts_path: str = ""                # TTS 음성 파일 경로
    tts_duration: float = 0.0         # 실제 TTS 재생 시간
    video_clip_path: str = ""         # 배경 영상 클립 경로
    word_timestamps: list[dict] = field(default_factory=list)  # Whisper 단어 타임스탬프


@dataclass
class ShortsContent:
    """V2 숏폼 콘텐츠 (세탁 영상 기반)"""
    scenes: list[ShortsScene] = field(default_factory=list)  # 5-7개 장면
    source_videos: list[dict] = field(default_factory=list)  # 크롤링 원본 [{path, source, duration, license}]
    laundered_videos: list[str] = field(default_factory=list) # 4단계 세탁 완료 영상
    sfx_paths: list[str] = field(default_factory=list)       # Mixkit SFX 경로
    bgm_path: str = ""                                       # BGM 경로
    final_video_path: str = ""                               # 최종 렌더링 영상
    subtitle_path: str = ""                                  # ASS 자막 파일 경로
    dm_prompt_keyword: str = ""                              # DM 유도 키워드
    copyright_notice: str = ""                               # 저작권 방어 문구
    coupang_link: str = ""                                   # 쿠팡 어필리에이트 링크


@dataclass
class PlaceholderItem:
    """AI 생성 필요 플레이스홀더"""
    media_type: str = "image"         # "image" 또는 "video"
    context: str = ""                 # 설명 (무엇이 필요한지)
    folder_path: str = ""             # 파일을 넣어야 할 폴더
    specs: dict = field(default_factory=dict)  # {width, height, format} 또는 {duration, resolution}
    message: str = ""                 # 사용자에게 보여줄 메시지
    filled: bool = False              # 채워졌는지 여부


@dataclass
class V2CampaignConfig:
    """V2 캠페인 설정"""
    mode: ContentMode = ContentMode.FULL_V2
    coupang_link: str = ""
    blog_enabled: bool = True         # 네이버 블로그 생성
    shorts_enabled: bool = True       # 숏폼 영상 생성
    youtube_enabled: bool = True      # YouTube Shorts 업로드
    instagram_enabled: bool = True    # Instagram Reels 업로드
    naver_upload: bool = True         # 네이버 블로그 업로드
    dm_automation: bool = True        # DM 유도 문구 삽입
    copyright_defense: bool = True    # 저작권 방어 문구 삽입
    placeholder_enabled: bool = True  # 플레이스홀더 활성화
    drive_archive: bool = True        # Google Drive 아카이빙
    brand: str = ""
    persona: str = ""
    user_email: str = ""              # 저작권 방어용 이메일


@dataclass
class V2Campaign:
    """V2 캠페인 전체 데이터"""
    id: str = ""
    config: V2CampaignConfig = field(default_factory=V2CampaignConfig)
    product: Product = field(default_factory=Product)
    state: PipelineStateV2 = PipelineStateV2.IDLE

    # V2 콘텐츠
    blog_content: BlogContent = field(default_factory=BlogContent)
    shorts_content: ShortsContent = field(default_factory=ShortsContent)
    placeholders: list[PlaceholderItem] = field(default_factory=list)

    # 렌더링 결과
    platform_videos: dict[str, str] = field(default_factory=dict)    # {platform: video_path}
    platform_thumbnails: dict[str, str] = field(default_factory=dict) # {platform: thumb_path}

    # 업로드 결과
    upload_results: dict = field(default_factory=dict)
    drive_url: str = ""

    # 비용/메타
    ai_cost_usd: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    error_message: str = ""

    # V1 호환
    ai_content: AIContent = field(default_factory=AIContent)
    status: CampaignStatus = CampaignStatus.DRAFT
