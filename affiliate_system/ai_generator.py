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

import time
from typing import Callable, Optional

from affiliate_system.config import GEMINI_API_KEY, ANTHROPIC_API_KEY, AI_ROUTING
from affiliate_system.models import Product, AIContent, Campaign
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
