"""
Affiliate Marketing System — Data Models
"""
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional


class CampaignStatus(Enum):
    DRAFT       = "draft"
    SCRAPING    = "scraping"
    GENERATING  = "generating"
    RENDERING   = "rendering"
    UPLOADING   = "uploading"
    COMPLETE    = "complete"
    ERROR       = "error"


class Platform(Enum):
    YOUTUBE     = "youtube"
    NAVER_BLOG  = "naver_blog"
    INSTAGRAM   = "instagram"


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


@dataclass
class RenderConfig:
    width: int = 1080
    height: int = 1920
    fps: int = 60
    tts_speed: str = "+15%"
    tts_voice: str = "ko-female"
    effect_mode: str = "dynamic"
    # Anti-ban
    dimension_jitter: bool = True
    opacity_jitter: bool = True
    audio_pad_jitter: bool = True
    subtitle_enabled: bool = True
    subtitle_fontsize: int = 65


@dataclass
class Campaign:
    id: str = ""
    product: Product = field(default_factory=Product)
    ai_content: AIContent = field(default_factory=AIContent)
    render_config: RenderConfig = field(default_factory=RenderConfig)
    status: CampaignStatus = CampaignStatus.DRAFT
    target_platforms: list[Platform] = field(default_factory=list)
    video_path: str = ""
    upload_results: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    total_cost_usd: float = 0.0
    persona: str = ""
    hook_directive: str = ""
    error_message: str = ""
