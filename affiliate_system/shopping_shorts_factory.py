# -*- coding: utf-8 -*-
"""
쇼핑쇼츠 팩토리 (Shopping Shorts Factory)
==========================================
레퍼런스: 타임투쇼츠 방식 (월 2천만원 수익)
- 소스 영상(도우인/틱톡 등) 다운로드
- AI 대본 생성 (상품 리뷰 스크립트)
- Edge-TTS 나레이션 + SRT 자막 동시 생성 (1.2배속)
- FFmpeg로 소스영상 + TTS + 자막 합성 → 쇼츠 완성

핵심 차이: 이미지 슬라이드쇼가 아니라 "실제 영상 리믹스"

Usage:
    python -m affiliate_system.shopping_shorts_factory \\
        --video "https://v.douyin.com/xxxxx" \\
        --product "접이식 신발건조기"

    python -m affiliate_system.shopping_shorts_factory \\
        --video "local_video.mp4" \\
        --product "베베숲 물티슈" \\
        --skip-upload
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env", override=True)

from affiliate_system.config import (
    RENDER_OUTPUT_DIR, WORK_DIR,
    COUPANG_DISCLAIMER,
    FFMPEG_ENCODER, FFMPEG_ENCODER_FALLBACK,
    FFMPEG_HWACCEL, FFMPEG_CRF, FFMPEG_PRESET,
)

# Claude 모델 상수 — ai_generator에서 가져오면 순환참조 위험, 직접 정의
CLAUDE_HAIKU = "claude-3-haiku-20240307"
from affiliate_system.utils import setup_logger, ensure_dir, send_telegram

log = setup_logger("shopping_shorts", "shopping_shorts.log")

# ── TTS 설정 ──
TTS_VOICE = "ko-KR-SunHiNeural"        # 여성 (자연스러운 리뷰 톤)
TTS_VOICE_MALE = "ko-KR-InJoonNeural"  # 남성
TTS_RATE = "+5%"                        # +5% 거의 자연어 속도 (+10%→+5%, 자연스러움 최우선)
TTS_PITCH = "+0Hz"

# ── 자막 스타일 (레거시, SRT 폴백용) ──
SUBTITLE_FONT = "Malgun Gothic"         # 윈도우 기본 한글 폰트
SUBTITLE_FONTSIZE = 52                  # 쇼츠 자막 크기
SUBTITLE_COLOR = "&Hffffff"             # 흰색
SUBTITLE_OUTLINE = 3                    # 외곽선 두께
SUBTITLE_OUTLINE_COLOR = "&H000000"     # 검정 외곽선
SUBTITLE_SHADOW = 1                     # 그림자
SUBTITLE_MARGIN_V = 80                  # 하단 여백

# ═══════════════════════════════════════════════════════════════════════════
# 레퍼런스 스타일 설정 (풀프레임 + 상단 자막 오버레이 + 인트로 타이틀)
# 레퍼런스: @살림남 The Life, @리뷰몽키 (조회수 24만~47만)
# 스타일: 풀프레임 영상 + 상단 1/3 흰색 볼드 자막 + 2초 인트로 타이틀(흰+노랑)
# ═══════════════════════════════════════════════════════════════════════════
HQ_CANVAS_W = 1080              # 캔버스 가로
HQ_CANVAS_H = 1920              # 캔버스 세로 (9:16)

# ── 본편 자막 (상단 1/4 오버레이, 배경 없이 영상 위 직접 표시) ──
HQ_FONT = "Malgun Gothic"       # 한글 기본 폰트 (안정적, 모든 PC 보유)
HQ_SUBTITLE_FONTSIZE = 60       # 자막 크기 (56→60, 가독성 강화)
HQ_SUBTITLE_OUTLINE = 6         # 두꺼운 다크 아웃라인 (5→6)
HQ_SUBTITLE_SHADOW = 2          # 드롭 쉐도우 (미묘하게)
HQ_SUBTITLE_MARGIN_TOP = 380    # 상단에서의 거리 (px) — 화면 1/5 지점 (320→380)

# ── 인트로 타이틀 (0~2초, =썸네일) ──
HQ_INTRO_DURATION = 2.0         # 인트로 타이틀 표시 시간 (초)
HQ_INTRO_TITLE_SIZE = 85        # 메인 타이틀 폰트 크기 (초대형, 80→85)
HQ_INTRO_TITLE_OUTLINE = 8      # 매우 두꺼운 아웃라인 (7→8)
HQ_INTRO_TITLE_SHADOW = 3       # 뚜렷한 그림자
HQ_INTRO_HOOK_SIZE = 32         # 후크 텍스트 크기 (30→32)
HQ_YELLOW_COLOR = "&H0000FFFF"  # 순수 노란색 (BGR: 00FFFF = RGB #FFFF00, 더 선명)


class ShoppingScriptGenerator:
    """쇼핑쇼츠 전용 AI 대본 생성기

    모드:
    - direct: 직접 홍보 (기본) — 상품 리뷰/추천 스타일
    - story: 간접 홍보 (5탄 전략) — 썰/꿀팁 형태로 상품을 자연스럽게 녹여냄
    - bestof: 베스트 콘텐츠 (4탄) — "~베스트 5", 추천/비교 컨셉
    - beforeafter: 비포/애프터 비교 (4탄) — 사용 전/후 극적 비교
    """

    # 직접 홍보 대본 (기본)
    SCRIPT_PROMPT = """당신은 YouTube 쇼핑 쇼츠 전문 카피라이터입니다.
다음 상품에 대한 30~50초 분량의 쇼츠 나레이션 대본을 작성하세요.

상품: {product_name}
{product_info}

## 필수 규칙:
1. 첫 문장은 반드시 "훅" — 시청자가 스크롤을 멈추게 하는 강렬한 한마디
   예: "이거 진짜 미쳤는데요", "아 이런게 있었다고?", "이거 모르면 손해"
2. 2~3번째 문장: 공감대 형성 (일상의 불편함/니즈)
3. 4~6번째 문장: 상품 소개 + 핵심 기능 설명
4. 5번째 문장 이후: 중간 후킹 ("근데 진짜 중요한건 이건데요", "여기서 반전") — 이탈 방지
5. 마지막 문장: CTA ("링크는 댓글에!", "고정 댓글 확인!")
6. 총 6~10문장, 각 문장은 15자~40자
7. 말하듯 자연스러운 구어체 (음슴체/반말)
8. 절대 딱딱하거나 광고 같지 않게

## 출력 형식 (JSON):
{{
    "hook": "첫 훅 문장",
    "script": ["문장1", "문장2", "문장3", ...],
    "thumbnail_text": "썸네일 문구 (7자 이내)",
    "hashtags": ["#해시태그1", "#해시태그2", ...]
}}

JSON만 출력하세요. 다른 텍스트 없이."""

    # 간접 홍보 / 스토리 대본 (5탄 전략 - 알고리즘 정복)
    STORY_PROMPT = """당신은 YouTube 쇼츠 스토리 전문 작가입니다.
다음 상품을 "꿀팁" 또는 "썰" 형태의 스토리로 자연스럽게 녹여주세요.
직접 홍보하지 마세요. 시청자가 광고라고 느끼면 안 됩니다.

상품: {product_name}
{product_info}

## 전략 (간접 홍보):
1. 첫 문장: 궁금증/반전 유발 훅 (상품명 언급 X)
   예: "이거 아는 사람만 아는 꿀팁인데", "나만 몰랐던 거 실화?"
2. 2~4문장: 일상 에피소드/꿀팁 형태로 상황 설명
3. 5~7문장: 자연스럽게 상품 등장 (해결책으로)
4. 중간에 반전: "근데 진짜 대박인건", "여기서 반전인데"
5. 마지막: 약한 CTA ("궁금하면 댓글에", "저거 뭔지 궁금하면 프로필")
6. 유튜브가 "꿀팁/썰 채널"로 인식하도록 — 썸네일도 상품 대신 텍스트

## 출력 형식 (JSON):
{{
    "hook": "첫 훅 문장",
    "script": ["문장1", "문장2", ...],
    "thumbnail_text": "썸네일 문구 (7자 이내, 꿀팁/반전 스타일)",
    "hashtags": ["#꿀팁", "#생활꿀팁", "#알뜰살뜰", ...]
}}

JSON만 출력하세요."""

    # 베스트 콘텐츠 대본 (4탄 전략)
    BESTOF_PROMPT = """당신은 YouTube 쇼츠 베스트 콘텐츠 전문 작가입니다.
다음 상품 카테고리로 "OO 베스트 추천" 또는 "비포&애프터" 콘텐츠를 만드세요.

상품: {product_name}
{product_info}

## 전략 (베스트 콘텐츠):
1. 첫 문장: "OO 추천 TOP 3" 또는 "써보고 인생템 등극" 스타일 훅
2. 비교/순위 형태로 자연스럽게 구성
3. 중간 후킹: "근데 1위가 진짜 미쳤어요"
4. 마지막: CTA ("1위 링크는 댓글!", "여기서 살 수 있어요")
5. 총 6~10문장, 구어체

## 출력 형식 (JSON):
{{
    "hook": "첫 훅 문장",
    "script": ["문장1", "문장2", ...],
    "thumbnail_text": "썸네일 문구 (7자 이내)",
    "hashtags": ["#추천", "#꿀템", "#베스트", ...]
}}

JSON만 출력하세요."""

    # 최저가 vs 최고가 비교 대본 (3탄 핵심 — 가격 비교 콘텐츠)
    PRICECOMPARE_PROMPT = """당신은 YouTube 쇼츠 가격 비교 전문 작가입니다.
다음 상품의 "최저가 vs 최고가" 또는 "가성비 TOP 3" 비교 콘텐츠를 만드세요.

상품: {product_name}
{product_info}

## 전략 (가격 비교):
1. 첫 문장: 가격 차이 충격 훅 ("같은 제품인데 가격이 5배?!", "이거 3000원짜리가 3만원짜리를 이김")
2. 2~3문장: 최고가 제품 소개 (브랜드, 가격, 특징)
3. 4~5문장: 최저가 제품 소개 (가성비, 쿠팡 검색 가능)
4. 중간 후킹: "근데 진짜 반전은요", "결론부터 말하면"
5. 6~8문장: 실제 비교 결과 (품질, 내구성, 만족도)
6. 마지막: CTA ("최저가 링크는 고정 댓글!", "3번 제품 구매링크 댓글")
7. 구체적 가격 언급 → 시청자 클릭 유도

## 출력 형식 (JSON):
{{
    "hook": "가격 차이 충격 훅",
    "script": ["문장1", "문장2", ...],
    "thumbnail_text": "최저가vs최고가 (7자 이내)",
    "hashtags": ["#가성비", "#최저가", "#가격비교", ...]
}}

JSON만 출력하세요."""

    # Before/After 대본 (4탄 핵심 — 비포/애프터 비교 콘텐츠)
    BEFOREAFTER_PROMPT = """당신은 YouTube 쇼츠 Before/After 전문 작가입니다.
다음 상품을 사용하기 전(Before)과 후(After)를 극적으로 비교하는 콘텐츠를 만드세요.

상품: {product_name}
{product_info}

## 전략 (Before/After):
1. 첫 문장: 도발적/공감 훅 (Before 상황의 불편함/고민)
   예: "이거 쓰는 사람 허세라고 생각했는데", "솔직히 이거 필요없다고 생각했거든요"
2. 2~3문장: Before 상황 (일상의 불편함, 문제점 구체적 묘사)
3. 4문장: 반전 전환 — "근데 써보고 인생 바뀜", "그래서 나도 바꿨는데요"
4. 5~7문장: After 상황 (상품 사용 후 변화, 구체적 장점)
5. 중간 후킹: "근데 진짜 대박인 건요" (이탈 방지)
6. 마지막: CTA ("비교 영상 보고 싶으면 댓글!", "링크는 고정 댓글")
7. Before에선 단점만, After에선 장점만 — 극적 대비
8. 총 7~10문장, 자연스러운 구어체

## 출력 형식 (JSON):
{{
    "hook": "첫 훅 문장 (Before 도발)",
    "script": ["Before문장1", "Before문장2", "반전", "After문장1", "After문장2", ...],
    "thumbnail_text": "비포→애프터 (7자 이내)",
    "hashtags": ["#비포애프터", "#솔직후기", "#인생템", ...]
}}

JSON만 출력하세요."""

    def __init__(self):
        self._ai = None

    def _get_ai(self):
        """Gemini 우선, 실패시 폴백"""
        if self._ai:
            return self._ai
        try:
            from affiliate_system.ai_generator import AIGenerator
            self._ai = AIGenerator()
            return self._ai
        except Exception as e:
            log.error("AIGenerator 초기화 실패: %s", e)
            return None

    def generate(self, product_name: str, product_info: str = "",
                 mode: str = "direct") -> dict:
        """쇼핑쇼츠 대본 생성

        Args:
            product_name: 상품명
            product_info: 추가 상품 정보
            mode: 대본 모드
                - "direct": 직접 홍보 (기본, 상품 리뷰)
                - "story": 간접 홍보 (썰/꿀팁, 알고리즘 최적화)
                - "bestof": 베스트 콘텐츠 (추천/비교)
                - "beforeafter": 비포/애프터 비교 (4탄 전략)

        Returns:
            {
                "hook": str,
                "script": [str, ...],
                "full_script": str,
                "thumbnail_text": str,
                "hashtags": [str, ...],
            }
        """
        # 모드별 프롬프트 선택
        prompt_map = {
            "direct": self.SCRIPT_PROMPT,
            "story": self.STORY_PROMPT,
            "bestof": self.BESTOF_PROMPT,
            "beforeafter": self.BEFOREAFTER_PROMPT,
            "pricecompare": self.PRICECOMPARE_PROMPT,
        }
        template = prompt_map.get(mode, self.SCRIPT_PROMPT)
        prompt = template.format(
            product_name=product_name,
            product_info=product_info or "(추가 정보 없음)",
        )
        log.info("대본 생성 모드: %s (상품: %s)", mode, product_name)

        ai = self._get_ai()
        if ai:
            try:
                # Gemini 무료 우선 (task 파라미터 없음)
                raw = ai._call_gemini(prompt)
                return self._parse_script(raw, product_name)
            except Exception as e:
                log.warning("Gemini 대본 생성 실패: %s, 폴백 시도", e)
                try:
                    raw = ai._call_claude(CLAUDE_HAIKU, prompt)
                    return self._parse_script(raw, product_name)
                except Exception as e2:
                    log.warning("Claude 대본 생성도 실패: %s", e2)

        # 최종 폴백: 기본 대본
        return self._fallback_script(product_name)

    def _parse_script(self, raw: str, product_name: str) -> dict:
        """AI 응답에서 JSON 파싱"""
        try:
            # JSON 블록 추출
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(raw)

            hook = data.get("hook", f"이거 진짜 미쳤는데요")
            script_lines = data.get("script", [])
            if not script_lines:
                raise ValueError("script 필드 비어있음")

            # hook을 첫 줄에 추가
            full_lines = [hook] + script_lines
            full_script = " ".join(full_lines)

            return {
                "hook": hook,
                "script": full_lines,
                "full_script": full_script,
                "thumbnail_text": data.get("thumbnail_text", product_name[:7]),
                "hashtags": data.get("hashtags", [f"#{product_name}", "#쇼츠", "#추천"]),
            }
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("대본 JSON 파싱 실패: %s - 텍스트 기반 파싱", e)
            # 텍스트 기반 파싱
            lines = [l.strip() for l in raw.split('\n') if l.strip() and not l.startswith('{')]
            lines = [l for l in lines if len(l) > 5 and len(l) < 100][:10]
            if lines:
                return {
                    "hook": lines[0],
                    "script": lines,
                    "full_script": " ".join(lines),
                    "thumbnail_text": product_name[:7],
                    "hashtags": [f"#{product_name}", "#쇼츠"],
                }
            return self._fallback_script(product_name)

    def _fallback_script(self, product_name: str) -> dict:
        """AI 실패시 기본 대본"""
        hook = "이거 진짜 써보고 깜짝 놀랐어요"
        lines = [
            hook,
            f"{product_name} 써본 사람만 아는 진짜 후기",
            "솔직히 처음에는 반신반의했거든요",
            "근데 직접 써보니까 확실히 다르더라구요",
            "가성비까지 좋아서 재구매 확정",
            "궁금하면 링크는 고정 댓글 확인!",
        ]
        return {
            "hook": hook,
            "script": lines,
            "full_script": " ".join(lines),
            "thumbnail_text": product_name[:7],
            "hashtags": [f"#{product_name}", "#쇼츠", "#추천", "#리뷰"],
        }


class EdgeTTSWithSRT:
    """Edge-TTS 나레이션 + SRT 자막 동시 생성기

    핵심: edge-tts의 word_boundary 이벤트로 정확한 타임스탬프 추출
    → SRT 자막과 오디오가 완벽 싱크
    """

    def __init__(
        self,
        voice: str = TTS_VOICE,
        rate: str = TTS_RATE,
        pitch: str = TTS_PITCH,
    ):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch

    def generate(
        self,
        script_lines: list[str],
        output_dir: str,
        filename_prefix: str = "tts",
    ) -> dict:
        """TTS 오디오 + SRT 자막 동시 생성

        Args:
            script_lines: 나레이션 문장 리스트
            output_dir: 출력 디렉토리
            filename_prefix: 파일명 접두어

        Returns:
            {
                "audio_path": str,  # MP3 오디오 파일
                "srt_path": str,    # SRT 자막 파일
                "duration": float,  # 오디오 길이 (초)
                "word_timings": [...],  # 단어별 타이밍
            }
        """
        ensure_dir(Path(output_dir))
        audio_path = os.path.join(output_dir, f"{filename_prefix}.mp3")
        srt_path = os.path.join(output_dir, f"{filename_prefix}.srt")

        # 전체 텍스트를 하나로 합침 (문장 사이 짧은 쉼)
        full_text = self._prepare_text(script_lines)

        # edge-tts 비동기 실행
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        self._generate_async(full_text, audio_path, srt_path, script_lines)
                    ).result(timeout=120)
            else:
                result = loop.run_until_complete(
                    self._generate_async(full_text, audio_path, srt_path, script_lines)
                )
        except RuntimeError:
            result = asyncio.run(
                self._generate_async(full_text, audio_path, srt_path, script_lines)
            )

        return result

    def _prepare_text(self, lines: list[str]) -> str:
        """문장 리스트를 TTS용 텍스트로 합침"""
        # 각 문장 끝에 마침표가 없으면 추가 (자연스러운 쉼)
        processed = []
        for line in lines:
            line = line.strip()
            if line and not line[-1] in '.!?。':
                line += '.'
            processed.append(line)
        return ' '.join(processed)

    async def _generate_async(
        self,
        text: str,
        audio_path: str,
        srt_path: str,
        original_lines: list[str],
    ) -> dict:
        """비동기 TTS 생성 + 워드 바운더리 수집"""
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch,
            boundary="WordBoundary",   # 단어별 타이밍 수신 (기본값은 SentenceBoundary)
        )

        # 워드 바운더리 이벤트 수집
        word_timings = []
        audio_data = bytearray()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_timings.append({
                    "offset": chunk["offset"] / 10_000_000,  # 100ns → 초
                    "duration": chunk["duration"] / 10_000_000,
                    "text": chunk["text"],
                })

        # 오디오 저장
        with open(audio_path, 'wb') as f:
            f.write(bytes(audio_data))

        log.info("TTS 오디오 생성 완료: %s (words=%d)", audio_path, len(word_timings))

        # SRT 자막 생성 (문장 단위 그룹핑)
        srt_entries = self._words_to_srt(word_timings, original_lines)
        self._write_srt(srt_entries, srt_path)

        log.info("SRT 자막 생성 완료: %s (entries=%d)", srt_path, len(srt_entries))

        # 오디오 길이 측정
        duration = self._get_audio_duration(audio_path)

        return {
            "audio_path": audio_path,
            "srt_path": srt_path,
            "duration": duration,
            "word_timings": word_timings,
        }

    def _words_to_srt(
        self,
        word_timings: list[dict],
        original_lines: list[str],
    ) -> list[dict]:
        """워드 바운더리를 문장 단위 SRT 엔트리로 변환

        레퍼런스 방식: 한 줄에 짧게 (10~20자), 읽기 편하게
        """
        if not word_timings:
            # 폴백: 균등 분배
            return self._fallback_srt(original_lines)

        entries = []
        idx = 1
        current_text = ""
        current_start = None

        for wt in word_timings:
            word = wt["text"]
            start = wt["offset"]
            end = start + wt["duration"]

            if current_start is None:
                current_start = start

            # 단어 사이 공백 추가 (한글 자연스러운 띄어쓰기)
            if current_text:
                current_text += " " + word
            else:
                current_text = word

            # 자막 줄바꿈 조건: 15자 넘거나 문장부호
            # 레퍼런스 쇼츠: 한 줄에 10~18자 (짧고 읽기 쉽게)
            should_break = (
                len(current_text) >= 15 or
                word.rstrip().endswith(('.', '!', '?', '。')) or
                (word.rstrip().endswith((',', '，')) and len(current_text) >= 10)
            )

            if should_break and current_text.strip():
                entries.append({
                    "index": idx,
                    "start": current_start,
                    "end": end + 0.1,  # 약간 여유
                    "text": current_text.strip(),
                })
                idx += 1
                current_text = ""
                current_start = None

        # 마지막 남은 텍스트
        if current_text.strip() and word_timings:
            last = word_timings[-1]
            entries.append({
                "index": idx,
                "start": current_start or last["offset"],
                "end": last["offset"] + last["duration"] + 0.3,
                "text": current_text.strip(),
            })

        return entries

    def _fallback_srt(self, lines: list[str], total_duration: float = 30.0) -> list[dict]:
        """워드 바운더리 없을 때 균등 분배 SRT"""
        entries = []
        dt = total_duration / max(len(lines), 1)
        for i, line in enumerate(lines):
            entries.append({
                "index": i + 1,
                "start": i * dt,
                "end": (i + 1) * dt,
                "text": line.strip(),
            })
        return entries

    def _write_srt(self, entries: list[dict], path: str):
        """SRT 파일 작성"""
        with open(path, 'w', encoding='utf-8') as f:
            for e in entries:
                start_ts = self._seconds_to_srt_time(e["start"])
                end_ts = self._seconds_to_srt_time(e["end"])
                f.write(f"{e['index']}\n")
                f.write(f"{start_ts} --> {end_ts}\n")
                f.write(f"{e['text']}\n\n")

    @staticmethod
    def _seconds_to_srt_time(seconds: float) -> str:
        """초 → SRT 타임스탬프 (HH:MM:SS,mmm)"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _get_audio_duration(self, path: str) -> float:
        """오디오 파일 길이 측정"""
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries',
                 'format=duration', '-of', 'csv=p=0', path],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
            )
            return float(result.stdout.strip())
        except Exception:
            try:
                from moviepy.editor import AudioFileClip
                clip = AudioFileClip(path)
                dur = clip.duration
                clip.close()
                return dur
            except Exception:
                return 30.0  # 폴백


class ShoppingFFmpegComposer:
    """소스영상 + TTS + SRT 자막을 FFmpeg로 합성하는 엔진

    레퍼런스 방식:
    1. 소스 영상을 9:16 (1080x1920)으로 크롭/스케일
    2. 원본 오디오 제거 또는 볼륨 대폭 감소
    3. TTS 오디오 오버레이
    4. SRT 자막 번인 (깔끔한 스타일)
    5. 59초 이내로 트리밍

    중복도 ZERO 편집 (튜브렌즈 3탄 기법):
    6. 미세 확대 (1.03~1.08배) — pHash 변경
    7. 미러링 (좌우반전) — 랜덤 적용
    8. 미세 속도 변경 (0.97~1.03) — 프레임 변경
    9. 미세 색상 보정 — 채도/밝기 미세 조정

    고급 기능 (튜브렌즈 3탄+4탄 추가):
    10. 다중 소스 영상 조합 — 여러 영상 쪼개기 + 타임라인 배치
    11. SFX 효과음 — 전환/후킹 포인트에 효과음 삽입
    12. 전환 효과 (fade/crossfade) — 클립 사이 자연스러운 전환
    """

    # SFX 효과음 디렉토리 (카테고리별)
    SFX_CATEGORIES = {
        "whooshh": "화면전환",
        "glitch": "글리치",
        "impact": "타격/임팩트",
        "reveal": "공개/반전",
        "click": "버튼/클릭",
    }

    def __init__(self, anti_duplicate: bool = True):
        self.encoder = self._detect_encoder()
        self.anti_duplicate = anti_duplicate  # 중복도 ZERO 편집 활성화
        self.sfx_dir = Path(__file__).parent / "sfx"  # 효과음 디렉토리
        log.info("FFmpeg 인코더: %s (anti_dup=%s)", self.encoder, anti_duplicate)

    def _detect_encoder(self) -> str:
        """GPU 인코더 감지 — 실제 인코딩 테스트로 검증"""
        for enc in [FFMPEG_ENCODER, 'h264_nvenc', 'h264_amf']:
            try:
                # 실제 작은 영상을 인코딩해서 검증 (color source → 파일)
                import tempfile
                test_out = os.path.join(tempfile.gettempdir(), f"enc_test_{enc}.mp4")
                r = subprocess.run(
                    ['ffmpeg', '-y', '-f', 'lavfi', '-i',
                     'color=c=black:s=128x128:d=0.5:r=30',
                     '-c:v', enc, '-frames:v', '10',
                     test_out],
                    capture_output=True, timeout=15,
                    encoding='utf-8', errors='replace',
                )
                if r.returncode == 0 and os.path.exists(test_out):
                    sz = os.path.getsize(test_out)
                    os.remove(test_out)
                    if sz > 100:  # 의미 있는 파일이 생성됐는지
                        return enc
            except Exception:
                continue
        return FFMPEG_ENCODER_FALLBACK  # libx264

    def compose(
        self,
        source_video: str,
        tts_audio: str,
        srt_file: str,
        output_path: str,
        max_duration: float = 59.0,
        keep_original_audio: bool = False,
        original_audio_volume: float = 0.05,
        bgm_enabled: bool = True,
        bgm_volume: float = 0.10,
        bgm_genre: str = "lofi",
        # ── 레퍼런스 스타일 파라미터 ──
        product_name: str = "",
        word_timings: list = None,
        hq_mode: bool = True,
        hook_text: str = "",
        intro_lines: list = None,
    ) -> str:
        """소스영상 + TTS + BGM + 자막 합성 — 레퍼런스 스타일

        레퍼런스 모드 (기본 ON):
        - 풀프레임: 영상이 1080x1920 전체를 채움 (블랙바 없음)
        - 인트로: 0~2초 대형 타이틀 (흰+노랑+흰)
        - 자막: 상단 1/3에 흰색 볼드 + 두꺼운 아웃라인 오버레이
        - 오디오: 원본 뮤트 → TTS 더빙 + BGM으로 완전 교체
        - anti-duplicate 비활성 (wash_video()가 이미 처리)

        Args:
            source_video: 소스 영상 파일
            tts_audio: TTS 나레이션 MP3
            srt_file: SRT 자막 파일
            output_path: 출력 파일
            max_duration: 최대 길이 (초)
            keep_original_audio: 원본 오디오 유지 (기본 False=뮤트)
            original_audio_volume: 원본 오디오 볼륨 (0.0~1.0)
            bgm_enabled: BGM 배경음 추가 여부
            bgm_volume: BGM 볼륨 (0.0~1.0)
            bgm_genre: BGM 장르 (lofi, upbeat, chill)
            product_name: 상품명 (인트로 타이틀 + 자막용)
            word_timings: TTS 단어별 타이밍 (자막 싱크용)
            hq_mode: 레퍼런스 스타일 모드 (기본 True)
            hook_text: 인트로 후크 텍스트 (빈 값이면 자동 생성)
            intro_lines: 인트로 타이틀 3줄 (빈 값이면 상품명에서 자동)

        Returns:
            출력 파일 경로
        """
        ensure_dir(Path(output_path).parent)

        # 1. 소스 영상 정보 확인
        src_info = self._probe_video(source_video)
        src_dur = src_info.get("duration", 60.0)

        # TTS 길이 확인
        tts_dur = self._get_duration(tts_audio)

        # 최종 영상 길이 = min(TTS 길이 + 여유, 소스 길이, max_duration)
        final_dur = min(tts_dur + 1.5, src_dur, max_duration)

        log.info(
            "합성 시작: source=%.1fs, tts=%.1fs, final=%.1fs, encoder=%s, hq=%s, bgm=%s",
            src_dur, tts_dur, final_dur, self.encoder, hq_mode,
            f"{bgm_genre}@{bgm_volume}" if bgm_enabled else "OFF"
        )

        # 한글 경로 문제 회피: 소스/TTS를 temp에 복사
        import shutil
        temp_dir = tempfile.mkdtemp(prefix="shorts_hq_")
        temp_src = os.path.join(temp_dir, "source.mp4")
        temp_tts = os.path.join(temp_dir, "tts.mp3")
        shutil.copy2(source_video, temp_src)
        shutil.copy2(tts_audio, temp_tts)

        # BGM 파일 준비
        temp_bgm = None
        if bgm_enabled:
            bgm_dir = Path(__file__).parent / "bgm"
            bgm_file = bgm_dir / f"{bgm_genre}.wav"
            if not bgm_file.exists():
                fallback_map = {"cinematic": "chill", "dramatic": "chill",
                                "energetic": "upbeat", "trendy": "upbeat"}
                alt = fallback_map.get(bgm_genre, "lofi")
                bgm_file = bgm_dir / f"{alt}.wav"
            if bgm_file.exists():
                temp_bgm = os.path.join(temp_dir, "bgm.wav")
                shutil.copy2(str(bgm_file), temp_bgm)
                log.info("BGM 파일 사용: %s (vol=%.2f)", bgm_file.name, bgm_volume)
            else:
                log.warning("BGM 파일 미발견, BGM 없이 합성")

        # 2. ASS 자막 생성 (인트로 타이틀 + 상단 자막 오버레이)
        temp_ass = None
        if hq_mode and (word_timings or srt_file or product_name):
            try:
                ass_content = self._generate_typing_ass(
                    word_timings=word_timings,
                    srt_file=srt_file,
                    product_name=product_name,
                    total_duration=final_dur,
                    hook_text=hook_text,
                    intro_lines=intro_lines,
                )
                temp_ass = os.path.join(temp_dir, "typing.ass")
                with open(temp_ass, 'w', encoding='utf-8-sig') as f:
                    f.write(ass_content)
                log.info("레퍼런스 스타일 ASS 생성 완료: %s", temp_ass)
            except Exception as e:
                log.warning("ASS 자막 생성 실패, SRT 폴백: %s", e)
                temp_ass = None

        # 3. 비디오 필터 체인 구성
        if hq_mode:
            vf_chain = self._build_hq_video_filter(temp_ass, srt_file, temp_dir)
        else:
            vf_chain = self._build_legacy_video_filter(
                src_info.get("width", 1080), src_info.get("height", 1920), srt_file
            )

        # 4. FFmpeg filter_complex 구성 (비디오 + 오디오 통합)
        fc_parts = []

        # 비디오 체인
        fc_parts.append(f"[0:v]{vf_chain}[vout]")

        # 오디오 체인
        audio_out = "[aout]"
        if temp_bgm:
            if keep_original_audio:
                fc_parts.append(f"[0:a]volume={original_audio_volume}[orig]")
                fc_parts.append(f"[1:a]volume=1.0[tts]")
                fc_parts.append(
                    f"[2:a]volume={bgm_volume},"
                    f"afade=t=out:st={max(0, final_dur - 2.0):.1f}:d=2.0[bgm]"
                )
                fc_parts.append(
                    f"[orig][tts][bgm]amix=inputs=3:duration=first:dropout_transition=2{audio_out}"
                )
            else:
                fc_parts.append(f"[1:a]volume=1.0[tts]")
                fc_parts.append(
                    f"[2:a]volume={bgm_volume},"
                    f"afade=t=out:st={max(0, final_dur - 2.0):.1f}:d=2.0[bgm]"
                )
                fc_parts.append(
                    f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=2{audio_out}"
                )
        elif keep_original_audio:
            fc_parts.append(f"[0:a]volume={original_audio_volume}[bg]")
            fc_parts.append(f"[1:a]volume=1.0[tts]")
            fc_parts.append(f"[bg][tts]amix=inputs=2:duration=first{audio_out}")
        else:
            audio_out = None  # TTS만 직접 매핑

        # 5. FFmpeg 명령 구성
        cmd = ['ffmpeg', '-y']
        cmd += ['-i', temp_src]       # [0] 소스 영상
        cmd += ['-i', temp_tts]       # [1] TTS 오디오
        if temp_bgm:
            cmd += ['-i', temp_bgm]   # [2] BGM 오디오

        cmd += ['-filter_complex', ';'.join(fc_parts)]
        cmd += ['-map', '[vout]']

        if audio_out:
            cmd += ['-map', audio_out]
        else:
            cmd += ['-map', '1:a']

        # 인코딩 설정 (HQ 최적화)
        cmd += ['-c:v', self.encoder]
        if self.encoder == 'h264_nvenc':
            cmd += ['-preset', 'p7', '-rc', 'vbr', '-cq', '16']  # p4→p7, CRF 18→16
        elif self.encoder == 'h264_amf':
            cmd += ['-quality', 'quality']
        else:
            cmd += ['-preset', 'slow', '-crf', '15']

        cmd += [
            '-c:a', 'aac',
            '-b:a', '256k',
            '-ar', '44100',
            '-ac', '2',
            '-b:v', '20M',      # 18M→20M 비트레이트 향상
            '-maxrate', '25M',   # 22M→25M
            '-bufsize', '40M',   # 36M→40M
            '-t', str(final_dur),
            '-movflags', '+faststart',
            '-shortest',
            output_path,
        ]

        log.info("FFmpeg HQ 명령: %s", ' '.join(cmd[:12]) + '...')

        # 6. 실행
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=600,
        )

        # 정리
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        if result.returncode != 0:
            log.error("FFmpeg HQ 실패: %s", result.stderr[-800:] if result.stderr else "")
            # 레거시 모드로 폴백
            return self._compose_legacy_fallback(
                source_video, tts_audio, srt_file, output_path, final_dur,
                keep_original_audio, original_audio_volume,
                bgm_enabled, bgm_volume, bgm_genre,
            )

        if os.path.exists(output_path):
            sz = os.path.getsize(output_path) / (1024 * 1024)
            log.info("✅ HQ 합성 완료: %s (%.1fMB)", output_path, sz)
            return output_path

        return ""

    # ═══════════════════════════════════════════════════════════════════════
    # HQ 3단 레이아웃 메서드
    # ═══════════════════════════════════════════════════════════════════════

    def _build_hq_video_filter(
        self, ass_file: str = None, srt_file: str = None, temp_dir: str = None,
    ) -> str:
        """레퍼런스 스타일 비디오 필터 (풀프레임 + 자막 오버레이)

        구조:
        ┌──────────────────────┐ ← y=0
        │                      │
        │    풀프레임 영상      │ 1920px
        │   (1080x1920 꽉채움) │ ← 블랙바 없음!
        │                      │
        │  [상단 자막 오버레이] │ ← y≈320 (1/6 지점)
        │                      │
        └──────────────────────┘ ← y=1920

        레퍼런스: @살림남 — 영상이 전체 프레임을 채우고,
        자막은 상단 영역에 흰색 볼드+아웃라인으로 직접 오버레이
        """
        filters = []

        # 1. 소스 영상을 풀프레임으로 스케일 (커버 모드)
        filters.append(
            f"scale={HQ_CANVAS_W}:{HQ_CANVAS_H}:"
            f"force_original_aspect_ratio=increase"
        )
        # 2. 정확히 9:16 크기로 크롭 (넘치는 부분 잘라냄)
        filters.append(f"crop={HQ_CANVAS_W}:{HQ_CANVAS_H}")

        # 3. ASS 자막 적용 (인트로 타이틀 + 본편 자막)
        if ass_file and os.path.exists(ass_file):
            ass_escaped = ass_file.replace('\\', '/').replace(':', '\\:')
            filters.append(f"ass='{ass_escaped}'")
        elif srt_file:
            # ASS 실패 시 SRT 폴백 (상단 자막)
            import shutil
            temp_srt = os.path.join(
                temp_dir or tempfile.gettempdir(), "shorts_sub.srt"
            )
            shutil.copy2(srt_file, temp_srt)
            srt_escaped = temp_srt.replace('\\', '/').replace(':', '\\:')
            subtitle_style = (
                f"FontName={HQ_FONT},"
                f"FontSize={HQ_SUBTITLE_FONTSIZE},"
                f"PrimaryColour=&Hffffff,"
                f"OutlineColour=&H000000,"
                f"Outline={HQ_SUBTITLE_OUTLINE},"
                f"Shadow={HQ_SUBTITLE_SHADOW},"
                f"MarginV={HQ_SUBTITLE_MARGIN_TOP},"
                f"Bold=1,"
                f"Alignment=8"  # 8 = top-center (상단 중앙)
            )
            filters.append(
                f"subtitles='{srt_escaped}':force_style='{subtitle_style}'"
            )

        return ','.join(filters)

    def _generate_typing_ass(
        self,
        word_timings: list = None,
        srt_file: str = None,
        product_name: str = "",
        total_duration: float = 30.0,
        hook_text: str = "",
        intro_lines: list = None,
    ) -> str:
        """ASS 자막 생성 — 레퍼런스 스타일 (인트로 타이틀 + 상단 자막)

        레퍼런스(@살림남) 분석 결과:
        1. 인트로 (0~2초): 대형 타이틀 (흰+노랑+흰 3줄) + 작은 후크 텍스트
        2. 본편 (2초~): 상단 1/3 위치에 흰색 볼드 자막 (배경 없이 오버레이)

        Args:
            word_timings: TTS 단어별 타이밍 [{offset, duration, text}, ...]
            srt_file: SRT 파일 경로 (word_timings 없을 때 폴백)
            product_name: 상품명 (인트로 타이틀용)
            hook_text: 후크 텍스트 (인트로 상단 작은 글씨)
            intro_lines: 인트로 타이틀 3줄 리스트 (없으면 상품명에서 자동 생성)
            total_duration: 총 영상 길이

        Returns:
            ASS 파일 내용 문자열
        """
        events = []
        intro_end = HQ_INTRO_DURATION

        # ═══ 인트로 타이틀 (0~2초) — 썸네일/첫인상 ═══
        if product_name:
            title = self._clean_title(product_name, max_len=40)
            intro_end_t = self._ass_time(intro_end)

            # 인트로 3줄 텍스트 생성 (사용자 지정 또는 자동)
            if intro_lines and len(intro_lines) >= 2:
                lines = intro_lines
            else:
                lines = self._generate_intro_lines(title)

            # 후크 텍스트 (상단 작은 글씨 + 반투명 배경)
            if hook_text:
                hook = hook_text
            else:
                hook = f"지금 쿠팡에서 확인해보세요! 🔥"
            # {\an8} = 상단 중앙, \pos로 정확한 위치 지정
            # \bord0 + \shad0 + \3c&H80000000 = 반투명 배경 박스 효과
            events.append(
                f"Dialogue: 2,0:00:00.00,{intro_end_t},IntroHook,,0,0,0,,"
                f"{{\\an8\\pos(540,280)}}{hook}"
            )

            # 메인 타이틀 (3줄: 흰-노랑-흰)
            y_start = 440  # 타이틀 시작 Y (400→440, 좀 더 아래로)
            line_gap = 120  # 줄 간격 (100→120, 더 넓게)
            for i, line in enumerate(lines[:3]):
                y_pos = y_start + (i * line_gap)
                if i == 1:
                    # 2번째 줄: 노란색 강조 (레퍼런스 핵심!)
                    # \\1c 로 PrimaryColour를 직접 노란색으로 오버라이드
                    events.append(
                        f"Dialogue: 2,0:00:00.00,{intro_end_t},IntroYellow,,0,0,0,,"
                        f"{{\\an5\\pos(540,{y_pos})\\1c{HQ_YELLOW_COLOR}}}{line}"
                    )
                else:
                    events.append(
                        f"Dialogue: 2,0:00:00.00,{intro_end_t},IntroWhite,,0,0,0,,"
                        f"{{\\an5\\pos(540,{y_pos})}}{line}"
                    )

        # ═══ 본편 자막 (인트로 이후~끝) — 상단 오버레이 ═══
        # \pos(540, Y) 으로 정확한 위치 지정 (스타일 MarginV 무시 방지)
        sub_y = HQ_SUBTITLE_MARGIN_TOP  # 상단에서의 거리

        if word_timings:
            # 단어 타이밍으로 싱크 자막 생성
            chunks = self._group_words_to_chunks(word_timings)
            for chunk in chunks:
                start = chunk[0]["offset"]
                end = chunk[-1]["offset"] + chunk[-1]["duration"] + 0.15
                # 자막 텍스트 결합
                text_parts = []
                for i, wt in enumerate(chunk):
                    text_parts.append(wt["text"])
                sub_text = ' '.join(text_parts)
                events.append(
                    f"Dialogue: 0,{self._ass_time(start)},"
                    f"{self._ass_time(end)},Sub,,0,0,0,,"
                    f"{{\\an8\\pos(540,{sub_y})}}{sub_text}"
                )
        elif srt_file and os.path.exists(srt_file):
            # SRT 파싱 폴백
            srt_entries = self._parse_srt(srt_file)
            for entry in srt_entries:
                events.append(
                    f"Dialogue: 0,{self._ass_time(entry['start'])},"
                    f"{self._ass_time(entry['end'])},Sub,,0,0,0,,"
                    f"{{\\an8\\pos(540,{sub_y})}}{entry['text']}"
                )

        return self._ass_header(total_duration) + '\n'.join(events) + '\n'

    def _generate_intro_lines(self, product_name: str) -> list:
        """상품명에서 인트로 타이틀 3줄 자동 생성

        패턴 (레퍼런스):
        - "가족 건강 챙기는 / 해외 필수 품목 / BEST 3"
        - "쿠팡에 찾은 / 후기로 증명한 / BEST 5"

        우리 패턴:
        - "쿠팡에서 찾은" / "{상품명}" / "리뷰 BEST"
        """
        title = self._clean_title(product_name, max_len=16)
        return [
            "쿠팡에서 찾은",
            title,
            "리뷰 BEST 🔥",
        ]

    def _ass_header(self, total_duration: float = 30.0) -> str:
        """ASS 파일 헤더 — 레퍼런스 스타일

        스타일 구성:
        1. Sub: 본편 자막 (상단 1/3, 흰색 볼드 + 다크 아웃라인)
        2. IntroWhite: 인트로 메인 타이틀 흰색 줄
        3. IntroYellow: 인트로 강조 줄 (노란색)
        4. IntroHook: 인트로 후크 텍스트 (작은 흰색)
        """
        # 폰트: NanumSquareRound → Malgun Gothic 폴백
        font = HQ_FONT
        return (
            "[Script Info]\n"
            "Title: Shopping Shorts Reference Style\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {HQ_CANVAS_W}\n"
            f"PlayResY: {HQ_CANVAS_H}\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            # ── Sub: 본편 자막 ──
            # 상단 중앙(8), 흰색, 볼드, 두꺼운 아웃라인
            # 레퍼런스: 배경 없이 영상 위 직접 오버레이
            f"Style: Sub,{font},{HQ_SUBTITLE_FONTSIZE},"
            f"&H00FFFFFF,&H00FFFFFF,&H00333333,&H00000000,"
            f"-1,0,0,0,100,100,2,0,1,"
            f"{HQ_SUBTITLE_OUTLINE},{HQ_SUBTITLE_SHADOW},"
            f"8,40,40,{HQ_SUBTITLE_MARGIN_TOP},1\n"
            # ── IntroWhite: 인트로 흰색 타이틀 ──
            # 화면 중앙(5), 초대형, Extra Bold
            f"Style: IntroWhite,{font},{HQ_INTRO_TITLE_SIZE},"
            f"&H00FFFFFF,&H00FFFFFF,&H00222222,&H00000000,"
            f"-1,0,0,0,100,100,1,0,1,"
            f"{HQ_INTRO_TITLE_OUTLINE},{HQ_INTRO_TITLE_SHADOW},"
            f"5,20,20,0,1\n"
            # ── IntroYellow: 인트로 노란색 강조 ──
            # 레퍼런스 핵심: 2번째 줄을 노란색으로!
            f"Style: IntroYellow,{font},{HQ_INTRO_TITLE_SIZE},"
            f"{HQ_YELLOW_COLOR},&H00FFFFFF,&H00222222,&H00000000,"
            f"-1,0,0,0,100,100,1,0,1,"
            f"{HQ_INTRO_TITLE_OUTLINE},{HQ_INTRO_TITLE_SHADOW},"
            f"5,20,20,0,1\n"
            # ── IntroHook: 후크 텍스트 ──
            # 작은 흰색, 반투명 배경 바 효과 (BorderStyle=3)
            f"Style: IntroHook,{font},{HQ_INTRO_HOOK_SIZE},"
            f"&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
            f"-1,0,0,0,100,100,0,0,3,"
            f"15,0,"
            f"8,30,30,0,1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text\n"
        )

    def _group_words_to_chunks(self, word_timings: list) -> list:
        """단어 타이밍을 자막 청크로 그룹핑 (15자 기준)"""
        chunks = []
        current = []
        current_text = ""

        for wt in word_timings:
            word = wt["text"]
            if current_text:
                current_text += " " + word
            else:
                current_text = word
            current.append(wt)

            should_break = (
                len(current_text) >= 15
                or word.rstrip().endswith(('.', '!', '?', '。'))
                or (word.rstrip().endswith((',', '，')) and len(current_text) >= 10)
            )

            if should_break and current_text.strip():
                chunks.append(current[:])
                current = []
                current_text = ""

        if current:
            chunks.append(current[:])

        return chunks

    def _parse_srt(self, srt_path: str) -> list:
        """SRT 파일을 파싱하여 엔트리 리스트 반환"""
        entries = []
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            blocks = content.strip().split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    time_line = lines[1]
                    parts = time_line.split(' --> ')
                    if len(parts) == 2:
                        start = self._srt_time_to_seconds(parts[0].strip())
                        end = self._srt_time_to_seconds(parts[1].strip())
                        text = ' '.join(lines[2:])
                        entries.append({"start": start, "end": end, "text": text})
        except Exception as e:
            log.warning("SRT 파싱 실패: %s", e)
        return entries

    def _srt_time_to_seconds(self, time_str: str) -> float:
        """SRT 타임코드 → 초 변환 (00:00:01,500 → 1.5)"""
        time_str = time_str.replace(',', '.')
        parts = time_str.split(':')
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        return 0.0

    @staticmethod
    def _ass_time(seconds: float) -> str:
        """초 → ASS 타임코드 (H:MM:SS.CC)"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    def _clean_title(product_name: str, max_len: int = 28) -> str:
        """상품명을 제목용으로 정리 (모델번호 제거, 길이 제한)"""
        # 모델번호 패턴 제거 (영문+숫자 조합)
        cleaned = re.sub(r'[A-Z]{1,3}\d{3,}\w*', '', product_name)
        # 연속 공백 정리
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if not cleaned:
            cleaned = product_name
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len] + '…'
        return cleaned

    # ═══════════════════════════════════════════════════════════════════════
    # 레거시 호환 메서드
    # ═══════════════════════════════════════════════════════════════════════

    def _build_legacy_video_filter(
        self, src_w: int, src_h: int, srt_file: str
    ) -> str:
        """레거시 비디오 필터 (9:16 크롭 + 자막, anti-duplicate 제거)"""
        filters = []
        target_w, target_h = 1080, 1920

        # 스케일 + 크롭
        filters.append(
            f"scale={target_w}:{target_h}:"
            f"force_original_aspect_ratio=increase"
        )
        filters.append(f"crop={target_w}:{target_h}")

        # SRT 자막
        if srt_file and os.path.exists(srt_file):
            import shutil
            temp_srt = os.path.join(tempfile.gettempdir(), "shorts_sub.srt")
            shutil.copy2(srt_file, temp_srt)
            srt_escaped = temp_srt.replace('\\', '/').replace(':', '\\:')
            subtitle_style = (
                f"FontName={SUBTITLE_FONT},"
                f"FontSize={SUBTITLE_FONTSIZE},"
                f"PrimaryColour={SUBTITLE_COLOR},"
                f"OutlineColour={SUBTITLE_OUTLINE_COLOR},"
                f"Outline={SUBTITLE_OUTLINE},"
                f"Shadow={SUBTITLE_SHADOW},"
                f"MarginV={SUBTITLE_MARGIN_V},"
                f"Bold=1,Alignment=2"
            )
            filters.append(
                f"subtitles='{srt_escaped}':force_style='{subtitle_style}'"
            )

        return ','.join(filters)

    def _compose_legacy_fallback(
        self, source_video, tts_audio, srt_file, output_path, duration,
        keep_original_audio, original_audio_volume,
        bgm_enabled, bgm_volume, bgm_genre,
    ) -> str:
        """HQ 실패 시 레거시 방식으로 폴백"""
        log.warning("HQ 합성 실패, 레거시 모드로 폴백")
        import shutil
        temp_dir = tempfile.mkdtemp(prefix="shorts_fb_")
        temp_src = os.path.join(temp_dir, "source.mp4")
        temp_tts = os.path.join(temp_dir, "tts.mp3")
        shutil.copy2(source_video, temp_src)
        shutil.copy2(tts_audio, temp_tts)

        # 간단한 합성 (크롭+스케일 + TTS + 자막)
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        if srt_file and os.path.exists(srt_file):
            temp_srt = os.path.join(temp_dir, "sub.srt")
            shutil.copy2(srt_file, temp_srt)
            srt_esc = temp_srt.replace('\\', '/').replace(':', '\\:')
            vf += (
                f",subtitles='{srt_esc}':force_style='"
                f"FontName={HQ_FONT},FontSize={HQ_SUBTITLE_FONTSIZE},"
                f"PrimaryColour=&Hffffff,OutlineColour=&H000000,"
                f"Outline={HQ_SUBTITLE_OUTLINE},Shadow={HQ_SUBTITLE_SHADOW},"
                f"MarginV=60,Bold=1,Alignment=2'"
            )

        cmd = [
            'ffmpeg', '-y',
            '-i', temp_src, '-i', temp_tts,
            '-filter_complex',
            f'[0:v]{vf}[vout]',
            '-map', '[vout]', '-map', '1:a',
            '-c:v', self.encoder, '-c:a', 'aac',
            '-b:a', '256k', '-b:v', '18M',
            '-t', str(duration), '-shortest',
            output_path,
        ]
        if self.encoder == 'h264_nvenc':
            cmd.insert(-1, '-preset')
            cmd.insert(-1, 'p6')

        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=300,
        )
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        if r.returncode == 0 and os.path.exists(output_path):
            sz = os.path.getsize(output_path) / (1024 * 1024)
            log.info("레거시 폴백 합성 완료: %s (%.1fMB)", output_path, sz)
            return output_path

        log.error("레거시 폴백도 실패: %s", r.stderr[-500:] if r.stderr else "")
        return ""

    # _compose_without_srt 제거됨 — _compose_legacy_fallback으로 통합

    def _probe_video(self, path: str) -> dict:
        """비디오 메타데이터 조회"""
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json',
                 '-show_format', '-show_streams', path],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
            )
            data = json.loads(result.stdout)
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    return {
                        "width": int(stream.get("width", 1080)),
                        "height": int(stream.get("height", 1920)),
                        "duration": float(
                            stream.get("duration") or
                            data.get("format", {}).get("duration", 60)
                        ),
                        "fps": eval(stream.get("r_frame_rate", "30/1")),
                    }
        except Exception as e:
            log.warning("ffprobe 실패: %s", e)
        return {"width": 1080, "height": 1920, "duration": 60.0, "fps": 30}

    def _get_duration(self, path: str) -> float:
        """파일 길이 조회"""
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries',
                 'format=duration', '-of', 'csv=p=0', path],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
            )
            return float(result.stdout.strip())
        except Exception:
            return 30.0

    # ── 다중 소스 영상 조합 (3탄 핵심: 여러 영상 쪼개기+배치) ──

    def concat_sources(
        self,
        source_videos: list[str],
        output_path: str,
        target_duration: float = 59.0,
        transition: str = "fade",  # fade, none
        transition_duration: float = 0.3,
    ) -> str:
        """여러 소스 영상을 쪼개서 하나로 조합 (중복도 ZERO 극대화)

        튜브렌즈 3탄 핵심: 하나의 소스가 아닌 여러 소스를 짧게 쪼개서 타임라인 배치
        - 각 클립에 서로 다른 중복도ZERO 편집 적용
        - 클립 사이 전환 효과 (fade/crossfade)

        Args:
            source_videos: 소스 영상 파일 리스트 (2개 이상)
            output_path: 출력 파일 경로
            target_duration: 목표 길이 (초)
            transition: 전환 효과 종류
            transition_duration: 전환 효과 길이 (초)

        Returns:
            합성된 영상 파일 경로
        """
        if not source_videos or len(source_videos) < 2:
            log.warning("다중 소스 조합: 영상 2개 이상 필요 (단일 소스 반환)")
            return source_videos[0] if source_videos else ""

        ensure_dir(Path(output_path).parent)
        import shutil

        # 각 클립의 길이 계산
        n = len(source_videos)
        clip_dur = target_duration / n

        temp_dir = tempfile.mkdtemp(prefix="multi_src_")
        clip_paths = []

        for i, src in enumerate(source_videos):
            # 각 소스에서 랜덤 구간 추출 + 개별 중복도ZERO 적용
            src_dur = self._get_duration(src)
            max_start = max(0, src_dur - clip_dur - 1)
            start_time = random.uniform(0, max_start) if max_start > 0 else 0

            clip_out = os.path.join(temp_dir, f"clip_{i:02d}.mp4")

            # 각 클립마다 다른 중복도 편집 적용
            vf = self._build_clip_filter(i)

            cmd = [
                'ffmpeg', '-y',
                '-ss', f'{start_time:.2f}',
                '-i', src,
                '-t', f'{clip_dur:.2f}',
                '-vf', vf,
                '-an',  # 오디오 제거 (나중에 TTS 입힘)
                '-c:v', self.encoder,
                '-b:v', '18M',
                clip_out,
            ]
            if self.encoder == 'h264_nvenc':
                cmd.insert(-1, '-preset')
                cmd.insert(-1, FFMPEG_PRESET)

            r = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=120,
            )
            if r.returncode == 0 and os.path.exists(clip_out):
                clip_paths.append(clip_out)
                log.info("클립 %d/%d 생성: %.1fs from %s", i+1, n, clip_dur, Path(src).name)
            else:
                log.warning("클립 %d 생성 실패: %s", i+1, r.stderr[-200:] if r.stderr else "")

        if not clip_paths:
            return ""

        # concat demuxer로 클립 합치기
        concat_file = os.path.join(temp_dir, "concat.txt")
        with open(concat_file, 'w', encoding='utf-8') as f:
            for cp in clip_paths:
                f.write(f"file '{cp}'\n")

        # 전환 효과 적용
        if transition == "fade" and len(clip_paths) > 1:
            # xfade 필터로 크로스페이드
            result = self._concat_with_fade(clip_paths, output_path, clip_dur, transition_duration)
        else:
            # 단순 concat
            cmd_concat = [
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', concat_file,
                '-c:v', self.encoder, '-b:v', '18M',
                '-t', str(target_duration),
                output_path,
            ]
            r = subprocess.run(
                cmd_concat, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=180,
            )
            result = output_path if (r.returncode == 0 and os.path.exists(output_path)) else ""

        # 임시 파일 정리
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        if result:
            log.info("다중 소스 조합 완료: %d클립 → %s", len(clip_paths), Path(output_path).name)
        return result

    def _build_clip_filter(self, clip_index: int) -> str:
        """각 클립별 개별 중복도ZERO 필터 생성 (클립마다 다른 편집)"""
        filters = []
        target_w, target_h = 1080, 1920

        # 9:16 크롭+스케일 (기본)
        filters.append(f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2")

        if self.anti_duplicate:
            # 클립별로 다른 편집 적용 (다양성 극대화)
            zoom = random.uniform(1.02, 1.06)
            crop_w = int(target_w / zoom)
            crop_h = int(target_h / zoom)
            filters.append(f"crop={crop_w}:{crop_h}")
            filters.append(f"scale={target_w}:{target_h}")

            # 홀수 클립만 미러링 (다양성)
            if clip_index % 2 == 1:
                filters.append("hflip")

            # 색보정 (클립마다 다른 값)
            sat = random.uniform(0.96, 1.06)
            bri = random.uniform(-0.015, 0.02)
            con = random.uniform(0.98, 1.04)
            filters.append(f"eq=brightness={bri:.3f}:contrast={con:.2f}:saturation={sat:.2f}")

        return ','.join(filters)

    def _concat_with_fade(
        self, clips: list[str], output: str,
        clip_dur: float, fade_dur: float = 0.3
    ) -> str:
        """클립 간 crossfade 전환 효과"""
        # 간단한 concat+fade: 각 클립을 순차 concat 후 fade 효과
        # (FFmpeg xfade는 복잡하므로, 간단한 concat → fade in/out)
        import shutil
        temp_dir = tempfile.mkdtemp(prefix="fade_")
        faded_clips = []

        for i, clip in enumerate(clips):
            faded = os.path.join(temp_dir, f"faded_{i:02d}.mp4")
            vf_parts = []

            # 첫 클립 아닌 경우: fade in
            if i > 0:
                vf_parts.append(f"fade=t=in:st=0:d={fade_dur}")
            # 마지막 클립 아닌 경우: fade out
            if i < len(clips) - 1:
                fade_start = max(0, clip_dur - fade_dur - 0.1)
                vf_parts.append(f"fade=t=out:st={fade_start:.2f}:d={fade_dur}")

            if vf_parts:
                cmd = [
                    'ffmpeg', '-y', '-i', clip,
                    '-vf', ','.join(vf_parts),
                    '-c:v', self.encoder, '-b:v', '18M',
                    '-an', faded,
                ]
                r = subprocess.run(
                    cmd, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=60,
                )
                if r.returncode == 0:
                    faded_clips.append(faded)
                else:
                    faded_clips.append(clip)  # 실패시 원본 사용
            else:
                faded_clips.append(clip)

        # concat
        concat_file = os.path.join(temp_dir, "concat.txt")
        with open(concat_file, 'w', encoding='utf-8') as f:
            for fc in faded_clips:
                f.write(f"file '{fc}'\n")

        cmd_concat = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', concat_file,
            '-c:v', self.encoder, '-b:v', '18M',
            output,
        ]
        r = subprocess.run(
            cmd_concat, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=180,
        )

        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        return output if (r.returncode == 0 and os.path.exists(output)) else ""

    # ── SFX 효과음 시스템 (4탄: 전환/후킹 포인트 효과음) ──

    def add_sfx(
        self, video_path: str, output_path: str,
        sfx_points: list[dict] | None = None,
        auto_sfx: bool = True,
    ) -> str:
        """영상에 효과음(SFX) 삽입

        4탄 핵심: 전환/후킹/공개 포인트에 효과음 삽입으로 프로 퀄리티

        Args:
            video_path: 입력 영상
            output_path: 출력 영상
            sfx_points: 수동 효과음 포인트 [{"time": 3.0, "type": "whooshh"}, ...]
            auto_sfx: True면 자동으로 시작(0초)과 중간(50%)에 효과음 삽입

        Returns:
            출력 파일 경로
        """
        if not self.sfx_dir.exists():
            self.sfx_dir.mkdir(parents=True, exist_ok=True)
            log.info("SFX 디렉토리 생성: %s (효과음 파일을 넣어주세요)", self.sfx_dir)

        # 효과음 파일 탐색
        sfx_files = list(self.sfx_dir.glob("*.mp3")) + list(self.sfx_dir.glob("*.wav"))
        if not sfx_files:
            log.info("SFX 파일 없음 → 효과음 없이 진행 (%s에 파일 추가)", self.sfx_dir)
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path

        # 자동 SFX 포인트 생성
        if auto_sfx and not sfx_points:
            vid_dur = self._get_duration(video_path)
            sfx_points = [
                {"time": 0.0, "type": "whooshh"},       # 시작
                {"time": vid_dur * 0.45, "type": "reveal"},  # 중간 후킹
            ]

        if not sfx_points:
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path

        # FFmpeg로 SFX 오버레이
        import shutil
        temp_dir = tempfile.mkdtemp(prefix="sfx_")

        # 영상 복사
        temp_vid = os.path.join(temp_dir, "input.mp4")
        shutil.copy2(video_path, temp_vid)

        # 가장 적합한 SFX 파일 선택
        cmd = ['ffmpeg', '-y', '-i', temp_vid]
        filter_parts = []
        sfx_inputs = []

        for i, point in enumerate(sfx_points):
            # 카테고리별 SFX 파일 매칭
            sfx_type = point.get("type", "whooshh")
            matched = [f for f in sfx_files if sfx_type.lower() in f.stem.lower()]
            if not matched:
                matched = sfx_files  # 없으면 아무거나
            sfx = random.choice(matched)

            temp_sfx = os.path.join(temp_dir, f"sfx_{i}.wav")
            shutil.copy2(str(sfx), temp_sfx)
            cmd += ['-i', temp_sfx]
            sfx_inputs.append((i + 1, point["time"]))  # input index, timestamp

        # 오디오 필터: 각 SFX를 지정 시간에 배치 + 원본 오디오와 믹스
        amix_parts = ["[0:a]volume=1.0[main]"]
        mix_labels = ["[main]"]

        for idx, (input_idx, time_sec) in enumerate(sfx_inputs):
            label = f"sfx{idx}"
            amix_parts.append(
                f"[{input_idx}:a]volume=0.4,adelay={int(time_sec * 1000)}|{int(time_sec * 1000)}[{label}]"
            )
            mix_labels.append(f"[{label}]")

        filter_str = ';'.join(amix_parts) + ';'
        filter_str += ''.join(mix_labels) + f'amix=inputs={len(mix_labels)}:duration=first[aout]'

        cmd += [
            '-filter_complex', filter_str,
            '-map', '0:v', '-map', '[aout]',
            '-c:v', 'copy',  # 비디오 재인코딩 불필요
            '-c:a', 'aac', '-b:a', '256k',
            output_path,
        ]

        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=120,
        )

        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        if r.returncode == 0 and os.path.exists(output_path):
            log.info("SFX 삽입 완료: %d개 효과음 → %s", len(sfx_points), Path(output_path).name)
            return output_path

        log.warning("SFX 삽입 실패, 원본 유지: %s", r.stderr[-200:] if r.stderr else "")
        shutil.copy2(video_path, output_path)
        return output_path


class ShoppingShortsPipeline:
    """쇼핑쇼츠 풀 파이프라인

    URL → 다운로드 → 대본 → TTS+SRT → 합성 → (업로드)

    Usage:
        pipeline = ShoppingShortsPipeline(skip_upload=True)
        result = pipeline.run(
            video_url="https://v.douyin.com/xxxxx",
            product_name="접이식 신발건조기",
        )
    """

    def __init__(
        self,
        skip_upload: bool = False,
        voice: str = TTS_VOICE,
        rate: str = TTS_RATE,
    ):
        self.skip_upload = skip_upload
        self.voice = voice
        self.rate = rate
        self._output_dir = ensure_dir(RENDER_OUTPUT_DIR)
        log.info("ShoppingShortsPipeline 초기화 (skip_upload=%s)", skip_upload)

    def run(
        self,
        product_name: str,
        video_url: str = "",
        local_video: str = "",
        product_info: str = "",
        voice: str = "",
        coupang_link: str = "",
    ) -> dict:
        """풀 파이프라인 실행

        Args:
            product_name: 상품명
            video_url: 도우인/틱톡 등 영상 URL
            local_video: 로컬 영상 파일
            product_info: 추가 상품 정보
            voice: TTS 음성 (기본: 여성)
            coupang_link: 쿠팡 파트너스 링크

        Returns:
            {
                "video_path": str,
                "srt_path": str,
                "audio_path": str,
                "script": dict,
                "duration": float,
                "campaign_dir": str,
            }
        """
        campaign_id = uuid.uuid4().hex[:8]
        campaign_dir = ensure_dir(WORK_DIR / f"shorts_{campaign_id}")
        start_time = time.time()

        print("\n" + "=" * 60)
        print("  쇼핑쇼츠 팩토리 v1.0")
        print("=" * 60)
        print(f"  캠페인   : {campaign_id}")
        print(f"  상품     : {product_name}")
        print(f"  영상소스 : {video_url or local_video or '없음'}")
        print("=" * 60 + "\n")

        result = {
            "campaign_id": campaign_id,
            "video_path": "",
            "srt_path": "",
            "audio_path": "",
            "script": {},
            "source_video": "",
            "duration": 0.0,
            "campaign_dir": str(campaign_dir),
        }

        # ── Step 1: 소스 영상 확보 ──
        print("[1/4] 소스 영상 확보...")
        source_video = self._get_source_video(
            video_url, local_video, campaign_dir
        )
        if not source_video:
            print("  [!] 소스 영상 없음 - 중단")
            return result
        result["source_video"] = source_video
        sz = os.path.getsize(source_video) / (1024 * 1024)
        print(f"  > 소스 영상: {Path(source_video).name} ({sz:.1f}MB)")

        # ── Step 2: AI 대본 생성 ──
        print("\n[2/4] AI 대본 생성...")
        script_gen = ShoppingScriptGenerator()
        script = script_gen.generate(product_name, product_info)
        result["script"] = script
        print(f"  > 훅: {script['hook']}")
        print(f"  > 대본: {len(script['script'])}문장")
        for i, line in enumerate(script['script']):
            print(f"    [{i+1}] {line}")

        # ── Step 3: TTS + SRT 생성 ──
        print(f"\n[3/4] TTS 나레이션 + SRT 자막 생성 (배속: {self.rate})...")
        tts_gen = EdgeTTSWithSRT(
            voice=voice or self.voice,
            rate=self.rate,
        )
        tts_result = tts_gen.generate(
            script_lines=script["script"],
            output_dir=str(campaign_dir),
            filename_prefix=f"tts_{campaign_id}",
        )
        result["audio_path"] = tts_result["audio_path"]
        result["srt_path"] = tts_result["srt_path"]
        result["duration"] = tts_result["duration"]
        print(f"  > 오디오: {Path(tts_result['audio_path']).name} ({tts_result['duration']:.1f}초)")
        print(f"  > 자막: {Path(tts_result['srt_path']).name}")

        # ── Step 4: FFmpeg 합성 ──
        print("\n[4/4] FFmpeg 합성 (소스영상 + TTS + 자막)...")
        output_path = str(self._output_dir / f"shorts_{campaign_id}.mp4")

        composer = ShoppingFFmpegComposer(anti_duplicate=False)  # wash_video()가 처리
        final_video = composer.compose(
            source_video=source_video,
            tts_audio=tts_result["audio_path"],
            srt_file=tts_result["srt_path"],
            output_path=output_path,
            max_duration=59.0,
            product_name=product_name,
            word_timings=tts_result.get("word_timings"),
            hq_mode=True,
        )
        result["video_path"] = final_video

        if final_video and os.path.exists(final_video):
            sz = os.path.getsize(final_video) / (1024 * 1024)
            print(f"  > 완성: {Path(final_video).name} ({sz:.1f}MB)")
        else:
            print("  > [!] 합성 실패")

        # ── 완료 ──
        elapsed = time.time() - start_time
        print(f"\n{'=' * 60}")
        print(f"  쇼핑쇼츠 완성! (소요: {elapsed:.1f}초)")
        print(f"  출력: {final_video or '실패'}")
        print(f"  캠페인: {campaign_dir}")
        print(f"{'=' * 60}\n")

        return result

    def _get_source_video(
        self,
        video_url: str,
        local_video: str,
        campaign_dir: Path,
    ) -> Optional[str]:
        """소스 영상 확보 (URL 다운로드 또는 로컬 파일)"""
        # 로컬 파일
        if local_video and os.path.exists(local_video):
            log.info("로컬 영상 사용: %s", local_video)
            return local_video

        # URL 다운로드
        if video_url:
            try:
                from affiliate_system.dual_deployer import VideoExtractor
                extractor = VideoExtractor(output_dir=str(campaign_dir / "source"))
                path = extractor.extract_video(video_url)
                if path and os.path.exists(path):
                    return path
            except Exception as e:
                log.error("영상 다운로드 실패: %s", e)

        return None


# ── CLI ──
def main():
    parser = argparse.ArgumentParser(
        description="쇼핑쇼츠 팩토리 — 소스영상 + AI나레이션 + 자막 자동 합성"
    )
    parser.add_argument("--product", "-p", required=True, help="상품명")
    parser.add_argument("--video", "-v", default="", help="소스 영상 URL 또는 로컬 파일")
    parser.add_argument("--info", "-i", default="", help="추가 상품 정보")
    parser.add_argument("--voice", default="", help="TTS 음성 (ko-KR-SunHiNeural)")
    parser.add_argument("--rate", default=TTS_RATE, help="TTS 배속 (기본: +20%%)")
    parser.add_argument("--coupang-link", default="", help="쿠팡 파트너스 링크")
    parser.add_argument("--skip-upload", action="store_true", help="업로드 건너뛰기")

    args = parser.parse_args()

    # 로컬 파일 vs URL 판별
    video_url = ""
    local_video = ""
    if args.video:
        if os.path.exists(args.video):
            local_video = args.video
        else:
            video_url = args.video

    pipeline = ShoppingShortsPipeline(
        skip_upload=args.skip_upload,
        rate=args.rate,
    )

    result = pipeline.run(
        product_name=args.product,
        video_url=video_url,
        local_video=local_video,
        product_info=args.info,
        voice=args.voice,
        coupang_link=args.coupang_link,
    )

    if result["video_path"]:
        print(f"\n[OK] 쇼핑쇼츠 완성: {result['video_path']}")
    else:
        print("\n[FAIL] 쇼핑쇼츠 생성 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
