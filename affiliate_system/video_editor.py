"""
Affiliate Marketing System -- Video Rendering & Anti-Ban Pipeline
=================================================================
MoviePy 기반 숏폼 영상 렌더링, 안티밴 변조, 기존 영상 세탁 기능.
MoviePy v1 / v2 양쪽 API 를 자동 감지하여 호환 동작.
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
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

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
from affiliate_system.models import RenderConfig, Campaign
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
# 한글 폰트 탐색
# ---------------------------------------------------------------------------

def _find_korean_font() -> Optional[str]:
    """시스템에서 사용 가능한 한글 폰트를 찾아 반환한다."""
    if sys.platform == "win32":
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ["malgunbd.ttf", "malgun.ttf", "NanumGothicBold.ttf", "NanumGothic.ttf"]:
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


KOREAN_FONT: Optional[str] = _find_korean_font()


# ═══════════════════════════════════════════════════════════════════════════
# 유틸리티 함수
# ═══════════════════════════════════════════════════════════════════════════

def ease_io(t: float) -> float:
    """Smooth ease-in-out (Hermite interpolation)."""
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - math.pow(-2.0 * t + 2.0, 2) / 2.0


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
) -> np.ndarray:
    """자막 텍스트를 RGBA numpy 배열로 렌더링."""
    pad = 50
    try:
        font = ImageFont.truetype(KOREAN_FONT, fontsize) if KOREAN_FONT else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # 줄바꿈 계산
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

    full = "\n".join(lines)
    bb = draw.multiline_textbbox((0, 0), full, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    canvas_w, canvas_h = width, th + 50

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if bg_enabled:
        draw.rounded_rectangle(
            [(pad // 2, 5), (canvas_w - pad // 2, canvas_h - 5)],
            radius=16,
            fill=(0, 0, 0, 160),
        )

    x, y = (canvas_w - tw) // 2, 25
    s = stroke_width

    # 그림자
    draw.multiline_text((x + 2, y + 2), full, font=font, fill=(0, 0, 0, 120), align="center")
    # 외곽선
    for dx, dy in [(-s, 0), (s, 0), (0, -s), (0, s), (-s, -s), (s, -s), (-s, s), (s, s)]:
        draw.multiline_text((x + dx, y + dy), full, font=font, fill=stroke_color, align="center")
    # 본문
    draw.multiline_text((x, y), full, font=font, fill=text_color, align="center")

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
                clip = self.apply_motion_effect(clip, effect_name, zoom_ratio=1.2)

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

        # ── 자막 오버레이 ──
        if cfg.subtitle_enabled and subtitle_text:
            log.info("자막 오버레이 렌더링")
            sub_lines = [t.strip() for t in subtitle_text.split("\n") if t.strip()]
            sub_layers = [final]
            current_time = 0.0

            for i in range(min(len(clips), len(sub_lines))):
                clip_dur = clips[i].duration if i < len(clips) else default_duration
                try:
                    sub_arr = _render_subtitle_image(
                        sub_lines[i], w, fontsize=cfg.subtitle_fontsize,
                    )
                    sub_h = sub_arr.shape[0]
                    sub_dur = max(clip_dur - 0.8, 0.5)

                    if MOVIEPY_V2:
                        sub_clip = (
                            ImageClip(sub_arr, duration=sub_dur, is_mask=False)
                            .with_start(current_time + 0.3)
                            .with_position(("center", h - sub_h - 140))
                            .crossfadein(0.2)
                        )
                    else:
                        sub_clip = (
                            ImageClip(sub_arr, ismask=False)
                            .set_duration(sub_dur)
                            .set_start(current_time + 0.3)
                            .set_position(("center", h - sub_h - 140))
                            .crossfadein(0.2)
                        )
                    sub_layers.append(sub_clip)
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

        # BGM 레이어
        try:
            bgm_path = str(WORK_DIR / f"_bgm_{uuid.uuid4().hex[:6]}.wav")
            self.generate_bgm(bgm_path, final.duration)
            bgm = AudioFileClip(bgm_path)
            self._tmp_audio.append(bgm)
            self._tmp_files.append(bgm_path)

            # TTS 가 있으면 BGM 볼륨을 낮춤
            bgm_vol = 0.08 if tts_paths else 0.25
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

        # ── 안티밴 적용 ──
        final = self.apply_anti_ban(final)

        # ── 인코딩 ──
        log.info("인코딩 시작: %s", output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        final.write_videofile(
            output_path,
            fps=cfg.fps,
            codec="libx264",
            bitrate="10M",
            audio_codec="aac",
            audio_bitrate="192k",
            threads=4,
            preset="medium",
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

        try:
            # 이미 실행 중인 이벤트 루프가 있을 수 있으므로 안전하게 처리
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(
                        asyncio.run,
                        edge_tts.Communicate(text, voice_id, rate=rate).save(output_path),
                    ).result(timeout=30)
            except RuntimeError:
                asyncio.run(
                    edge_tts.Communicate(text, voice_id, rate=rate).save(output_path)
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
