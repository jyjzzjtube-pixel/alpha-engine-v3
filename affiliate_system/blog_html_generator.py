"""
Naver Blog HTML Generator V2
=============================
자연스러운 설명/추천 스타일 블로그 HTML 생성기.
이미지-텍스트 교차 배치, CTA 이미지(쿠팡 링크), 면책고지 자동 삽입.
네이버 스마트에디터 호환 HTML 출력.
"""
import logging
import os
import re
import html as html_lib
from pathlib import Path
from typing import Optional

from affiliate_system.config import (
    COUPANG_DISCLAIMER, BLOG_IMAGE_RESIZE_WIDTH
)

logger = logging.getLogger("blog_html_generator")


class NaverBlogHTMLGenerator:
    """네이버 블로그 HTML 생성기 — V2 텍스트-이미지 교차 배치."""

    # 네이버 스마트에디터 호환 인라인 스타일
    STYLES = {
        "wrapper": (
            "font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif; "
            "font-size: 16px; line-height: 1.8; color: #333; "
            "max-width: 860px; margin: 0 auto; padding: 0 16px;"
        ),
        "intro": (
            "font-size: 17px; color: #555; margin-bottom: 24px; "
            "line-height: 1.9; padding: 16px 0; "
            "border-bottom: 1px solid #eee;"
        ),
        "body_section": (
            "font-size: 16px; color: #333; margin: 20px 0; "
            "line-height: 1.9; word-break: keep-all;"
        ),
        "image_wrap": (
            "text-align: center; margin: 24px 0;"
        ),
        "image": (
            f"max-width: 100%; width: {BLOG_IMAGE_RESIZE_WIDTH}px; "
            "height: auto; border-radius: 8px; "
            "box-shadow: 0 2px 8px rgba(0,0,0,0.1);"
        ),
        "cta_wrap": (
            "text-align: center; margin: 32px 0; "
            "padding: 20px; background: #fff9f0; "
            "border: 2px dashed #ff6b35; border-radius: 12px;"
        ),
        "cta_text": (
            "font-size: 15px; color: #ff6b35; font-weight: 700; "
            "margin-bottom: 12px; display: block;"
        ),
        "cta_button": (
            "display: inline-block; padding: 14px 40px; "
            "background: linear-gradient(135deg, #ff6b35, #ff4500); "
            "color: #fff; font-size: 16px; font-weight: 700; "
            "text-decoration: none; border-radius: 30px; "
            "box-shadow: 0 4px 12px rgba(255,107,53,0.4);"
        ),
        "disclaimer": (
            "font-size: 12px; color: #999; margin-top: 40px; "
            "padding-top: 16px; border-top: 1px solid #eee; "
            "text-align: center;"
        ),
        "hashtags": (
            "font-size: 14px; color: #0077cc; margin-top: 16px; "
            "text-align: center; word-spacing: 4px;"
        ),
        "section_divider": (
            "border: 0; height: 1px; background: #f0f0f0; "
            "margin: 28px 0;"
        ),
    }

    def __init__(self):
        """HTML 생성기 초기화."""
        self.logger = logger

    def generate_blog_html(
        self,
        title: str,
        intro: str,
        body_sections: list[str],
        image_paths: list[str],
        coupang_link: str,
        cta_text: str = "",
        hashtags: list[str] = None,
        disclaimer: str = "",
        banner_tag: str = "",
    ) -> str:
        """네이버 블로그용 HTML 생성.

        구조:
        [인트로] → [이미지1] → [본문1] → [이미지2] → [본문2]
        → [CTA+쿠팡링크] → [이미지3] → [본문3] → [이미지4] → [본문4]
        → [CTA+쿠팡링크] → [이미지5] → [면책고지] → [해시태그]

        Args:
            title: 블로그 제목 (에디터에서 별도 설정)
            intro: 도입부 텍스트
            body_sections: 본문 섹션 리스트 (4개 권장)
            image_paths: 이미지 파일 경로 리스트 (5-7개)
            coupang_link: 쿠팡 파트너스 어필리에이트 링크
            cta_text: CTA 문구 (기본: "최저가로 확인하기")
            hashtags: 해시태그 리스트
            disclaimer: 면책고지 (기본: 쿠팡 파트너스 문구)

        Returns:
            네이버 스마트에디터 호환 HTML 문자열
        """
        try:
            # 기본값 설정
            if not cta_text:
                cta_text = "지금 최저가로 확인해 보세요!"
            if not disclaimer:
                disclaimer = COUPANG_DISCLAIMER
            if hashtags is None:
                hashtags = []

            # 이미지/본문 개수 보정
            body_sections = body_sections or []
            image_paths = image_paths or []

            # 최소 보장: 본문 4개, 이미지 5개
            while len(body_sections) < 4:
                body_sections.append("")
            while len(image_paths) < 5:
                image_paths.append("")

            # HTML 조립 시작
            parts = []
            parts.append(f'<div style="{self.STYLES["wrapper"]}">')

            # ── 인트로 ──
            if intro:
                intro_html = self._text_to_html(intro)
                parts.append(f'<div style="{self.STYLES["intro"]}">')
                parts.append(intro_html)
                parts.append('</div>')

            # ── 이미지1 + 본문1 ──
            parts.append(self._make_image_block(image_paths, 0))
            parts.append(self._make_body_block(body_sections, 0))

            # ── 이미지2 + 본문2 ──
            parts.append(self._make_image_block(image_paths, 1))
            parts.append(self._make_body_block(body_sections, 1))

            # ── 중간 CTA (쿠팡 배너 이미지 + 링크) ──
            parts.append(self._make_cta_block(coupang_link, cta_text, banner_tag))
            parts.append(f'<hr style="{self.STYLES["section_divider"]}">')

            # ── 이미지3 + 본문3 ──
            parts.append(self._make_image_block(image_paths, 2))
            parts.append(self._make_body_block(body_sections, 2))

            # ── 이미지4 + 본문4 ──
            parts.append(self._make_image_block(image_paths, 3))
            parts.append(self._make_body_block(body_sections, 3))

            # ── 마지막 CTA (쿠팡 배너 이미지 + 링크) ──
            parts.append(self._make_cta_block(coupang_link, cta_text, banner_tag))

            # ── 이미지5 (라이프스타일) ──
            if len(image_paths) > 4 and image_paths[4]:
                parts.append(self._make_image_block(image_paths, 4))

            # ── 추가 이미지 (6, 7번째) ──
            for idx in range(5, min(len(image_paths), 7)):
                if image_paths[idx]:
                    parts.append(self._make_image_block(image_paths, idx))

            # ── 면책고지 ──
            parts.append(f'<p style="{self.STYLES["disclaimer"]}">')
            parts.append(html_lib.escape(disclaimer))
            parts.append('</p>')

            # ── 해시태그 ──
            if hashtags:
                tags_str = " ".join(
                    f"#{tag.strip().lstrip('#')}" for tag in hashtags if tag.strip()
                )
                parts.append(f'<p style="{self.STYLES["hashtags"]}">')
                parts.append(html_lib.escape(tags_str))
                parts.append('</p>')

            parts.append('</div>')

            result_html = "\n".join(parts)
            self.logger.info(
                f"블로그 HTML 생성 완료: {len(result_html)}자, "
                f"이미지 {len([p for p in image_paths if p])}장"
            )
            return result_html

        except Exception as e:
            self.logger.error(f"블로그 HTML 생성 실패: {e}")
            # 폴백: 최소한의 HTML 반환
            return self._generate_fallback_html(
                intro, body_sections, coupang_link, disclaimer
            )

    def _make_image_block(self, image_paths: list[str], index: int) -> str:
        """이미지 블록 HTML 생성."""
        if index >= len(image_paths) or not image_paths[index]:
            return ""

        img_path = image_paths[index]

        # 네이버 블로그에서는 업로드된 이미지 URL 사용
        # 로컬 경로일 경우 파일명만 참조 (업로드 후 URL 교체)
        if img_path.startswith("http"):
            img_src = img_path
        else:
            # 로컬 파일 — 네이버 업로드 시 교체될 플레이스홀더
            img_filename = Path(img_path).name
            img_src = f"__LOCAL_IMAGE_{index}_{img_filename}__"

        return (
            f'<div style="{self.STYLES["image_wrap"]}">'
            f'<img src="{html_lib.escape(img_src)}" '
            f'style="{self.STYLES["image"]}" '
            f'alt="상품 이미지 {index + 1}" loading="lazy">'
            f'</div>'
        )

    def _make_body_block(self, body_sections: list[str], index: int) -> str:
        """본문 섹션 HTML 생성."""
        if index >= len(body_sections) or not body_sections[index]:
            return ""

        body_html = self._text_to_html(body_sections[index])
        return (
            f'<div style="{self.STYLES["body_section"]}">'
            f'{body_html}'
            f'</div>'
        )

    def _make_cta_block(self, coupang_link: str, cta_text: str,
                        banner_tag: str = "") -> str:
        """CTA (Call-To-Action) 블록 — 쿠팡 배너 이미지 + 링크 포함.

        네이버 블로그에서는 쿠팡 파트너스 배너(<a><img>) + 단축URL 버튼 배치.
        배너 태그가 없으면 버튼만 표시.
        """
        if not coupang_link:
            return ""

        safe_link = html_lib.escape(coupang_link)
        safe_text = html_lib.escape(cta_text)

        parts = [f'<div style="{self.STYLES["cta_wrap"]}">']

        # 쿠팡 파트너스 배너/위젯 (배너 이미지 <a><img> 또는 iframe)
        if banner_tag:
            _tag = banner_tag.strip()
            # 보안 검증: 쿠팡 관련 도메인인지 확인
            is_coupang = any(domain in _tag for domain in (
                "coupa.ng", "coupang.com", "coupangcdn.com",
                "link.coupang.com",
            ))
            if is_coupang:
                parts.append(
                    f'<div style="text-align:center;margin-bottom:12px;">'
                    f'{_tag}'
                    f'</div>'
                )

        # CTA 텍스트 + 버튼
        parts.append(
            f'<span style="{self.STYLES["cta_text"]}">'
            f'아래 버튼을 눌러 확인해 보세요!</span>'
        )
        parts.append(
            f'<a href="{safe_link}" target="_blank" rel="noopener" '
            f'style="{self.STYLES["cta_button"]}">'
            f'{safe_text}</a>'
        )
        parts.append('</div>')

        return "\n".join(parts)

    def _text_to_html(self, text: str) -> str:
        """일반 텍스트를 HTML로 변환.

        - 줄바꿈 → <br>
        - **볼드** → <b>
        - 이모지 유지
        - XSS 방지용 이스케이프
        """
        if not text:
            return ""

        # HTML 이스케이프
        safe = html_lib.escape(text)

        # **볼드** 처리
        safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)

        # 줄바꿈 처리
        safe = safe.replace('\n', '<br>')

        return safe

    def _generate_fallback_html(
        self,
        intro: str,
        body_sections: list[str],
        coupang_link: str,
        disclaimer: str,
    ) -> str:
        """에러 시 폴백 HTML — 최소한의 텍스트만."""
        parts = ['<div>']
        if intro:
            parts.append(f'<p>{html_lib.escape(intro)}</p>')
        for section in body_sections:
            if section:
                parts.append(f'<p>{html_lib.escape(section)}</p>')
        if coupang_link:
            parts.append(
                f'<p><a href="{html_lib.escape(coupang_link)}">구매 링크</a></p>'
            )
        if disclaimer:
            parts.append(f'<p style="font-size:12px;color:#999">{html_lib.escape(disclaimer)}</p>')
        parts.append('</div>')
        return "\n".join(parts)


# ── 단독 테스트 ──
if __name__ == "__main__":
    gen = NaverBlogHTMLGenerator()
    test_html = gen.generate_blog_html(
        title="테스트 상품 리뷰",
        intro="요즘 이 제품이 엄청 핫하더라고요. 왜 인기 있는지 한번 살펴볼게요!",
        body_sections=[
            "첫 눈에 봤을 때 디자인이 꽤 깔끔해요. 색감도 예쁘고 마감도 좋은 편이에요.",
            "실제로 사용해 보면 기능도 다양하고 성능도 꽤 괜찮아요. 이 가격대에서 이 정도면 놀라운 수준이에요.",
            "가성비로 따지면 솔직히 이 가격에 이 퀄리티면 무조건 이득이에요. 단점을 굳이 찾자면 배송이 좀 느릴 수 있어요.",
            "전체적으로 추천할 만한 제품이에요! 궁금하신 분들은 아래에서 확인해 보세요.",
        ],
        image_paths=[
            "test_image_1.jpg", "test_image_2.jpg",
            "test_image_3.jpg", "test_image_4.jpg",
            "test_image_5.jpg",
        ],
        coupang_link="https://link.coupang.com/test123",
        hashtags=["가성비템", "추천템", "인기상품", "생활용품", "쿠팡추천"],
    )
    print(f"생성된 HTML 길이: {len(test_html)}자")
    print(test_html[:500])
