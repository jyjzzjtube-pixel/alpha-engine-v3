# -*- coding: utf-8 -*-
"""
오더 엔진 — 자연어 명령 파싱 + AI 실행
하이브리드: 로컬 패턴 매칭 우선 → Gemini(무료) → Claude(유료) 폴백
"""
import re
import time
from typing import Optional, Tuple

from ..config import GEMINI_API_KEY, ANTHROPIC_API_KEY, AI_FALLBACK_CHAIN, PROJECT_DIR


# ── 명령 패턴 ──
ORDER_PATTERNS = [
    (r"(?:전체\s*)?(?:점검|체크|check|health)", "health_check_all", None),
    (r"(?:전체\s*)?배포|deploy\s*all", "deploy_all", None),
    (r"(?:배포|deploy)\s+(.+)", "deploy", "site"),
    (r"(?:봇|bot)\s*(?:재시작|restart)\s*(.*)?", "bot_restart", "bot"),
    (r"(?:봇|bot)\s*(?:시작|start)\s*(.*)?", "bot_start", "bot"),
    (r"(?:봇|bot)\s*(?:중지|stop)\s*(.*)?", "bot_stop", "bot"),
    (r"(?:비용|cost)\s*(?:분석|요약|summary|report)?", "cost_report", None),
    (r"(?:사이트|site)\s*(?:열기|open)\s+(.+)", "open_site", "site"),
    (r"(?:알림|alert)\s*(?:확인|check)?", "check_alerts", None),
    (r"(?:상태|status)", "status_all", None),
]


class OrderEngine:
    """자연어 명령 → 액션 매핑 + AI 폴백"""

    def __init__(self):
        self._gemini_client = None
        self._anthropic_client = None
        self._init_ai()

    def _init_ai(self):
        if GEMINI_API_KEY:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            except Exception:
                pass
        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except Exception:
                pass

    def parse_command(self, text: str) -> Tuple[str, Optional[str]]:
        """자연어 → (action, target) 매핑
        Returns: (action_name, target_param) or ("ai_query", original_text)
        """
        text = text.strip()
        for pattern, action, param_type in ORDER_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                target = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else None
                return action, target
        # 패턴 매칭 실패 → AI 쿼리로 분류
        return "ai_query", text

    def ai_chat(self, prompt: str, context: str = "") -> str:
        """하이브리드 AI 채팅 — Gemini(무료) 우선 → Claude 폴백"""
        system = (
            "너는 YJ Partners 통합 커맨드센터의 AI 어시스턴트야. "
            "사용자의 질문에 한국어로 간결하게 답변해. "
            "기술 용어는 알기 쉽게 설명하고, 숫자는 한국 원(₩)과 달러($)로 표시해."
        )
        if context:
            system += f"\n\n현재 시스템 상태:\n{context}"

        full_prompt = f"{system}\n\n사용자: {prompt}"

        # 1차: Gemini (무료)
        if self._gemini_client:
            try:
                resp = self._gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=full_prompt,
                )
                return resp.text.strip()
            except Exception:
                pass

        # 2차: Claude Haiku (저비용)
        if self._anthropic_client:
            try:
                resp = self._anthropic_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                    system=system,
                )
                return resp.content[0].text.strip()
            except Exception:
                pass

        return "AI 서비스에 연결할 수 없습니다. API 키를 확인해주세요."

    def generate_report(self, data: dict) -> str:
        """시스템 상태 리포트 AI 생성"""
        prompt = (
            f"다음 시스템 상태를 분석해서 간결한 리포트를 작성해줘:\n"
            f"사이트: {data.get('sites_up', 0)}/{data.get('sites_total', 0)} 정상\n"
            f"봇: {data.get('bots_running', 0)}/{data.get('bots_total', 0)} 실행중\n"
            f"오늘 API 비용: ₩{data.get('cost_today_krw', 0):,}\n"
            f"이번달 API 비용: ₩{data.get('cost_monthly_krw', 0):,} / ₩{data.get('budget_limit', 50000):,}\n"
            f"새 알림: {data.get('unread_alerts', 0)}건\n"
        )
        return self.ai_chat(prompt)
