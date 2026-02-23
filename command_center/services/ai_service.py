# -*- coding: utf-8 -*-
"""
통합 AI 서비스 — Gemini / Claude / OpenAI 멀티 프로바이더
비용 최적화: Gemini(무료) → Claude Haiku(저가) → OpenAI Mini(저가) → OpenAI(중가) → Claude Sonnet(고가)
"""
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from command_center.config import (
    GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY,
    AI_PROVIDERS, AI_FALLBACK_CHAIN,
)


@dataclass
class AIResponse:
    """AI 응답 통합 구조"""
    text: str
    provider: str           # gemini, claude_haiku, openai_mini, openai, claude_sonnet
    model: str              # 실제 모델명
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None


class AIService:
    """멀티 프로바이더 AI 서비스"""

    # 모델별 USD/1K 토큰 가격 (input, output)
    PRICING = {
        "gemini-2.5-flash":              (0.0, 0.0),        # 무료
        "claude-haiku-4-5-20251001":     (0.001, 0.005),
        "gpt-4o-mini":                   (0.00015, 0.0006),
        "gpt-4o":                        (0.0025, 0.01),
        "claude-sonnet-4-6-20250610":    (0.003, 0.015),
        "o1":                            (0.015, 0.06),
    }

    def __init__(self):
        self._clients = {}

    # ── 프로바이더별 호출 ──

    def _call_gemini(self, prompt: str, model: str = "gemini-2.5-flash",
                     system: str = "", **kwargs) -> AIResponse:
        """Gemini API 호출 (무료)"""
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        t0 = time.time()

        contents = prompt
        if system:
            contents = f"[System] {system}\n\n{prompt}"

        response = client.models.generate_content(model=model, contents=contents)
        elapsed = int((time.time() - t0) * 1000)

        text = response.text.strip() if response.text else ""
        usage = getattr(response, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", 0) or 0
        out_tok = getattr(usage, "candidates_token_count", 0) or 0

        return AIResponse(
            text=text, provider="gemini", model=model,
            input_tokens=in_tok, output_tokens=out_tok,
            elapsed_ms=elapsed, cost_usd=0.0,
        )

    def _call_anthropic(self, prompt: str, model: str = "claude-haiku-4-5-20251001",
                        system: str = "", max_tokens: int = 4096, **kwargs) -> AIResponse:
        """Anthropic Claude API 호출"""
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        t0 = time.time()

        msg_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            msg_kwargs["system"] = system

        response = client.messages.create(**msg_kwargs)
        elapsed = int((time.time() - t0) * 1000)

        text = response.content[0].text if response.content else ""
        in_tok = response.usage.input_tokens
        out_tok = response.usage.output_tokens
        cost = self._calc_cost(model, in_tok, out_tok)

        return AIResponse(
            text=text, provider=self._provider_name(model), model=model,
            input_tokens=in_tok, output_tokens=out_tok,
            elapsed_ms=elapsed, cost_usd=cost,
        )

    def _call_openai(self, prompt: str, model: str = "gpt-4o-mini",
                     system: str = "", max_tokens: int = 4096, **kwargs) -> AIResponse:
        """OpenAI API 호출"""
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        t0 = time.time()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        elapsed = int((time.time() - t0) * 1000)

        text = response.choices[0].message.content or ""
        in_tok = response.usage.prompt_tokens if response.usage else 0
        out_tok = response.usage.completion_tokens if response.usage else 0
        cost = self._calc_cost(model, in_tok, out_tok)

        return AIResponse(
            text=text, provider=self._provider_name(model), model=model,
            input_tokens=in_tok, output_tokens=out_tok,
            elapsed_ms=elapsed, cost_usd=cost,
        )

    # ── 통합 인터페이스 ──

    def ask(self, prompt: str, provider: Optional[str] = None,
            system: str = "", max_tokens: int = 4096, **kwargs) -> AIResponse:
        """
        AI에게 질문. provider를 지정하면 해당 프로바이더만, 미지정 시 fallback chain 자동.

        Args:
            prompt: 사용자 프롬프트
            provider: gemini, claude_haiku, openai_mini, openai, claude_sonnet, openai_o1
            system: 시스템 프롬프트
            max_tokens: 최대 출력 토큰
        """
        if provider:
            return self._dispatch(provider, prompt, system, max_tokens, **kwargs)

        # fallback chain 순회
        errors = []
        for prov in AI_FALLBACK_CHAIN:
            if not self._is_available(prov):
                continue
            try:
                return self._dispatch(prov, prompt, system, max_tokens, **kwargs)
            except Exception as e:
                errors.append(f"{prov}: {e}")
                continue

        return AIResponse(
            text="", provider="none", model="none",
            error=f"모든 AI 프로바이더 실패: {'; '.join(errors)}"
        )

    def ask_openai(self, prompt: str, model: str = "gpt-4o-mini",
                   system: str = "", max_tokens: int = 4096) -> AIResponse:
        """OpenAI 직접 호출 단축 메서드"""
        return self._call_openai(prompt, model=model, system=system, max_tokens=max_tokens)

    def ask_claude(self, prompt: str, model: str = "claude-haiku-4-5-20251001",
                   system: str = "", max_tokens: int = 4096) -> AIResponse:
        """Claude 직접 호출 단축 메서드"""
        return self._call_anthropic(prompt, model=model, system=system, max_tokens=max_tokens)

    def ask_gemini(self, prompt: str, system: str = "") -> AIResponse:
        """Gemini 직접 호출 단축 메서드"""
        return self._call_gemini(prompt, system=system)

    def list_providers(self) -> list[dict]:
        """사용 가능한 프로바이더 목록"""
        result = []
        for name, info in AI_PROVIDERS.items():
            result.append({
                "name": name,
                "model": info["model"],
                "cost": info["cost"],
                "available": self._is_available(name),
            })
        return sorted(result, key=lambda x: AI_PROVIDERS.get(x["name"], {}).get("priority", 99))

    # ── 내부 유틸 ──

    def _dispatch(self, provider: str, prompt: str, system: str,
                  max_tokens: int, **kwargs) -> AIResponse:
        """프로바이더별 분기"""
        info = AI_PROVIDERS.get(provider, {})
        model = info.get("model", "")

        if provider == "gemini":
            return self._call_gemini(prompt, model=model, system=system, **kwargs)
        elif provider in ("claude_haiku", "claude_sonnet"):
            return self._call_anthropic(prompt, model=model, system=system,
                                        max_tokens=max_tokens, **kwargs)
        elif provider in ("openai_mini", "openai", "openai_o1"):
            return self._call_openai(prompt, model=model, system=system,
                                     max_tokens=max_tokens, **kwargs)
        else:
            raise ValueError(f"알 수 없는 프로바이더: {provider}")

    def _is_available(self, provider: str) -> bool:
        """프로바이더 키 존재 여부"""
        if provider == "gemini":
            return bool(GEMINI_API_KEY)
        elif provider in ("claude_haiku", "claude_sonnet"):
            return bool(ANTHROPIC_API_KEY)
        elif provider in ("openai_mini", "openai", "openai_o1"):
            return bool(OPENAI_API_KEY)
        return False

    def _calc_cost(self, model: str, in_tok: int, out_tok: int) -> float:
        """USD 비용 계산"""
        prices = self.PRICING.get(model, (0.0, 0.0))
        return (in_tok / 1000 * prices[0]) + (out_tok / 1000 * prices[1])

    def _provider_name(self, model: str) -> str:
        """모델명 → 프로바이더명 매핑"""
        for name, info in AI_PROVIDERS.items():
            if info["model"] == model:
                return name
        return "unknown"

    def _record_cost(self, response: AIResponse):
        """비용 기록 (api_cost_tracker 연동)"""
        try:
            from api_cost_tracker import CostTracker
            tracker = CostTracker(project_name="ai_service")
            tracker.record(response.model, response.input_tokens, response.output_tokens)
        except Exception:
            pass  # 비용 추적 실패해도 무시
