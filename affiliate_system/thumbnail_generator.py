# -*- coding: utf-8 -*-
"""
AI 썸네일 자동 생성기
====================
플랫폼별 최적 썸네일을 자동 생성한다.
- YouTube Shorts: 1080x1920 세로형 + 임팩트 텍스트
- Instagram Reels: 1080x1920 세로형 + 감성 디자인
- Naver Blog: 900x600 가로형 + 정보 중심

Pillow 기반 고품질 렌더링, 그라디언트 오버레이, 텍스트 그림자 등 적용.
"""

from __future__ import annotations

import math
import os
import random
import sys
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from affiliate_system.config import WORK_DIR, RENDER_OUTPUT_DIR
from affiliate_system.models import (
    Platform, PlatformPreset, PLATFORM_PRESETS,
    BrandingConfig, BRAND_BRANDING,
)
from affiliate_system.utils import setup_logger, ensure_dir

__all__ = ["ThumbnailGenerator"]

log = setup_logger("thumbnail_gen", "thumbnail_gen.log")


# ── 한글 폰트 탐색 ──

def _find_font(bold: bool = True) -> Optional[str]:
    """시스템에서 사용 가능한 한글 폰트를 찾는다."""
    if sys.platform == "win32":
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates = (
            ["malgunbd.ttf", "NanumGothicBold.ttf", "malgun.ttf"]
            if bold else
            ["malgun.ttf", "NanumGothic.ttf", "malgunbd.ttf"]
        )
        for name in candidates:
            if (fonts_dir / name).exists():
                return str(fonts_dir / name)
    elif sys.platform == "darwin":
        for p in ["/System/Library/Fonts/AppleSDGothicNeo.ttc"]:
            if Path(p).exists():
                return p
    else:
        for p in [
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        ]:
            if Path(p).exists():
                return p
    return None


_FONT_BOLD = _find_font(bold=True)
_FONT_REGULAR = _find_font(bold=False)


# ── 색상 팔레트 ──

THUMB_PALETTES = {
    "dark": {
        "bg": "#1a1a2e",
        "gradient_start": (26, 26, 46, 200),
        "gradient_end": (0, 0, 0, 230),
        "text": "#ffffff",
        "accent": "#e94560",
        "subtitle": "#cccccc",
    },
    "warm": {
        "bg": "#2d1b0e",
        "gradient_start": (45, 27, 14, 180),
        "gradient_end": (20, 10, 0, 220),
        "text": "#ffffff",
        "accent": "#ff9f43",
        "subtitle": "#f0d9b5",
    },
    "cool": {
        "bg": "#0f3460",
        "gradient_start": (15, 52, 96, 180),
        "gradient_end": (0, 0, 30, 220),
        "text": "#ffffff",
        "accent": "#00d2ff",
        "subtitle": "#a0d2f0",
    },
    "vibrant": {
        "bg": "#1a0030",
        "gradient_start": (26, 0, 48, 190),
        "gradient_end": (0, 0, 0, 230),
        "text": "#ffffff",
        "accent": "#ff006e",
        "subtitle": "#e0b0ff",
    },
    "nature": {
        "bg": "#0d2818",
        "gradient_start": (13, 40, 24, 180),
        "gradient_end": (0, 0, 0, 220),
        "text": "#ffffff",
        "accent": "#2ecc71",
        "subtitle": "#b0e0c0",
    },
}


class ThumbnailGenerator:
    """플랫폼별 AI 썸네일 자동 생성기.

    배경 이미지 + 그라디언트 오버레이 + 임팩트 텍스트 조합으로
    고품질 썸네일을 생성한다.
    """

    def __init__(self):
        self._output_dir = ensure_dir(RENDER_OUTPUT_DIR / "thumbnails")
        log.info("ThumbnailGenerator 초기화 (출력: %s)", self._output_dir)

    def generate(
        self,
        platform: Platform,
        title: str,
        subtitle: str = "",
        background_image: str = "",
        brand: str = "",
        palette_name: str = "",
        output_path: str = "",
    ) -> str:
        """플랫폼에 맞는 썸네일을 생성한다.

        Args:
            platform: 대상 플랫폼
            title: 메인 텍스트 (큰 글씨)
            subtitle: 서브 텍스트 (작은 글씨)
            background_image: 배경 이미지 경로 (없으면 그라디언트 배경)
            brand: 브랜드명 (브랜딩 적용)
            palette_name: 색상 팔레트 이름
            output_path: 출력 파일 경로

        Returns:
            생성된 썸네일 파일 경로
        """
        preset = PLATFORM_PRESETS.get(platform)
        if not preset:
            raise ValueError(f"지원하지 않는 플랫폼: {platform}")

        w, h = preset.thumb_width, preset.thumb_height

        # 팔레트 결정
        if not palette_name:
            palette_name = random.choice(list(THUMB_PALETTES.keys()))
        palette = THUMB_PALETTES.get(palette_name, THUMB_PALETTES["dark"])

        log.info(
            "썸네일 생성 시작: %s, %dx%d, palette=%s",
            platform.value, w, h, palette_name,
        )

        # ── 배경 레이어 ──
        if background_image and os.path.exists(background_image):
            bg = self._load_and_fit(background_image, w, h)
            # 살짝 블러 + 밝기 저하 (텍스트 가독성)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=2))
            bg = ImageEnhance.Brightness(bg).enhance(0.6)
        else:
            bg = self._create_gradient_bg(w, h, palette)

        # RGBA 변환
        img = bg.convert("RGBA")

        # ── 그라디언트 오버레이 (하단) ──
        overlay = self._create_bottom_gradient(
            w, h,
            palette["gradient_start"],
            palette["gradient_end"],
        )
        img = Image.alpha_composite(img, overlay)

        # ── 악센트 라인 (상단) ──
        accent_color = palette["accent"]
        draw = ImageDraw.Draw(img)
        accent_rgb = self._hex_to_rgb(accent_color)
        if platform == Platform.NAVER_BLOG:
            # 블로그: 상단 가로 바
            draw.rectangle([(0, 0), (w, 6)], fill=(*accent_rgb, 255))
        else:
            # Shorts/Reels: 좌측 세로 바
            bar_w = 8
            draw.rectangle([(30, h // 3), (30 + bar_w, h * 2 // 3)],
                           fill=(*accent_rgb, 255))

        # ── 메인 텍스트 ──
        self._draw_impact_text(
            img, title,
            position="center" if platform != Platform.NAVER_BLOG else "left_center",
            max_width=int(w * 0.85),
            fontsize=self._calc_fontsize(title, w, h, platform),
            color=palette["text"],
            stroke_color="#000000",
            stroke_width=4,
        )

        # ── 서브 텍스트 ──
        if subtitle:
            sub_fontsize = max(24, self._calc_fontsize(title, w, h, platform) // 2)
            self._draw_subtitle(
                img, subtitle,
                fontsize=sub_fontsize,
                color=palette["subtitle"],
                y_offset=0.65 if platform != Platform.NAVER_BLOG else 0.6,
            )

        # ── 브랜드 워터마크 ──
        branding = BRAND_BRANDING.get(brand)
        if branding and branding.watermark_text:
            self._draw_watermark(
                img, branding.watermark_text,
                opacity=branding.watermark_opacity,
            )

        # ── 저장 ──
        if not output_path:
            filename = f"thumb_{platform.value}_{random.randint(1000, 9999)}.jpg"
            output_path = str(self._output_dir / filename)

        # RGB 변환 후 JPEG 저장
        final = img.convert("RGB")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        final.save(output_path, "JPEG", quality=95)

        size_kb = os.path.getsize(output_path) / 1024
        log.info("썸네일 생성 완료: %s (%.1f KB)", output_path, size_kb)
        return output_path

    def generate_all_platforms(
        self,
        title: str,
        subtitle: str = "",
        background_image: str = "",
        brand: str = "",
        palette_name: str = "",
    ) -> dict[str, str]:
        """모든 플랫폼용 썸네일을 한 번에 생성한다.

        Returns:
            {"youtube": "/path/to/thumb.jpg", "instagram": "...", "naver_blog": "..."}
        """
        results: dict[str, str] = {}
        for platform in [Platform.YOUTUBE, Platform.INSTAGRAM, Platform.NAVER_BLOG]:
            try:
                path = self.generate(
                    platform=platform,
                    title=title,
                    subtitle=subtitle,
                    background_image=background_image,
                    brand=brand,
                    palette_name=palette_name,
                )
                results[platform.value] = path
            except Exception as e:
                log.error("썸네일 생성 실패 (%s): %s", platform.value, e)
        return results

    # ──────────────────────────────────────────────
    # 내부 헬퍼
    # ──────────────────────────────────────────────

    @staticmethod
    def _load_and_fit(image_path: str, w: int, h: int) -> Image.Image:
        """이미지를 w x h에 맞게 center-crop 후 리사이즈."""
        img = Image.open(image_path).convert("RGB")
        iw, ih = img.size
        target_ratio = w / h
        current_ratio = iw / ih
        if current_ratio > target_ratio:
            nw = int(ih * target_ratio)
            left = (iw - nw) // 2
            img = img.crop((left, 0, left + nw, ih))
        else:
            nh = int(iw / target_ratio)
            top = (ih - nh) // 2
            img = img.crop((0, top, iw, top + nh))
        return img.resize((w, h), Image.LANCZOS)

    @staticmethod
    def _create_gradient_bg(w: int, h: int, palette: dict) -> Image.Image:
        """그라디언트 배경 생성."""
        bg_hex = palette["bg"]
        r, g, b = int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16)
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        for y in range(h):
            ratio = y / h
            cr = int(r * (1 - ratio * 0.5))
            cg = int(g * (1 - ratio * 0.3))
            cb = int(b * (1 + ratio * 0.3))
            draw.line([(0, y), (w, y)], fill=(
                max(0, min(255, cr)),
                max(0, min(255, cg)),
                max(0, min(255, cb)),
            ))
        return img

    @staticmethod
    def _create_bottom_gradient(
        w: int, h: int,
        start_rgba: tuple, end_rgba: tuple,
    ) -> Image.Image:
        """하단 그라디언트 오버레이 (RGBA)."""
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        gradient_start = h // 3  # 상단 1/3부터 그라디언트 시작
        for y in range(gradient_start, h):
            ratio = (y - gradient_start) / (h - gradient_start)
            r = int(start_rgba[0] + (end_rgba[0] - start_rgba[0]) * ratio)
            g = int(start_rgba[1] + (end_rgba[1] - start_rgba[1]) * ratio)
            b = int(start_rgba[2] + (end_rgba[2] - start_rgba[2]) * ratio)
            a = int(start_rgba[3] + (end_rgba[3] - start_rgba[3]) * ratio)
            draw.line([(0, y), (w, y)], fill=(r, g, b, a))
        return overlay

    def _draw_impact_text(
        self,
        img: Image.Image,
        text: str,
        position: str = "center",
        max_width: int = 900,
        fontsize: int = 80,
        color: str = "#ffffff",
        stroke_color: str = "#000000",
        stroke_width: int = 4,
    ):
        """임팩트 있는 메인 텍스트를 렌더링한다."""
        draw = ImageDraw.Draw(img)
        font = self._get_font(fontsize, bold=True)
        w, h = img.size

        # 줄바꿈 계산
        lines = self._wrap_text(draw, text, font, max_width)
        full_text = "\n".join(lines)

        # 텍스트 크기 계산
        bbox = draw.multiline_textbbox((0, 0), full_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        # 위치 결정
        if position == "center":
            x = (w - tw) // 2
            y = (h - th) // 2 + h // 10  # 약간 아래로
        elif position == "left_center":
            x = w // 10
            y = (h - th) // 2
        else:
            x = (w - tw) // 2
            y = h * 2 // 3 - th // 2

        text_color = self._hex_to_rgb(color)

        # 그림자 (더 큰 오프셋)
        shadow_offset = max(3, stroke_width)
        draw.multiline_text(
            (x + shadow_offset, y + shadow_offset),
            full_text,
            font=font,
            fill=(0, 0, 0, 180),
            align="center" if position == "center" else "left",
        )

        # 외곽선
        stroke_rgb = self._hex_to_rgb(stroke_color)
        s = stroke_width
        for dx, dy in [(-s, 0), (s, 0), (0, -s), (0, s),
                        (-s, -s), (s, -s), (-s, s), (s, s)]:
            draw.multiline_text(
                (x + dx, y + dy), full_text,
                font=font, fill=stroke_rgb,
                align="center" if position == "center" else "left",
            )

        # 본문
        draw.multiline_text(
            (x, y), full_text,
            font=font,
            fill=(*text_color, 255) if len(text_color) == 3 else text_color,
            align="center" if position == "center" else "left",
        )

    def _draw_subtitle(
        self,
        img: Image.Image,
        text: str,
        fontsize: int = 36,
        color: str = "#cccccc",
        y_offset: float = 0.65,
    ):
        """서브 텍스트를 렌더링한다."""
        draw = ImageDraw.Draw(img)
        font = self._get_font(fontsize, bold=False)
        w, h = img.size

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2
        y = int(h * y_offset)

        text_color = self._hex_to_rgb(color)

        # 그림자
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 150))
        # 본문
        draw.text((x, y), text, font=font, fill=text_color)

    def _draw_watermark(
        self,
        img: Image.Image,
        text: str,
        fontsize: int = 28,
        opacity: float = 0.3,
    ):
        """워터마크를 우측 하단에 렌더링한다."""
        w, h = img.size
        wm = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(wm)
        font = self._get_font(fontsize, bold=False)

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = w - tw - 20
        y = h - th - 20

        alpha = int(255 * opacity)
        draw.text((x, y), text, font=font, fill=(255, 255, 255, alpha))

        img.paste(Image.alpha_composite(
            img.convert("RGBA"), wm
        ).convert("RGBA"), (0, 0))

    @staticmethod
    def _get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
        """폰트를 가져온다."""
        font_path = _FONT_BOLD if bold else (_FONT_REGULAR or _FONT_BOLD)
        if font_path:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    @staticmethod
    def _wrap_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
    ) -> list[str]:
        """텍스트를 max_width에 맞게 줄바꿈한다."""
        lines: list[str] = []
        for original_line in text.split("\n"):
            current = ""
            for ch in original_line:
                test = current + ch
                bbox = draw.textbbox((0, 0), test, font=font)
                if bbox[2] - bbox[0] > max_width and current:
                    lines.append(current)
                    current = ch
                else:
                    current = test
            if current:
                lines.append(current)
        return lines or [""]

    @staticmethod
    def _calc_fontsize(
        text: str, w: int, h: int, platform: Platform,
    ) -> int:
        """텍스트 길이와 플랫폼에 따른 최적 폰트 크기를 계산한다."""
        # 기본 크기
        if platform == Platform.NAVER_BLOG:
            base = 52  # 블로그는 가로형이라 작게
        else:
            base = 80  # Shorts/Reels는 세로형이라 크게

        # 텍스트 길이에 따른 보정
        char_count = len(text)
        if char_count > 30:
            base = int(base * 0.7)
        elif char_count > 20:
            base = int(base * 0.8)
        elif char_count > 10:
            base = int(base * 0.9)

        return max(28, min(base, 120))

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple:
        """Hex 색상을 RGB 튜플로 변환."""
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
