"""
Affiliate Marketing System -- Video Rendering & Anti-Ban Pipeline
=================================================================
MoviePy 기반 숏폼 영상 렌더링, 안티밴 변조, 기존 영상 세탁 기능.
MoviePy v1 / v2 양쪽 API 를 자동 감지하여 호환 동작.

v2 업그레이드 (Pro Quality):
- 플랫폼별 렌더링 (YouTube Shorts / Instagram Reels / Naver Blog)
- 다양한 전환 효과 (슬라이드, 줌, 와이프, 플래시, 글리치 등)
- 모션 텍스트 애니메이션 (타자기, 바운스, 스케일, 글로우 등)
- 장르별 BGM 생성 (Lo-Fi, Upbeat, Cinematic, Energetic 등)
- 인트로/아웃트로/워터마크 브랜딩 시스템
- 플랫폼별 RenderConfig 자동 설정
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import uuid
import wave
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from affiliate_system.config import (
    VIDEO_WIDTH_BASE,
    VIDEO_HEIGHT_BASE,
    VIDEO_FPS,
    DIMENSION_JITTER,
    OPACITY_JITTER,
    AUDIO_PAD_JITTER,
    TTS_SPEED_RATE,
    RENDER_OUTPUT_DIR,
    WORK_DIR,
)
from affiliate_system.models import (
    RenderConfig, Campaign, Platform,
    PlatformPreset, PLATFORM_PRESETS,
    BrandingConfig, BRAND_BRANDING,
    TransitionType, BGMGenre, TextAnimation,
)
from affiliate_system.utils import setup_logger, retry, file_md5, ensure_dir

__all__ = ["VideoForge"]

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
log = setup_logger("video_editor", "video_editor.log")

# ---------------------------------------------------------------------------
# MoviePy 호환 레이어
# ---------------------------------------------------------------------------
MOVIEPY_V2: bool = False

try:
    from moviepy import (
        VideoFileClip,
        ImageClip,
        AudioFileClip,
        CompositeVideoClip,
        CompositeAudioClip,
        concatenate_videoclips,
        concatenate_audioclips,
    )
    MOVIEPY_V2 = True
except ImportError:
    try:
        from moviepy.editor import (  # type: ignore[no-redef]
            VideoFileClip,
            ImageClip,
            AudioFileClip,
            CompositeVideoClip,
            CompositeAudioClip,
            concatenate_videoclips,
        )
        try:
            from moviepy.editor import concatenate_audioclips  # type: ignore[no-redef]
        except ImportError:
            concatenate_audioclips = None  # type: ignore[assignment]
    except ImportError:
        raise ImportError(
            "moviepy 가 설치되어 있지 않습니다. pip install moviepy 를 실행하세요."
        )

log.info("MoviePy %s 감지됨", "v2" if MOVIEPY_V2 else "v1")

# ---------------------------------------------------------------------------
# TTS 음성 매핑
# ---------------------------------------------------------------------------
TTS_VOICES = {
    "ko-female": "ko-KR-SunHiNeural",
    "ko-male": "ko-KR-InJoonNeural",
    "en-female": "en-US-JennyNeural",
    "en-male": "en-US-GuyNeural",
    # 추가 음성 (감정/스타일 변화용)
    "ko-female-bright": "ko-KR-SunHiNeural",   # 밝은 톤 (SSML prosody 조절)
    "ko-male-calm": "ko-KR-InJoonNeural",       # 차분한 톤
}

# SSML 감정 프리셋 — generate_tts_ssml()에서 사용
TTS_EMOTION_PRESETS = {
    "excited": {"rate": "+20%", "pitch": "+10%", "volume": "+10%"},
    "calm": {"rate": "-10%", "pitch": "-5%", "volume": "-5%"},
    "dramatic": {"rate": "-15%", "pitch": "+5%", "volume": "+15%"},
    "friendly": {"rate": "+5%", "pitch": "+3%", "volume": "+0%"},
    "urgent": {"rate": "+25%", "pitch": "+8%", "volume": "+15%"},
    "whisper": {"rate": "-20%", "pitch": "-10%", "volume": "-20%"},
}

# ---------------------------------------------------------------------------
# 모션 이펙트 프리셋
# ---------------------------------------------------------------------------
EFFECT_PRESETS = {
    "dynamic": [
        "zoom_in", "pan_right", "tilt_up", "zoom_out",
        "diag_dr", "pulse", "pan_left", "drift",
        "tilt_down", "zoom_rotate", "diag_dl", "bounce",
    ],
    "cinematic": ["zoom_in", "drift", "zoom_out", "drift", "zoom_in", "drift"],
    "speed": ["pan_left", "pan_right", "diag_dr", "diag_dl", "tilt_up", "tilt_down"],
    "simple": ["zoom_in"] * 12,
}

# ---------------------------------------------------------------------------
# BGM 장르별 파라미터 — generate_bgm_pro()에서 사용
# ---------------------------------------------------------------------------
BGM_GENRE_PARAMS = {
    "lofi": {"bpm": 85, "key_freq": 55, "pad_freqs": (220, 330, 440),
             "pad_vol": 0.02, "kick_vol": 0.4, "bass_vol": 0.1,
             "hihat_vol": 0.06, "fade_in": 0.8, "fade_out": 2.0},
    "upbeat": {"bpm": 120, "key_freq": 65, "pad_freqs": (261, 392, 523),
               "pad_vol": 0.03, "kick_vol": 0.5, "bass_vol": 0.15,
               "hihat_vol": 0.08, "fade_in": 0.3, "fade_out": 1.5},
    "cinematic": {"bpm": 60, "key_freq": 44, "pad_freqs": (174, 261, 349),
                  "pad_vol": 0.04, "kick_vol": 0.25, "bass_vol": 0.08,
                  "hihat_vol": 0.02, "fade_in": 2.0, "fade_out": 3.0},
    "energetic": {"bpm": 140, "key_freq": 73, "pad_freqs": (293, 440, 587),
                  "pad_vol": 0.025, "kick_vol": 0.55, "bass_vol": 0.18,
                  "hihat_vol": 0.10, "fade_in": 0.2, "fade_out": 1.0},
    "chill": {"bpm": 75, "key_freq": 49, "pad_freqs": (196, 294, 392),
              "pad_vol": 0.035, "kick_vol": 0.3, "bass_vol": 0.08,
              "hihat_vol": 0.04, "fade_in": 1.5, "fade_out": 2.5},
    "dramatic": {"bpm": 70, "key_freq": 41, "pad_freqs": (165, 247, 330),
                 "pad_vol": 0.05, "kick_vol": 0.45, "bass_vol": 0.12,
                 "hihat_vol": 0.03, "fade_in": 1.0, "fade_out": 3.0},
    "trendy": {"bpm": 110, "key_freq": 58, "pad_freqs": (233, 349, 466),
               "pad_vol": 0.03, "kick_vol": 0.48, "bass_vol": 0.14,
               "hihat_vol": 0.09, "fade_in": 0.5, "fade_out": 1.5},
}

# ---------------------------------------------------------------------------
# 한글 폰트 탐색
# ---------------------------------------------------------------------------

def _find_korean_font(bold: bool = True) -> Optional[str]:
    """시스템에서 사용 가능한 한글 폰트를 찾아 반환한다. bold=True면 굵은 폰트 우선."""
    if sys.platform == "win32":
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        # Noto Sans KR 우선 (고품질 가변폰트)
        bold_fonts = [
            "NotoSansKR-VF.ttf", "NotoSansKR-Bold.otf",
            "malgunbd.ttf", "NanumGothicBold.ttf",
        ]
        regular_fonts = [
            "NotoSansKR-VF.ttf", "NotoSansKR-Regular.otf",
            "malgun.ttf", "NanumGothic.ttf",
        ]
        search_list = bold_fonts if bold else regular_fonts
        for name in search_list:
            if (fonts_dir / name).exists():
                return str(fonts_dir / name)
    elif sys.platform == "darwin":
        for p in [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/Library/Fonts/AppleGothic.ttf",
        ]:
            if Path(p).exists():
                return p
    else:
        for p in [
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]:
            if Path(p).exists():
                return p
    return None


KOREAN_FONT: Optional[str] = _find_korean_font(bold=True)
KOREAN_FONT_REGULAR: Optional[str] = _find_korean_font(bold=False)


# ═══════════════════════════════════════════════════════════════════════════
# 캔버스 레이아웃 렌더러 — 레퍼런스 퀄리티 프레임 생성
# ═══════════════════════════════════════════════════════════════════════════

class CanvasRenderer:
    """
    레퍼런스(@핫이글) 스타일 캔버스 프레임 생성기 v2.
    이미지가 화면을 꽉 채우고, 텍스트-이미지 밸런스 최적화.

    레이아웃:
      - "title_card": 상단 제목 + 중앙 이미지 + 하단 자막
      - "product":    상품 이미지 중앙 + 가격/설명 텍스트
      - "split_top":  상단 텍스트 영역 + 하단 이미지
      - "split_bottom": 상단 이미지 + 하단 텍스트 영역
      - "fullscreen":  전체 이미지 + 하단 자막 바
      - "data_card":   통계/숫자 강조 카드
    """

    def __init__(self, width: int = 1080, height: int = 1920):
        self.w = width
        self.h = height
        self._load_fonts()

    def _load_fonts(self):
        """폰트 로드 (v2: XL/Price 추가)."""
        _bf = KOREAN_FONT
        _rf = KOREAN_FONT_REGULAR or KOREAN_FONT
        try:
            self.font_bold_xl = ImageFont.truetype(_bf, 88) if _bf else ImageFont.load_default()
            self.font_bold_lg = ImageFont.truetype(_bf, 72) if _bf else ImageFont.load_default()
            self.font_bold_md = ImageFont.truetype(_bf, 54) if _bf else ImageFont.load_default()
            self.font_bold_sm = ImageFont.truetype(_bf, 42) if _bf else ImageFont.load_default()
            self.font_regular = ImageFont.truetype(_rf, 40) if _rf else ImageFont.load_default()
            self.font_small = ImageFont.truetype(_rf, 32) if _rf else ImageFont.load_default()
            self.font_price = ImageFont.truetype(_bf, 96) if _bf else ImageFont.load_default()
        except Exception:
            self.font_bold_xl = ImageFont.load_default()
            self.font_bold_lg = self.font_bold_xl
            self.font_bold_md = self.font_bold_xl
            self.font_bold_sm = self.font_bold_xl
            self.font_regular = self.font_bold_xl
            self.font_small = self.font_bold_xl
            self.font_price = self.font_bold_xl

    def _wrap_text(self, draw, text: str, font, max_width: int) -> list[str]:
        """텍스트를 max_width에 맞게 줄바꿈."""
        lines = []
        for original_line in text.split("\n"):
            current = ""
            for ch in original_line:
                test = current + ch
                bb = draw.textbbox((0, 0), test, font=font)
                if bb[2] - bb[0] > max_width and current:
                    lines.append(current)
                    current = ch
                else:
                    current = test
            if current:
                lines.append(current)
        return lines

    def _draw_centered_text(self, draw, text: str, font, y: int,
                            color: str = "#1a1a1a", max_width: int = 0,
                            shadow: bool = False):
        """중앙 정렬 텍스트 그리기. 자동 줄바꿈 + 선택적 그림자."""
        mw = max_width or (self.w - 100)
        lines = self._wrap_text(draw, text, font, mw)
        spacing = 16
        for line in lines:
            bb = draw.textbbox((0, 0), line, font=font)
            tw = bb[2] - bb[0]
            th = bb[3] - bb[1]
            x = (self.w - tw) // 2
            if shadow:
                draw.text((x + 3, y + 3), line, font=font, fill="#00000066")
            draw.text((x, y), line, font=font, fill=color)
            y += th + spacing
        return y

    def _crop_fill(self, img_path: str, target_w: int, target_h: int) -> Image.Image:
        """이미지를 target 크기로 꽉 채우기 (crop+resize). 빈 공간 없음."""
        try:
            img = Image.open(img_path).convert("RGB")
        except Exception:
            return Image.new("RGB", (target_w, target_h), "#f0f0f0")
        iw, ih = img.size
        scale = max(target_w / iw, target_h / ih)
        new_w, new_h = int(iw * scale), int(ih * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        return img.crop((left, top, left + target_w, top + target_h))

    def _make_gradient(self, w: int, h: int, direction: str = "bottom",
                       color: tuple = (0, 0, 0), max_alpha: int = 200) -> Image.Image:
        """그라데이션 오버레이 생성."""
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for i in range(h):
            alpha = int(max_alpha * (i / h)) if direction == "bottom" else int(max_alpha * (1 - i / h))
            ImageDraw.Draw(overlay).line([(0, i), (w, i)], fill=(*color, alpha))
        return overlay

    def _place_image(self, canvas: Image.Image, img_path: str,
                     x: int, y: int, max_w: int, max_h: int,
                     radius: int = 20, shadow: bool = True) -> int:
        """이미지를 캔버스에 배치. 비율 유지 + 라운드 코너 + 그림자."""
        try:
            img = Image.open(img_path).convert("RGB")
        except Exception:
            return y

        # 비율 유지하며 max 크기에 맞춤
        iw, ih = img.size
        scale = min(max_w / iw, max_h / ih)
        new_w, new_h = int(iw * scale), int(ih * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # 중앙 정렬
        px = x + (max_w - new_w) // 2
        py = y

        # 그림자 효과
        if shadow:
            shadow_img = Image.new("RGBA", (new_w + 16, new_h + 16), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_img)
            shadow_draw.rounded_rectangle(
                [(0, 0), (new_w + 15, new_h + 15)],
                radius=radius, fill=(0, 0, 0, 40),
            )
            shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(8))
            canvas.paste(shadow_img, (px - 4, py + 4), shadow_img)

        # 라운드 코너 마스크
        if radius > 0:
            mask = Image.new("L", (new_w, new_h), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (new_w - 1, new_h - 1)],
                                        radius=radius, fill=255)
            img_rgba = img.convert("RGBA")
            img_rgba.putalpha(mask)
            canvas.paste(img_rgba, (px, py), img_rgba)
        else:
            canvas.paste(img, (px, py))

        return py + new_h

    # ------------------------------------------------------------------
    # 레이아웃별 프레임 생성
    # ------------------------------------------------------------------

    def render_frame(self, layout: str, image_path: str = "",
                     title: str = "", subtitle: str = "",
                     extra_text: str = "", price: str = "",
                     brand_logo: str = "", bg_color: str = "#FFFFFF",
                     accent_color: str = "#FF4444") -> Image.Image:
        """레이아웃에 맞는 캔버스 프레임 생성 (v2: 이미지 꽉 채움)."""
        if layout == "framed":
            return self._layout_framed(image_path, title, subtitle, bg_color, accent_color)
        elif layout == "product":
            return self._layout_product(image_path, title, subtitle, price, bg_color, accent_color)
        elif layout == "split_top":
            return self._layout_split_top(image_path, title, subtitle, bg_color, accent_color)
        elif layout == "split_bottom":
            return self._layout_split_bottom(image_path, title, subtitle, extra_text, bg_color, accent_color)
        elif layout == "data_card":
            return self._layout_data_card(image_path, title, subtitle, extra_text, bg_color, accent_color)
        elif layout == "fullscreen":
            return self._layout_fullscreen(image_path, subtitle)
        elif layout == "split_text":
            return self._layout_split_top(image_path, title, subtitle, bg_color, accent_color)
        elif layout == "cta":
            return self._layout_title_card(image_path, title, subtitle, bg_color, accent_color)
        elif layout == "full_bleed":
            return self._layout_fullscreen(image_path, subtitle)
        else:  # title_card
            return self._layout_title_card(image_path, title, subtitle, bg_color, accent_color)

    def _layout_title_card(self, image_path, title, subtitle, bg_color, accent_color):
        """v2: 풀스크린 이미지 + 상단/하단 그라데이션 + 큰 제목."""
        canvas = self._crop_fill(image_path, self.w, self.h)
        canvas = canvas.convert("RGBA")
        # 상단 그라데이션 (제목용)
        top_g = self._make_gradient(self.w, 600, "top", (0, 0, 0), 220)
        canvas.paste(top_g, (0, 0), top_g)
        # 하단 그라데이션 (자막용)
        bot_g = self._make_gradient(self.w, 500, "bottom", (0, 0, 0), 200)
        canvas.paste(bot_g, (0, self.h - 500), bot_g)
        canvas = canvas.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([(0, 0), (self.w, 10)], fill=accent_color)
        if title:
            self._draw_centered_text(draw, title, self.font_bold_xl, 80, "#FFFFFF", shadow=True)
        if subtitle:
            self._draw_centered_text(draw, subtitle, self.font_bold_md, self.h - 300, "#FFFFFF", shadow=True)
        return canvas

    def _layout_product(self, image_path, title, subtitle, price, bg_color, accent_color):
        """v2: 이미지 상단 58% 꽉 채움 + 하단 상품 카드."""
        canvas = Image.new("RGB", (self.w, self.h), bg_color)
        draw = ImageDraw.Draw(canvas)
        img_h = int(self.h * 0.58)
        if image_path and os.path.exists(image_path):
            product_img = self._crop_fill(image_path, self.w, img_h)
            canvas.paste(product_img, (0, 0))
        card_y = img_h - 40
        draw.rounded_rectangle([(0, card_y), (self.w, self.h)], radius=40, fill=bg_color)
        y = card_y + 60
        if title:
            y = self._draw_centered_text(draw, title, self.font_bold_lg, y, "#1a1a1a")
            y += 20
        if subtitle:
            y = self._draw_centered_text(draw, subtitle, self.font_regular, y, "#555555")
            y += 30
        if price:
            self._draw_centered_text(draw, price, self.font_price, y, accent_color)
        draw.rectangle([(0, self.h - 10), (self.w, self.h)], fill=accent_color)
        return canvas

    def _layout_split_top(self, image_path, title, subtitle, bg_color, accent_color):
        """v2: 상단 텍스트(28%) + 이미지(72%) 꽉 채움."""
        canvas = Image.new("RGB", (self.w, self.h), bg_color)
        draw = ImageDraw.Draw(canvas)
        text_h = int(self.h * 0.28)
        img_h = self.h - text_h
        if image_path and os.path.exists(image_path):
            img = self._crop_fill(image_path, self.w, img_h)
            canvas.paste(img, (0, text_h))
        draw.rectangle([(0, 0), (self.w, text_h + 30)], fill=bg_color)
        draw.rectangle([(0, 0), (self.w, 8)], fill=accent_color)
        y = 60
        if title:
            y = self._draw_centered_text(draw, title, self.font_bold_lg, y, "#1a1a1a")
            y += 10
        if subtitle:
            self._draw_centered_text(draw, subtitle, self.font_regular, y, "#555555")
        return canvas

    def _layout_split_bottom(self, image_path, title, subtitle, extra_text, bg_color, accent_color):
        """v2: 이미지(62%) + 하단 텍스트 카드(38%)."""
        canvas = Image.new("RGB", (self.w, self.h), bg_color)
        draw = ImageDraw.Draw(canvas)
        img_h = int(self.h * 0.62)
        text_y = img_h - 30
        if image_path and os.path.exists(image_path):
            img = self._crop_fill(image_path, self.w, img_h)
            canvas.paste(img, (0, 0))
        draw.rounded_rectangle([(0, text_y), (self.w, self.h)], radius=40, fill=bg_color)
        y = text_y + 50
        if title:
            y = self._draw_centered_text(draw, title, self.font_bold_lg, y, "#1a1a1a")
            y += 10
        if subtitle:
            y = self._draw_centered_text(draw, subtitle, self.font_regular, y, "#555555")
            y += 10
        if extra_text:
            self._draw_centered_text(draw, extra_text, self.font_bold_sm, y, accent_color)
        draw.rectangle([(0, self.h - 8), (self.w, self.h)], fill=accent_color)
        return canvas

    def _layout_data_card(self, image_path, title, subtitle, extra_text, bg_color, accent_color):
        """v2: 이미지 배경 블러 + 중앙 데이터 카드 오버레이."""
        if image_path and os.path.exists(image_path):
            canvas = self._crop_fill(image_path, self.w, self.h)
            canvas = canvas.filter(ImageFilter.GaussianBlur(25))
            canvas = ImageEnhance.Brightness(canvas).enhance(0.4)
        else:
            canvas = Image.new("RGB", (self.w, self.h), "#1a1a1a")
        canvas = canvas.convert("RGBA")
        card_m = 60
        card_top = self.h // 2 - 350
        card_bot = self.h // 2 + 350
        card_ol = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        ImageDraw.Draw(card_ol).rounded_rectangle(
            [(card_m, card_top), (self.w - card_m, card_bot)],
            radius=30, fill=(255, 255, 255, 230))
        canvas.paste(card_ol, (0, 0), card_ol)
        canvas = canvas.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            [(card_m + 20, card_top + 20), (self.w - card_m - 20, card_top + 28)],
            radius=4, fill=accent_color)
        y = card_top + 60
        if title:
            y = self._draw_centered_text(draw, title, self.font_bold_lg, y, "#1a1a1a")
            y += 40
        if subtitle:
            y = self._draw_centered_text(draw, subtitle, self.font_price, y, accent_color)
            y += 30
        if extra_text:
            self._draw_centered_text(draw, extra_text, self.font_bold_sm, y, "#555555")
        return canvas

    def _layout_fullscreen(self, image_path, subtitle):
        """v2: 전체 이미지 꽉 채움 + 하단 그라데이션 자막."""
        canvas = self._crop_fill(image_path, self.w, self.h)
        canvas = canvas.convert("RGBA")
        if subtitle:
            bot_g = self._make_gradient(self.w, 500, "bottom", (0, 0, 0), 220)
            canvas.paste(bot_g, (0, self.h - 500), bot_g)
            canvas = canvas.convert("RGB")
            draw = ImageDraw.Draw(canvas)
            self._draw_centered_text(draw, subtitle, self.font_bold_lg, self.h - 300, "#FFFFFF", shadow=True)
        else:
            canvas = canvas.convert("RGB")
        return canvas

    def _layout_framed(self, image_path, title, subtitle="",
                       bg_color="#FAFAFA", accent_color="#222222"):
        """
        v3 프레임 레이아웃: 흰 배경 + 상단 설명 + 중앙 이미지 + 하단 자막 영역.
        레퍼런스 @dogestime_ / @핫이글 스타일.

        구조:
          ┌──────────────────┐
          │  (상단 여백 80px) │
          │  ▸ 설명 텍스트     │  ← title (검은 볼드)
          │  (여백 30px)      │
          ├──────────────────┤
          │                  │
          │   [이미지 영역]   │  ← 중앙 60%, 라운드 코너
          │                  │
          ├──────────────────┤
          │  (여백 20px)      │
          │  ▸ 자막 텍스트     │  ← subtitle (TTS 동기화 오버레이 영역)
          │  (하단 여백)      │
          └──────────────────┘
        """
        canvas = Image.new("RGB", (self.w, self.h), bg_color)
        draw = ImageDraw.Draw(canvas)

        # ── 레이아웃 비율 계산 ──
        top_pad = 80         # 상단 여백
        img_margin_x = 30    # 이미지 좌우 여백
        img_margin_top = 30  # 텍스트~이미지 사이
        bottom_area = 320    # 하단 자막 영역 높이

        # ── 상단 설명 텍스트 ──
        y = top_pad
        if title:
            y = self._draw_centered_text(
                draw, title, self.font_bold_lg, y,
                color="#1a1a1a", max_width=self.w - 120,
            )
        y += img_margin_top

        # ── 중앙 이미지 영역 ──
        img_area_top = y
        img_area_bot = self.h - bottom_area
        img_area_h = img_area_bot - img_area_top
        img_area_w = self.w - img_margin_x * 2

        if image_path and os.path.exists(image_path):
            self._place_image(
                canvas, image_path,
                x=img_margin_x, y=img_area_top,
                max_w=img_area_w, max_h=img_area_h,
                radius=16, shadow=True,
            )

        # ── 하단 구분선 (얇은 회색 라인) ──
        sep_y = self.h - bottom_area
        draw.line([(40, sep_y), (self.w - 40, sep_y)], fill="#E0E0E0", width=1)

        # 자막은 render_shorts()의 오버레이에서 TTS 동기화로 표시됨
        # 여기서는 빈 하단 영역만 확보

        return canvas

    # ------------------------------------------------------------------
    # 장면 시퀀스 → 프레임 리스트 생성
    # ------------------------------------------------------------------

    def render_scenes(self, scenes: list[dict]) -> list[str]:
        """
        장면 리스트를 받아 프레임 이미지 파일 리스트 반환.

        Args:
            scenes: [
                {"layout": "title_card", "image": "path", "title": "제목", "subtitle": "자막"},
                {"layout": "product", "image": "path", "title": "상품명", "price": "₩19,900"},
                ...
            ]

        Returns:
            생성된 프레임 이미지 경로 리스트
        """
        out_dir = WORK_DIR / f"canvas_{uuid.uuid4().hex[:8]}"
        os.makedirs(out_dir, exist_ok=True)

        frame_paths = []
        for i, scene in enumerate(scenes):
            frame = self.render_frame(
                layout=scene.get("layout", "title_card"),
                image_path=scene.get("image", ""),
                title=scene.get("title", ""),
                subtitle=scene.get("subtitle", ""),
                extra_text=scene.get("extra_text", ""),
                price=scene.get("price", ""),
                brand_logo=scene.get("brand_logo", ""),
                bg_color=scene.get("bg_color", "#FFFFFF"),
                accent_color=scene.get("accent_color", "#FF4444"),
            )
            path = str(out_dir / f"frame_{i:03d}.png")
            frame.save(path)  # PNG 무손실
            frame_paths.append(path)
            log.info("캔버스 프레임 생성 [%d/%d]: %s layout", i + 1, len(scenes), scene.get("layout"))

        return frame_paths


# ═══════════════════════════════════════════════════════════════════════════
# 유틸리티 함수
# ═══════════════════════════════════════════════════════════════════════════

# GPU 인코더 감지 캐시
_GPU_ENCODER_CACHE: Optional[str] = None

def detect_gpu_encoder() -> str:
    """실제 테스트 인코딩으로 GPU 인코더 사용 가능 여부 확인."""
    global _GPU_ENCODER_CACHE
    if _GPU_ENCODER_CACHE is not None:
        return _GPU_ENCODER_CACHE

    for encoder in ["h264_nvenc", "h264_amf"]:
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
                 "-c:v", encoder, "-f", "null", "-"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                log.info("GPU 인코더 확인: %s (실제 테스트 통과)", encoder)
                _GPU_ENCODER_CACHE = encoder
                return encoder
        except Exception:
            pass

    log.info("GPU 인코더 없음 → libx264 사용")
    _GPU_ENCODER_CACHE = "libx264"
    return "libx264"


def ease_io(t: float) -> float:
    """Smooth ease-in-out (cubic bezier — 더 자연스러운 가감속)."""
    # cubic bezier 근사: ease-in-out (0.42, 0, 0.58, 1)
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - math.pow(-2.0 * t + 2.0, 3) / 2.0


def _crop_and_resize(img: Image.Image, w: int, h: int) -> Image.Image:
    """이미지를 w x h 비율로 중앙 크롭 후 리사이즈."""
    iw, ih = img.size
    if iw < 2 or ih < 2:
        return img.resize((w, h), Image.LANCZOS)
    target_ratio = w / h
    current_ratio = iw / ih
    if current_ratio > target_ratio:
        # 좌우 크롭
        nw = int(ih * target_ratio)
        left = (iw - nw) // 2
        img = img.crop((left, 0, left + nw, ih))
    else:
        # 상하 크롭
        nh = int(iw / target_ratio)
        top = (ih - nh) // 2
        img = img.crop((0, top, iw, top + nh))
    return img.resize((w, h), Image.LANCZOS)


def _apply_color_filter(
    img: Image.Image,
    brightness: float = 1.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
) -> Image.Image:
    """밝기/대비/채도 필터 적용."""
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    return img


def _render_subtitle_image(
    text: str,
    width: int,
    fontsize: int = 65,
    stroke_width: int = 3,
    stroke_color: str = "#000000",
    text_color: str = "#FFFFFF",
    bg_enabled: bool = True,
    style: str = "modern",
) -> np.ndarray:
    """
    자막 텍스트를 RGBA numpy 배열로 렌더링.

    style:
      - "modern": 깔끔한 반투명 bg + 굵은 텍스트 (기본)
      - "clean": 흰 배경 + 검정 텍스트 (핫이글 스타일)
      - "bold_center": 화면 중앙 대형 텍스트 + 외곽선
      - "news": 하단 뉴스 자막 바 스타일
      - "minimal": 배경 없이 외곽선만
    """
    pad = 60
    line_spacing = 12  # 줄간격 추가
    try:
        font = ImageFont.truetype(KOREAN_FONT, fontsize) if KOREAN_FONT else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # 줄바꿈 계산 — 자연스러운 단어 단위로 개선
    tmp = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(tmp)
    max_width = width - pad * 2
    lines: list[str] = []
    for original_line in text.split("\n"):
        current = ""
        for ch in original_line:
            test = current + ch
            bb = draw.textbbox((0, 0), test, font=font)
            if bb[2] - bb[0] > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = test
        if current:
            lines.append(current)

    # ── 텍스트 밸런스: 줄 길이 균등 분배 ──
    if len(lines) == 1 and len(lines[0]) > 14:
        # 한 줄이 너무 길면 2줄로 균등 분배
        txt = lines[0]
        mid = len(txt) // 2
        # 가장 가까운 공백이나 중간 지점에서 분할
        best_split = mid
        for offset in range(min(5, mid)):
            if mid + offset < len(txt) and txt[mid + offset] in " ,. 、":
                best_split = mid + offset + 1
                break
            if mid - offset >= 0 and txt[mid - offset] in " ,. 、":
                best_split = mid - offset + 1
                break
        lines = [txt[:best_split].strip(), txt[best_split:].strip()]
        lines = [l for l in lines if l]

    full = "\n".join(lines)
    bb = draw.multiline_textbbox((0, 0), full, font=font, spacing=line_spacing)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]

    # ── 스타일별 렌더링 ──
    if style == "pro":
        # ★ 레퍼런스급 세련된 자막: 굵은 폰트 + 두꺼운 아웃라인 + 컬러 강조
        # @핫이글/@구독해줘코노가자 수준의 임팩트 있는 텍스트
        v_pad = 30
        canvas_w = width
        canvas_h = th + v_pad * 2 + 10
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x = (canvas_w - tw) // 2
        y = v_pad

        # 강한 드롭 쉐도우 (깊이감)
        for sx, sy in [(5, 5), (4, 4), (3, 3)]:
            draw.multiline_text((x + sx, y + sy), full, font=font,
                               fill=(0, 0, 0, int(120 - sx * 20)),
                               align="center", spacing=line_spacing)

        # 두꺼운 아웃라인 (Pillow stroke_width 지원 시 사용, 아니면 수동)
        s = max(stroke_width, 4)
        try:
            # Pillow 8.0+ stroke 지원
            draw.multiline_text((x, y), full, font=font,
                               fill=text_color, align="center",
                               spacing=line_spacing,
                               stroke_width=s, stroke_fill="#000000")
        except TypeError:
            # 폴백: 수동 16방향 아웃라인
            for dx in range(-s, s + 1):
                for dy in range(-s, s + 1):
                    if dx * dx + dy * dy <= s * s:
                        draw.multiline_text((x + dx, y + dy), full, font=font,
                                           fill="#000000", align="center",
                                           spacing=line_spacing)
            draw.multiline_text((x, y), full, font=font, fill=text_color,
                               align="center", spacing=line_spacing)
        return np.array(img)

    elif style == "framed":
        # 프레임 레이아웃용: 흰 배경에 깔끔한 검정 볼드 텍스트
        v_pad = 20
        canvas_w = width
        canvas_h = th + v_pad * 2
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x = (canvas_w - tw) // 2
        y = v_pad

        # 작은따옴표로 감싸서 대사 느낌 (레퍼런스 스타일)
        quoted = f"'{full}'"
        q_bb = draw.multiline_textbbox((0, 0), quoted, font=font, spacing=line_spacing)
        q_tw = q_bb[2] - q_bb[0]
        q_x = (canvas_w - q_tw) // 2

        draw.multiline_text((q_x, y), quoted, font=font, fill="#1a1a1a",
                           align="center", spacing=line_spacing)
        return np.array(img)

    elif style == "clean":
        # 핫이글/구독해줘코노가자 스타일: 흰 배경 + 검정 텍스트
        v_pad = 30
        h_pad = 50
        canvas_w = width
        canvas_h = th + v_pad * 2 + 10
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 깔끔한 흰색 라운드 박스
        draw.rounded_rectangle(
            [(pad - h_pad, 5), (canvas_w - pad + h_pad, canvas_h - 5)],
            radius=20,
            fill=(255, 255, 255, 240),
        )
        x = (canvas_w - tw) // 2
        y = v_pad + 5
        # 검정 텍스트 (외곽선 없음, 깔끔하게)
        draw.multiline_text((x, y), full, font=font, fill="#1a1a1a",
                           align="center", spacing=line_spacing)
        return np.array(img)

    elif style == "bold_center":
        # 화면 중앙 대형 텍스트 — 강한 외곽선 + 그림자
        v_pad = 40
        canvas_w = width
        canvas_h = th + v_pad * 2
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x = (canvas_w - tw) // 2
        y = v_pad
        s = max(stroke_width, 5)  # 굵은 외곽선
        # 강한 드롭 쉐도우
        draw.multiline_text((x + 4, y + 4), full, font=font,
                           fill=(0, 0, 0, 180), align="center", spacing=line_spacing)
        # 외곽선 (16방향)
        for dx in range(-s, s + 1):
            for dy in range(-s, s + 1):
                if dx * dx + dy * dy <= s * s:
                    draw.multiline_text((x + dx, y + dy), full, font=font,
                                       fill=stroke_color, align="center", spacing=line_spacing)
        # 본문 (밝은 텍스트)
        draw.multiline_text((x, y), full, font=font, fill=text_color,
                           align="center", spacing=line_spacing)
        return np.array(img)

    elif style == "news":
        # 뉴스 자막 바 스타일: 좌측 악센트 + 배경
        v_pad = 20
        h_pad = 70
        canvas_w = width
        canvas_h = th + v_pad * 2 + 10
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 어두운 배경 바
        draw.rounded_rectangle(
            [(20, 2), (canvas_w - 20, canvas_h - 2)],
            radius=8,
            fill=(15, 15, 25, 220),
        )
        # 좌측 악센트 바 (빨간색)
        draw.rectangle([(20, 2), (28, canvas_h - 2)], fill=(230, 50, 50, 255))
        x = (canvas_w - tw) // 2
        y = v_pad + 4
        draw.multiline_text((x, y), full, font=font, fill="#FFFFFF",
                           align="center", spacing=line_spacing)
        return np.array(img)

    elif style == "minimal":
        # 배경 없이 외곽선만 — 깔끔한 느낌
        v_pad = 25
        canvas_w = width
        canvas_h = th + v_pad * 2
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x = (canvas_w - tw) // 2
        y = v_pad
        s = stroke_width
        # 외곽선
        for dx, dy in [(-s, 0), (s, 0), (0, -s), (0, s), (-s, -s), (s, -s), (-s, s), (s, s)]:
            draw.multiline_text((x + dx, y + dy), full, font=font,
                               fill=stroke_color, align="center", spacing=line_spacing)
        draw.multiline_text((x, y), full, font=font, fill=text_color,
                           align="center", spacing=line_spacing)
        return np.array(img)

    # ── "modern" (기본, 업그레이드) ──
    v_pad = 25
    canvas_w = width
    canvas_h = th + v_pad * 2 + 10
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if bg_enabled:
        # 업그레이드된 반투명 배경 (더 둥글고 세련된)
        bg_left = max((canvas_w - tw) // 2 - 40, pad // 2)
        bg_right = min((canvas_w + tw) // 2 + 40, canvas_w - pad // 2)
        draw.rounded_rectangle(
            [(bg_left, 3), (bg_right, canvas_h - 3)],
            radius=20,
            fill=(0, 0, 0, 180),
        )

    x = (canvas_w - tw) // 2
    y = v_pad + 5
    s = stroke_width

    # 드롭 쉐도우
    draw.multiline_text((x + 3, y + 3), full, font=font,
                       fill=(0, 0, 0, 140), align="center", spacing=line_spacing)
    # 외곽선 (8방향)
    for dx, dy in [(-s, 0), (s, 0), (0, -s), (0, s), (-s, -s), (s, -s), (-s, s), (s, s)]:
        draw.multiline_text((x + dx, y + dy), full, font=font,
                           fill=stroke_color, align="center", spacing=line_spacing)
    # 본문
    draw.multiline_text((x, y), full, font=font, fill=text_color,
                       align="center", spacing=line_spacing)

    return np.array(img)


# ═══════════════════════════════════════════════════════════════════════════
# VideoForge  --  메인 클래스
# ═══════════════════════════════════════════════════════════════════════════

class VideoForge:
    """안티밴 비디오 렌더러 및 영상 세탁 파이프라인."""

    def __init__(self, config: Optional[RenderConfig] = None):
        self.cfg = config or RenderConfig()
        self._tmp_files: list[str] = []
        self._tmp_audio: list = []
        log.info(
            "VideoForge 초기화: %dx%d @%dfps, 이펙트=%s, TTS=%s",
            self.cfg.width, self.cfg.height, self.cfg.fps,
            self.cfg.effect_mode, self.cfg.tts_voice,
        )

    # ------------------------------------------------------------------
    # 메인 렌더 파이프라인
    # ------------------------------------------------------------------

    def render_shorts(
        self,
        images: list[str],
        narrations: list[str],
        output_path: str,
        subtitle_text: str = "",
    ) -> str:
        """
        이미지 슬라이드쇼 + 모션 + TTS + BGM + 자막 → Shorts 영상 렌더링.

        Args:
            images: 이미지 파일 경로 리스트
            narrations: 장면별 나레이션 텍스트 리스트
            output_path: 출력 파일 경로
            subtitle_text: 자막 텍스트 (줄바꿈으로 장면 구분)

        Returns:
            최종 출력 파일 경로
        """
        t_start = time.time()
        self._tmp_audio = []
        cfg = self.cfg
        w, h = self._jittered_dimensions()

        log.info("렌더 시작: 이미지 %d장, 나레이션 %d개", len(images), len(narrations))

        if not images:
            raise ValueError("이미지가 하나도 없습니다")

        # ── TTS 생성 ──
        tts_paths: list[Optional[str]] = []
        tts_durations: list[float] = []
        if narrations:
            log.info("TTS 생성 시작 (%d개 장면)", len(narrations))
            tts_dir = ensure_dir(WORK_DIR / f"tts_{uuid.uuid4().hex[:8]}")
            tts_paths, tts_durations = self._generate_scene_tts(
                narrations, str(tts_dir), cfg.tts_voice,
            )
            ok_count = sum(1 for p in tts_paths if p)
            log.info("TTS 완료: %d/%d 성공", ok_count, len(narrations))

        # ── Framed 캔버스 자동 변환 ──
        # canvas_layout이 "framed"면 원본 이미지를 프레임 레이아웃으로 자동 변환
        _canvas_layout = getattr(cfg, "canvas_layout", "auto")
        if _canvas_layout == "framed":
            log.info("Framed 레이아웃 자동 변환: %d장 이미지", len(images))
            _renderer = CanvasRenderer(w, h)
            _sub_lines = [t.strip() for t in subtitle_text.split("\n") if t.strip()] if subtitle_text else narrations
            _scenes = []
            for idx, img_path in enumerate(images):
                # 상단 설명 = 나레이션 텍스트 (or 자막)
                _top_text = _sub_lines[idx] if idx < len(_sub_lines) else ""
                _scenes.append({
                    "layout": "framed",
                    "image": img_path,
                    "title": _top_text,
                })
            images = _renderer.render_scenes(_scenes)
            log.info("Framed 캔버스 %d장 생성 완료", len(images))

        # ── 이미지 → 클립 변환 ──
        effects = EFFECT_PRESETS.get(cfg.effect_mode, EFFECT_PRESETS["dynamic"])
        clips: list = []
        default_duration = 3.5  # 기본 장면 길이 (초)

        for i, img_path in enumerate(images):
            log.info("클립 생성 [%d/%d]: %s", i + 1, len(images), Path(img_path).name)

            # TTS 길이에 맞춰 장면 길이 조정
            dur = default_duration
            if i < len(tts_durations) and tts_durations[i] > 0:
                dur = max(tts_durations[i] + 0.5, default_duration)

            try:
                img = Image.open(img_path).convert("RGB")
                img = _crop_and_resize(img, w, h)
                arr = np.array(img)

                if MOVIEPY_V2:
                    clip = ImageClip(arr, duration=dur)
                else:
                    clip = ImageClip(arr).set_duration(dur)

                # 모션 이펙트 적용
                effect_name = effects[i % len(effects)]
                clip = self.apply_motion_effect(clip, effect_name, zoom_ratio=1.12)

                if MOVIEPY_V2:
                    clip = clip.with_fps(cfg.fps)
                else:
                    clip = clip.set_fps(cfg.fps)

                clips.append(clip)
            except Exception as e:
                log.error("클립 생성 실패 [%d]: %s", i, e)
                continue

        if not clips:
            raise RuntimeError("처리 가능한 클립이 없습니다")

        # ── 크로스디졸브 ──
        log.info("크로스디졸브 적용중 (%d 클립)", len(clips))
        transition_dur = 0.4
        if len(clips) > 1:
            processed = [clips[0]]
            current_time = clips[0].duration
            for i in range(1, len(clips)):
                start = current_time - transition_dur
                if MOVIEPY_V2:
                    c2 = clips[i].with_start(start).crossfadein(transition_dur)
                else:
                    c2 = clips[i].set_start(start).crossfadein(transition_dur)
                processed.append(c2)
                current_time = start + clips[i].duration
            final = CompositeVideoClip(processed)
        else:
            final = clips[0]

        # ── 자막 오버레이 (TTS 동기화 + 타이핑 애니메이션) ──
        if cfg.subtitle_enabled and subtitle_text:
            _sub_animation = getattr(cfg, "subtitle_animation", "fade")
            log.info("자막 오버레이 렌더링 (모드=%s)", _sub_animation)
            sub_lines = [t.strip() for t in subtitle_text.split("\n") if t.strip()]
            sub_layers = [final]
            current_time = 0.0

            _tts_offset = 0.2

            # subtitle_style 매핑
            _style_map = {
                "bold": "bold_center", "classic": "clean",
                "modern": "modern", "minimal": "minimal",
                "clean": "clean", "news": "news",
                "bold_center": "bold_center",
                "framed": "framed", "pro": "pro",
            }
            _sub_style = _style_map.get(cfg.subtitle_style, "modern")

            for i in range(min(len(clips), len(sub_lines))):
                clip_dur = clips[i].duration if i < len(clips) else default_duration
                try:
                    # TTS 동기화 타이밍 계산
                    if i < len(tts_durations) and tts_durations[i] > 0:
                        sub_dur = tts_durations[i] + 0.3
                    else:
                        sub_dur = max(clip_dur - 0.8, 0.5)
                    sub_start = current_time + _tts_offset

                    if _sub_animation == "typing":
                        # ★★ 타이핑 애니메이션: 단어 단위로 순차 등장 ★★
                        words = sub_lines[i].split()
                        if not words:
                            current_time += clip_dur - transition_dur
                            continue

                        # 단어별 등장 시간 계산 (TTS 길이에 맞춰 균등 배분)
                        type_total = min(sub_dur * 0.7, len(words) * 0.25)
                        word_interval = type_total / max(len(words), 1)
                        hold_time = sub_dur - type_total  # 전체 텍스트 유지 시간

                        for w_idx in range(len(words)):
                            partial_text = " ".join(words[:w_idx + 1])
                            w_arr = _render_subtitle_image(
                                partial_text, w,
                                fontsize=cfg.subtitle_fontsize,
                                style=_sub_style,
                            )
                            w_h = w_arr.shape[0]

                            # 위치 계산
                            _pos = cfg.subtitle_position
                            if _pos == "center" or _sub_style == "bold_center":
                                sub_y = (h - w_h) // 2
                            elif _pos == "top":
                                sub_y = 120
                            else:
                                sub_y = h - w_h - 160

                            # 각 단계 시작 시간과 길이
                            w_start = sub_start + w_idx * word_interval
                            if w_idx < len(words) - 1:
                                # 중간 단계: 다음 단어가 나올 때까지
                                w_dur = word_interval + 0.05
                            else:
                                # 마지막 단계: hold_time까지 유지
                                w_dur = hold_time + 0.1

                            if MOVIEPY_V2:
                                w_clip = (
                                    ImageClip(w_arr, duration=w_dur, is_mask=False)
                                    .with_start(w_start)
                                    .with_position(("center", sub_y))
                                )
                            else:
                                w_clip = (
                                    ImageClip(w_arr, ismask=False)
                                    .set_duration(w_dur)
                                    .set_start(w_start)
                                    .set_position(("center", sub_y))
                                )
                            sub_layers.append(w_clip)

                        log.debug("타이핑자막[%d]: %d단어, start=%.2fs, dur=%.2fs",
                                  i, len(words), sub_start, sub_dur)
                    else:
                        # 기본 fade 모드: 한번에 등장
                        sub_arr = _render_subtitle_image(
                            sub_lines[i], w,
                            fontsize=cfg.subtitle_fontsize,
                            style=_sub_style,
                        )
                        sub_h = sub_arr.shape[0]

                        _pos = cfg.subtitle_position
                        if _pos == "center" or _sub_style == "bold_center":
                            sub_y = (h - sub_h) // 2
                        elif _pos == "top":
                            sub_y = 120
                        else:
                            sub_y = h - sub_h - 160

                        if MOVIEPY_V2:
                            sub_clip = (
                                ImageClip(sub_arr, duration=sub_dur, is_mask=False)
                                .with_start(sub_start)
                                .with_position(("center", sub_y))
                                .crossfadein(0.15)
                            )
                        else:
                            sub_clip = (
                                ImageClip(sub_arr, ismask=False)
                                .set_duration(sub_dur)
                                .set_start(sub_start)
                                .set_position(("center", sub_y))
                                .crossfadein(0.15)
                            )
                        sub_layers.append(sub_clip)
                        log.debug("자막[%d] fade: start=%.2fs, dur=%.2fs",
                                  i, sub_start, sub_dur)
                except Exception as e:
                    log.warning("자막 렌더링 실패 [%d]: %s", i, e)

                current_time += clip_dur - transition_dur

            if len(sub_layers) > 1:
                final = CompositeVideoClip(sub_layers)

        # ── 오디오 믹싱 ──
        log.info("오디오 믹싱 시작")
        audio_layers: list = []

        # TTS 오디오 레이어
        if tts_paths:
            current_time = 0.0
            for i in range(min(len(tts_paths), len(clips))):
                if tts_paths[i] and os.path.exists(tts_paths[i]):
                    try:
                        tts_audio = AudioFileClip(tts_paths[i])
                        self._tmp_audio.append(tts_audio)
                        if MOVIEPY_V2:
                            tts_audio = tts_audio.with_start(current_time + 0.2)
                        else:
                            tts_audio = tts_audio.set_start(current_time + 0.2)
                        audio_layers.append(tts_audio)
                    except Exception as e:
                        log.warning("TTS 오디오 로드 실패 [%d]: %s", i, e)
                clip_dur = clips[i].duration if i < len(clips) else default_duration
                current_time += clip_dur - transition_dur

        # BGM 레이어 — 로열티프리 파일 우선, 없으면 합성 폴백
        try:
            bgm_path = str(WORK_DIR / f"_bgm_{uuid.uuid4().hex[:6]}.wav")
            bgm_loaded = False

            # 로열티프리 BGM 파일 탐색
            _bgm_dir = Path(__file__).parent / "bgm"
            _genre = cfg.bgm_genre if hasattr(cfg, "bgm_genre") else "lofi"
            _bgm_files = []
            if _bgm_dir.exists():
                for ext in ("*.mp3", "*.wav", "*.ogg", "*.m4a"):
                    _bgm_files.extend(_bgm_dir.glob(f"{_genre}*{ext[1:]}"))
                if not _bgm_files:  # 장르 매칭 실패 시 아무 파일
                    for ext in ("*.mp3", "*.wav", "*.ogg", "*.m4a"):
                        _bgm_files.extend(_bgm_dir.glob(ext))

            if _bgm_files:
                _chosen = random.choice(_bgm_files)
                log.info("로열티프리 BGM 사용: %s", _chosen.name)
                try:
                    bgm = AudioFileClip(str(_chosen))
                    bgm_loaded = True
                except Exception as e:
                    log.warning("BGM 파일 로드 실패: %s, 합성으로 폴백", e)

            if not bgm_loaded:
                self.generate_bgm(bgm_path, final.duration)
                bgm = AudioFileClip(bgm_path)
                self._tmp_files.append(bgm_path)

            self._tmp_audio.append(bgm)

            # TTS 가 있으면 BGM 볼륨을 낮춤
            bgm_vol = cfg.bgm_volume if tts_paths else 0.25
            if MOVIEPY_V2:
                bgm = bgm.with_volume_scaled(bgm_vol)
            else:
                bgm = bgm.volumex(bgm_vol)

            # 루프
            if bgm.duration < final.duration:
                loops = int(final.duration / bgm.duration) + 1
                if concatenate_audioclips:
                    bgm = concatenate_audioclips([bgm] * loops)
            if bgm.duration > final.duration:
                if MOVIEPY_V2:
                    bgm = bgm.subclipped(0, final.duration)
                else:
                    bgm = bgm.subclip(0, final.duration)
            audio_layers.append(bgm)
        except Exception as e:
            log.error("BGM 생성 실패: %s", e)

        # 오디오 병합
        if audio_layers:
            if final.audio:
                audio_layers.insert(0, final.audio)
            mixed = CompositeAudioClip(audio_layers)
            if MOVIEPY_V2:
                final = final.with_audio(mixed)
            else:
                final = final.set_audio(mixed)

        # ── 안티밴 적용 (HQ 모드에서는 스킵) ──
        if cfg.anti_ban_enabled:
            final = self.apply_anti_ban(final)
        else:
            log.info("HQ 모드: 안티밴 스킵 (노이즈/지터 없음)")

        # ── 인코딩 (GPU 자동 감지 + HQ 설정) ──
        _codec = detect_gpu_encoder()
        _bitrate = getattr(cfg, "video_bitrate", "10M")
        _audio_br = getattr(cfg, "audio_bitrate", "192k")
        _preset = getattr(cfg, "encode_preset", "medium")
        log.info("인코딩 시작: %s (codec=%s, bitrate=%s, preset=%s)",
                output_path, _codec, _bitrate, _preset)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        _ffmpeg_params = ["-preset", _preset]
        if _codec == "h264_nvenc":
            _ffmpeg_params = ["-preset", "p7", "-rc", "vbr", "-cq", "18"]
        elif _codec == "h264_amf":
            _ffmpeg_params = ["-quality", "quality"]

        final.write_videofile(
            output_path,
            fps=cfg.fps,
            codec=_codec,
            bitrate=_bitrate,
            audio_codec="aac",
            audio_bitrate=_audio_br,
            threads=4,
            ffmpeg_params=_ffmpeg_params,
            logger="bar",
        )

        # ── 정리 ──
        self._cleanup(clips, final)

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
            raise RuntimeError("렌더링 실패: 출력 파일이 생성되지 않았습니다")

        elapsed = time.time() - t_start
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        md5 = file_md5(output_path)
        log.info(
            "렌더 완료: %.1fMB, %d초 소요, MD5=%s", size_mb, int(elapsed), md5,
        )
        return output_path

    # ------------------------------------------------------------------
    # 안티밴 변환
    # ------------------------------------------------------------------

    def apply_anti_ban(self, clip):
        """
        안티밴 변조를 적용하여 고유 핑거프린트를 생성한다.

        적용 항목:
        - 랜덤 해상도 지터 (이미 jittered_dimensions 에서 처리)
        - 불투명도 지터 (0.92 ~ 1.0)
        - 오디오 패딩 지터 (50~300ms 무음 삽입)
        - 픽셀 노이즈 오버레이
        - 색상 그레이딩 변동 (밝기, 대비, 채도)
        """
        cfg = self.cfg
        log.info("안티밴 변조 적용 시작")

        # ── 불투명도 지터 ──
        if cfg.opacity_jitter:
            lo, hi = OPACITY_JITTER
            opacity = random.uniform(lo, hi)
            log.debug("불투명도 지터: %.3f", opacity)

            if opacity < 1.0:
                def opacity_fn(get_frame, t, _op=opacity):
                    frame = get_frame(t)
                    return (frame.astype(np.float64) * _op).astype(np.uint8)

                if MOVIEPY_V2:
                    clip = clip.transform(opacity_fn)
                else:
                    clip = clip.fl(opacity_fn)

        # ── 픽셀 노이즈 오버레이 ──
        noise_intensity = random.uniform(2.0, 6.0)
        log.debug("픽셀 노이즈 강도: %.2f", noise_intensity)

        def noise_fn(get_frame, t, _ni=noise_intensity):
            frame = get_frame(t)
            noise = np.random.normal(0, _ni, frame.shape).astype(np.float64)
            result = np.clip(frame.astype(np.float64) + noise, 0, 255)
            return result.astype(np.uint8)

        if MOVIEPY_V2:
            clip = clip.transform(noise_fn)
        else:
            clip = clip.fl(noise_fn)

        # ── 색상 그레이딩 변동 ──
        brightness_shift = random.uniform(0.97, 1.03)
        contrast_shift = random.uniform(0.97, 1.03)
        log.debug(
            "색상 그레이딩: 밝기=%.3f, 대비=%.3f",
            brightness_shift, contrast_shift,
        )

        def color_grade_fn(get_frame, t, _b=brightness_shift, _c=contrast_shift):
            frame = get_frame(t).astype(np.float64)
            # 밝기
            frame = frame * _b
            # 대비
            mean = frame.mean()
            frame = (frame - mean) * _c + mean
            return np.clip(frame, 0, 255).astype(np.uint8)

        if MOVIEPY_V2:
            clip = clip.transform(color_grade_fn)
        else:
            clip = clip.fl(color_grade_fn)

        # ── 오디오 패딩 지터 ──
        if cfg.audio_pad_jitter and clip.audio is not None:
            lo_ms, hi_ms = AUDIO_PAD_JITTER
            pad_ms = random.randint(lo_ms, hi_ms)
            pad_sec = pad_ms / 1000.0
            log.debug("오디오 패딩: %dms (%.3f초)", pad_ms, pad_sec)

            try:
                sr = 44100
                silence_samples = int(sr * pad_sec)
                silence_arr = np.zeros((silence_samples, 2), dtype=np.float32)

                from moviepy.audio.AudioClip import AudioClip as _AudioClipBase
                silence_clip = _AudioClipBase(
                    make_frame=lambda t: np.zeros((1, 2)),
                    duration=pad_sec,
                )
                if MOVIEPY_V2:
                    silence_clip = silence_clip.with_fps(sr)
                else:
                    silence_clip = silence_clip.set_fps(sr)

                if concatenate_audioclips:
                    padded = concatenate_audioclips([silence_clip, clip.audio])
                    if MOVIEPY_V2:
                        clip = clip.with_audio(padded)
                    else:
                        clip = clip.set_audio(padded)
            except Exception as e:
                log.warning("오디오 패딩 적용 실패 (무시): %s", e)

        log.info("안티밴 변조 완료")
        return clip

    # ------------------------------------------------------------------
    # 영상 세탁 파이프라인
    # ------------------------------------------------------------------

    def wash_video(self, input_path: str, output_path: str) -> str:
        """
        기존 영상을 세탁하여 고유한 파일로 재인코딩한다.

        적용 항목:
        - 수평 반전
        - 5% 가장자리 크롭
        - 속도 랜덤화 (1.05x ~ 1.15x)
        - 색상 변조
        - libx264 재인코딩

        Args:
            input_path: 입력 영상 경로
            output_path: 출력 영상 경로

        Returns:
            출력 파일 경로
        """
        log.info("영상 세탁 시작: %s", input_path)

        if not os.path.exists(input_path):
            raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_path}")

        clip = VideoFileClip(input_path)
        original_w, original_h = clip.size
        log.info("원본 해상도: %dx%d, 길이: %.1f초", original_w, original_h, clip.duration)

        # ── 수평 반전 ──
        log.info("수평 반전 적용")

        def mirror_fn(get_frame, t):
            return get_frame(t)[:, ::-1, :]

        if MOVIEPY_V2:
            clip = clip.transform(mirror_fn)
        else:
            clip = clip.fl(mirror_fn)

        # ── 5% 가장자리 크롭 ──
        crop_pct = 0.05
        cx = int(original_w * crop_pct)
        cy = int(original_h * crop_pct)
        log.info("5%% 크롭: x=%d, y=%d", cx, cy)

        if MOVIEPY_V2:
            clip = clip.cropped(x1=cx, y1=cy, x2=original_w - cx, y2=original_h - cy)
            clip = clip.resized((original_w, original_h))
        else:
            clip = clip.crop(x1=cx, y1=cy, x2=original_w - cx, y2=original_h - cy)
            clip = clip.resize((original_w, original_h))

        # ── 속도 랜덤화 ──
        speed_factor = random.uniform(1.05, 1.15)
        log.info("속도 변경: %.2fx", speed_factor)

        if MOVIEPY_V2:
            clip = clip.with_speed_scaled(speed_factor)
        else:
            clip = clip.speedx(speed_factor)

        # ── 색상 변조 ──
        brightness = random.uniform(0.95, 1.05)
        contrast = random.uniform(0.95, 1.05)
        saturation_shift = random.uniform(0.95, 1.05)
        log.info(
            "색상 변조: 밝기=%.3f, 대비=%.3f, 채도=%.3f",
            brightness, contrast, saturation_shift,
        )

        def color_fn(get_frame, t, _b=brightness, _c=contrast, _s=saturation_shift):
            frame = get_frame(t).astype(np.float64)
            # 밝기
            frame *= _b
            # 대비
            mean = frame.mean()
            frame = (frame - mean) * _c + mean
            # 채도 (간략 버전: RGB 평균과의 차이를 조절)
            gray = frame.mean(axis=2, keepdims=True)
            frame = gray + (frame - gray) * _s
            return np.clip(frame, 0, 255).astype(np.uint8)

        if MOVIEPY_V2:
            clip = clip.transform(color_fn)
        else:
            clip = clip.fl(color_fn)

        # ── 픽셀 노이즈 ──
        noise_level = random.uniform(1.5, 4.0)

        def wash_noise_fn(get_frame, t, _nl=noise_level):
            frame = get_frame(t)
            noise = np.random.normal(0, _nl, frame.shape)
            return np.clip(frame.astype(np.float64) + noise, 0, 255).astype(np.uint8)

        if MOVIEPY_V2:
            clip = clip.transform(wash_noise_fn)
        else:
            clip = clip.fl(wash_noise_fn)

        # ── 인코딩 ──
        log.info("세탁 영상 인코딩: %s", output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        clip.write_videofile(
            output_path,
            fps=clip.fps or VIDEO_FPS,
            codec="libx264",
            bitrate="10M",
            audio_codec="aac",
            audio_bitrate="192k",
            threads=4,
            preset="medium",
            logger="bar",
        )
        clip.close()

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
            raise RuntimeError("세탁 실패: 출력 파일이 생성되지 않았습니다")

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        md5 = file_md5(output_path)
        log.info("세탁 완료: %.1fMB, MD5=%s", size_mb, md5)
        return output_path

    # ------------------------------------------------------------------
    # yt-dlp 다운로드 + 세탁
    # ------------------------------------------------------------------

    def download_and_wash(self, url: str, output_path: str) -> str:
        """
        yt-dlp 로 영상을 다운로드한 후 wash_video 로 세탁한다.

        Args:
            url: 다운로드할 영상 URL (YouTube, Instagram 등)
            output_path: 최종 출력 경로

        Returns:
            세탁된 출력 파일 경로
        """
        log.info("영상 다운로드 시작: %s", url)

        # 임시 다운로드 경로
        tmp_dir = ensure_dir(WORK_DIR / "downloads")
        tmp_filename = f"dl_{uuid.uuid4().hex[:8]}.mp4"
        tmp_path = str(tmp_dir / tmp_filename)

        # yt-dlp 실행 (subprocess 사용 -- pip 패키지가 아닐 수 있음)
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", tmp_path,
            "--no-playlist",
            "--quiet",
            url,
        ]

        log.info("yt-dlp 명령: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                log.error("yt-dlp 실패: %s", result.stderr)
                raise RuntimeError(f"yt-dlp 다운로드 실패: {result.stderr}")
        except FileNotFoundError:
            raise RuntimeError(
                "yt-dlp 가 설치되어 있지 않습니다. "
                "pip install yt-dlp 또는 시스템 패키지로 설치하세요."
            )

        if not os.path.exists(tmp_path):
            raise RuntimeError(f"다운로드된 파일을 찾을 수 없습니다: {tmp_path}")

        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        log.info("다운로드 완료: %.1fMB → 세탁 시작", size_mb)

        # 세탁
        result_path = self.wash_video(tmp_path, output_path)

        # 원본 임시 파일 삭제
        try:
            os.remove(tmp_path)
            log.debug("임시 파일 삭제: %s", tmp_path)
        except OSError:
            pass

        return result_path

    # ------------------------------------------------------------------
    # TTS 생성
    # ------------------------------------------------------------------

    @staticmethod
    def generate_tts(
        text: str,
        output_path: str,
        voice: str = "ko-female",
        rate: str = "+15%",
    ) -> bool:
        """
        Edge-TTS 를 사용하여 텍스트를 음성 파일로 변환한다.

        Args:
            text: 변환할 텍스트
            output_path: 출력 .mp3 파일 경로
            voice: 음성 프리셋 키 (ko-female, ko-male, en-female, en-male)
            rate: 속도 조절 (예: "+15%", "+0%", "-10%")

        Returns:
            성공 여부
        """
        try:
            import edge_tts
        except ImportError:
            log.error("edge-tts 가 설치되어 있지 않습니다. pip install edge-tts")
            return False

        voice_id = TTS_VOICES.get(voice, "ko-KR-SunHiNeural")
        log.debug("TTS 생성: voice=%s(%s), rate=%s, text=%s...", voice, voice_id, rate, text[:30])

        # 문장 간 자연스러운 휴지 삽입 (마침표, 물음표, 느낌표 뒤)
        import re
        _text = re.sub(r'([.!?。])\s*', r'\1 ... ', text.strip())
        _text = _text.rstrip(' .')

        try:
            # 이미 실행 중인 이벤트 루프가 있을 수 있으므로 안전하게 처리
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(
                        asyncio.run,
                        edge_tts.Communicate(_text, voice_id, rate=rate).save(output_path),
                    ).result(timeout=30)
            except RuntimeError:
                asyncio.run(
                    edge_tts.Communicate(_text, voice_id, rate=rate).save(output_path)
                )

            success = os.path.exists(output_path) and os.path.getsize(output_path) > 1000
            if success:
                log.debug("TTS 저장 완료: %s", output_path)
            else:
                log.warning("TTS 파일이 너무 작거나 없음: %s", output_path)
            return success

        except Exception as e:
            log.error("TTS 생성 실패: %s", e)
            return False

    # ------------------------------------------------------------------
    # SSML 기반 감정 TTS 생성
    # ------------------------------------------------------------------

    @staticmethod
    def generate_tts_ssml(
        text: str,
        output_path: str,
        voice: str = "ko-female",
        emotion: str = "friendly",
        rate: str = "",
    ) -> bool:
        """SSML 기반으로 감정이 담긴 TTS를 생성한다.

        Edge-TTS의 SSML(prosody) 지원을 활용하여
        감정별 음성 속도/음높이/볼륨을 자동 조절한다.

        Args:
            text: 변환할 텍스트
            output_path: 출력 파일 경로
            voice: 음성 프리셋 키
            emotion: 감정 프리셋 (excited, calm, dramatic, friendly, urgent, whisper)
            rate: 속도 오버라이드 (지정 시 감정 프리셋 무시)

        Returns:
            성공 여부
        """
        try:
            import edge_tts
        except ImportError:
            log.error("edge-tts 미설치")
            return False

        voice_id = TTS_VOICES.get(voice, "ko-KR-SunHiNeural")
        preset = TTS_EMOTION_PRESETS.get(emotion, TTS_EMOTION_PRESETS["friendly"])

        # 속도 결정 (명시적 rate > 감정 프리셋)
        final_rate = rate or preset["rate"]
        final_pitch = preset["pitch"]

        log.debug(
            "SSML TTS: voice=%s, emotion=%s, rate=%s, pitch=%s",
            voice, emotion, final_rate, final_pitch,
        )

        try:
            # Edge-TTS는 직접 SSML을 지원하지 않지만,
            # rate와 pitch를 통해 감정 표현 가능
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(
                        asyncio.run,
                        edge_tts.Communicate(
                            text, voice_id,
                            rate=final_rate,
                            pitch=final_pitch,
                        ).save(output_path),
                    ).result(timeout=30)
            except RuntimeError:
                asyncio.run(
                    edge_tts.Communicate(
                        text, voice_id,
                        rate=final_rate,
                        pitch=final_pitch,
                    ).save(output_path)
                )

            success = os.path.exists(output_path) and os.path.getsize(output_path) > 1000
            if success:
                log.debug("SSML TTS 저장 완료: %s", output_path)
            return success

        except Exception as e:
            log.error("SSML TTS 생성 실패: %s", e)
            # 폴백: 일반 TTS
            return VideoForge.generate_tts(text, output_path, voice, rate=final_rate)

    @staticmethod
    def generate_multi_speaker_tts(
        scripts: list[dict],
        output_dir: str,
    ) -> tuple[list[Optional[str]], list[float]]:
        """다중 화자 TTS를 생성한다.

        Args:
            scripts: [{"text": "...", "voice": "ko-female", "emotion": "excited"}, ...]
            output_dir: 출력 디렉토리

        Returns:
            (경로 리스트, 길이 리스트)
        """
        paths: list[Optional[str]] = []
        durations: list[float] = []

        os.makedirs(output_dir, exist_ok=True)

        for i, script in enumerate(scripts):
            text = script.get("text", "")
            voice = script.get("voice", "ko-female")
            emotion = script.get("emotion", "friendly")
            rate = script.get("rate", "")

            if not text or not text.strip():
                paths.append(None)
                durations.append(2.5)
                continue

            fp = os.path.join(output_dir, f"tts_{i:02d}.mp3")

            if VideoForge.generate_tts_ssml(text, fp, voice, emotion, rate):
                try:
                    ac = AudioFileClip(fp)
                    durations.append(ac.duration)
                    ac.close()
                except Exception:
                    durations.append(2.5)
                paths.append(fp)
            else:
                paths.append(None)
                durations.append(2.5)

        log.info("다중 화자 TTS 완료: %d/%d 성공", sum(1 for p in paths if p), len(scripts))
        return paths, durations

    # ------------------------------------------------------------------
    # 프로시저럴 Lo-Fi BGM 생성
    # ------------------------------------------------------------------

    @staticmethod
    def generate_bgm(output_path: str, duration: float) -> str:
        """
        프로시저럴 Lo-Fi BGM 을 생성하여 .wav 로 저장한다.

        구성 요소:
        - 킥 드럼 (50Hz, BPM 85)
        - 하이햇 (랜덤 노이즈)
        - 베이스 멜로디 (55~82Hz)
        - 앰비언트 패드 (220/330/440Hz)
        - 페이드인 0.8초, 페이드아웃 2.0초

        Args:
            output_path: 출력 .wav 파일 경로
            duration: 음원 길이 (초)

        Returns:
            출력 파일 경로
        """
        sr = 44100
        total_samples = int(sr * duration)
        bpm = 85
        beat_len = int(sr * 60.0 / bpm)
        audio = np.zeros(total_samples, dtype=np.float64)

        # ── 킥 드럼 (50Hz, 지수 감쇠) ──
        for s in range(0, total_samples, beat_len):
            t = np.arange(min(int(sr * 0.12), total_samples - s)) / sr
            kick = np.sin(2 * np.pi * 50 * t) * np.exp(-t * 14) * 0.4
            end = min(s + len(kick), total_samples)
            audio[s:end] += kick[:end - s]

        # ── 하이햇 (랜덤 노이즈, 반박자 간격) ──
        for s in range(beat_len // 2, total_samples, beat_len // 2):
            t = np.arange(min(int(sr * 0.025), total_samples - s)) / sr
            hihat = np.random.randn(len(t)) * np.exp(-t * 90) * 0.06
            end = min(s + len(hihat), total_samples)
            audio[s:end] += hihat[:end - s]

        # ── 베이스 멜로디 (55~82Hz 순환) ──
        bass_notes = [55, 65.4, 73.4, 82.4, 73.4, 65.4]
        note_len = beat_len * 2
        for i, s in enumerate(range(0, total_samples, note_len)):
            freq = bass_notes[i % len(bass_notes)]
            t = np.arange(min(note_len, total_samples - s)) / sr
            bass = np.sin(2 * np.pi * freq * t) * np.exp(-t * 1.2) * 0.1
            end = min(s + len(bass), total_samples)
            audio[s:end] += bass[:end - s]

        # ── 앰비언트 패드 (220/330/440Hz 합성) ──
        t_full = np.arange(total_samples) / sr
        pad = (
            np.sin(2 * np.pi * 220 * t_full) * 0.02
            + np.sin(2 * np.pi * 330 * t_full) * 0.012
            + np.sin(2 * np.pi * 440 * t_full) * 0.008
        )
        pad *= 1.0 + 0.25 * np.sin(2 * np.pi * 0.08 * t_full)
        audio += pad

        # ── 페이드인 / 페이드아웃 ──
        fade_in_samples = int(sr * 0.8)
        fade_out_samples = int(sr * 2.0)
        if fade_in_samples > 0 and fade_in_samples <= total_samples:
            audio[:fade_in_samples] *= np.linspace(0, 1, fade_in_samples)
        if fade_out_samples > 0 and fade_out_samples <= total_samples:
            audio[-fade_out_samples:] *= np.linspace(1, 0, fade_out_samples)

        # ── 정규화 ──
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val * 0.65

        # ── WAV 저장 ──
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with wave.open(output_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes((audio * 32767).astype(np.int16).tobytes())

        log.debug("BGM 생성 완료: %s (%.1f초)", output_path, duration)
        return output_path

    # ------------------------------------------------------------------
    # 장르별 BGM 생성 (Pro)
    # ------------------------------------------------------------------

    @staticmethod
    def generate_bgm_pro(
        output_path: str, duration: float, genre: str = "lofi",
    ) -> str:
        """장르별 프로시저럴 BGM을 생성한다.

        Args:
            output_path: 출력 .wav 파일 경로
            duration: 음원 길이 (초)
            genre: BGM 장르 (lofi, upbeat, cinematic, energetic, chill, dramatic, trendy)

        Returns:
            출력 파일 경로
        """
        params = BGM_GENRE_PARAMS.get(genre, BGM_GENRE_PARAMS["lofi"])
        sr = 44100
        total_samples = int(sr * duration)
        bpm = params["bpm"]
        beat_len = int(sr * 60.0 / bpm)
        audio = np.zeros(total_samples, dtype=np.float64)

        # ── 킥 드럼 ──
        for s in range(0, total_samples, beat_len):
            t = np.arange(min(int(sr * 0.12), total_samples - s)) / sr
            kick_freq = 50 + random.uniform(-3, 3)  # 약간의 변동
            kick = np.sin(2 * np.pi * kick_freq * t) * np.exp(-t * 14) * params["kick_vol"]
            end = min(s + len(kick), total_samples)
            audio[s:end] += kick[:end - s]

        # ── 하이햇 ──
        hihat_interval = beat_len // (4 if genre in ("energetic", "upbeat", "trendy") else 2)
        for s in range(hihat_interval, total_samples, hihat_interval):
            t = np.arange(min(int(sr * 0.025), total_samples - s)) / sr
            decay = 90 if genre in ("energetic", "trendy") else 60
            hihat = np.random.randn(len(t)) * np.exp(-t * decay) * params["hihat_vol"]
            end = min(s + len(hihat), total_samples)
            audio[s:end] += hihat[:end - s]

        # ── 베이스 멜로디 ──
        base_freq = params["key_freq"]
        # 장르별 코드 진행
        if genre in ("cinematic", "dramatic"):
            bass_notes = [base_freq, base_freq * 1.125, base_freq * 1.333,
                          base_freq * 1.5, base_freq * 1.333, base_freq * 1.125]
        elif genre in ("upbeat", "energetic", "trendy"):
            bass_notes = [base_freq, base_freq * 1.189, base_freq * 1.335,
                          base_freq * 1.498, base_freq * 1.682, base_freq * 1.335]
        else:  # lofi, chill
            bass_notes = [base_freq, base_freq * 1.189, base_freq * 1.335,
                          base_freq * 1.498, base_freq * 1.335, base_freq * 1.189]

        note_len = beat_len * (4 if genre in ("cinematic", "dramatic") else 2)
        for i, s in enumerate(range(0, total_samples, note_len)):
            freq = bass_notes[i % len(bass_notes)]
            t = np.arange(min(note_len, total_samples - s)) / sr
            bass = np.sin(2 * np.pi * freq * t) * np.exp(-t * 1.2) * params["bass_vol"]
            # 하모닉 추가 (풍성한 소리)
            bass += np.sin(2 * np.pi * freq * 2 * t) * np.exp(-t * 2.0) * params["bass_vol"] * 0.3
            end = min(s + len(bass), total_samples)
            audio[s:end] += bass[:end - s]

        # ── 앰비언트 패드 ──
        t_full = np.arange(total_samples) / sr
        pad_freqs = params["pad_freqs"]
        pad_vol = params["pad_vol"]
        pad = np.zeros(total_samples)
        for i, freq in enumerate(pad_freqs):
            vol_scale = 1.0 - i * 0.25  # 높은 주파수일수록 작게
            pad += np.sin(2 * np.pi * freq * t_full) * pad_vol * vol_scale

        # LFO 모듈레이션 (부드러운 볼륨 변화)
        lfo_rate = 0.08 if genre in ("lofi", "chill", "cinematic") else 0.15
        pad *= 1.0 + 0.3 * np.sin(2 * np.pi * lfo_rate * t_full)
        audio += pad

        # ── 스네어 (upbeat/energetic/trendy) ──
        if genre in ("upbeat", "energetic", "trendy"):
            for s in range(beat_len, total_samples, beat_len * 2):
                t = np.arange(min(int(sr * 0.08), total_samples - s)) / sr
                snare = np.random.randn(len(t)) * np.exp(-t * 25) * 0.2
                snare += np.sin(2 * np.pi * 180 * t) * np.exp(-t * 30) * 0.15
                end = min(s + len(snare), total_samples)
                audio[s:end] += snare[:end - s]

        # ── 페이드인 / 페이드아웃 ──
        fade_in_samples = int(sr * params["fade_in"])
        fade_out_samples = int(sr * params["fade_out"])
        if fade_in_samples > 0 and fade_in_samples <= total_samples:
            audio[:fade_in_samples] *= np.linspace(0, 1, fade_in_samples)
        if fade_out_samples > 0 and fade_out_samples <= total_samples:
            audio[-fade_out_samples:] *= np.linspace(1, 0, fade_out_samples)

        # ── 정규화 ──
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val * 0.65

        # ── WAV 저장 ──
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with wave.open(output_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes((audio * 32767).astype(np.int16).tobytes())

        log.debug("BGM Pro 생성 완료: %s (%.1f초, 장르=%s)", output_path, duration, genre)
        return output_path

    # ------------------------------------------------------------------
    # 인트로/아웃트로 생성
    # ------------------------------------------------------------------

    def render_intro(
        self, w: int, h: int, duration: float,
        branding: BrandingConfig,
    ) -> Optional[object]:
        """브랜딩 인트로 클립을 생성한다.

        Args:
            w, h: 영상 해상도
            duration: 인트로 길이 (초)
            branding: 브랜딩 설정

        Returns:
            MoviePy 클립 또는 None
        """
        if not branding or not branding.intro_text:
            return None

        try:
            # 배경
            bg_color = self._hex_to_rgb(branding.intro_bg_color)
            accent_color = self._hex_to_rgb(branding.intro_accent_color)

            # 인트로 프레임 생성
            img = Image.new("RGB", (w, h), bg_color)
            draw = ImageDraw.Draw(img)

            # 중앙 악센트 라인
            line_y = h // 2 - 80
            draw.rectangle(
                [(w // 4, line_y), (w * 3 // 4, line_y + 4)],
                fill=accent_color,
            )

            # 메인 텍스트
            font_large = self._get_korean_font(min(72, w // 12))
            font_small = self._get_korean_font(min(36, w // 24))

            # 메인 텍스트 중앙 정렬
            main_text = branding.intro_text
            bbox = draw.textbbox((0, 0), main_text, font=font_large)
            tw = bbox[2] - bbox[0]
            draw.text(
                ((w - tw) // 2, h // 2 - 40),
                main_text, font=font_large,
                fill=(255, 255, 255),
            )

            # 서브 텍스트
            if branding.intro_subtitle:
                sub = branding.intro_subtitle
                bbox = draw.textbbox((0, 0), sub, font=font_small)
                tw = bbox[2] - bbox[0]
                draw.text(
                    ((w - tw) // 2, h // 2 + 50),
                    sub, font=font_small,
                    fill=(200, 200, 200),
                )

            # 하단 악센트 라인
            line_y2 = h // 2 + 100
            draw.rectangle(
                [(w // 4, line_y2), (w * 3 // 4, line_y2 + 4)],
                fill=accent_color,
            )

            arr = np.array(img)
            if MOVIEPY_V2:
                clip = ImageClip(arr, duration=duration).with_fps(self.cfg.fps)
            else:
                clip = ImageClip(arr).set_duration(duration).set_fps(self.cfg.fps)

            # 페이드인 효과
            clip = clip.crossfadein(0.5)

            log.info("인트로 클립 생성 완료: %.1f초", duration)
            return clip

        except Exception as e:
            log.error("인트로 생성 실패: %s", e)
            return None

    def render_outro(
        self, w: int, h: int, duration: float,
        branding: BrandingConfig, cta_text: str = "",
    ) -> Optional[object]:
        """브랜딩 아웃트로 클립을 생성한다.

        Args:
            w, h: 영상 해상도
            duration: 아웃트로 길이 (초)
            branding: 브랜딩 설정
            cta_text: CTA 텍스트 (없으면 branding에서 가져옴)

        Returns:
            MoviePy 클립 또는 None
        """
        if not branding or not branding.outro_text:
            return None

        try:
            bg_color = self._hex_to_rgb(branding.outro_bg_color)
            text_color = self._hex_to_rgb(branding.outro_text_color)

            img = Image.new("RGB", (w, h), bg_color)
            draw = ImageDraw.Draw(img)

            font_large = self._get_korean_font(min(64, w // 14))
            font_medium = self._get_korean_font(min(40, w // 20))
            font_small = self._get_korean_font(min(32, w // 28))

            # 메인 텍스트
            main_text = branding.outro_text
            bbox = draw.textbbox((0, 0), main_text, font=font_large)
            tw = bbox[2] - bbox[0]
            draw.text(
                ((w - tw) // 2, h // 2 - 80),
                main_text, font=font_large,
                fill=text_color,
            )

            # CTA 텍스트
            cta = cta_text or branding.outro_cta
            if cta:
                bbox = draw.textbbox((0, 0), cta, font=font_medium)
                tw = bbox[2] - bbox[0]

                # CTA 버튼 스타일 배경
                pad_x, pad_y = 30, 12
                btn_x = (w - tw) // 2 - pad_x
                btn_y = h // 2 + 20 - pad_y
                accent_color = self._hex_to_rgb(branding.intro_accent_color)
                draw.rounded_rectangle(
                    [(btn_x, btn_y),
                     (btn_x + tw + pad_x * 2, btn_y + (bbox[3] - bbox[1]) + pad_y * 2)],
                    radius=12,
                    fill=accent_color,
                )
                draw.text(
                    ((w - tw) // 2, h // 2 + 20),
                    cta, font=font_medium,
                    fill=(255, 255, 255),
                )

            # 하단 안내
            guide = "감사합니다 ❤️"
            bbox = draw.textbbox((0, 0), guide, font=font_small)
            tw = bbox[2] - bbox[0]
            draw.text(
                ((w - tw) // 2, h * 3 // 4),
                guide, font=font_small,
                fill=(180, 180, 180),
            )

            arr = np.array(img)
            if MOVIEPY_V2:
                clip = ImageClip(arr, duration=duration).with_fps(self.cfg.fps)
            else:
                clip = ImageClip(arr).set_duration(duration).set_fps(self.cfg.fps)

            clip = clip.crossfadein(0.5)
            log.info("아웃트로 클립 생성 완료: %.1f초", duration)
            return clip

        except Exception as e:
            log.error("아웃트로 생성 실패: %s", e)
            return None

    def render_watermark_overlay(
        self, w: int, h: int, duration: float,
        branding: BrandingConfig,
    ) -> Optional[object]:
        """워터마크 오버레이 클립을 생성한다.

        Args:
            w, h: 영상 해상도
            duration: 오버레이 유지 시간
            branding: 브랜딩 설정

        Returns:
            MoviePy 클립 (투명 배경) 또는 None
        """
        if not branding or not branding.watermark_text:
            return None

        try:
            # RGBA 투명 배경
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            font = self._get_korean_font(branding.watermark_size)
            text = branding.watermark_text
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

            # 위치 결정
            pos = branding.watermark_position
            margin = 20
            if "right" in pos:
                x = w - tw - margin
            elif "left" in pos:
                x = margin
            else:
                x = (w - tw) // 2

            if "bottom" in pos:
                y = h - th - margin
            elif "top" in pos:
                y = margin
            else:
                y = (h - th) // 2

            alpha = int(255 * branding.watermark_opacity)
            draw.text((x, y), text, font=font, fill=(255, 255, 255, alpha))

            arr = np.array(img)
            if MOVIEPY_V2:
                clip = ImageClip(arr, duration=duration, is_mask=False).with_fps(self.cfg.fps)
            else:
                clip = ImageClip(arr, ismask=False).set_duration(duration).set_fps(self.cfg.fps)

            log.info("워터마크 오버레이 생성 완료")
            return clip

        except Exception as e:
            log.error("워터마크 생성 실패: %s", e)
            return None

    # ------------------------------------------------------------------
    # 플랫폼별 렌더링 (Pro Pipeline)
    # ------------------------------------------------------------------

    def render_for_platform(
        self,
        platform: Platform,
        images: list[str],
        narrations: list[str],
        output_path: str,
        subtitle_text: str = "",
        brand: str = "",
        cta_text: str = "",
    ) -> str:
        """플랫폼에 최적화된 영상을 렌더링한다.

        Args:
            platform: 대상 플랫폼 (YouTube, Instagram, Naver Blog)
            images: 이미지 파일 경로 리스트
            narrations: 장면별 나레이션 텍스트
            output_path: 출력 파일 경로
            subtitle_text: 자막 텍스트
            brand: 브랜드명 (인트로/아웃트로 적용)
            cta_text: CTA 텍스트

        Returns:
            최종 출력 파일 경로
        """
        preset = PLATFORM_PRESETS.get(platform)
        if not preset:
            log.warning("플랫폼 프리셋 없음: %s, 기본 렌더링 사용", platform)
            return self.render_shorts(images, narrations, output_path, subtitle_text)

        # 플랫폼에 맞는 RenderConfig 생성
        self.cfg = RenderConfig.from_platform_preset(preset, brand=brand)

        log.info(
            "플랫폼 렌더링 시작: %s, %dx%d @%dfps, 전환=%s, BGM=%s",
            platform.value, self.cfg.width, self.cfg.height,
            self.cfg.fps, self.cfg.transition_type, self.cfg.bgm_genre,
        )

        t_start = time.time()
        self._tmp_audio = []
        cfg = self.cfg
        w, h = self._jittered_dimensions()

        if not images:
            raise ValueError("이미지가 하나도 없습니다")

        # ── TTS 생성 ──
        tts_paths: list[Optional[str]] = []
        tts_durations: list[float] = []
        if narrations:
            tts_dir = ensure_dir(WORK_DIR / f"tts_{uuid.uuid4().hex[:8]}")
            tts_paths, tts_durations = self._generate_scene_tts(
                narrations, str(tts_dir), cfg.tts_voice,
            )

        # ── Framed 캔버스 자동 변환 (render_for_platform) ──
        _canvas_layout = getattr(cfg, "canvas_layout", "auto")
        if _canvas_layout == "framed":
            log.info("Framed 레이아웃 자동 변환: %d장 이미지", len(images))
            _renderer = CanvasRenderer(w, h)
            _sub_lines = [t.strip() for t in subtitle_text.split("\n") if t.strip()] if subtitle_text else narrations
            _scenes = []
            for idx, img_path in enumerate(images):
                _top_text = _sub_lines[idx] if idx < len(_sub_lines) else ""
                _scenes.append({
                    "layout": "framed",
                    "image": img_path,
                    "title": _top_text,
                })
            images = _renderer.render_scenes(_scenes)
            log.info("Framed 캔버스 %d장 생성 완료", len(images))

        # ── 이미지 → 클립 변환 ──
        effects = EFFECT_PRESETS.get(cfg.effect_mode, EFFECT_PRESETS["dynamic"])
        clips: list = []
        default_duration = 3.5

        for i, img_path in enumerate(images):
            dur = default_duration
            if i < len(tts_durations) and tts_durations[i] > 0:
                dur = max(tts_durations[i] + 0.5, default_duration)

            try:
                img = Image.open(img_path).convert("RGB")
                img = _crop_and_resize(img, w, h)
                # 색보정 (framed면 이미 캔버스이므로 약하게)
                if _canvas_layout != "framed":
                    img = _apply_color_filter(img, brightness=1.02, contrast=1.05, saturation=1.08)
                arr = np.array(img)

                if MOVIEPY_V2:
                    clip = ImageClip(arr, duration=dur).with_fps(cfg.fps)
                else:
                    clip = ImageClip(arr).set_duration(dur).set_fps(cfg.fps)

                # 모션 이펙트
                effect_name = effects[i % len(effects)]
                clip = self.apply_motion_effect(clip, effect_name, zoom_ratio=1.12)
                clips.append(clip)

            except Exception as e:
                log.error("클립 생성 실패 [%d]: %s", i, e)
                continue

        if not clips:
            raise RuntimeError("처리 가능한 클립이 없습니다")

        # ── 전환 효과 적용 ──
        transition_dur = cfg.transition_duration
        final = self._apply_transitions(clips, cfg.transition_type, transition_dur)

        # ── 자막 오버레이 (TTS 동기화) ──
        if cfg.subtitle_enabled and subtitle_text:
            final = self._apply_subtitles(
                final, clips, subtitle_text, w, h,
                cfg.subtitle_fontsize, transition_dur, default_duration,
                tts_durations=tts_durations,
            )

        # ── 오디오 믹싱 ──
        audio_layers: list = []

        # TTS 오디오
        if tts_paths:
            current_time = 0.0
            for i in range(min(len(tts_paths), len(clips))):
                if tts_paths[i] and os.path.exists(tts_paths[i]):
                    try:
                        tts_audio = AudioFileClip(tts_paths[i])
                        self._tmp_audio.append(tts_audio)
                        if MOVIEPY_V2:
                            tts_audio = tts_audio.with_start(current_time + 0.2)
                        else:
                            tts_audio = tts_audio.set_start(current_time + 0.2)
                        audio_layers.append(tts_audio)
                    except Exception as e:
                        log.warning("TTS 오디오 로드 실패 [%d]: %s", i, e)
                clip_dur = clips[i].duration if i < len(clips) else default_duration
                current_time += clip_dur - transition_dur

        # BGM (장르별)
        try:
            bgm_path = str(WORK_DIR / f"_bgm_{uuid.uuid4().hex[:6]}.wav")
            self.generate_bgm_pro(bgm_path, final.duration, genre=cfg.bgm_genre)
            bgm = AudioFileClip(bgm_path)
            self._tmp_audio.append(bgm)
            self._tmp_files.append(bgm_path)

            bgm_vol = cfg.bgm_volume if tts_paths else cfg.bgm_volume * 3
            if MOVIEPY_V2:
                bgm = bgm.with_volume_scaled(bgm_vol)
            else:
                bgm = bgm.volumex(bgm_vol)

            # 루프
            if bgm.duration < final.duration:
                loops = int(final.duration / bgm.duration) + 1
                if concatenate_audioclips:
                    bgm = concatenate_audioclips([bgm] * loops)
            if bgm.duration > final.duration:
                if MOVIEPY_V2:
                    bgm = bgm.subclipped(0, final.duration)
                else:
                    bgm = bgm.subclip(0, final.duration)
            audio_layers.append(bgm)
        except Exception as e:
            log.error("BGM 생성 실패: %s", e)

        # 오디오 병합
        if audio_layers:
            if final.audio:
                audio_layers.insert(0, final.audio)
            mixed = CompositeAudioClip(audio_layers)
            if MOVIEPY_V2:
                final = final.with_audio(mixed)
            else:
                final = final.set_audio(mixed)

        # ── 워터마크 오버레이 ──
        branding = cfg.branding_config
        if cfg.watermark_enabled and branding:
            wm_clip = self.render_watermark_overlay(w, h, final.duration, branding)
            if wm_clip:
                if MOVIEPY_V2:
                    wm_clip = wm_clip.with_position((0, 0))
                else:
                    wm_clip = wm_clip.set_position((0, 0))
                final = CompositeVideoClip([final, wm_clip])

        # ── 인트로/아웃트로 결합 ──
        final_clips = []
        if cfg.intro_enabled and branding:
            intro = self.render_intro(w, h, preset.intro_duration, branding)
            if intro:
                final_clips.append(intro)

        final_clips.append(final)

        if cfg.outro_enabled and branding:
            outro = self.render_outro(
                w, h, preset.outro_duration, branding,
                cta_text=cta_text or preset.cta_text,
            )
            if outro:
                final_clips.append(outro)

        if len(final_clips) > 1:
            final = concatenate_videoclips(final_clips, method="compose")

        # ── 최대 길이 제한 ──
        if final.duration > preset.max_duration_sec:
            log.warning(
                "영상 길이 %.1f초 → %d초로 잘림",
                final.duration, preset.max_duration_sec,
            )
            if MOVIEPY_V2:
                final = final.subclipped(0, preset.max_duration_sec)
            else:
                final = final.subclip(0, preset.max_duration_sec)

        # ── 안티밴 적용 (HQ 모드면 스킵) ──
        if cfg.anti_ban_enabled:
            final = self.apply_anti_ban(final)
        else:
            log.info("HQ 모드: 안티밴 스킵 (render_for_platform)")

        # ── 인코딩 (GPU 감지 + HQ 설정) ──
        log.info("인코딩 시작: %s", output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        _codec = detect_gpu_encoder()
        _bitrate = getattr(cfg, 'video_bitrate', preset.video_bitrate)
        _audio_br = getattr(cfg, 'audio_bitrate', '192k')
        _preset = getattr(cfg, 'encode_preset', 'medium')

        _ffmpeg_params = ["-preset", _preset]
        if _codec == "h264_nvenc":
            _ffmpeg_params = ["-preset", "p7", "-rc", "vbr", "-cq", "18"]
        elif _codec == "h264_amf":
            _ffmpeg_params = ["-quality", "quality"]

        final.write_videofile(
            output_path,
            fps=cfg.fps,
            codec=_codec,
            bitrate=_bitrate,
            audio_codec="aac",
            audio_bitrate=_audio_br,
            threads=4,
            ffmpeg_params=_ffmpeg_params,
            logger="bar",
        )

        # ── 정리 ──
        self._cleanup(clips, final)

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
            raise RuntimeError("렌더링 실패: 출력 파일이 생성되지 않았습니다")

        elapsed = time.time() - t_start
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        log.info(
            "[%s] 렌더 완료: %.1fMB, %d초 소요",
            platform.value, size_mb, int(elapsed),
        )
        return output_path

    # ------------------------------------------------------------------
    # 전환 효과 적용
    # ------------------------------------------------------------------

    def _apply_transitions(
        self, clips: list, transition_type: str, transition_dur: float,
    ):
        """클립 사이에 전환 효과를 적용한다."""
        if len(clips) <= 1:
            return clips[0] if clips else None

        log.info(
            "전환 효과 적용: type=%s, duration=%.2f초, %d클립",
            transition_type, transition_dur, len(clips),
        )

        if transition_type in ("crossfade", "blur"):
            # 크로스디졸브 (기본)
            processed = [clips[0]]
            current_time = clips[0].duration
            for i in range(1, len(clips)):
                start = current_time - transition_dur
                if MOVIEPY_V2:
                    c2 = clips[i].with_start(start).crossfadein(transition_dur)
                else:
                    c2 = clips[i].set_start(start).crossfadein(transition_dur)
                processed.append(c2)
                current_time = start + clips[i].duration
            return CompositeVideoClip(processed)

        elif transition_type in ("slide_left", "slide_right", "slide_up"):
            # 슬라이드 전환
            processed = [clips[0]]
            current_time = clips[0].duration
            for i in range(1, len(clips)):
                start = current_time - transition_dur
                clip_next = clips[i]

                # 슬라이드 위치 함수
                if transition_type == "slide_left":
                    pos_fn = lambda t, _d=transition_dur, _w=self.cfg.width: (
                        max(0, int(_w * (1 - t / _d))) if t < _d else 0, 0
                    )
                elif transition_type == "slide_right":
                    pos_fn = lambda t, _d=transition_dur, _w=self.cfg.width: (
                        min(0, int(-_w * (1 - t / _d))) if t < _d else 0, 0
                    )
                else:  # slide_up
                    pos_fn = lambda t, _d=transition_dur, _h=self.cfg.height: (
                        0, max(0, int(_h * (1 - t / _d))) if t < _d else 0
                    )

                if MOVIEPY_V2:
                    c2 = clip_next.with_start(start).with_position(pos_fn)
                else:
                    c2 = clip_next.set_start(start).set_position(pos_fn)
                processed.append(c2)
                current_time = start + clip_next.duration
            return CompositeVideoClip(processed)

        elif transition_type == "flash":
            # 화이트 플래시 전환
            result_clips = [clips[0]]
            current_time = clips[0].duration

            for i in range(1, len(clips)):
                # 플래시 프레임 삽입
                flash_dur = min(transition_dur, 0.15)
                white_arr = np.full(
                    (self.cfg.height, self.cfg.width, 3), 255, dtype=np.uint8,
                )
                if MOVIEPY_V2:
                    flash = (ImageClip(white_arr, duration=flash_dur)
                             .with_start(current_time - flash_dur / 2)
                             .with_fps(self.cfg.fps)
                             .crossfadein(flash_dur / 2)
                             .crossfadeout(flash_dur / 2))
                else:
                    flash = (ImageClip(white_arr)
                             .set_duration(flash_dur)
                             .set_start(current_time - flash_dur / 2)
                             .set_fps(self.cfg.fps)
                             .crossfadein(flash_dur / 2)
                             .crossfadeout(flash_dur / 2))
                result_clips.append(flash)

                if MOVIEPY_V2:
                    c2 = clips[i].with_start(current_time)
                else:
                    c2 = clips[i].set_start(current_time)
                result_clips.append(c2)
                current_time += clips[i].duration
            return CompositeVideoClip(result_clips)

        else:
            # 기본 크로스디졸브 폴백
            return self._apply_transitions(clips, "crossfade", transition_dur)

    # ------------------------------------------------------------------
    # 자막 오버레이 (리팩토링)
    # ------------------------------------------------------------------

    def _apply_subtitles(
        self, final, clips, subtitle_text, w, h,
        fontsize, transition_dur, default_duration,
        tts_durations: list[float] = None,
    ):
        """자막 오버레이를 적용한다. TTS 동기화 + 스타일 지원."""
        cfg = self.cfg
        sub_lines = [t.strip() for t in subtitle_text.split("\n") if t.strip()]
        sub_layers = [final]
        current_time = 0.0
        _tts_offset = 0.2

        # 자막 스타일 매핑
        _style_map = {
            "bold": "bold_center", "classic": "clean",
            "modern": "modern", "minimal": "minimal",
            "clean": "clean", "news": "news",
            "bold_center": "bold_center", "framed": "framed",
        }
        _sub_style = _style_map.get(cfg.subtitle_style, "modern")

        for i in range(min(len(clips), len(sub_lines))):
            clip_dur = clips[i].duration if i < len(clips) else default_duration
            try:
                sub_arr = _render_subtitle_image(
                    sub_lines[i], w, fontsize=fontsize,
                    style=_sub_style,
                )
                sub_h = sub_arr.shape[0]

                # ★ TTS 동기화: TTS 길이가 있으면 그걸 자막 길이로 사용
                if tts_durations and i < len(tts_durations) and tts_durations[i] > 0:
                    sub_dur = tts_durations[i] + 0.3
                else:
                    sub_dur = max(clip_dur - 0.8, 0.5)

                # ★ 자막 시작 = TTS 시작과 동일
                sub_start = current_time + _tts_offset

                # 자막 위치 (framed면 하단 자막 영역에)
                _pos = cfg.subtitle_position
                if _pos == "center" or _sub_style == "bold_center":
                    sub_y = (h - sub_h) // 2
                elif _pos == "top":
                    sub_y = 120
                else:  # bottom
                    sub_y = h - sub_h - 100

                if MOVIEPY_V2:
                    sub_clip = (
                        ImageClip(sub_arr, duration=sub_dur, is_mask=False)
                        .with_start(sub_start)
                        .with_position(("center", sub_y))
                        .crossfadein(0.15)
                    )
                else:
                    sub_clip = (
                        ImageClip(sub_arr, ismask=False)
                        .set_duration(sub_dur)
                        .set_start(sub_start)
                        .set_position(("center", sub_y))
                        .crossfadein(0.15)
                    )
                sub_layers.append(sub_clip)
            except Exception as e:
                log.warning("자막 렌더링 실패 [%d]: %s", i, e)

            current_time += clip_dur - transition_dur

        if len(sub_layers) > 1:
            return CompositeVideoClip(sub_layers)
        return final

    # ------------------------------------------------------------------
    # 헬퍼: 한글 폰트, 색상 변환
    # ------------------------------------------------------------------

    @staticmethod
    def _get_korean_font(size: int) -> ImageFont.FreeTypeFont:
        """한글 폰트를 가져온다."""
        if KOREAN_FONT:
            try:
                return ImageFont.truetype(KOREAN_FONT, size)
            except Exception:
                pass
        return ImageFont.load_default()

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple:
        """Hex 색상을 RGB 튜플로 변환."""
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    # ------------------------------------------------------------------
    # 모션 이펙트
    # ------------------------------------------------------------------

    @staticmethod
    def apply_motion_effect(clip, effect_name: str, zoom_ratio: float = 1.2):
        """
        클립에 단일 모션 이펙트를 적용한다.

        프레임 단위로 crop 영역을 이동/확대하여 카메라 움직임을 시뮬레이션.

        지원 이펙트:
            zoom_in, zoom_out, pan_left, pan_right, tilt_up, tilt_down,
            diag_dr, diag_dl, pulse, drift, zoom_rotate, bounce

        Args:
            clip: MoviePy 클립 객체
            effect_name: 이펙트 이름
            zoom_ratio: 줌 배율 (기본 1.2)

        Returns:
            이펙트가 적용된 클립
        """
        duration = clip.duration
        if duration is None or duration <= 0:
            return clip

        def make_effect(get_frame, t, _f=effect_name, _z=zoom_ratio, _d=duration):
            raw = t / _d if _d > 0 else 0
            pr = ease_io(min(raw, 1.0))
            frame = get_frame(t)
            h, w = frame.shape[:2]
            mg = _z - 1.0  # margin (줌 여유 비율)

            # 기본값
            x, y = 0, 0
            nw, nh = w, h

            if _f == "zoom_in":
                cz = 1 + mg * pr
                nh, nw = int(h / cz), int(w / cz)
                y, x = (h - nh) // 2, (w - nw) // 2

            elif _f == "zoom_out":
                cz = _z - mg * pr
                nh, nw = int(h / cz), int(w / cz)
                y, x = (h - nh) // 2, (w - nw) // 2

            elif _f == "pan_left":
                cz = _z
                nh, nw = int(h / cz), int(w / cz)
                mx = max(w - nw, 1)
                x = int(mx * (1 - pr))
                y = (h - nh) // 2

            elif _f == "pan_right":
                cz = _z
                nh, nw = int(h / cz), int(w / cz)
                mx = max(w - nw, 1)
                x = int(mx * pr)
                y = (h - nh) // 2

            elif _f == "tilt_up":
                cz = _z
                nh, nw = int(h / cz), int(w / cz)
                my = max(h - nh, 1)
                y = int(my * (1 - pr))
                x = (w - nw) // 2

            elif _f == "tilt_down":
                cz = _z
                nh, nw = int(h / cz), int(w / cz)
                my = max(h - nh, 1)
                y = int(my * pr)
                x = (w - nw) // 2

            elif _f == "diag_dr":
                cz = _z
                nh, nw = int(h / cz), int(w / cz)
                mx = max(w - nw, 1)
                my = max(h - nh, 1)
                x = int(mx * pr)
                y = int(my * pr)

            elif _f == "diag_dl":
                cz = _z
                nh, nw = int(h / cz), int(w / cz)
                mx = max(w - nw, 1)
                my = max(h - nh, 1)
                x = int(mx * (1 - pr))
                y = int(my * pr)

            elif _f == "pulse":
                wave_pr = 0.5 + 0.5 * math.sin(pr * math.pi * 2)
                cz = 1 + mg * wave_pr
                nh, nw = int(h / cz), int(w / cz)
                y, x = (h - nh) // 2, (w - nw) // 2

            elif _f == "drift":
                cz = 1 + mg * 0.5
                nh, nw = int(h / cz), int(w / cz)
                cx = 0.5 + 0.25 * math.sin(pr * math.pi * 1.5)
                cy = 0.5 + 0.25 * math.cos(pr * math.pi)
                mx = max(w - nw, 1)
                my = max(h - nh, 1)
                x = int(mx * cx)
                y = int(my * cy)

            elif _f == "zoom_rotate":
                cz = 1 + mg * pr * 0.8
                nh, nw = int(h / cz), int(w / cz)
                y, x = (h - nh) // 2, (w - nw) // 2
                offset_x = int(mg * 6 * math.sin(pr * math.pi))
                x = max(0, min(x + offset_x, max(w - nw, 0)))

            elif _f == "bounce":
                # 바운스: ease-out cubic
                bounce_pr = 1 - math.pow(1 - pr, 3)
                cz = 1 + mg * bounce_pr
                nh, nw = int(h / cz), int(w / cz)
                y, x = (h - nh) // 2, (w - nw) // 2

            else:
                # 기본: zoom_in fallback
                cz = 1 + mg * pr
                nh, nw = int(h / cz), int(w / cz)
                y, x = (h - nh) // 2, (w - nw) // 2

            # 안전 클램핑
            x = max(0, min(x, w - 1))
            y = max(0, min(y, h - 1))
            nw = max(nw, 2)
            nh = max(nh, 2)

            cropped = frame[y:min(y + nh, h), x:min(x + nw, w)]

            if cropped.shape[0] < 2 or cropped.shape[1] < 2:
                return frame

            return np.array(Image.fromarray(cropped).resize((w, h), Image.LANCZOS))

        if MOVIEPY_V2:
            return clip.transform(make_effect)
        else:
            return clip.fl(make_effect)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _jittered_dimensions(self) -> tuple[int, int]:
        """안티밴용 해상도 지터를 적용한 (width, height) 를 반환."""
        cfg = self.cfg
        if cfg.dimension_jitter:
            lo, hi = DIMENSION_JITTER
            dw = random.randint(lo, hi) * random.choice([-1, 1])
            dh = random.randint(lo, hi) * random.choice([-1, 1])
            # 짝수로 맞춤 (인코더 호환)
            w = (cfg.width + dw) // 2 * 2
            h = (cfg.height + dh) // 2 * 2
            log.debug("해상도 지터: %dx%d → %dx%d", cfg.width, cfg.height, w, h)
            return w, h
        return cfg.width, cfg.height

    def _generate_scene_tts(
        self,
        texts: list[str],
        out_dir: str,
        voice: str = "ko-female",
    ) -> tuple[list[Optional[str]], list[float]]:
        """장면별 TTS 생성. (경로 리스트, 길이 리스트) 반환."""
        paths: list[Optional[str]] = []
        durations: list[float] = []
        rate = self.cfg.tts_speed or TTS_SPEED_RATE

        for i, text in enumerate(texts):
            if not text or not text.strip():
                paths.append(None)
                durations.append(2.5)
                continue

            fp = str(Path(out_dir) / f"tts_{i:02d}.mp3")
            if self.generate_tts(text, fp, voice, rate=rate):
                try:
                    ac = AudioFileClip(fp)
                    durations.append(ac.duration)
                    ac.close()
                except Exception:
                    durations.append(2.5)
                paths.append(fp)
            else:
                paths.append(None)
                durations.append(2.5)

        return paths, durations

    def _cleanup(self, clips: list, final) -> None:
        """MoviePy 리소스 정리."""
        for ac in self._tmp_audio:
            try:
                ac.close()
            except Exception:
                pass
        for c in clips:
            try:
                c.close()
            except Exception:
                pass
        try:
            final.close()
        except Exception:
            pass
        # 임시 파일 정리
        for fp in self._tmp_files:
            try:
                if os.path.exists(fp):
                    os.remove(fp)
            except OSError:
                pass
        self._tmp_files.clear()
        self._tmp_audio.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 미디어 추출 유틸리티 — 실제 이미지/영상 추출
# ═══════════════════════════════════════════════════════════════════════════

class MediaExtractor:
    """YouTube 영상/웹 이미지에서 실제 미디어를 추출하는 유틸리티."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir) if output_dir else WORK_DIR / "extracted"
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # YouTube 영상에서 프레임 이미지 추출
    # ------------------------------------------------------------------
    def extract_frames_from_url(
        self,
        url: str,
        count: int = 5,
        quality: str = "best",
    ) -> list[str]:
        """
        YouTube URL에서 주요 프레임을 이미지로 추출.

        Args:
            url: YouTube 영상 URL
            count: 추출할 프레임 수
            quality: 다운로드 품질 (best, 720p, 480p)

        Returns:
            추출된 이미지 파일 경로 리스트
        """
        job_id = uuid.uuid4().hex[:8]
        dl_dir = self.output_dir / f"frames_{job_id}"
        os.makedirs(dl_dir, exist_ok=True)

        # yt-dlp로 영상 다운로드
        video_path = str(dl_dir / "source.mp4")
        fmt = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
        if quality == "720p":
            fmt = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"

        try:
            cmd = [
                sys.executable, "-m", "yt_dlp",
                "-f", fmt,
                "-o", video_path,
                "--no-playlist",
                "--quiet",
                url,
            ]
            subprocess.run(cmd, timeout=120, check=True, capture_output=True)
        except Exception as e:
            log.error("영상 다운로드 실패: %s", e)
            return []

        if not os.path.exists(video_path):
            # yt-dlp가 확장자를 바꿀 수 있음
            for ext in [".mp4", ".webm", ".mkv"]:
                alt = str(dl_dir / f"source{ext}")
                if os.path.exists(alt):
                    video_path = alt
                    break
            else:
                log.error("다운로드된 영상 파일을 찾을 수 없음")
                return []

        return self.extract_frames_from_file(video_path, count)

    def extract_frames_from_file(
        self,
        video_path: str,
        count: int = 5,
    ) -> list[str]:
        """
        로컬 영상 파일에서 균등 간격으로 프레임 추출.

        Args:
            video_path: 영상 파일 경로
            count: 추출할 프레임 수

        Returns:
            추출된 이미지 파일 경로 리스트
        """
        job_id = uuid.uuid4().hex[:8]
        out_dir = self.output_dir / f"frames_{job_id}"
        os.makedirs(out_dir, exist_ok=True)

        # FFmpeg로 영상 길이 확인
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=30,
            )
            duration = float(probe.stdout.strip())
        except Exception:
            duration = 60.0  # 기본값

        # 균등 간격으로 프레임 추출
        frames = []
        interval = max(duration / (count + 1), 0.5)
        for i in range(count):
            timestamp = interval * (i + 1)
            out_path = str(out_dir / f"frame_{i:03d}.jpg")
            try:
                subprocess.run(
                    ["ffmpeg", "-ss", str(timestamp), "-i", video_path,
                     "-vframes", "1", "-q:v", "2", "-y", out_path],
                    capture_output=True, timeout=30, check=True,
                )
                if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                    frames.append(out_path)
            except Exception as e:
                log.warning("프레임 추출 실패 [%d]: %s", i, e)

        log.info("프레임 추출 완료: %d/%d (영상: %s)", len(frames), count, video_path)
        return frames

    # ------------------------------------------------------------------
    # YouTube 영상에서 클립 추출
    # ------------------------------------------------------------------
    def extract_clip_from_url(
        self,
        url: str,
        start_time: float = 0,
        duration: float = 10,
    ) -> Optional[str]:
        """
        YouTube URL에서 특정 구간 클립 추출.

        Args:
            url: YouTube 영상 URL
            start_time: 시작 시간 (초)
            duration: 클립 길이 (초)

        Returns:
            추출된 클립 파일 경로
        """
        job_id = uuid.uuid4().hex[:8]
        dl_dir = self.output_dir / f"clip_{job_id}"
        os.makedirs(dl_dir, exist_ok=True)

        video_path = str(dl_dir / "source.mp4")
        try:
            cmd = [
                sys.executable, "-m", "yt_dlp",
                "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
                "-o", video_path,
                "--no-playlist",
                "--quiet",
                url,
            ]
            subprocess.run(cmd, timeout=120, check=True, capture_output=True)
        except Exception as e:
            log.error("영상 다운로드 실패: %s", e)
            return None

        if not os.path.exists(video_path):
            for ext in [".mp4", ".webm", ".mkv"]:
                alt = str(dl_dir / f"source{ext}")
                if os.path.exists(alt):
                    video_path = alt
                    break
            else:
                return None

        return self.extract_clip_from_file(video_path, start_time, duration)

    def extract_clip_from_file(
        self,
        video_path: str,
        start_time: float = 0,
        duration: float = 10,
    ) -> Optional[str]:
        """로컬 영상에서 특정 구간 클립 추출."""
        job_id = uuid.uuid4().hex[:8]
        out_path = str(self.output_dir / f"clip_{job_id}.mp4")
        try:
            subprocess.run(
                ["ffmpeg", "-ss", str(start_time), "-i", video_path,
                 "-t", str(duration), "-c:v", "libx264", "-c:a", "aac",
                 "-y", out_path],
                capture_output=True, timeout=60, check=True,
            )
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                log.info("클립 추출 완료: %s (%.1fs ~ %.1fs)",
                        out_path, start_time, start_time + duration)
                return out_path
        except Exception as e:
            log.error("클립 추출 실패: %s", e)
        return None

    # ------------------------------------------------------------------
    # 쿠팡 상품 이미지 스크래핑
    # ------------------------------------------------------------------
    def scrape_coupang_images(
        self,
        product_url: str,
        max_images: int = 5,
    ) -> list[str]:
        """
        쿠팡 상품 페이지에서 실제 상품 이미지 다운로드.

        Args:
            product_url: 쿠팡 상품 URL
            max_images: 최대 다운로드 이미지 수

        Returns:
            다운로드된 이미지 파일 경로 리스트
        """
        import urllib.request
        import re

        job_id = uuid.uuid4().hex[:8]
        img_dir = self.output_dir / f"coupang_{job_id}"
        os.makedirs(img_dir, exist_ok=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

        try:
            req = urllib.request.Request(product_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            log.error("쿠팡 페이지 로드 실패: %s", e)
            return []

        # 상품 이미지 URL 추출 (쿠팡 CDN 패턴)
        img_urls = []
        # 메인 상품 이미지 (og:image)
        og_match = re.search(r'property="og:image"\s+content="([^"]+)"', html)
        if og_match:
            img_urls.append(og_match.group(1))

        # 상품 상세 이미지 (CDN 패턴)
        cdn_patterns = [
            r'(https?://thumbnail\d*\.coupangcdn\.com/thumbnails/remote/\d+x\d+[^"\'>\s]+)',
            r'(https?://image\d*\.coupangcdn\.com/image/[^"\'>\s]+)',
            r'data-img-src="([^"]+)"',
            r'src="(https?://[^"]*coupangcdn\.com[^"]*\.(?:jpg|jpeg|png|webp))"',
        ]
        for pattern in cdn_patterns:
            matches = re.findall(pattern, html)
            for m in matches:
                url = m if not m.startswith("//") else f"https:{m}"
                if url not in img_urls and "icon" not in url.lower():
                    img_urls.append(url)

        if not img_urls:
            log.warning("쿠팡 이미지를 찾을 수 없음: %s", product_url)
            return []

        # 이미지 다운로드
        saved = []
        for i, img_url in enumerate(img_urls[:max_images]):
            out_path = str(img_dir / f"product_{i:02d}.jpg")
            try:
                req = urllib.request.Request(img_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                if len(data) < 3000:
                    continue
                Image.open(__import__("io").BytesIO(data)).convert("RGB").save(
                    out_path, quality=95
                )
                if os.path.exists(out_path):
                    saved.append(out_path)
            except Exception as e:
                log.warning("이미지 다운로드 실패 [%d]: %s", i, e)

        log.info("쿠팡 이미지 스크래핑 완료: %d/%d (%s)",
                len(saved), len(img_urls[:max_images]), product_url)
        return saved

    # ------------------------------------------------------------------
    # 웹 이미지 다운로드 (범용)
    # ------------------------------------------------------------------
    def download_image(self, url: str, filename: Optional[str] = None) -> Optional[str]:
        """URL에서 이미지 다운로드."""
        import urllib.request, io
        fname = filename or f"img_{uuid.uuid4().hex[:8]}.jpg"
        out_path = str(self.output_dir / fname)
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            if len(data) < 2000:
                return None
            Image.open(io.BytesIO(data)).convert("RGB").save(
                out_path, quality=95
            )
            return out_path
        except Exception as e:
            log.warning("이미지 다운로드 실패: %s", e)
            return None

    # ------------------------------------------------------------------
    # Google 이미지 검색 → 이미지 추출
    # ------------------------------------------------------------------
    def search_google_images(
        self,
        query: str,
        count: int = 5,
    ) -> list[str]:
        """
        Google 이미지 검색으로 고화질 이미지 다운로드.

        Args:
            query: 검색어 (예: "교촌치킨 메뉴", "BBQ 매장")
            count: 다운로드할 이미지 수

        Returns:
            다운로드된 이미지 파일 경로 리스트
        """
        import urllib.request, urllib.parse, re, io

        job_id = uuid.uuid4().hex[:8]
        img_dir = self.output_dir / f"google_{job_id}"
        os.makedirs(img_dir, exist_ok=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        }

        # Google 이미지 검색 (isch)
        search_url = (
            "https://www.google.com/search?q="
            + urllib.parse.quote(query)
            + "&tbm=isch&ijn=0"
        )

        try:
            req = urllib.request.Request(search_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            log.error("Google 이미지 검색 실패: %s", e)
            return []

        # 이미지 URL 추출 (실제 이미지 URL 패턴)
        img_urls = []
        # 패턴 1: data 속성의 실제 이미지 URL
        patterns = [
            r'\["(https?://[^"]+\.(?:jpg|jpeg|png|webp))",\d+,\d+\]',
            r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp))"',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html)
            for m in matches:
                if ("gstatic" not in m and "google" not in m
                        and "favicon" not in m and len(m) > 30
                        and m not in img_urls):
                    img_urls.append(m)
            if len(img_urls) >= count * 3:
                break

        # 중복 제거 후 다운로드
        saved = []
        for i, img_url in enumerate(img_urls):
            if len(saved) >= count:
                break
            out_path = str(img_dir / f"img_{i:03d}.jpg")
            try:
                req = urllib.request.Request(img_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                if len(data) < 5000:  # 너무 작은 이미지 스킵
                    continue
                img = Image.open(io.BytesIO(data)).convert("RGB")
                # 최소 해상도 필터 (300x300 이상만)
                if img.size[0] < 300 or img.size[1] < 300:
                    continue
                img.save(out_path, quality=95)
                saved.append(out_path)
            except Exception:
                continue

        log.info("Google 이미지 검색 완료: '%s' → %d장 다운로드", query, len(saved))
        return saved

    # ------------------------------------------------------------------
    # 브라우저 캡처 이미지 수집 (쿠팡 등 봇 차단 사이트용)
    # ------------------------------------------------------------------
    def capture_browser_images(
        self,
        image_urls: list[str],
        product_name: str = "product",
        max_images: int = 8,
    ) -> list[str]:
        """
        브라우저 DOM에서 추출한 이미지 URL 리스트를 다운로드.
        Claude가 Chrome에서 JS로 추출한 URL을 전달받아 처리.

        Args:
            image_urls: Chrome DOM에서 추출한 이미지 URL 리스트
            product_name: 제품명 (폴더명용)
            max_images: 최대 다운로드 수

        Returns:
            다운로드된 이미지 파일 경로 리스트
        """
        import urllib.request, io

        safe_name = "".join(c for c in product_name[:20] if c.isalnum() or c in "_ -")
        job_id = uuid.uuid4().hex[:6]
        img_dir = self.output_dir / f"browser_{safe_name}_{job_id}"
        os.makedirs(img_dir, exist_ok=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://www.coupang.com/",
        }

        saved = []
        seen_sizes = set()  # 중복 이미지 필터링 (파일 크기 기반)

        for i, url in enumerate(image_urls[:max_images * 2]):
            if len(saved) >= max_images:
                break
            out_path = str(img_dir / f"cap_{i:03d}.jpg")
            try:
                # URL 정규화
                if url.startswith("//"):
                    url = "https:" + url
                if not url.startswith("http"):
                    continue

                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()

                # 너무 작은 이미지(아이콘 등) 스킵
                if len(data) < 5000:
                    continue

                # 중복 이미지 스킵 (파일 크기 기반)
                size_key = len(data)
                if size_key in seen_sizes:
                    continue
                seen_sizes.add(size_key)

                img = Image.open(io.BytesIO(data)).convert("RGB")
                # 최소 해상도 필터 (200x200 이상)
                if img.size[0] < 200 or img.size[1] < 200:
                    continue

                # 고해상도 저장 (PNG 무손실)
                png_path = out_path.replace(".jpg", ".png")
                img.save(png_path)
                saved.append(png_path)
                log.info("브라우저 이미지 캡처 [%d]: %dx%d (%s)",
                        len(saved), img.size[0], img.size[1], os.path.basename(png_path))
            except Exception as e:
                log.warning("브라우저 이미지 다운로드 실패 [%d]: %s", i, e)

        log.info("브라우저 캡처 완료: %d장 (%s)", len(saved), product_name)
        return saved

    def register_local_images(
        self,
        image_paths: list[str],
        product_name: str = "product",
    ) -> list[str]:
        """
        이미 로컬에 저장된 이미지 파일들을 작업 디렉토리로 복사 등록.
        스크린샷으로 캡처한 이미지나 수동 저장 이미지를 파이프라인에 연결.

        Args:
            image_paths: 이미지 파일 경로 리스트
            product_name: 제품명 (폴더명용)

        Returns:
            등록된 이미지 파일 경로 리스트
        """
        import shutil

        safe_name = "".join(c for c in product_name[:20] if c.isalnum() or c in "_ -")
        job_id = uuid.uuid4().hex[:6]
        img_dir = self.output_dir / f"local_{safe_name}_{job_id}"
        os.makedirs(img_dir, exist_ok=True)

        registered = []
        for i, src in enumerate(image_paths):
            if not os.path.exists(src):
                continue
            try:
                ext = os.path.splitext(src)[1] or ".png"
                dst = str(img_dir / f"img_{i:03d}{ext}")
                shutil.copy2(src, dst)
                registered.append(dst)
            except Exception as e:
                log.warning("이미지 등록 실패 [%d]: %s", i, e)

        log.info("로컬 이미지 등록 완료: %d장 (%s)", len(registered), product_name)
        return registered

    # ------------------------------------------------------------------
    # 쿠팡 상품 이미지 수집 (브라우저 우선 통합)
    # ------------------------------------------------------------------
    def get_coupang_images(
        self,
        product_url: str = "",
        browser_image_urls: list[str] | None = None,
        local_images: list[str] | None = None,
        product_name: str = "coupang_product",
        max_images: int = 8,
    ) -> list[str]:
        """
        쿠팡 상품 이미지 통합 수집 (우선순위: 브라우저캡처 > 로컬 > HTTP스크래핑).

        쿠팡은 봇 차단이 강력해서 HTTP 스크래핑이 실패할 확률이 높음.
        반드시 브라우저 캡처(Chrome DOM 추출)를 우선 사용.

        Args:
            product_url: 쿠팡 상품 URL (HTTP 스크래핑용 폴백)
            browser_image_urls: Chrome DOM에서 추출한 이미지 URL 리스트 (최우선)
            local_images: 이미 저장된 이미지 파일 경로 리스트
            product_name: 제품명
            max_images: 최대 이미지 수

        Returns:
            수집된 이미지 파일 경로 리스트
        """
        images: list[str] = []

        # 1순위: 브라우저에서 추출한 URL로 다운로드
        if browser_image_urls:
            log.info("쿠팡 이미지 수집: 브라우저 캡처 모드 (%d URLs)", len(browser_image_urls))
            images = self.capture_browser_images(
                browser_image_urls, product_name, max_images
            )
            if images:
                return images

        # 2순위: 로컬에 이미 저장된 이미지
        if local_images:
            log.info("쿠팡 이미지 수집: 로컬 이미지 등록 모드 (%d files)", len(local_images))
            images = self.register_local_images(local_images, product_name)
            if images:
                return images

        # 3순위: HTTP 스크래핑 (쿠팡 403 가능성 높음)
        if product_url:
            log.info("쿠팡 이미지 수집: HTTP 스크래핑 시도 (폴백) — 403 에러 가능")
            images = self.scrape_coupang_images(product_url, max_images)
            if images:
                return images

        log.warning("쿠팡 이미지 수집 실패! 브라우저에서 쿠팡 페이지를 열고 캡처해주세요.")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# CLI 진입점 (테스트용)
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VideoForge CLI")
    sub = parser.add_subparsers(dest="command")

    # render 명령
    render_p = sub.add_parser("render", help="Shorts 렌더링")
    render_p.add_argument("--images", nargs="+", required=True, help="이미지 파일 경로들")
    render_p.add_argument("--narrations", nargs="+", default=[], help="나레이션 텍스트들")
    render_p.add_argument("--output", default=str(RENDER_OUTPUT_DIR / "output.mp4"))
    render_p.add_argument("--subtitle", default="", help="자막 텍스트 (줄바꿈 구분)")
    render_p.add_argument("--effect", default="dynamic", choices=list(EFFECT_PRESETS.keys()))
    render_p.add_argument("--voice", default="ko-female", choices=list(TTS_VOICES.keys()))

    # wash 명령
    wash_p = sub.add_parser("wash", help="영상 세탁")
    wash_p.add_argument("input", help="입력 영상 경로")
    wash_p.add_argument("--output", default=str(RENDER_OUTPUT_DIR / "washed.mp4"))

    # download 명령
    dl_p = sub.add_parser("download", help="다운로드 + 세탁")
    dl_p.add_argument("url", help="영상 URL")
    dl_p.add_argument("--output", default=str(RENDER_OUTPUT_DIR / "downloaded_washed.mp4"))

    # bgm 명령
    bgm_p = sub.add_parser("bgm", help="BGM 생성 테스트")
    bgm_p.add_argument("--output", default=str(WORK_DIR / "test_bgm.wav"))
    bgm_p.add_argument("--duration", type=float, default=30.0)

    # tts 명령
    tts_p = sub.add_parser("tts", help="TTS 생성 테스트")
    tts_p.add_argument("text", help="변환할 텍스트")
    tts_p.add_argument("--output", default=str(WORK_DIR / "test_tts.mp3"))
    tts_p.add_argument("--voice", default="ko-female", choices=list(TTS_VOICES.keys()))

    args = parser.parse_args()

    if args.command == "render":
        cfg = RenderConfig(effect_mode=args.effect, tts_voice=args.voice)
        forge = VideoForge(cfg)
        result = forge.render_shorts(
            args.images, args.narrations, args.output, args.subtitle,
        )
        print(f"렌더 완료: {result}")
        print(f"MD5: {file_md5(result)}")

    elif args.command == "wash":
        forge = VideoForge()
        result = forge.wash_video(args.input, args.output)
        print(f"세탁 완료: {result}")
        print(f"MD5: {file_md5(result)}")

    elif args.command == "download":
        forge = VideoForge()
        result = forge.download_and_wash(args.url, args.output)
        print(f"다운로드+세탁 완료: {result}")
        print(f"MD5: {file_md5(result)}")

    elif args.command == "bgm":
        VideoForge.generate_bgm(args.output, args.duration)
        print(f"BGM 생성 완료: {args.output}")

    elif args.command == "tts":
        ok = VideoForge.generate_tts(args.text, args.output, args.voice)
        print(f"TTS {'성공' if ok else '실패'}: {args.output}")

    else:
        parser.print_help()
