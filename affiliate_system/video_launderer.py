"""
Video Launderer V2 — FFmpeg GPU 기반 영상 세탁 + 숏폼 렌더링
=============================================================
MoviePy 사용 금지. 모든 영상 처리는 FFmpeg 하드웨어 가속(GPU)으로 직접 호출.
자막은 Whisper word_timestamps로 0.1초 오차 없이 단어 단위 동기화.

4단계 세탁 파이프라인:
  1. Crop: 상하좌우 3-6% 크롭 → 원본 해상도 스케일업
  2. Audio Delete: 원본 오디오 100% 음소거
  3. Speed: 1.1x~1.2x 랜덤 배속
  4. Quality Filter: 샤프닝 + 색보정 → "8K 업스케일링 느낌"
"""
import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from affiliate_system.config import (
    LAUNDER_CROP_PCT_MIN, LAUNDER_CROP_PCT_MAX,
    LAUNDER_SPEED_MIN, LAUNDER_SPEED_MAX,
    LAUNDER_SHARPEN_AMOUNT, LAUNDER_CONTRAST_BOOST,
    LAUNDER_VIBRANCE_BOOST, LAUNDER_BRIGHTNESS_BOOST,
    FFMPEG_HWACCEL, FFMPEG_ENCODER, FFMPEG_ENCODER_FALLBACK,
    FFMPEG_CRF, FFMPEG_PRESET,
    WHISPER_MODEL_SIZE, WHISPER_LANGUAGE, WHISPER_DEVICE,
    TTS_EMOTION_PRESETS,
    SHORTS_RESOLUTION, SHORTS_FPS, SHORTS_MAX_DURATION,
    V2_LAUNDERED_DIR, V2_TTS_DIR, V2_SUBTITLE_DIR,
    V2_SHORTS_DIR, V2_SFX_DIR,
    IS_WINDOWS,
)

logger = logging.getLogger("video_launderer")


# ═══════════════════════════════════════════════════════════════════════════
# FFmpeg 유틸리티 함수
# ═══════════════════════════════════════════════════════════════════════════

def _run_ffmpeg(args: list[str], desc: str = "", timeout: int = 600) -> bool:
    """FFmpeg 명령 실행 (에러 핸들링 + 로깅).

    Args:
        args: FFmpeg 인자 리스트 (ffmpeg 제외)
        desc: 작업 설명 (로그용)
        timeout: 타임아웃 (초)

    Returns:
        성공 여부
    """
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    logger.info(f"[FFmpeg] {desc}: {' '.join(cmd[:15])}...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            logger.warning(f"[FFmpeg] {desc} stderr: {result.stderr[:500]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"[FFmpeg] {desc} 타임아웃 ({timeout}초)")
        return False
    except FileNotFoundError:
        logger.error("[FFmpeg] ffmpeg 바이너리를 찾을 수 없습니다!")
        return False
    except Exception as e:
        logger.error(f"[FFmpeg] {desc} 예외: {e}")
        return False


def _run_ffprobe(input_path: str) -> dict:
    """FFprobe로 영상 메타데이터 추출.

    Returns:
        {"width": int, "height": int, "duration": float, "fps": float,
         "has_audio": bool, "codec": str}
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(input_path)
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            logger.warning(f"ffprobe 실패: {result.stderr[:300]}")
            return {}

        data = json.loads(result.stdout)
        info = {"has_audio": False}

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = int(stream.get("width", 0))
                info["height"] = int(stream.get("height", 0))
                info["codec"] = stream.get("codec_name", "")
                # FPS 계산
                r_fps = stream.get("r_frame_rate", "30/1")
                try:
                    num, den = r_fps.split("/")
                    info["fps"] = round(float(num) / float(den), 2)
                except (ValueError, ZeroDivisionError):
                    info["fps"] = 30.0
            elif stream.get("codec_type") == "audio":
                info["has_audio"] = True

        fmt = data.get("format", {})
        info["duration"] = float(fmt.get("duration", 0))

        return info
    except Exception as e:
        logger.error(f"ffprobe 예외: {e}")
        return {}


def _check_gpu_encoder() -> str:
    """GPU 인코더 사용 가능 여부 확인. 불가시 CPU 폴백."""
    # NVENC 체크
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace'
        )
        if FFMPEG_ENCODER in result.stdout:
            logger.info(f"GPU 인코더 사용: {FFMPEG_ENCODER}")
            return FFMPEG_ENCODER
    except Exception:
        pass

    logger.warning(f"GPU 인코더 {FFMPEG_ENCODER} 불가, CPU 폴백: {FFMPEG_ENCODER_FALLBACK}")
    return FFMPEG_ENCODER_FALLBACK


# 전역 인코더 캐시
_ENCODER = None

def _get_encoder() -> str:
    """캐시된 인코더 반환."""
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = _check_gpu_encoder()
    return _ENCODER


# ═══════════════════════════════════════════════════════════════════════════
# 4단계 영상 세탁 파이프라인
# ═══════════════════════════════════════════════════════════════════════════

class VideoLaunderer:
    """FFmpeg GPU 기반 4단계 영상 세탁 엔진.

    1. Crop: 상하좌우 3-6% → 원본 스케일업
    2. Audio Delete: 100% 음소거
    3. Speed: 1.1x-1.2x 랜덤
    4. Quality: 샤프닝 + 색보정
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """세탁 엔진 초기화."""
        self.output_dir = output_dir or V2_LAUNDERED_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.encoder = _get_encoder()
        self.logger = logger

    def launder_video(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        target_width: int = 1080,
        target_height: int = 1920,
    ) -> Optional[str]:
        """4단계 영상 세탁 풀 파이프라인.

        Args:
            input_path: 원본 영상 경로
            output_path: 출력 경로 (없으면 자동 생성)
            target_width: 최종 가로 해상도
            target_height: 최종 세로 해상도

        Returns:
            세탁 완료된 영상 경로 또는 None (실패 시)
        """
        input_path = str(input_path)
        if not Path(input_path).exists():
            self.logger.error(f"입력 파일 없음: {input_path}")
            return None

        # 출력 경로 설정
        if not output_path:
            stem = Path(input_path).stem
            uid = uuid.uuid4().hex[:6]
            output_path = str(self.output_dir / f"{stem}_laundered_{uid}.mp4")

        # 원본 정보 취득
        info = _run_ffprobe(input_path)
        if not info.get("width"):
            self.logger.error(f"영상 메타데이터 읽기 실패: {input_path}")
            return None

        orig_w = info["width"]
        orig_h = info["height"]
        self.logger.info(
            f"세탁 시작: {Path(input_path).name} "
            f"({orig_w}x{orig_h}, {info.get('duration', 0):.1f}s)"
        )

        # ── 4단계를 하나의 FFmpeg 명령으로 결합 (성능 최적화) ──
        # 파이프라인: 입력 → crop → scale → speed → sharpen+색보정 → 출력

        # Step 1: Crop 비율 랜덤 결정
        crop_pct = random.uniform(LAUNDER_CROP_PCT_MIN, LAUNDER_CROP_PCT_MAX)
        crop_px_w = int(orig_w * crop_pct)
        crop_px_h = int(orig_h * crop_pct)
        crop_w = orig_w - (crop_px_w * 2)
        crop_h = orig_h - (crop_px_h * 2)

        # Step 3: Speed 랜덤 결정
        speed = round(random.uniform(LAUNDER_SPEED_MIN, LAUNDER_SPEED_MAX), 3)

        # 복합 필터 체인 구성
        filters = []

        # Step 1: Crop → Scale up (원본 → 타겟 해상도)
        filters.append(f"crop={crop_w}:{crop_h}:{crop_px_w}:{crop_px_h}")
        filters.append(f"scale={target_width}:{target_height}:flags=lanczos")

        # Step 3: Speed 변경
        filters.append(f"setpts=PTS/{speed}")

        # Step 4: Quality Filter — 샤프닝 + 색보정
        # unsharp: luma_msize_x:luma_msize_y:luma_amount
        sharpen = LAUNDER_SHARPEN_AMOUNT
        filters.append(f"unsharp=5:5:{sharpen}:5:5:0")

        # 색보정: eq 필터 (밝기, 대비, 채도)
        brightness = LAUNDER_BRIGHTNESS_BOOST - 1.0  # eq는 -1.0~1.0 범위
        contrast = LAUNDER_CONTRAST_BOOST
        saturation = LAUNDER_VIBRANCE_BOOST
        filters.append(
            f"eq=brightness={brightness:.3f}"
            f":contrast={contrast:.3f}"
            f":saturation={saturation:.3f}"
        )

        # FPS 고정
        filters.append(f"fps={SHORTS_FPS}")

        vf_chain = ",".join(filters)

        # 인코더별 옵션
        if self.encoder == "h264_nvenc":
            enc_opts = [
                "-c:v", self.encoder,
                "-preset", FFMPEG_PRESET,
                "-rc", "constqp",
                "-qp", FFMPEG_CRF,
                "-b:v", "0",
            ]
            # GPU 하드웨어 가속 입력
            hw_opts = ["-hwaccel", FFMPEG_HWACCEL]
        else:
            enc_opts = [
                "-c:v", self.encoder,
                "-preset", "medium",
                "-crf", FFMPEG_CRF,
            ]
            hw_opts = []

        # 최종 FFmpeg 명령 조립
        args = (
            hw_opts +
            ["-i", input_path] +
            ["-vf", vf_chain] +
            ["-an"] +                    # Step 2: 오디오 100% 삭제
            enc_opts +
            ["-pix_fmt", "yuv420p"] +
            ["-movflags", "+faststart"] +
            [output_path]
        )

        success = _run_ffmpeg(
            args,
            desc=f"4단계 세탁 (crop={crop_pct:.1%}, speed={speed}x)",
            timeout=300
        )

        if success and Path(output_path).exists():
            out_size = Path(output_path).stat().st_size
            self.logger.info(
                f"세탁 완료: {Path(output_path).name} "
                f"({out_size / 1024 / 1024:.1f}MB, speed={speed}x)"
            )
            return output_path
        else:
            # GPU 실패 시 CPU 폴백 재시도
            if self.encoder != FFMPEG_ENCODER_FALLBACK:
                self.logger.warning("GPU 인코딩 실패, CPU 폴백 재시도...")
                self.encoder = FFMPEG_ENCODER_FALLBACK
                return self.launder_video(input_path, output_path,
                                          target_width, target_height)
            self.logger.error(f"세탁 최종 실패: {input_path}")
            return None

    def batch_launder(
        self,
        input_paths: list[str],
        target_width: int = 1080,
        target_height: int = 1920,
        progress_callback=None,
    ) -> list[str]:
        """여러 영상 일괄 세탁.

        Args:
            input_paths: 원본 영상 경로 리스트
            target_width/height: 타겟 해상도
            progress_callback: fn(current, total, path) 콜백

        Returns:
            세탁 완료된 영상 경로 리스트
        """
        results = []
        total = len(input_paths)

        for idx, path in enumerate(input_paths):
            try:
                result = self.launder_video(
                    path, target_width=target_width,
                    target_height=target_height
                )
                if result:
                    results.append(result)
                else:
                    self.logger.warning(f"세탁 건너뜀 ({idx+1}/{total}): {path}")
            except Exception as e:
                self.logger.error(f"세탁 에러 ({idx+1}/{total}): {e}")

            if progress_callback:
                try:
                    progress_callback(idx + 1, total, path)
                except Exception:
                    pass

        self.logger.info(f"일괄 세탁 완료: {len(results)}/{total}개 성공")
        return results


# ═══════════════════════════════════════════════════════════════════════════
# Edge-TTS 감정 연동 + Whisper 자막 싱크
# ═══════════════════════════════════════════════════════════════════════════

class EmotionTTSEngine:
    """Edge-TTS 감정 연동 TTS 엔진 + Whisper 단어 타임스탬프."""

    TTS_VOICE = "ko-KR-SunHiNeural"  # 한국어 여성 (자연스러운 톤)

    def __init__(self, output_dir: Optional[Path] = None):
        """TTS 엔진 초기화."""
        self.output_dir = output_dir or V2_TTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    async def _generate_tts_async(
        self, text: str, output_path: str, emotion: str = "friendly"
    ) -> bool:
        """Edge-TTS SSML로 감정 연동 TTS 생성 (비동기)."""
        try:
            import edge_tts

            # 감정별 SSML prosody 파라미터
            preset = TTS_EMOTION_PRESETS.get(emotion, TTS_EMOTION_PRESETS["friendly"])
            rate = preset["rate"]
            pitch = preset["pitch"]
            volume = preset["volume"]

            # SSML 생성
            ssml = (
                f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xml:lang="ko-KR">'
                f'<voice name="{self.TTS_VOICE}">'
                f'<prosody rate="{rate}" pitch="{pitch}" volume="{volume}">'
                f'{text}'
                f'</prosody></voice></speak>'
            )

            communicate = edge_tts.Communicate(ssml, self.TTS_VOICE)
            await communicate.save(output_path)

            if Path(output_path).exists() and Path(output_path).stat().st_size > 1000:
                return True
            else:
                self.logger.warning(f"TTS 파일 너무 작음: {output_path}")
                return False

        except Exception as e:
            self.logger.error(f"Edge-TTS 생성 실패: {e}")
            return False

    def generate_tts(
        self, text: str, output_path: str, emotion: str = "friendly"
    ) -> bool:
        """Edge-TTS 동기 래퍼."""
        import asyncio

        try:
            # Windows 이벤트 루프 호환
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # 이미 이벤트 루프가 실행 중 → nest_asyncio 또는 새 스레드
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._generate_tts_async(text, output_path, emotion)
                    )
                    return future.result(timeout=60)
            else:
                return asyncio.run(
                    self._generate_tts_async(text, output_path, emotion)
                )
        except Exception as e:
            self.logger.error(f"TTS 동기 실행 실패: {e}")
            return False

    def generate_scenes_tts(
        self, scenes: list[dict], campaign_id: str = ""
    ) -> list[dict]:
        """여러 장면의 TTS를 일괄 생성하고 duration 측정.

        Args:
            scenes: [{"scene_num": 1, "text": "...", "emotion": "excited"}, ...]
            campaign_id: 캠페인 ID (파일명용)

        Returns:
            scenes에 tts_path, tts_duration 추가된 리스트
        """
        uid = campaign_id or uuid.uuid4().hex[:8]
        results = []

        for scene in scenes:
            scene_num = scene.get("scene_num", 0)
            text = scene.get("text", "")
            emotion = scene.get("emotion", "friendly")

            if not text.strip():
                scene["tts_path"] = ""
                scene["tts_duration"] = 0.0
                results.append(scene)
                continue

            output_path = str(self.output_dir / f"{uid}_scene{scene_num}.mp3")

            try:
                success = self.generate_tts(text, output_path, emotion)

                if success:
                    # FFprobe로 정확한 duration 측정
                    info = _run_ffprobe(output_path)
                    duration = info.get("duration", 3.0)
                    scene["tts_path"] = output_path
                    scene["tts_duration"] = round(duration, 3)
                    self.logger.info(
                        f"Scene {scene_num} TTS 완료: {duration:.2f}s, "
                        f"emotion={emotion}"
                    )
                else:
                    scene["tts_path"] = ""
                    scene["tts_duration"] = 3.0  # 폴백 기본 3초
                    self.logger.warning(f"Scene {scene_num} TTS 실패, 3초 폴백")

            except Exception as e:
                self.logger.error(f"Scene {scene_num} TTS 에러: {e}")
                scene["tts_path"] = ""
                scene["tts_duration"] = 3.0

            results.append(scene)
            time.sleep(0.5)  # Edge-TTS 레이트 리밋 방지

        return results

    def extract_word_timestamps(
        self, audio_path: str
    ) -> list[dict]:
        """Whisper로 TTS 오디오에서 단어별 타임스탬프 추출.

        Args:
            audio_path: TTS 음성 파일 경로

        Returns:
            [{"word": "안녕", "start": 0.0, "end": 0.3}, ...]
        """
        if not audio_path or not Path(audio_path).exists():
            return []

        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device=WHISPER_DEVICE if WHISPER_DEVICE != "cuda" else "auto",
                compute_type="float16" if WHISPER_DEVICE == "cuda" else "int8"
            )

            segments, info = model.transcribe(
                audio_path,
                language=WHISPER_LANGUAGE,
                word_timestamps=True,
                vad_filter=True,
            )

            words = []
            for segment in segments:
                if segment.words:
                    for w in segment.words:
                        words.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                        })

            self.logger.info(
                f"Whisper 단어 추출: {len(words)}개 단어, "
                f"언어={info.language}"
            )
            return words

        except ImportError:
            self.logger.warning(
                "faster-whisper 미설치. pip install faster-whisper 필요. "
                "균등 분할 폴백 사용."
            )
            return self._fallback_word_timestamps(audio_path)
        except Exception as e:
            self.logger.error(f"Whisper 추출 실패: {e}")
            return self._fallback_word_timestamps(audio_path)

    def _fallback_word_timestamps(self, audio_path: str) -> list[dict]:
        """Whisper 실패 시 균등 분할 폴백."""
        info = _run_ffprobe(audio_path)
        duration = info.get("duration", 3.0)
        # 대략 0.3초 간격으로 빈 타임스탬프 생성
        words = []
        t = 0.0
        idx = 0
        while t < duration:
            words.append({
                "word": f"[word_{idx}]",
                "start": round(t, 3),
                "end": round(min(t + 0.3, duration), 3),
            })
            t += 0.3
            idx += 1
        return words


# ═══════════════════════════════════════════════════════════════════════════
# ASS 자막 생성기
# ═══════════════════════════════════════════════════════════════════════════

class SubtitleGenerator:
    """ASS 자막 파일 생성기 — Whisper 단어 타임스탬프 기반."""

    # ASS 헤더 (숏폼 최적화 스타일)
    ASS_HEADER = """[Script Info]
Title: V2 Shorts Subtitle
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Pretendard,70,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,0,2,50,50,200,1
Style: Highlight,Pretendard,75,&H0000BFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,0,2,50,50,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def __init__(self, output_dir: Optional[Path] = None):
        """자막 생성기 초기화."""
        self.output_dir = output_dir or V2_SUBTITLE_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    def generate_ass_from_scenes(
        self,
        scenes: list[dict],
        campaign_id: str = "",
    ) -> Optional[str]:
        """여러 장면의 TTS 타임스탬프를 기반으로 ASS 자막 생성.

        Args:
            scenes: [{"scene_num", "text", "tts_duration", "word_timestamps"}, ...]
            campaign_id: 파일명용

        Returns:
            ASS 자막 파일 경로
        """
        uid = campaign_id or uuid.uuid4().hex[:8]
        output_path = str(self.output_dir / f"{uid}_subtitle.ass")

        try:
            lines = [self.ASS_HEADER]
            cumulative_time = 0.0  # 장면 누적 시간

            for scene in scenes:
                text = scene.get("text", "")
                duration = scene.get("tts_duration", 3.0)
                word_ts = scene.get("word_timestamps", [])
                emotion = scene.get("emotion", "friendly")

                if not text.strip():
                    cumulative_time += duration
                    continue

                # 감정에 따른 스타일 선택
                style = "Highlight" if emotion in ("excited", "hyped", "urgent") else "Default"

                if word_ts and len(word_ts) >= 2:
                    # Whisper 단어 타임스탬프 기반 자막
                    # 2-4 단어씩 묶어서 자막 라인 생성
                    chunk_size = 3
                    for i in range(0, len(word_ts), chunk_size):
                        chunk = word_ts[i:i + chunk_size]
                        if not chunk:
                            continue

                        start_t = cumulative_time + chunk[0]["start"]
                        end_t = cumulative_time + chunk[-1]["end"]
                        chunk_text = " ".join(w["word"] for w in chunk)

                        lines.append(
                            f"Dialogue: 0,"
                            f"{self._format_ass_time(start_t)},"
                            f"{self._format_ass_time(end_t)},"
                            f"{style},,0,0,0,,"
                            f"{chunk_text}"
                        )
                else:
                    # 폴백: 전체 장면을 하나의 자막으로
                    start_t = cumulative_time
                    end_t = cumulative_time + duration
                    lines.append(
                        f"Dialogue: 0,"
                        f"{self._format_ass_time(start_t)},"
                        f"{self._format_ass_time(end_t)},"
                        f"{style},,0,0,0,,"
                        f"{text}"
                    )

                cumulative_time += duration

            # 파일 쓰기
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            self.logger.info(f"ASS 자막 생성: {output_path}")
            return output_path

        except Exception as e:
            self.logger.error(f"ASS 자막 생성 실패: {e}")
            return None

    @staticmethod
    def _format_ass_time(seconds: float) -> str:
        """초 → ASS 시간 포맷 (H:MM:SS.CC)."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ═══════════════════════════════════════════════════════════════════════════
# 숏폼 최종 렌더링 엔진
# ═══════════════════════════════════════════════════════════════════════════

class ShortsRenderer:
    """FFmpeg GPU 기반 숏폼 최종 렌더링.

    세탁된 비디오 + TTS + 자막 + BGM → 최종 영상 합성.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """렌더러 초기화."""
        self.output_dir = output_dir or V2_SHORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.encoder = _get_encoder()
        self.logger = logger

    def render_final_shorts(
        self,
        scenes: list[dict],
        bgm_path: Optional[str] = None,
        campaign_id: str = "",
        subtitle_path: Optional[str] = None,
        coupang_link: str = "",
        brand: str = "",
    ) -> Optional[str]:
        """세탁된 클립 + TTS + 자막 + BGM → 최종 숏폼 영상.

        Args:
            scenes: [{"video_clip_path", "tts_path", "tts_duration", "text"}, ...]
            bgm_path: BGM 오디오 경로 (없으면 무배경음)
            campaign_id: 파일명용
            subtitle_path: ASS 자막 경로
            coupang_link: 쿠팡 링크 (워터마크용)
            brand: 브랜드명

        Returns:
            최종 영상 경로
        """
        uid = campaign_id or uuid.uuid4().hex[:8]
        output_path = str(self.output_dir / f"{uid}_shorts_final.mp4")

        try:
            # 유효한 장면만 필터링
            valid_scenes = [
                s for s in scenes
                if s.get("video_clip_path") and Path(s["video_clip_path"]).exists()
            ]

            if not valid_scenes:
                self.logger.error("유효한 비디오 클립이 없습니다!")
                return None

            # Step 1: 각 클립을 TTS 길이에 맞춰 자르기 + concat
            clip_list_path = str(self.output_dir / f"{uid}_clips.txt")
            trimmed_clips = []

            for idx, scene in enumerate(valid_scenes):
                clip_path = scene["video_clip_path"]
                duration = scene.get("tts_duration", 3.0)
                if duration <= 0:
                    duration = 3.0

                # 총 길이 제한 체크
                current_total = sum(
                    s.get("tts_duration", 3.0) for s in trimmed_clips
                )
                if current_total + duration > SHORTS_MAX_DURATION:
                    duration = max(1.0, SHORTS_MAX_DURATION - current_total)
                    if duration < 1.0:
                        break

                trimmed_path = str(
                    self.output_dir / f"{uid}_trim_{idx}.mp4"
                )

                # FFmpeg: 클립을 정확한 길이로 트림 + 해상도 통일
                trim_args = [
                    "-i", clip_path,
                    "-t", str(round(duration, 3)),
                    "-vf", (
                        f"scale={SHORTS_RESOLUTION[0]}:{SHORTS_RESOLUTION[1]}"
                        f":force_original_aspect_ratio=decrease,"
                        f"pad={SHORTS_RESOLUTION[0]}:{SHORTS_RESOLUTION[1]}"
                        f":(ow-iw)/2:(oh-ih)/2:black,"
                        f"fps={SHORTS_FPS}"
                    ),
                    "-an",  # 오디오 제거 (TTS로 대체)
                    "-c:v", self.encoder,
                    "-pix_fmt", "yuv420p",
                ]

                if self.encoder == "h264_nvenc":
                    trim_args += ["-preset", FFMPEG_PRESET, "-rc", "constqp", "-qp", "20"]
                else:
                    trim_args += ["-preset", "fast", "-crf", "20"]

                trim_args.append(trimmed_path)

                success = _run_ffmpeg(
                    trim_args,
                    desc=f"클립 트림 {idx+1}/{len(valid_scenes)}"
                )

                if success and Path(trimmed_path).exists():
                    trimmed_clips.append(scene.copy())
                    trimmed_clips[-1]["_trimmed_path"] = trimmed_path
                else:
                    self.logger.warning(f"클립 트림 실패: {clip_path}")

            if not trimmed_clips:
                self.logger.error("트림된 클립이 없습니다!")
                return None

            # Step 2: concat 파일 생성
            with open(clip_list_path, "w", encoding="utf-8") as f:
                for sc in trimmed_clips:
                    p = sc["_trimmed_path"].replace("\\", "/")
                    f.write(f"file '{p}'\n")

            # Step 3: 비디오 연결
            concat_video = str(self.output_dir / f"{uid}_concat.mp4")
            concat_args = [
                "-f", "concat", "-safe", "0",
                "-i", clip_list_path,
                "-c", "copy",
                concat_video,
            ]
            if not _run_ffmpeg(concat_args, desc="비디오 연결"):
                self.logger.error("비디오 concat 실패")
                return None

            # Step 4: TTS 오디오 연결
            tts_concat = self._concat_tts_audio(trimmed_clips, uid)

            # Step 5: 최종 합성 (비디오 + TTS + BGM + 자막)
            final_args = ["-i", concat_video]
            filter_complex_parts = []
            audio_inputs = []

            # TTS 오디오
            if tts_concat and Path(tts_concat).exists():
                final_args += ["-i", tts_concat]
                audio_inputs.append(1)

            # BGM
            bgm_input_idx = None
            if bgm_path and Path(bgm_path).exists():
                bgm_input_idx = len(final_args) // 2  # 대략적 인덱스
                final_args += ["-i", bgm_path]
                audio_inputs.append(bgm_input_idx)

            # 오디오 믹스 필터
            if len(audio_inputs) >= 2 and bgm_input_idx is not None:
                # TTS + BGM 믹스
                filter_complex_parts.append(
                    f"[1:a]volume=1.0[tts];"
                    f"[{bgm_input_idx}:a]volume=0.08[bgm];"
                    f"[tts][bgm]amix=inputs=2:duration=first[aout]"
                )
                audio_map = ["-map", "0:v", "-map", "[aout]"]
            elif audio_inputs:
                # TTS만
                audio_map = ["-map", "0:v", "-map", "1:a"]
            else:
                audio_map = ["-map", "0:v"]

            # 자막 필터 (ASS burn-in)
            video_filter = ""
            if subtitle_path and Path(subtitle_path).exists():
                # Windows 경로 이스케이프
                sub_escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
                video_filter = f"ass='{sub_escaped}'"

            # 인코더 옵션
            if self.encoder == "h264_nvenc":
                enc_opts = [
                    "-c:v", self.encoder,
                    "-preset", FFMPEG_PRESET,
                    "-rc", "constqp", "-qp", FFMPEG_CRF,
                ]
            else:
                enc_opts = ["-c:v", self.encoder, "-preset", "medium", "-crf", FFMPEG_CRF]

            # 최종 명령 조립
            if filter_complex_parts:
                final_args += ["-filter_complex", ";".join(filter_complex_parts)]

            if video_filter:
                final_args += ["-vf", video_filter]

            final_args += audio_map
            final_args += enc_opts
            final_args += [
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-shortest",
                output_path,
            ]

            success = _run_ffmpeg(final_args, desc="최종 숏폼 렌더링", timeout=600)

            # 임시 파일 정리
            self._cleanup_temp_files(uid)

            if success and Path(output_path).exists():
                out_info = _run_ffprobe(output_path)
                self.logger.info(
                    f"숏폼 렌더링 완료: {Path(output_path).name} "
                    f"({out_info.get('duration', 0):.1f}s, "
                    f"{Path(output_path).stat().st_size / 1024 / 1024:.1f}MB)"
                )
                return output_path
            else:
                self.logger.error("최종 렌더링 실패")
                return None

        except Exception as e:
            self.logger.error(f"숏폼 렌더링 예외: {e}")
            self._cleanup_temp_files(uid)
            return None

    def _concat_tts_audio(
        self, scenes: list[dict], uid: str
    ) -> Optional[str]:
        """장면별 TTS 오디오를 순서대로 연결.

        TTS가 없는 장면은 무음으로 채움.
        """
        output_path = str(self.output_dir / f"{uid}_tts_concat.mp3")
        list_path = str(self.output_dir / f"{uid}_tts_list.txt")

        try:
            entries = []
            for idx, scene in enumerate(scenes):
                tts_path = scene.get("tts_path", "")
                duration = scene.get("tts_duration", 3.0)

                if tts_path and Path(tts_path).exists():
                    entries.append(tts_path)
                else:
                    # 무음 생성
                    silence_path = str(self.output_dir / f"{uid}_silence_{idx}.mp3")
                    silence_ok = _run_ffmpeg(
                        ["-f", "lavfi", "-i",
                         f"anullsrc=r=44100:cl=mono",
                         "-t", str(round(duration, 3)),
                         "-c:a", "libmp3lame", "-b:a", "128k",
                         silence_path],
                        desc=f"무음 생성 ({duration:.1f}s)"
                    )
                    if silence_ok:
                        entries.append(silence_path)

            if not entries:
                return None

            # concat 파일
            with open(list_path, "w", encoding="utf-8") as f:
                for path in entries:
                    p = path.replace("\\", "/")
                    f.write(f"file '{p}'\n")

            success = _run_ffmpeg(
                ["-f", "concat", "-safe", "0",
                 "-i", list_path,
                 "-c:a", "libmp3lame", "-b:a", "192k",
                 output_path],
                desc="TTS 오디오 연결"
            )

            return output_path if success else None

        except Exception as e:
            self.logger.error(f"TTS 연결 실패: {e}")
            return None

    def _cleanup_temp_files(self, uid: str):
        """임시 파일 정리."""
        try:
            patterns = [
                f"{uid}_trim_*.mp4",
                f"{uid}_concat.mp4",
                f"{uid}_clips.txt",
                f"{uid}_tts_list.txt",
                f"{uid}_tts_concat.mp3",
                f"{uid}_silence_*.mp3",
            ]
            for pattern in patterns:
                for f in self.output_dir.glob(pattern):
                    try:
                        f.unlink()
                    except Exception:
                        pass
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 통합 테스트
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("Video Launderer V2 — FFmpeg GPU 엔진 테스트")
    print("=" * 60)

    # GPU 인코더 체크
    encoder = _check_gpu_encoder()
    print(f"사용 인코더: {encoder}")

    # FFprobe 테스트
    print("\n[테스트] FFprobe 동작 확인...")
    test_probe = _run_ffprobe("nonexistent.mp4")
    print(f"  존재하지 않는 파일: {test_probe}")

    print("\nVideo Launderer V2 초기화 완료!")
    print(f"  세탁 출력: {V2_LAUNDERED_DIR}")
    print(f"  TTS 출력: {V2_TTS_DIR}")
    print(f"  자막 출력: {V2_SUBTITLE_DIR}")
    print(f"  숏폼 출력: {V2_SHORTS_DIR}")
