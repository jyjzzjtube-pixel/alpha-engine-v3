# -*- coding: utf-8 -*-
"""
AI Content Generator -- YJ Partners MCN & F&B Automation
=======================================================
Claude 3 + Gemini 전용 (OpenAI 미사용)

- Mode A (제휴 상품): 스크래핑된 상품 데이터 -> 훅/본문/해시태그/내레이션 생성
- Mode B (자사 브랜드 F&B): 브랜드별 페르소나 기반 프로모션 콘텐츠
- Mode C (MCN 대량 생산): 배치 처리, 다수 상품 일괄 콘텐츠 생성

모든 API 호출은 CostTracker를 통해 토큰/비용이 기록된다.
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

from affiliate_system.config import GEMINI_API_KEY, ANTHROPIC_API_KEY, AI_ROUTING
from affiliate_system.models import (
    Product, AIContent, Campaign, Platform,
    PlatformPreset, PLATFORM_PRESETS,
)
from affiliate_system.utils import setup_logger, retry
from api_cost_tracker import CostTracker

__all__ = [
    "AIGenerator",
    "BRAND_TEMPLATES",
    "CLAUDE_HAIKU",
    "CLAUDE_SONNET",
    "GEMINI_FLASH",
]

logger = setup_logger("ai_generator", "ai_generator.log")

# ── 모델 상수 ──
CLAUDE_HAIKU = "claude-3-haiku-20240307"
CLAUDE_SONNET = "claude-3-sonnet-20240229"
GEMINI_FLASH = "gemini-2.5-flash"

# ── 브랜드별 프롬프트 템플릿 ──
BRAND_TEMPLATES: dict[str, dict[str, str]] = {
    "오레노카츠": {
        "persona": (
            "당신은 일본 정통 돈카츠 전문점 '오레노카츠'의 브랜드 마케터입니다. "
            "바삭한 식감, 프리미엄 등심/안심 카츠, 장인의 정성을 강조하세요. "
            "톤은 정직하고 따뜻하되, 음식의 퀄리티에 대한 자부심이 드러나야 합니다."
        ),
        "keywords": "돈카츠, 등심카츠, 안심카츠, 일본식, 프리미엄, 수제, 바삭",
        "hashtag_prefix": "#오레노카츠 #돈카츠맛집 #일본식돈카츠",
    },
    "무사짬뽕": {
        "persona": (
            "당신은 정통 중화풍 짬뽕 전문점 '무사짬뽕'의 브랜드 마케터입니다. "
            "화끈한 불맛, 진한 해물 육수, 푸짐한 토핑을 강조하세요. "
            "톤은 활기차고 대담하며, 한 그릇의 만족감을 전달해야 합니다."
        ),
        "keywords": "짬뽕, 중화요리, 해물짬뽕, 불맛, 면요리, 얼큰",
        "hashtag_prefix": "#무사짬뽕 #짬뽕맛집 #중화요리",
    },
    "브릿지원": {
        "persona": (
            "당신은 프랜차이즈 컨설팅 전문 기업 '브릿지원(BRIDGE ONE)'의 마케터입니다. "
            "예비 창업자에게 신뢰감과 전문성을 전달하세요. "
            "성공 포트폴리오, 체계적인 지원 시스템, 합리적인 창업 비용을 강조하세요. "
            "톤은 전문적이되 따뜻하고, 함께 성장하자는 파트너십을 전달해야 합니다."
        ),
        "keywords": "프랜차이즈, 창업, 컨설팅, 성공창업, 브릿지원, 파트너",
        "hashtag_prefix": "#브릿지원 #프랜차이즈창업 #창업컨설팅",
    },
}


class AIGenerator:
    """AI 콘텐츠 생성기 (Claude 3 + Gemini)

    제휴 마케팅, 브랜드 콘텐츠, MCN 대량 생산을 위한 통합 AI 파이프라인.
    모든 호출은 CostTracker에 의해 비용이 추적된다.
    """

    def __init__(self):
        """AI 클라이언트 및 비용 추적기를 초기화한다."""
        self.tracker = CostTracker(project_name="affiliate_ai")
        self._total_cost_usd: float = 0.0

        # Anthropic 클라이언트 (lazy init)
        self._anthropic_client = None
        # Gemini 클라이언트 (lazy init)
        self._gemini_client = None

        logger.info("AIGenerator 초기화 완료")

    # ──────────────────────────────────────────────
    # 클라이언트 Lazy Initialization
    # ──────────────────────────────────────────────

    @property
    def anthropic_client(self):
        """Anthropic 클라이언트를 필요 시 초기화하여 반환한다."""
        if self._anthropic_client is None:
            if not ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            logger.info("Anthropic 클라이언트 초기화 완료")
        return self._anthropic_client

    @property
    def gemini_client(self):
        """Gemini 클라이언트를 필요 시 초기화하여 반환한다."""
        if self._gemini_client is None:
            if not GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
            from google import genai
            self._gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("Gemini 클라이언트 초기화 완료")
        return self._gemini_client

    # ──────────────────────────────────────────────
    # 내부 API 호출 (with retry + cost tracking)
    # ──────────────────────────────────────────────

    @retry(max_attempts=3, delay=2.0, backoff=2.0)
    def _call_claude(self, model: str, prompt: str, max_tokens: int = 2048,
                     temperature: float = 0.7, system: str = "") -> str:
        """Claude API를 호출하고 비용을 기록한다.

        Args:
            model: 사용할 Claude 모델 ID
            prompt: 사용자 프롬프트 텍스트
            max_tokens: 최대 출력 토큰 수
            temperature: 창의성 파라미터 (0.0~1.0)
            system: 시스템 프롬프트 (선택)

        Returns:
            모델 응답 텍스트

        Raises:
            anthropic.APIError: API 호출 실패 시
        """
        logger.debug(f"Claude 호출: model={model}, prompt_len={len(prompt)}")

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        message = self.anthropic_client.messages.create(**kwargs)

        in_tok = message.usage.input_tokens
        out_tok = message.usage.output_tokens
        cost = self.tracker.record(model, in_tok, out_tok)
        self._total_cost_usd += cost

        result = message.content[0].text
        logger.info(f"Claude 응답 완료: in={in_tok}, out={out_tok}, cost=${cost:.6f}")
        return result

    @retry(max_attempts=3, delay=2.0, backoff=2.0)
    def _call_gemini(self, prompt: str, max_tokens: int = 4096,
                     temperature: float = 0.7, model: str = GEMINI_FLASH) -> str:
        """Gemini API를 호출하고 비용을 기록한다.

        Args:
            prompt: 사용자 프롬프트 텍스트
            max_tokens: 최대 출력 토큰 수
            temperature: 창의성 파라미터
            model: 사용할 Gemini 모델 ID

        Returns:
            모델 응답 텍스트

        Raises:
            Exception: API 호출 실패 시
        """
        from google.genai import types

        logger.debug(f"Gemini 호출: model={model}, prompt_len={len(prompt)}")

        response = self.gemini_client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        usage = getattr(response, "usage_metadata", None)
        in_tok = 0
        out_tok = 0
        if usage:
            in_tok = getattr(usage, "prompt_token_count", 0) or 0
            out_tok = getattr(usage, "candidates_token_count", 0) or 0

        cost = self.tracker.record(model, in_tok, out_tok)
        self._total_cost_usd += cost

        result = response.text
        logger.info(f"Gemini 응답 완료: in={in_tok}, out={out_tok}, cost=${cost:.6f}")
        return result

    def _call_with_fallback(self, primary_fn, fallback_fn,
                            prompt: str, **kwargs) -> str:
        """주 제공자 실패 시 대체 제공자로 자동 전환한다.

        Args:
            primary_fn: 우선 호출할 함수 (_call_claude 또는 _call_gemini)
            fallback_fn: 실패 시 대체 호출할 함수
            prompt: 프롬프트 텍스트
            **kwargs: 추가 파라미터

        Returns:
            모델 응답 텍스트
        """
        try:
            return primary_fn(prompt=prompt, **kwargs)
        except Exception as e:
            logger.warning(f"주 제공자 실패 ({e}), 대체 제공자로 전환")
            # fallback_fn에 맞지 않는 키워드 인자 제거
            fallback_kwargs = {k: v for k, v in kwargs.items()
                               if k in ("max_tokens", "temperature")}
            return fallback_fn(prompt=prompt, **fallback_kwargs)

    # ──────────────────────────────────────────────
    # Mode A: 제휴 상품 콘텐츠 생성
    # ──────────────────────────────────────────────

    def generate_hook(self, product: Product, persona: str = "",
                      directive: str = "") -> str:
        """상품에 대한 주목 끄는 훅 텍스트를 생성한다 (Claude Sonnet).

        숏폼 영상 첫 3초에 시청자의 관심을 사로잡는 2-3줄의
        한국어 훅 카피를 생성한다.

        Args:
            product: 대상 상품 정보
            persona: 화자 페르소나 (선택, 예: '20대 직장인')
            directive: 추가 지시사항 (선택)

        Returns:
            생성된 훅 텍스트 (한국어)
        """
        persona_line = f"\n화자 페르소나: {persona}" if persona else ""
        directive_line = f"\n추가 지시: {directive}" if directive else ""

        prompt = f"""당신은 숏폼 마케팅 카피라이터입니다.
아래 상품에 대해 시청자의 관심을 3초 안에 사로잡는 훅 텍스트를 작성하세요.

[상품 정보]
- 상품명: {product.title}
- 가격: {product.price}
- 설명: {product.description[:500] if product.description else '(없음)'}
{persona_line}{directive_line}

[요구사항]
- 한국어로 작성
- 2~3줄, 총 50자 이내
- 감탄사/질문/충격적 사실 중 하나의 패턴 사용
- 이모지 1~2개 포함
- 시청자가 스크롤을 멈추게 만드는 힘이 있어야 함

훅 텍스트만 출력하세요:"""

        return self._call_with_fallback(
            primary_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_SONNET, prompt=prompt, **kw),
            fallback_fn=self._call_gemini,
            prompt=prompt,
            max_tokens=512,
            temperature=0.9,
        )

    def generate_body(self, product: Product, hook: str,
                      persona: str = "") -> str:
        """상품 본문 카피를 생성한다 (Gemini Flash).

        훅 이후에 이어지는 상품 설명, 혜택, CTA를 포함한
        완성된 본문 텍스트를 생성한다.

        Args:
            product: 대상 상품 정보
            hook: 앞서 생성된 훅 텍스트
            persona: 화자 페르소나 (선택)

        Returns:
            생성된 본문 텍스트 (한국어)
        """
        persona_line = f"\n화자 페르소나: {persona}" if persona else ""

        prompt = f"""당신은 제휴 마케팅 콘텐츠 전문 작가입니다.
아래 상품에 대한 소개 본문을 작성하세요.

[상품 정보]
- 상품명: {product.title}
- 가격: {product.price}
- 설명: {product.description[:800] if product.description else '(없음)'}
- 제휴 링크: {product.affiliate_link or '(추후 삽입)'}

[이미 작성된 훅]
{hook}
{persona_line}

[요구사항]
- 한국어로 작성
- 200~400자 분량
- 구성: 상품 소개 -> 핵심 장점 3가지 -> 가격 메리트 -> CTA(구매 유도)
- 자연스러운 구어체, 과장하지 않되 매력적으로
- 줄바꿈으로 가독성 확보
- 마지막에 "링크는 프로필에서 확인하세요" 스타일의 CTA 포함

본문 텍스트만 출력하세요:"""

        return self._call_with_fallback(
            primary_fn=self._call_gemini,
            fallback_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_SONNET, prompt=prompt, **kw),
            prompt=prompt,
            max_tokens=2048,
            temperature=0.7,
        )

    def generate_narration(self, product: Product, body: str) -> list[str]:
        """TTS 내레이션 대본을 장면별로 생성한다 (Gemini Flash).

        숏폼 영상의 각 장면에 맞는 내레이션 스크립트를 리스트로 반환한다.
        각 장면은 3~5초 분량의 짧은 대사로 구성된다.

        Args:
            product: 대상 상품 정보
            body: 앞서 생성된 본문 텍스트

        Returns:
            장면별 내레이션 스크립트 리스트
        """
        prompt = f"""당신은 숏폼 영상 내레이션 전문가입니다.
아래 상품과 본문을 바탕으로 TTS 내레이션 대본을 작성하세요.

[상품명]
{product.title}

[본문 내용]
{body}

[요구사항]
- 총 5~7개 장면으로 나누세요
- 각 장면은 3~5초 분량 (15~30자)
- 자연스러운 구어체, TTS로 읽혔을 때 자연스러워야 함
- 첫 장면은 훅 (관심 끌기)
- 마지막 장면은 CTA (행동 유도)
- 각 장면을 [장면1], [장면2] 등으로 구분

아래 형식으로 출력하세요:
[장면1] 내레이션 텍스트
[장면2] 내레이션 텍스트
..."""

        raw = self._call_with_fallback(
            primary_fn=self._call_gemini,
            fallback_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_SONNET, prompt=prompt, **kw),
            prompt=prompt,
            max_tokens=2048,
            temperature=0.6,
        )

        # 파싱: [장면N] 패턴으로 분리
        scenes: list[str] = []
        for line in raw.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # [장면N] 접두사 제거
            if line.startswith("[") and "]" in line:
                text = line[line.index("]") + 1:].strip()
                if text:
                    scenes.append(text)
            elif scenes:
                # 이전 장면의 연속일 수 있음
                scenes[-1] += " " + line

        if not scenes:
            # 파싱 실패 시 줄 단위로 분할
            scenes = [l.strip() for l in raw.strip().splitlines() if l.strip()]

        logger.info(f"내레이션 {len(scenes)}개 장면 생성 완료")
        return scenes

    def generate_hashtags(self, product: Product, content: str) -> list[str]:
        """관련 한국어 해시태그를 생성한다 (Gemini Flash).

        상품과 콘텐츠에 맞는 검색 최적화된 한국어 해시태그를
        15~20개 생성한다.

        Args:
            product: 대상 상품 정보
            content: 생성된 본문 또는 전체 콘텐츠

        Returns:
            해시태그 문자열 리스트 (# 포함)
        """
        prompt = f"""당신은 SNS 마케팅 해시태그 전문가입니다.
아래 상품과 콘텐츠에 적합한 한국어 해시태그를 생성하세요.

[상품명]
{product.title}

[콘텐츠 내용 요약]
{content[:500]}

[요구사항]
- 15~20개의 해시태그 생성
- 모두 한국어
- 검색량 높은 일반 태그 + 상품 특화 태그 혼합
- #으로 시작, 공백 없이
- 한 줄에 하나씩 출력

해시태그만 출력하세요:"""

        raw = self._call_with_fallback(
            primary_fn=self._call_gemini,
            fallback_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_HAIKU, prompt=prompt, **kw),
            prompt=prompt,
            max_tokens=1024,
            temperature=0.5,
        )

        # 파싱: # 으로 시작하는 토큰 추출
        hashtags: list[str] = []
        for line in raw.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # 한 줄에 여러 해시태그가 있을 수 있음
            tokens = line.split()
            for token in tokens:
                token = token.strip(",. ")
                if token.startswith("#") and len(token) > 1:
                    hashtags.append(token)

        # 중복 제거 (순서 유지)
        seen: set[str] = set()
        unique: list[str] = []
        for tag in hashtags:
            if tag not in seen:
                seen.add(tag)
                unique.append(tag)

        logger.info(f"해시태그 {len(unique)}개 생성 완료")
        return unique

    # ──────────────────────────────────────────────
    # 플랫폼별 최적화 콘텐츠 생성
    # ──────────────────────────────────────────────

    def generate_platform_content(
        self, product: Product, platform: Platform,
        persona: str = "", brand: str = "",
    ) -> dict:
        """플랫폼에 최적화된 콘텐츠를 생성한다.

        각 플랫폼의 글자수, 톤, 형식에 맞춘 콘텐츠를 생성한다.

        Args:
            product: 대상 상품 정보
            platform: 대상 플랫폼
            persona: 화자 페르소나
            brand: 브랜드명 (자사 브랜드인 경우)

        Returns:
            {"title", "body", "hashtags", "narration", "cta", "thumbnail_text"}
        """
        preset = PLATFORM_PRESETS.get(platform)
        if not preset:
            raise ValueError(f"지원하지 않는 플랫폼: {platform}")

        if platform == Platform.YOUTUBE:
            return self._generate_shorts_content(product, preset, persona, brand)
        elif platform == Platform.INSTAGRAM:
            return self._generate_reels_content(product, preset, persona, brand)
        elif platform == Platform.NAVER_BLOG:
            return self._generate_blog_content(product, preset, persona, brand)
        else:
            raise ValueError(f"지원하지 않는 플랫폼: {platform}")

    def _generate_shorts_content(
        self, product: Product, preset: PlatformPreset,
        persona: str = "", brand: str = "",
    ) -> dict:
        """YouTube Shorts 최적화 콘텐츠를 생성한다.

        - 제목: 100자 이내, 검색 최적화 키워드 포함
        - 설명: 첫 2줄이 중요 (접히므로), 해시태그 3~10개
        - 나레이션: 5~7장면, 빠른 템포
        - 썸네일 텍스트: 7자 이내 임팩트 문구
        """
        persona_line = f"\n화자 페르소나: {persona}" if persona else ""
        brand_line = f"\n브랜드: {brand}" if brand else ""

        # 제목 + 설명 + 나레이션 + 해시태그 + 썸네일 한 번에 생성
        prompt = f"""당신은 한국어 YouTube Shorts 전문 크리에이터입니다.
아래 상품으로 Shorts 콘텐츠 전체를 생성하세요.{persona_line}{brand_line}

상품명: {product.title}
가격: {product.price}
설명: {product.description[:400] if product.description else '(없음)'}
구매 링크: {product.affiliate_link or '(프로필 링크)'}

반드시 아래 5개 섹션을 모두 빠짐없이 작성하세요:

[제목]
이모지 포함, 100자 이내 Shorts 제목

[설명]
핵심 메시지와 CTA 포함 200자 이내 설명문. 마지막에 "링크는 설명란에서 확인!" 같은 CTA 포함

[나레이션]
[장면1] 충격 도입 한 줄
[장면2] 상품 소개 한 줄
[장면3] 핵심 장점 한 줄
[장면4] 가격 혜택 한 줄
[장면5] 구독 유도 CTA 한 줄

[해시태그]
#해시태그1 #해시태그2 #해시태그3 #해시태그4 #해시태그5 #해시태그6 #해시태그7

[썸네일]
7자 이내 임팩트 문구
15자 이내 부제"""

        raw = self._call_with_fallback(
            primary_fn=self._call_gemini,
            fallback_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_HAIKU, prompt=prompt, **kw),
            prompt=prompt,
            max_tokens=4096,
            temperature=0.8,
        )

        return self._parse_platform_response(raw, "youtube")

    def _generate_reels_content(
        self, product: Product, preset: PlatformPreset,
        persona: str = "", brand: str = "",
    ) -> dict:
        """Instagram Reels 최적화 콘텐츠를 생성한다.

        - 캡션: 2200자 이내, 감성적 톤, 이모지 풍부
        - 해시태그: 15~25개 (최대 30개)
        - 나레이션: 감성적 + 트렌디
        - 썸네일: 감성 비주얼
        """
        persona_line = f"\n화자 페르소나: {persona}" if persona else ""
        brand_line = f"\n브랜드: {brand}" if brand else ""

        prompt = f"""당신은 한국어 Instagram Reels 전문 크리에이터입니다.
아래 상품으로 Instagram Reels 콘텐츠 전체를 작성하세요.{persona_line}{brand_line}

상품명: {product.title}
가격: {product.price}
설명: {product.description[:400] if product.description else '(없음)'}
구매 링크: {product.affiliate_link or '(프로필 링크)'}

반드시 아래 5개 섹션을 모두 빠짐없이 작성하세요:

[제목]
이모지 포함 릴스 제목 (50자 이내, 감성적이고 트렌디하게)

[캡션]
이모지와 줄바꿈을 활용한 감성적 캡션을 300~500자로 작성하세요.
상품의 매력을 감각적으로 표현하고, 마지막에 "구매 링크는 프로필에서!" 같은 CTA를 넣으세요.

[나레이션]
[장면1] 트렌디한 도입 인사 한 줄
[장면2] 상품 비주얼 포인트 한 줄
[장면3] 핵심 장점 한 줄
[장면4] 가격 혜택 한 줄
[장면5] 저장/팔로우 유도 CTA 한 줄

[해시태그]
#태그1 #태그2 #태그3 #태그4 #태그5 #태그6 #태그7 #태그8 #태그9 #태그10 #태그11 #태그12 #태그13 #태그14 #태그15

[썸네일]
감성적 임팩트 문구 7자 이내
부제 15자 이내"""

        raw = self._call_with_fallback(
            primary_fn=self._call_gemini,
            fallback_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_HAIKU, prompt=prompt, **kw),
            prompt=prompt,
            max_tokens=4096,
            temperature=0.8,
        )

        return self._parse_platform_response(raw, "instagram")

    def _generate_blog_content(
        self, product: Product, preset: PlatformPreset,
        persona: str = "", brand: str = "",
    ) -> dict:
        """네이버 블로그 최적화 콘텐츠를 생성한다.

        - 제목: SEO 키워드 포함, 100자 이내
        - 본문: 3000~5000자, 소제목/이미지 위치 표시
        - 해시태그: 10개 이하
        - 영상 나레이션: 느린 템포, 상세 설명
        """
        persona_line = f"\n화자 페르소나: {persona}" if persona else ""
        brand_line = f"\n브랜드: {brand}" if brand else ""

        prompt = f"""네이버 블로그 포스팅 콘텐츠를 아래 형식 그대로 작성하세요.
{persona_line}{brand_line}

상품명: {product.title}
가격: {product.price}
설명: {product.description[:500] if product.description else '(없음)'}
구매 링크: {product.affiliate_link or '(추후 삽입)'}

반드시 아래 형식을 지켜서 출력하세요:

[제목]
네이버 SEO 최적화 제목, 핵심 키워드 앞배치

[본문]
안녕하세요! 오늘은 (상품명) 소개합니다.

## 상품 소개
상품 기본 정보, 특징...

## 핵심 장점
장점 3가지를 상세히...

## 가격 및 구매
가격, 할인, 구매처 안내...

## 마무리
CTA + 링크 안내
(총 1500~3000자)

[나레이션]
[장면1] 블로그 영상 인트로 20자 이내
[장면2] 상품 소개 20자 이내
[장면3] 핵심 장점 20자 이내
[장면4] 가격 혜택 20자 이내
[장면5] 구매 안내 20자 이내
[장면6] 마무리 인사 15자 이내

[해시태그]
#태그1 #태그2 ... (5~10개)

[썸네일]
정보성 문구 10자 이내
부제 20자 이내"""

        raw = self._call_with_fallback(
            primary_fn=self._call_gemini,
            fallback_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_HAIKU, prompt=prompt, **kw),
            prompt=prompt,
            max_tokens=8192,
            temperature=0.7,
        )

        return self._parse_platform_response(raw, "naver_blog")

    def generate_all_platform_content(
        self, product: Product, persona: str = "", brand: str = "",
    ) -> dict[str, dict]:
        """모든 플랫폼용 콘텐츠를 한 번에 생성한다.

        Returns:
            {"youtube": {...}, "instagram": {...}, "naver_blog": {...}}
        """
        results: dict[str, dict] = {}

        for platform in [Platform.YOUTUBE, Platform.INSTAGRAM, Platform.NAVER_BLOG]:
            try:
                logger.info(f"플랫폼 콘텐츠 생성: {platform.value}")
                content = self.generate_platform_content(
                    product, platform, persona=persona, brand=brand,
                )
                results[platform.value] = content
                logger.info(f"플랫폼 콘텐츠 생성 완료: {platform.value}")
            except Exception as e:
                logger.error(f"플랫폼 콘텐츠 생성 실패 ({platform.value}): {e}")
                results[platform.value] = {
                    "title": "", "body": "", "hashtags": [],
                    "narration": [], "cta": "", "thumbnail_text": "",
                    "thumbnail_subtitle": "",
                }

        return results

    def generate_thumbnail_text(self, product: Product, platform: Platform) -> tuple[str, str]:
        """플랫폼에 맞는 썸네일 텍스트를 생성한다.

        Returns:
            (메인 텍스트, 서브 텍스트)
        """
        if platform == Platform.YOUTUBE:
            spec = "7자 이내 충격적/호기심 유발 문구"
        elif platform == Platform.INSTAGRAM:
            spec = "7자 이내 감성적/트렌디한 문구"
        else:
            spec = "10자 이내 정보성 핵심 키워드"

        prompt = f"""상품명: {product.title}

이 상품의 {platform.value} 썸네일에 들어갈 텍스트를 생성하세요.

[규격]
- 메인 텍스트: {spec}
- 부제: 15자 이내

[출력 형식]
메인: (텍스트)
부제: (텍스트)"""

        raw = self._call_gemini(prompt=prompt, max_tokens=256, temperature=0.9)

        main_text = ""
        sub_text = ""
        for line in raw.strip().splitlines():
            line = line.strip()
            if line.startswith("메인:") or line.startswith("메인 :"):
                main_text = line.split(":", 1)[1].strip().strip("()")
            elif line.startswith("부제:") or line.startswith("부제 :"):
                sub_text = line.split(":", 1)[1].strip().strip("()")

        return main_text or product.title[:7], sub_text or product.title[:15]

    # ──────────────────────────────────────────────
    # 응답 파싱 유틸리티
    # ──────────────────────────────────────────────

    @staticmethod
    def _parse_platform_response(raw: str, platform: str) -> dict:
        """플랫폼별 AI 응답을 파싱하여 구조화한다.

        Gemini는 마크다운을 적극적으로 사용하므로 다양한 형식을 처리:
        - ### [제목], ## [제목], **[제목]** 등 마크다운 래핑
        - **[장면1] 지시사항** + 다음 줄에 실제 텍스트
        - **나레이션:** 접두사
        """
        result = {
            "title": "",
            "body": "",
            "hashtags": [],
            "narration": [],
            "cta": "",
            "thumbnail_text": "",
            "thumbnail_subtitle": "",
        }

        current_section = ""
        body_lines: list[str] = []
        narration_items: list[str] = []
        hashtag_items: list[str] = []

        # 섹션 매핑 (한국어 + 영어)
        section_map = {
            "title": ["[제목]", "[title]"],
            "body": ["[설명]", "[캡션]", "[본문]", "[body]", "[caption]", "[description]"],
            "narration": ["[나레이션]", "[narration]"],
            "hashtag": ["[해시태그]", "[hashtag]", "[hashtags]"],
            "thumbnail": ["[썸네일]", "[thumbnail]"],
        }

        def _clean_line(text: str) -> str:
            """마크다운 접두사 제거: ###, ##, #, **, * 등"""
            t = text.strip()
            # ### / ## / # 헤더 제거
            t = re.sub(r'^#{1,6}\s*', '', t)
            # ** 볼드 래핑 제거 (양쪽)
            t = re.sub(r'^\*\*(.+?)\*\*$', r'\1', t)
            return t.strip()

        def _detect_section(text: str) -> str:
            """줄에서 섹션 헤더 감지. 발견 시 섹션명 반환, 아니면 빈 문자열."""
            cleaned = _clean_line(text)
            for section_name, markers in section_map.items():
                for m in markers:
                    if cleaned.lower().startswith(m.lower()):
                        return section_name
            return ""

        def _clean_narration_text(text: str) -> str:
            """나레이션 텍스트에서 지시사항/마크다운/따옴표 제거."""
            t = text.strip()
            # **나레이션:** 또는 **장면 설명:** 패턴 제거
            t = re.sub(r'^\*\*[^*]*\*\*\s*', '', t)
            # 괄호 안 지시사항 제거 (예: "(3초 이내 충격적 도입)")
            t = re.sub(r'^\([^)]*\)\s*', '', t)
            # 따옴표 제거 ("나레이션 텍스트" → 나레이션 텍스트)
            t = t.strip('"\'')
            # "블로그 영상 인트로:", "상품 소개:" 같은 지시 접두사 제거
            t = re.sub(r'^(?:블로그\s*영상\s*인트로|상품\s*소개|핵심\s*장점|가격\s*혜택|구매\s*안내|마무리\s*인사)\s*:\s*', '', t).strip()
            # "충격 도입 한 줄" 같은 프롬프트 지시가 남아있으면 건너뛰기
            skip_patterns = [
                "충격 도입 한 줄", "상품 소개 한 줄", "핵심 장점 한 줄",
                "가격 혜택 한 줄", "구독 유도 CTA 한 줄", "한 줄",
                "트렌디한 도입", "비주얼 포인트", "저장/팔로우",
            ]
            for sp in skip_patterns:
                if t == sp:
                    return ""
            return t.strip()

        for line in raw.strip().splitlines():
            line_stripped = line.strip()

            # 마크다운 접두 섹션 감지 (### [제목], ## [나레이션] 등)
            section = _detect_section(line_stripped)
            if section:
                current_section = section
                continue

            if not line_stripped:
                if current_section == "body":
                    body_lines.append("")
                continue

            # 섹션별 파싱
            if current_section == "title" and not result["title"]:
                clean = _clean_line(line_stripped).strip("()")
                if clean:
                    result["title"] = clean

            elif current_section == "body":
                body_lines.append(line_stripped)

            elif current_section == "narration":
                cleaned = _clean_line(line_stripped)

                # **[장면N] 지시사항** 패턴 (볼드 래핑된 장면 헤더)
                bold_scene = re.match(r'^\*\*\[장면\d+\]\s*.*?\*\*$', line_stripped)
                if bold_scene:
                    # 이것은 지시사항만 있는 헤더 → 빈 슬롯 추가
                    narration_items.append("")
                    continue

                # [장면N] 텍스트 패턴
                if cleaned.startswith("[") and "]" in cleaned:
                    bracket_content = cleaned[:cleaned.index("]") + 1]
                    # 실제 섹션 헤더인지 확인
                    if _detect_section(cleaned):
                        current_section = _detect_section(cleaned)
                        continue
                    text = cleaned[cleaned.index("]") + 1:].strip()
                    clean_text = _clean_narration_text(text)
                    if clean_text:
                        narration_items.append(clean_text)
                    else:
                        narration_items.append("")
                else:
                    # 이전 장면의 실제 텍스트 (다음 줄에 온 경우)
                    clean_text = _clean_narration_text(cleaned)
                    if clean_text:
                        if narration_items and not narration_items[-1]:
                            narration_items[-1] = clean_text
                        elif narration_items:
                            narration_items[-1] += " " + clean_text
                        else:
                            narration_items.append(clean_text)

            elif current_section == "hashtag":
                for token in line_stripped.split():
                    token = token.strip(",.*# ")
                    if not token:
                        continue
                    tag = f"#{token}" if not token.startswith("#") else token
                    # #으로만 구성된 것 제거
                    tag = tag.strip(",. ")
                    if tag.startswith("#") and len(tag) > 1:
                        hashtag_items.append(tag)

            elif current_section == "thumbnail":
                clean = _clean_line(line_stripped).strip("()")
                # "**임팩트 문구:** 텍스트" or "정보성 문구: 텍스트" 같은 접두사 제거
                clean = re.sub(r'^\*?\*?(?:임팩트\s*문구|감성적?\s*(?:임팩트\s*)?문구|정보성\s*문구|메인|부제)\s*:?\*?\*?\s*:?\s*', '', clean, flags=re.IGNORECASE).strip()
                if clean and not result["thumbnail_text"]:
                    result["thumbnail_text"] = clean
                elif clean and not result["thumbnail_subtitle"]:
                    result["thumbnail_subtitle"] = clean

        # 빈 나레이션 항목 제거
        narration_items = [n for n in narration_items if n.strip()]

        result["body"] = "\n".join(body_lines).strip()
        result["narration"] = narration_items
        result["hashtags"] = list(dict.fromkeys(hashtag_items))  # 중복 제거

        # 나레이션 폴백: Gemini가 나레이션을 1장면 이하로 반환했을 때
        # 본문(캡션)을 기반으로 5장면 나레이션을 자동 분할 생성
        if len(result["narration"]) < 2 and len(result["body"]) > 50:
            logger.info(f"나레이션 폴백 실행 ({platform}): {len(result['narration'])}장면 → 본문 기반 분할")
            body_text = result["body"]
            # 문장 단위로 분할
            sentences = re.split(r'[.!?。]\s*', body_text)
            sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 5]
            if len(sentences) >= 5:
                # 5개 구간으로 균등 분할
                chunk_size = max(1, len(sentences) // 5)
                fallback_narr = []
                for i in range(5):
                    start = i * chunk_size
                    end = start + chunk_size if i < 4 else len(sentences)
                    chunk = " ".join(sentences[start:end])
                    # 50자 이내로 자르기
                    if len(chunk) > 50:
                        chunk = chunk[:47] + "..."
                    fallback_narr.append(chunk)
                result["narration"] = fallback_narr
            elif sentences:
                result["narration"] = sentences[:5]

        # CTA 추출 (본문 마지막 줄에서)
        if body_lines:
            last_lines = [l for l in body_lines[-3:] if l.strip()]
            for l in reversed(last_lines):
                if any(kw in l for kw in ["확인", "클릭", "구독", "팔로우", "저장", "방문"]):
                    result["cta"] = l.strip()
                    break

        logger.info(
            f"플랫폼 응답 파싱 완료 ({platform}): "
            f"title={len(result['title'])}자, body={len(result['body'])}자, "
            f"narration={len(result['narration'])}장면, hashtags={len(result['hashtags'])}개"
        )
        return result

    def translate_to_english(self, text: str) -> str:
        """한국어 텍스트를 영어로 번역한다 (Claude Haiku).

        마케팅 톤을 유지하면서 자연스러운 영어로 번역한다.

        Args:
            text: 번역할 한국어 텍스트

        Returns:
            영어 번역 텍스트
        """
        prompt = f"""Translate the following Korean marketing text into natural, engaging English.
Maintain the marketing tone and persuasiveness.
Do NOT add any explanation - output ONLY the translation.

Korean text:
{text}

English translation:"""

        return self._call_with_fallback(
            primary_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_HAIKU, prompt=prompt, **kw),
            fallback_fn=self._call_gemini,
            prompt=prompt,
            max_tokens=2048,
            temperature=0.3,
        )

    def translate_to_korean(self, text: str) -> str:
        """영어 텍스트를 한국어로 번역한다 (Claude Haiku).

        자연스러운 한국어 구어체로 번역한다.

        Args:
            text: 번역할 영어 텍스트

        Returns:
            한국어 번역 텍스트
        """
        prompt = f"""아래 영어 텍스트를 자연스러운 한국어로 번역하세요.
마케팅 톤을 유지하고, 한국 소비자에게 자연스러운 표현을 사용하세요.
설명 없이 번역문만 출력하세요.

영어 텍스트:
{text}

한국어 번역:"""

        return self._call_with_fallback(
            primary_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_HAIKU, prompt=prompt, **kw),
            fallback_fn=self._call_gemini,
            prompt=prompt,
            max_tokens=2048,
            temperature=0.3,
        )

    # ──────────────────────────────────────────────
    # Mode B: 자사 브랜드 F&B 콘텐츠 생성
    # ──────────────────────────────────────────────

    def generate_brand_content(self, brand: str, content_type: str,
                               tone: str = "") -> AIContent:
        """브랜드별 프로모션 콘텐츠를 생성한다 (Mode B).

        오레노카츠, 무사짬뽕, 브릿지원 등 자사 브랜드에 맞는
        페르소나와 톤으로 마케팅 콘텐츠를 생성한다.

        Args:
            brand: 브랜드명 ('오레노카츠', '무사짬뽕', '브릿지원')
            content_type: 콘텐츠 유형 ('블로그', '인스타', '숏폼', '이벤트')
            tone: 추가 톤 지시 (선택, 기본값은 브랜드 템플릿 사용)

        Returns:
            생성된 AIContent 객체 (훅, 본문, 해시태그, 내레이션 포함)

        Raises:
            ValueError: 지원하지 않는 브랜드명인 경우
        """
        template = BRAND_TEMPLATES.get(brand)
        if not template:
            available = ", ".join(BRAND_TEMPLATES.keys())
            raise ValueError(
                f"지원하지 않는 브랜드: '{brand}'. 사용 가능: {available}"
            )

        persona_text = template["persona"]
        keywords = template["keywords"]
        hashtag_prefix = template["hashtag_prefix"]
        tone_text = tone or "브랜드 톤에 맞게"

        cost_before = self._total_cost_usd
        models_used: list[str] = []

        # ---- 훅 생성 (Claude Sonnet) ----
        hook_prompt = f"""{persona_text}

'{brand}'의 {content_type} 콘텐츠를 위한 훅(도입부)을 작성하세요.

[키워드]
{keywords}

[톤]
{tone_text}

[요구사항]
- 한국어, 2~3줄, 50자 이내
- {content_type}에 적합한 도입부
- 고객의 관심을 즉시 끌 수 있어야 함

훅 텍스트만 출력하세요:"""

        hook = self._call_claude(
            model=CLAUDE_SONNET, prompt=hook_prompt,
            max_tokens=512, temperature=0.9,
        )
        models_used.append(CLAUDE_SONNET)

        # ---- 본문 생성 (Gemini Flash) ----
        body_prompt = f"""{persona_text}

'{brand}'의 {content_type} 콘텐츠 본문을 작성하세요.

[이미 작성된 훅]
{hook}

[키워드]
{keywords}

[톤]
{tone_text}

[요구사항]
- 한국어, 300~500자
- {content_type} 플랫폼에 최적화된 형식
- 브랜드의 핵심 가치와 차별점 강조
- 자연스러운 구어체
- CTA (방문/예약/문의 유도) 포함

본문 텍스트만 출력하세요:"""

        body = self._call_gemini(
            prompt=body_prompt, max_tokens=2048, temperature=0.7,
        )
        models_used.append(GEMINI_FLASH)

        # ---- 해시태그 생성 (Gemini Flash) ----
        hashtag_prompt = f"""'{brand}' 브랜드의 {content_type} 콘텐츠에 적합한 해시태그를 생성하세요.

[필수 포함 해시태그]
{hashtag_prefix}

[키워드]
{keywords}

[요구사항]
- 총 15~20개 (필수 해시태그 포함)
- 한국어
- 검색량 높은 태그 + 브랜드 특화 태그 혼합
- 한 줄에 하나씩, #으로 시작

해시태그만 출력하세요:"""

        hashtag_raw = self._call_gemini(
            prompt=hashtag_prompt, max_tokens=1024, temperature=0.5,
        )

        hashtags: list[str] = []
        for line in hashtag_raw.strip().splitlines():
            for token in line.strip().split():
                token = token.strip(",. ")
                if token.startswith("#") and len(token) > 1:
                    hashtags.append(token)
        # 필수 해시태그가 누락되었으면 추가
        for prefix_tag in hashtag_prefix.split():
            prefix_tag = prefix_tag.strip()
            if prefix_tag and prefix_tag not in hashtags:
                hashtags.insert(0, prefix_tag)

        # ---- 내레이션 생성 (숏폼인 경우만) ----
        narration_scripts: list[str] = []
        if content_type in ("숏폼", "shorts", "릴스"):
            narration_prompt = f"""{persona_text}

아래 본문을 바탕으로 숏폼 영상 TTS 내레이션 대본을 작성하세요.

[본문]
{body}

[요구사항]
- 5~7개 장면
- 각 장면 3~5초 분량 (15~30자)
- TTS로 읽힐 때 자연스러운 구어체
- [장면1] 형식으로 출력

대본만 출력하세요:"""

            narration_raw = self._call_gemini(
                prompt=narration_prompt, max_tokens=2048, temperature=0.6,
            )
            for line in narration_raw.strip().splitlines():
                line = line.strip()
                if line.startswith("[") and "]" in line:
                    text = line[line.index("]") + 1:].strip()
                    if text:
                        narration_scripts.append(text)

        total_cost = self._total_cost_usd - cost_before

        content = AIContent(
            hook_text=hook.strip(),
            body_text=body.strip(),
            translated_text="",
            hashtags=hashtags,
            narration_scripts=narration_scripts,
            cost_usd=round(total_cost, 6),
            models_used=models_used,
        )

        logger.info(
            f"브랜드 콘텐츠 생성 완료: brand={brand}, type={content_type}, "
            f"cost=${total_cost:.6f}"
        )
        return content

    # ──────────────────────────────────────────────
    # Full Pipeline (Mode A)
    # ──────────────────────────────────────────────

    def generate_full_campaign(self, product: Product, persona: str = "",
                               hook_directive: str = "") -> AIContent:
        """상품에 대한 전체 콘텐츠 파이프라인을 실행한다 (Mode A).

        훅 -> 본문 -> 내레이션 -> 해시태그 -> 영어 번역 순서로
        모든 콘텐츠를 일괄 생성한다.

        Args:
            product: 대상 상품 정보
            persona: 화자 페르소나 (선택)
            hook_directive: 훅 생성 추가 지시사항 (선택)

        Returns:
            모든 콘텐츠가 채워진 AIContent 객체
        """
        cost_before = self._total_cost_usd
        models_used: list[str] = []

        logger.info(f"전체 캠페인 생성 시작: {product.title}")

        # Step 1: 훅 생성 (Claude Sonnet)
        hook = self.generate_hook(product, persona=persona, directive=hook_directive)
        models_used.append(CLAUDE_SONNET)
        logger.info(f"[1/5] 훅 생성 완료: {hook[:30]}...")

        # Step 2: 본문 생성 (Gemini Flash)
        body = self.generate_body(product, hook, persona=persona)
        models_used.append(GEMINI_FLASH)
        logger.info(f"[2/5] 본문 생성 완료: {len(body)}자")

        # Step 3: 내레이션 생성 (Gemini Flash)
        narration = self.generate_narration(product, body)
        logger.info(f"[3/5] 내레이션 생성 완료: {len(narration)}개 장면")

        # Step 4: 해시태그 생성 (Gemini Flash)
        hashtags = self.generate_hashtags(product, body)
        logger.info(f"[4/5] 해시태그 생성 완료: {len(hashtags)}개")

        # Step 5: 영어 번역 (Claude Haiku)
        translated = self.translate_to_english(f"{hook}\n\n{body}")
        models_used.append(CLAUDE_HAIKU)
        logger.info("[5/5] 영어 번역 완료")

        total_cost = self._total_cost_usd - cost_before

        content = AIContent(
            hook_text=hook.strip(),
            body_text=body.strip(),
            translated_text=translated.strip(),
            hashtags=hashtags,
            narration_scripts=narration,
            cost_usd=round(total_cost, 6),
            models_used=list(set(models_used)),
        )

        logger.info(
            f"전체 캠페인 생성 완료: {product.title}, "
            f"총 비용=${total_cost:.6f}"
        )
        return content

    # ──────────────────────────────────────────────
    # Mode C: MCN 대량 생산 (배치 처리)
    # ──────────────────────────────────────────────

    def batch_generate(self, products: list[Product],
                       callback: Optional[Callable[[int, int, Product, AIContent], None]] = None,
                       persona: str = "",
                       hook_directive: str = "") -> list[AIContent]:
        """다수 상품에 대한 콘텐츠를 일괄 생성한다 (Mode C).

        각 상품에 대해 generate_full_campaign을 순차적으로 실행하며,
        진행 상황을 콜백으로 알린다. 개별 상품 실패 시 해당 상품만
        건너뛰고 나머지를 계속 처리한다.

        Args:
            products: 처리할 상품 리스트
            callback: 진행 콜백 함수(현재인덱스, 총수, 상품, 결과)
            persona: 전체 배치에 적용할 페르소나 (선택)
            hook_directive: 전체 배치에 적용할 훅 지시사항 (선택)

        Returns:
            각 상품에 대한 AIContent 리스트 (실패 시 빈 AIContent)
        """
        total = len(products)
        results: list[AIContent] = []

        logger.info(f"배치 생성 시작: {total}개 상품")

        for idx, product in enumerate(products):
            logger.info(f"배치 진행: [{idx + 1}/{total}] {product.title}")

            try:
                content = self.generate_full_campaign(
                    product, persona=persona, hook_directive=hook_directive,
                )
            except Exception as e:
                logger.error(f"상품 생성 실패: {product.title} - {e}")
                content = AIContent(
                    hook_text="",
                    body_text="",
                    translated_text="",
                    hashtags=[],
                    narration_scripts=[],
                    cost_usd=0.0,
                    models_used=[],
                )

            results.append(content)

            if callback:
                try:
                    callback(idx + 1, total, product, content)
                except Exception as cb_err:
                    logger.warning(f"콜백 실행 실패: {cb_err}")

            # Rate limit 대응: 상품 간 2초 대기 (마지막 제외)
            if idx < total - 1:
                time.sleep(2.0)

        total_cost = sum(c.cost_usd for c in results)
        success_count = sum(1 for c in results if c.hook_text)
        logger.info(
            f"배치 생성 완료: {success_count}/{total} 성공, "
            f"총 비용=${total_cost:.6f}"
        )

        return results

    # ──────────────────────────────────────────────
    # 유틸리티
    # ──────────────────────────────────────────────

    def get_session_cost(self) -> float:
        """현재 세션의 누적 API 비용(USD)을 반환한다."""
        return round(self._total_cost_usd, 6)

    def print_cost_dashboard(self):
        """비용 대시보드를 콘솔에 출력한다."""
        self.tracker.print_dashboard()

    def structure_text(self, raw_text: str, format_type: str = "bullet") -> str:
        """비정형 텍스트를 구조화된 형식으로 변환한다 (Claude Haiku).

        스크래핑된 상품 설명 등 비정형 텍스트를 깔끔하게
        구조화하는 데 사용한다.

        Args:
            raw_text: 구조화할 원본 텍스트
            format_type: 출력 형식 ('bullet', 'numbered', 'table', 'summary')

        Returns:
            구조화된 텍스트
        """
        format_instructions = {
            "bullet": "불릿 포인트(-)로 핵심 내용을 정리하세요.",
            "numbered": "번호 리스트(1. 2. 3.)로 핵심 내용을 정리하세요.",
            "table": "표 형식(| 항목 | 내용 |)으로 정리하세요.",
            "summary": "3~5문장으로 핵심 내용을 요약하세요.",
        }

        instruction = format_instructions.get(format_type, format_instructions["bullet"])

        prompt = f"""아래 텍스트를 깔끔하게 구조화하세요.

[원본 텍스트]
{raw_text[:2000]}

[형식 지시]
{instruction}

설명 없이 구조화된 텍스트만 출력하세요:"""

        return self._call_with_fallback(
            primary_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_HAIKU, prompt=prompt, **kw),
            fallback_fn=self._call_gemini,
            prompt=prompt,
            max_tokens=2048,
            temperature=0.3,
        )

    def generate_content(self, prompt: str, max_tokens: int = 4096,
                         temperature: float = 0.7) -> str:
        """범용 AI 콘텐츠 생성 (이미지 편집 명령어 실행 등).

        Gemini를 우선 사용하고, 실패 시 Claude로 폴백한다.

        Args:
            prompt: 프롬프트 텍스트
            max_tokens: 최대 출력 토큰
            temperature: 창의성 파라미터

        Returns:
            AI 응답 텍스트
        """
        return self._call_with_fallback(
            primary_fn=self._call_gemini,
            fallback_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_HAIKU, prompt=prompt, **kw),
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def analyze_image(self, image_path: str, question: str = "") -> str:
        """이미지를 분석하여 설명을 반환한다 (Gemini Vision).

        Args:
            image_path: 분석할 이미지 파일 경로
            question: 추가 질문 (선택)

        Returns:
            이미지 분석 결과 텍스트
        """
        try:
            from PIL import Image
            from google.genai import types

            img = Image.open(image_path)
            prompt_text = question or (
                "이 이미지를 분석하고 한국어로 상세히 설명해주세요. "
                "구도, 색감, 주요 요소, 분위기를 포함해주세요."
            )

            response = self.gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[prompt_text, img],
            )

            usage = getattr(response, "usage_metadata", None)
            in_tok = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
            out_tok = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
            cost = self.tracker.record("gemini-2.0-flash-vision", in_tok, out_tok)
            self._total_cost_usd += cost

            result = response.text
            logger.info(f"이미지 분석 완료: {image_path}, cost=${cost:.6f}")
            return result

        except ImportError:
            return "[오류] Pillow 라이브러리가 필요합니다. pip install Pillow"
        except Exception as e:
            logger.error(f"이미지 분석 실패: {e}")
            return f"[분석 실패] {str(e)}"

    def analyze_product(self, product: Product) -> str:
        """상품 데이터를 분석하여 마케팅 인사이트를 생성한다 (Gemini Flash).

        가격대, 타겟 고객, 경쟁 포인트, 소구점 등을 분석한다.

        Args:
            product: 분석할 상품 정보

        Returns:
            분석 결과 텍스트 (한국어)
        """
        prompt = f"""당신은 제휴 마케팅 상품 분석 전문가입니다.
아래 상품을 분석하고 마케팅 인사이트를 제공하세요.

[상품 정보]
- 상품명: {product.title}
- 가격: {product.price}
- 설명: {product.description[:1000] if product.description else '(없음)'}
- URL: {product.url}

[분석 항목]
1. 타겟 고객층 (연령/성별/관심사)
2. 핵심 소구점 (왜 이 상품을 사야 하는가?)
3. 가격 경쟁력 분석
4. 추천 마케팅 앵글 (어떤 관점으로 홍보할 것인가?)
5. 주의사항 (과장 광고 소지, 규정 이슈 등)

각 항목별로 간결하게 분석 결과를 작성하세요:"""

        return self._call_with_fallback(
            primary_fn=self._call_gemini,
            fallback_fn=lambda prompt, **kw: self._call_claude(
                model=CLAUDE_SONNET, prompt=prompt, **kw),
            prompt=prompt,
            max_tokens=2048,
            temperature=0.5,
        )

    # ═══════════════════════════════════════════════════════════════════
    # V2 — Coupang Partners Profit-Maximizer 콘텐츠 생성
    # ═══════════════════════════════════════════════════════════════════

    def generate_blog_content_v2(self, product: Product,
                                  coupang_link: str = "") -> dict:
        """V2 네이버 블로그 콘텐츠 생성 — 자연스러운 설명/추천 스타일.

        내돈내산(거짓 구매후기) 절대 금지.
        친구한테 추천하듯 자연스러운 정보 전달 톤.

        Args:
            product: 상품 정보
            coupang_link: 쿠팡 어필리에이트 링크

        Returns:
            {"title", "intro", "body_sections":[4], "image_keywords":[5],
             "hashtags":[7], "seo_keywords":[4], "cta_text"}
        """
        prompt = f"""당신은 네이버 블로그 파워블로거이자 상품 리서처입니다.
아래 상품을 자연스럽게 소개하는 블로그 글을 작성하세요.

[상품 정보]
- 상품명: {product.title}
- 가격: {product.price}
- 설명: {product.description[:600] if product.description else '(정보 없음)'}

[작성 규칙 — 반드시 준수]
1. 실제로 구매해서 사용해본 척 절대 하지 마세요 (허위광고 금지)
2. 대신 "이 제품이 요즘 인기 있는 이유", "이런 분들한테 추천" 식으로 자연스럽게 설명하세요
3. 편한 존댓말 + 가끔 반말 섞어서 친근하게 ("근데 이거 진짜 괜찮더라고요ㅎㅎ")
4. 이모티콘(ㅋㅋ, ㅎㅎ, 😊) 적절히 사용
5. 총 1,500~2,000자 분량
6. 키워드 과도한 반복 금지 — 자연스러운 문장 흐름
7. "솔직히", "개인적으로", "확인해 보니" 같은 자연스러운 표현 사용

[필수 출력 구조 — 이 형식 그대로 출력]
[제목]
메인키워드 + 서브키워드3개를 자연스럽게 조합한 SEO 최적화 제목 (50자 이내)

[인트로]
왜 이 상품이 요즘 주목받는지 자연스러운 도입 (2-3줄)

[이미지1_키워드]
첫 번째 이미지 검색용 영어 키워드 (예: "premium wireless earbuds close up")

[본문1]
제품 소개 — 어떤 제품인지, 주요 특징 위주로 설명 (250-350자)

[이미지2_키워드]
두 번째 이미지 검색용 영어 키워드

[본문2]
장점 + 이런 분들한테 추천 — 타겟 고객 어필 (250-350자)

[이미지3_키워드]
세 번째 이미지 검색용 영어 키워드

[본문3]
가성비 분석 + 아쉬운 점(있다면) — 단, 장점이 훨씬 크다는 결론 (250-350자)

[이미지4_키워드]
네 번째 이미지 검색용 영어 키워드

[본문4]
총평 + "아래에서 확인해 보세요!" 같은 자연스러운 구매 유도 (200-300자)

[이미지5_키워드]
다섯 번째 이미지 검색용 영어 키워드 (라이프스타일 관련)

[해시태그]
#태그1 #태그2 #태그3 #태그4 #태그5 #태그6 #태그7

[SEO키워드]
메인키워드, 서브1, 서브2, 서브3"""

        try:
            raw = self._call_with_fallback(
                primary_fn=self._call_gemini,
                fallback_fn=lambda p, **kw: self._call_claude(
                    model=CLAUDE_HAIKU, prompt=p, **kw),
                prompt=prompt,
                max_tokens=4096,
                temperature=0.8,
            )
            return self._parse_blog_v2_response(raw, coupang_link)
        except Exception as e:
            logger.error(f"V2 블로그 콘텐츠 생성 실패: {e}")
            return self._fallback_blog_content(product, coupang_link)

    def _parse_blog_v2_response(self, raw: str, coupang_link: str = "") -> dict:
        """V2 블로그 AI 응답 파싱 → 구조화된 dict."""
        result = {
            "title": "",
            "intro": "",
            "body_sections": [],
            "image_keywords": [],
            "hashtags": [],
            "seo_keywords": [],
            "cta_text": "지금 최저가로 확인해 보세요!",
            "coupang_link": coupang_link,
        }

        try:
            # Gemini가 **[제목]** 처럼 마크다운 볼드로 감싸는 경우 대비
            # 전처리: **[라벨]** → [라벨] 으로 정규화
            cleaned = re.sub(r'\*{1,2}\[', '[', raw)
            cleaned = re.sub(r'\]\*{1,2}', ']', cleaned)

            # 섹션별 파싱 — 다음 [섹션] 또는 문자열 끝까지 캡처
            _NEXT = r'(?=\n\[|\Z)'

            sections = {
                "제목": "title",
                "인트로": "intro",
            }

            for label, key in sections.items():
                pattern = rf'\[{label}\]\s*\n(.+?){_NEXT}'
                match = re.search(pattern, cleaned, re.DOTALL)
                if match:
                    result[key] = match.group(1).strip()

            # 본문 1~4 파싱
            for i in range(1, 5):
                pattern = rf'\[본문{i}\]\s*\n(.+?){_NEXT}'
                match = re.search(pattern, cleaned, re.DOTALL)
                if match:
                    result["body_sections"].append(match.group(1).strip())

            # 이미지 키워드 1~5 파싱 — 첫 줄만 키워드 (나머지는 본문에 속함)
            for i in range(1, 6):
                pattern = rf'\[이미지{i}_키워드\]\s*\n(.+?)(?=\n|$)'
                match = re.search(pattern, cleaned)
                if match:
                    kw = match.group(1).strip()
                    # 200자 이상이면 파싱 오류 — 첫 줄만 추출
                    if len(kw) > 200:
                        kw = kw.split('\n')[0].strip()
                    result["image_keywords"].append(kw)

            # 해시태그 파싱
            ht_match = re.search(rf'\[해시태그\]\s*\n(.+?){_NEXT}', cleaned, re.DOTALL)
            if ht_match:
                ht_text = ht_match.group(1).strip()
                result["hashtags"] = [
                    t.strip().lstrip('#') for t in re.findall(r'#\S+', ht_text)
                ]

            # SEO 키워드 파싱
            seo_match = re.search(rf'\[SEO키워드\]\s*\n(.+?){_NEXT}', cleaned, re.DOTALL)
            if seo_match:
                seo_text = seo_match.group(1).strip()
                result["seo_keywords"] = [
                    k.strip() for k in re.split(r'[,，]', seo_text) if k.strip()
                ]

            # 마크다운 문법 제거
            for key in ["title", "intro"]:
                result[key] = re.sub(r'^[#*]+\s*', '', result[key])
            result["body_sections"] = [
                re.sub(r'^[#*]+\s*', '', s) for s in result["body_sections"]
            ]

            logger.info(
                f"V2 블로그 파싱: 제목={result['title'][:30]}, "
                f"본문={len(result['body_sections'])}섹션, "
                f"이미지KW={len(result['image_keywords'])}개"
            )
            return result

        except Exception as e:
            logger.error(f"V2 블로그 파싱 실패: {e}")
            return result

    def _fallback_blog_content(self, product: Product,
                                coupang_link: str = "") -> dict:
        """AI 실패 시 폴백 블로그 콘텐츠."""
        title = f"{product.title} — 요즘 핫한 이유 정리"
        return {
            "title": title,
            "intro": f"요즘 {product.title}이(가) 많은 관심을 받고 있어요. 왜 인기인지 한번 살펴볼게요!",
            "body_sections": [
                f"{product.title}은(는) {product.price} 가격대의 제품이에요. 기본적인 특징을 살펴보면 꽤 괜찮은 스펙을 갖추고 있어요.",
                "이런 분들한테 특히 추천할 만해요. 가성비를 중시하시는 분, 실용적인 제품을 찾으시는 분들이요.",
                "가격 대비 성능을 따져보면 충분히 만족스러운 수준이에요. 아쉬운 점이 있다면 배송이 조금 걸릴 수 있다는 정도?",
                "전체적으로 괜찮은 제품이에요! 궁금하신 분들은 아래에서 확인해 보세요 :)",
            ],
            "image_keywords": [
                f"{product.title} product photo",
                f"{product.title} detail close up",
                f"{product.title} lifestyle usage",
                f"{product.title} package unboxing",
                "happy customer using product",
            ],
            "hashtags": ["추천템", "가성비", "인기상품", "꿀템", "쇼핑추천", "생활용품", "쿠팡추천"],
            "seo_keywords": [product.title, "추천", "후기", "가성비"],
            "cta_text": "지금 최저가로 확인해 보세요!",
            "coupang_link": coupang_link,
        }

    def generate_shorts_hooking_script(
        self, product: Product, persona: str = "",
        coupang_link: str = "", dm_keyword: str = "링크",
    ) -> list[dict]:
        """V2 숏폼 전용 후킹 대본 생성 (블로그와 완전 별도).

        유튜브 쇼츠/인스타 릴스에 최적화된 짧고 강렬한 대본.
        각 장면에 감정 태그(emotion) 포함.

        Args:
            product: 상품 정보
            persona: 페르소나 (옵션)
            coupang_link: 쿠팡 링크
            dm_keyword: DM 유도 키워드

        Returns:
            [{"scene_num": 1, "text": "...", "duration": 2.0, "emotion": "excited"}, ...]
        """
        prompt = f"""당신은 유튜브 쇼츠/인스타 릴스 전문 크리에이터입니다.
아래 상품에 대한 숏폼 영상 대본을 작성하세요.

[상품 정보]
- 상품명: {product.title}
- 가격: {product.price}
- 설명: {product.description[:400] if product.description else '(없음)'}

[대본 작성 규칙 — 반드시 준수]
1. 총 5~6장면, 전체 40~55초 분량
2. 첫 장면(1-2초)은 무조건 후킹! "이거 모르면 손해", "와 이거 실화?" 스타일
3. 트렌디한 유튜브 쇼츠 톤 — 에너지 넘치고 빠르게
4. 각 장면에 반드시 감정 태그 포함: excited/friendly/urgent/dramatic/calm/hyped
5. 마지막 장면에 DM 유도 문구 포함: "[{dm_keyword}]를 댓글로 남겨주시면 구매 링크를 DM으로 즉시 보내드립니다!"
6. 블로그 본문 재사용 절대 금지 — 숏폼 전용 짧고 임팩트 있는 문장만
7. 각 장면 자막은 15~25자 이내로 짧게

[출력 형식 — 정확히 이 형식 준수]
[장면1]
텍스트: (자막 텍스트)
길이: (초 단위, 예: 2.0)
감정: (excited/friendly/urgent/dramatic/calm/hyped)

[장면2]
텍스트: (자막 텍스트)
길이: (초 단위)
감정: (태그)

... (5~6개 장면)"""

        try:
            raw = self._call_with_fallback(
                primary_fn=self._call_gemini,
                fallback_fn=lambda p, **kw: self._call_claude(
                    model=CLAUDE_HAIKU, prompt=p, **kw),
                prompt=prompt,
                max_tokens=2048,
                temperature=0.9,
            )
            scenes = self._parse_shorts_script(raw, dm_keyword)

            # 최소 5장면 보장
            if len(scenes) < 5:
                scenes = self._fallback_shorts_script(product, dm_keyword)

            logger.info(f"숏폼 대본 생성: {len(scenes)}장면")
            return scenes

        except Exception as e:
            logger.error(f"숏폼 대본 생성 실패: {e}")
            return self._fallback_shorts_script(product, dm_keyword)

    def _parse_shorts_script(self, raw: str,
                              dm_keyword: str = "링크") -> list[dict]:
        """숏폼 대본 AI 응답 파싱."""
        scenes = []
        valid_emotions = {"excited", "friendly", "urgent", "dramatic", "calm", "hyped"}

        try:
            # [장면N] 블록 파싱
            blocks = re.findall(
                r'\[장면(\d+)\]\s*\n(.+?)(?=\n\[장면|\Z)',
                raw, re.DOTALL
            )

            for scene_num_str, block in blocks:
                scene_num = int(scene_num_str)

                # 텍스트 추출
                text_match = re.search(r'텍스트:\s*(.+)', block)
                text = text_match.group(1).strip() if text_match else ""

                # 길이 추출
                dur_match = re.search(r'길이:\s*([\d.]+)', block)
                duration = float(dur_match.group(1)) if dur_match else 3.0

                # 감정 추출
                emo_match = re.search(r'감정:\s*(\w+)', block)
                emotion = emo_match.group(1).lower() if emo_match else "friendly"
                if emotion not in valid_emotions:
                    emotion = "friendly"

                if text:
                    scenes.append({
                        "scene_num": scene_num,
                        "text": text,
                        "duration": min(max(duration, 1.5), 12.0),
                        "emotion": emotion,
                    })

        except Exception as e:
            logger.error(f"숏폼 대본 파싱 에러: {e}")

        return scenes

    def _fallback_shorts_script(self, product: Product,
                                 dm_keyword: str = "링크") -> list[dict]:
        """대본 생성 실패 시 폴백 스크립트."""
        return [
            {"scene_num": 1, "text": "이거 아직도 모르면 손해예요!", "duration": 2.5, "emotion": "excited"},
            {"scene_num": 2, "text": f"{product.title[:15]} 찐템 발견", "duration": 3.0, "emotion": "hyped"},
            {"scene_num": 3, "text": f"가격이 {product.price}인데 이 퀄리티?", "duration": 3.5, "emotion": "friendly"},
            {"scene_num": 4, "text": "이 가격 진짜 실화인가요", "duration": 3.0, "emotion": "dramatic"},
            {"scene_num": 5, "text": f"[{dm_keyword}] 댓글 달면 링크 보내드려요!", "duration": 4.0, "emotion": "urgent"},
        ]

    def translate_for_search(self, korean_text: str) -> str:
        """상품명/키워드를 영어 검색어로 변환 (Gemini 무료).

        Args:
            korean_text: 한국어 상품명 또는 키워드

        Returns:
            영어 검색 키워드
        """
        prompt = f"""다음 한국어 상품명/키워드를 영어 검색 키워드로 변환해주세요.
검색엔진에서 관련 이미지/영상을 찾을 수 있는 핵심 키워드만 2-4단어로 짧게 작성하세요.

한국어: {korean_text}

영어 검색 키워드:"""

        try:
            result = self._call_gemini(
                prompt=prompt, max_tokens=100, temperature=0.3
            )
            # 깔끔하게 정리
            result = result.strip().strip('"').strip("'")
            result = re.sub(r'[^\w\s-]', '', result).strip()
            logger.info(f"번역: '{korean_text}' → '{result}'")
            return result if result else korean_text
        except Exception as e:
            logger.error(f"번역 실패: {e}")
            return korean_text
