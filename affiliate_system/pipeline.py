# -*- coding: utf-8 -*-
"""
1주제 → 3플랫폼 풀 파이프라인 오케스트레이터
=============================================
쿠팡 상품 URL 또는 주제 텍스트 하나를 입력하면:
  1. 상품 스크래핑 (쿠팡) or 주제 기반 Product 생성
  2. AI 콘텐츠 생성 (YouTube Shorts / Instagram Reels / Naver Blog)
  3. 스톡 이미지 수집 (Pexels + Unsplash)
  4. 썸네일 자동 생성 (3플랫폼)
  5. 영상 렌더링 (3플랫폼)
  6. (선택) 자동 업로드/발행

모든 기존 모듈을 재사용하며 새로운 코드는 연결 로직만 담당한다.
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from affiliate_system.config import RENDER_OUTPUT_DIR, WORK_DIR
from affiliate_system.models import (
    Product, AIContent, Campaign, Platform,
    RenderConfig, PLATFORM_PRESETS,
    CampaignStatus,
)
from affiliate_system.utils import setup_logger, ensure_dir

__all__ = ["ContentPipeline"]

logger = setup_logger("pipeline", "pipeline.log")

# 지원 플랫폼 전체
ALL_PLATFORMS = [Platform.YOUTUBE, Platform.INSTAGRAM, Platform.NAVER_BLOG]


class ContentPipeline:
    """1주제 → 3플랫폼 풀 자동화 파이프라인.

    사용법:
        pipeline = ContentPipeline()
        results = pipeline.run("https://www.coupang.com/vp/products/123456")
        # 또는
        results = pipeline.run("오레노카츠 프리미엄 돈카츠", brand="오레노카츠")
    """

    def __init__(self):
        self._output_dir = ensure_dir(RENDER_OUTPUT_DIR)
        self._media_dir = ensure_dir(WORK_DIR / "media_downloads")
        logger.info("ContentPipeline 초기화 완료")

    # ──────────────────────────────────────────────
    # 메인 파이프라인
    # ──────────────────────────────────────────────

    def run(
        self,
        topic_or_url: str,
        platforms: Optional[list[Platform]] = None,
        brand: str = "",
        persona: str = "",
        auto_upload: bool = False,
    ) -> dict:
        """풀 파이프라인을 실행한다.

        Args:
            topic_or_url: 쿠팡 상품 URL 또는 주제 텍스트
            platforms: 대상 플랫폼 리스트 (None이면 3개 모두)
            brand: 브랜드명 (브랜딩 적용 시)
            persona: AI 페르소나
            auto_upload: True이면 자동 업로드까지 수행

        Returns:
            {
              "campaign": Campaign 객체,
              "platforms": {
                "youtube": {"video": path, "thumbnail": path, "content": dict},
                "instagram": {...},
                "naver_blog": {...},
              },
              "upload_results": {...} (auto_upload일 때만)
            }
        """
        platforms = platforms or ALL_PLATFORMS
        campaign_id = uuid.uuid4().hex[:8]
        start_time = time.time()

        logger.info(f"{'='*60}")
        logger.info(f"파이프라인 시작: {topic_or_url[:60]}")
        logger.info(f"캠페인 ID: {campaign_id}")
        logger.info(f"플랫폼: {[p.value for p in platforms]}")
        logger.info(f"{'='*60}")

        results: dict = {"platforms": {}, "upload_results": {}}

        # ── Step 1: 상품 정보 준비 ──
        print(f"\n[1/6] 상품 정보 수집 중...")
        product = self._prepare_product(topic_or_url)
        logger.info(f"상품 준비 완료: {product.title}")
        print(f"  ✓ 상품: {product.title}")
        print(f"  ✓ 가격: {product.price or '(미지정)'}")
        print(f"  ✓ 제휴링크: {product.affiliate_link or '(없음)'}")

        # ── Step 2: AI 콘텐츠 생성 ──
        print(f"\n[2/6] AI 콘텐츠 생성 중 ({len(platforms)}개 플랫폼)...")
        platform_contents = self._generate_contents(product, platforms, persona, brand)
        for p_name, content in platform_contents.items():
            narr_count = len(content.get("narration", []))
            hash_count = len(content.get("hashtags", []))
            print(f"  ✓ {p_name}: 제목={len(content.get('title',''))}자, "
                  f"나레이션={narr_count}장면, 해시태그={hash_count}개")

        # ── Step 3: 미디어 수집 ──
        print(f"\n[3/6] 스톡 이미지 수집 중...")
        images = self._collect_media(product)
        print(f"  ✓ 이미지 {len(images)}개 수집 완료")

        # ── Step 4: 썸네일 생성 ──
        print(f"\n[4/6] 썸네일 생성 중...")
        thumbnails = self._generate_thumbnails(
            platforms, platform_contents, images, brand, campaign_id,
        )
        for p_name, thumb_path in thumbnails.items():
            print(f"  ✓ {p_name}: {Path(thumb_path).name}")

        # ── Step 5: 영상 렌더링 ──
        print(f"\n[5/6] 영상 렌더링 중...")
        videos = self._render_videos(
            platforms, platform_contents, images, brand, campaign_id,
        )
        for p_name, video_path in videos.items():
            if video_path:
                size_mb = Path(video_path).stat().st_size / (1024 * 1024)
                print(f"  ✓ {p_name}: {Path(video_path).name} ({size_mb:.1f}MB)")
            else:
                print(f"  ✗ {p_name}: 렌더링 실패")

        # 결과 조합
        campaign = Campaign(
            id=campaign_id,
            product=product,
            ai_content=AIContent(
                platform_contents=platform_contents,
            ),
            status=CampaignStatus.COMPLETE,
            target_platforms=platforms,
            platform_videos=videos,
            platform_thumbnails=thumbnails,
            created_at=datetime.now(),
        )

        for p in platforms:
            p_name = p.value
            results["platforms"][p_name] = {
                "video": videos.get(p_name, ""),
                "thumbnail": thumbnails.get(p_name, ""),
                "content": platform_contents.get(p_name, {}),
            }

        results["campaign"] = campaign

        # ── Step 6: 자동 업로드 ──
        if auto_upload:
            print(f"\n[6/6] 자동 업로드 중...")
            upload_results = self._upload_all(campaign)
            results["upload_results"] = upload_results
            for p_name, result in upload_results.items():
                status = "✓ 성공" if result.get("ok") else "✗ 실패"
                print(f"  {status}: {p_name}")
        else:
            print(f"\n[6/6] 업로드 건너뜀 (--upload 플래그로 활성화)")

        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"파이프라인 완료! (소요시간: {elapsed:.1f}초)")
        print(f"출력 경로: {self._output_dir}")
        print(f"{'='*60}\n")

        logger.info(f"파이프라인 완료: {elapsed:.1f}초")
        return results

    # ──────────────────────────────────────────────
    # Step 1: 상품 정보 준비
    # ──────────────────────────────────────────────

    def _prepare_product(self, topic_or_url: str) -> Product:
        """입력이 URL이면 스크래핑, 텍스트이면 주제 기반 Product 생성."""
        from affiliate_system.coupang_scraper import CoupangScraper

        if CoupangScraper.is_coupang_url(topic_or_url):
            logger.info("쿠팡 URL 감지 — 스크래핑 시작")
            scraper = CoupangScraper()
            return scraper.scrape_and_link(topic_or_url)

        # URL이지만 쿠팡이 아닌 경우 (일반 URL)
        if topic_or_url.startswith("http"):
            logger.info("일반 URL 감지 — OG 태그 스크래핑")
            return self._scrape_generic_url(topic_or_url)

        # 텍스트 주제 — Product 객체로 변환
        logger.info(f"주제 텍스트 입력: {topic_or_url}")
        return Product(
            title=topic_or_url,
            description=topic_or_url,
            scraped_at=datetime.now(),
        )

    def _scrape_generic_url(self, url: str) -> Product:
        """일반 URL에서 OG 태그로 기본 상품 정보를 추출한다."""
        import requests
        from bs4 import BeautifulSoup

        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            title = ""
            description = ""
            image_urls = []

            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content", "")

            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                description = og_desc.get("content", "")

            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_urls.append(og_image["content"])

            if not title:
                t = soup.find("title")
                title = t.get_text(strip=True) if t else url

            return Product(
                url=url,
                title=title,
                description=description,
                image_urls=image_urls,
                scraped_at=datetime.now(),
            )
        except Exception as e:
            logger.warning(f"일반 URL 스크래핑 실패: {e}")
            return Product(url=url, title=url, scraped_at=datetime.now())

    # ──────────────────────────────────────────────
    # Step 2: AI 콘텐츠 생성
    # ──────────────────────────────────────────────

    def _generate_contents(
        self, product: Product, platforms: list[Platform],
        persona: str = "", brand: str = "",
    ) -> dict[str, dict]:
        """플랫폼별 AI 콘텐츠를 생성한다."""
        from affiliate_system.ai_generator import AIGenerator

        gen = AIGenerator()
        results: dict[str, dict] = {}

        for platform in platforms:
            try:
                logger.info(f"AI 콘텐츠 생성: {platform.value}")
                content = gen.generate_platform_content(
                    product, platform, persona=persona, brand=brand,
                )
                results[platform.value] = content
            except Exception as e:
                logger.error(f"AI 생성 실패 ({platform.value}): {e}")
                results[platform.value] = {
                    "title": product.title,
                    "body": "",
                    "hashtags": [],
                    "narration": [],
                    "cta": "",
                    "thumbnail_text": product.title[:7],
                    "thumbnail_subtitle": "",
                }

        cost = gen.get_session_cost()
        logger.info(f"AI 생성 비용: ${cost:.6f}")
        return results

    # ──────────────────────────────────────────────
    # Step 3: 미디어 수집
    # ──────────────────────────────────────────────

    def _collect_media(self, product: Product) -> list[str]:
        """스톡 이미지를 수집하고 다운로드한다."""
        from affiliate_system.media_collector import MediaCollector

        collector = MediaCollector()
        downloaded: list[str] = []

        # 검색 키워드 생성 (상품명에서 핵심 키워드 추출)
        query = product.title[:30] if product.title else "product"
        # 한국어 키워드는 영어로 변환하여 검색
        query_en = self._extract_search_keywords(product)

        # Pexels + Unsplash 통합 검색
        all_results: list[dict] = []
        try:
            pexels = collector.search_pexels_images(query_en, count=5)
            all_results.extend(pexels)
        except Exception as e:
            logger.warning(f"Pexels 검색 실패: {e}")

        try:
            unsplash = collector.search_unsplash_images(query_en, count=5)
            all_results.extend(unsplash)
        except Exception as e:
            logger.warning(f"Unsplash 검색 실패: {e}")

        # 상위 5개 다운로드
        for item in all_results[:5]:
            try:
                img_url = item.get("url", "")
                if img_url:
                    path = collector.download_image(img_url)
                    if path:
                        downloaded.append(path)
            except Exception as e:
                logger.warning(f"이미지 다운로드 실패: {e}")

        # 상품 자체 이미지도 다운로드
        for img_url in product.image_urls[:3]:
            try:
                path = collector.download_image(img_url)
                if path:
                    downloaded.append(path)
            except Exception:
                pass

        logger.info(f"미디어 수집 완료: {len(downloaded)}개")
        return downloaded

    def _extract_search_keywords(self, product: Product) -> str:
        """상품 정보에서 영어 검색 키워드를 추출한다."""
        title = product.title or ""
        # 간단한 한→영 키워드 매핑 (자주 쓰이는 음식/상품 카테고리)
        keyword_map = {
            "돈카츠": "tonkatsu pork cutlet",
            "카츠": "katsu cutlet",
            "짬뽕": "jjamppong spicy noodle",
            "프랜차이즈": "franchise business",
            "창업": "startup business",
            "화장품": "cosmetics beauty",
            "의류": "fashion clothing",
            "전자제품": "electronics gadget",
            "식품": "food gourmet",
            "건강": "health wellness",
            "다이어트": "diet fitness",
            "주방": "kitchen cooking",
            "인테리어": "interior home decor",
            "캠핑": "camping outdoor",
        }

        for kr, en in keyword_map.items():
            if kr in title:
                return en

        # 기본: 상품 카테고리 추정
        return "product review lifestyle"

    # ──────────────────────────────────────────────
    # Step 4: 썸네일 생성
    # ──────────────────────────────────────────────

    def _generate_thumbnails(
        self,
        platforms: list[Platform],
        contents: dict[str, dict],
        images: list[str],
        brand: str,
        campaign_id: str,
    ) -> dict[str, str]:
        """플랫폼별 썸네일을 생성한다."""
        from affiliate_system.thumbnail_generator import ThumbnailGenerator

        gen = ThumbnailGenerator()
        thumbnails: dict[str, str] = {}

        bg_image = images[0] if images else ""

        for platform in platforms:
            p_name = platform.value
            content = contents.get(p_name, {})
            title = content.get("thumbnail_text", "") or content.get("title", "")[:7]
            subtitle = content.get("thumbnail_subtitle", "")

            output_path = str(
                self._output_dir / f"{campaign_id}_{p_name}_thumb.jpg"
            )

            try:
                result = gen.generate(
                    platform=platform,
                    title=title,
                    subtitle=subtitle,
                    background_image=bg_image,
                    brand=brand,
                    output_path=output_path,
                )
                thumbnails[p_name] = result
                logger.info(f"썸네일 생성 완료: {p_name}")
            except Exception as e:
                logger.error(f"썸네일 생성 실패 ({p_name}): {e}")
                thumbnails[p_name] = ""

        return thumbnails

    # ──────────────────────────────────────────────
    # Step 5: 영상 렌더링
    # ──────────────────────────────────────────────

    def _render_videos(
        self,
        platforms: list[Platform],
        contents: dict[str, dict],
        images: list[str],
        brand: str,
        campaign_id: str,
    ) -> dict[str, str]:
        """플랫폼별 영상을 렌더링한다."""
        from affiliate_system.video_editor import VideoForge

        videos: dict[str, str] = {}

        if not images:
            logger.warning("이미지 없음 — 영상 렌더링 건너뜀")
            return {p.value: "" for p in platforms}

        for platform in platforms:
            p_name = platform.value
            content = contents.get(p_name, {})
            narrations = content.get("narration", [])
            cta = content.get("cta", "")
            body = content.get("body", "")

            output_path = str(
                self._output_dir / f"{campaign_id}_{p_name}_video.mp4"
            )

            try:
                # 플랫폼 프리셋으로 RenderConfig 생성
                preset = PLATFORM_PRESETS[platform]
                config = RenderConfig.from_platform_preset(preset, brand=brand)
                forge = VideoForge(config=config)

                result = forge.render_for_platform(
                    platform=platform,
                    images=images[:5],  # 최대 5개 이미지
                    narrations=narrations,
                    output_path=output_path,
                    subtitle_text=body[:200],
                    brand=brand,
                    cta_text=cta,
                )
                videos[p_name] = result
                logger.info(f"영상 렌더링 완료: {p_name}")
            except Exception as e:
                logger.error(f"영상 렌더링 실패 ({p_name}): {e}")
                videos[p_name] = ""

        return videos

    # ──────────────────────────────────────────────
    # Step 6: 자동 업로드
    # ──────────────────────────────────────────────

    def _upload_all(self, campaign: Campaign) -> dict:
        """모든 플랫폼에 업로드한다."""
        from affiliate_system.auto_uploader import StealthUploader

        uploader = StealthUploader()
        results = uploader.upload_campaign(campaign)
        return results


# ──────────────────────────────────────────────
# CLI 진입점
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="1주제 → 3플랫폼 콘텐츠 자동 생성 파이프라인",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s "https://www.coupang.com/vp/products/123456"
  %(prog)s "오레노카츠 프리미엄 돈카츠" --brand 오레노카츠
  %(prog)s "다이어트 보충제" --platforms youtube instagram
  %(prog)s "https://www.coupang.com/vp/products/123" --upload
        """,
    )
    parser.add_argument("topic", help="쿠팡 상품 URL 또는 주제 텍스트")
    parser.add_argument("--brand", default="", help="브랜드명 (오레노카츠/무사짬뽕/브릿지원)")
    parser.add_argument("--persona", default="", help="AI 페르소나")
    parser.add_argument(
        "--platforms", nargs="+",
        choices=["youtube", "instagram", "naver_blog"],
        default=None,
        help="대상 플랫폼 (기본: 3개 모두)",
    )
    parser.add_argument("--upload", action="store_true", help="자동 업로드 활성화")

    args = parser.parse_args()

    # 플랫폼 파싱
    platforms = None
    if args.platforms:
        platform_map = {
            "youtube": Platform.YOUTUBE,
            "instagram": Platform.INSTAGRAM,
            "naver_blog": Platform.NAVER_BLOG,
        }
        platforms = [platform_map[p] for p in args.platforms]

    pipeline = ContentPipeline()
    results = pipeline.run(
        topic_or_url=args.topic,
        platforms=platforms,
        brand=args.brand,
        persona=args.persona,
        auto_upload=args.upload,
    )

    # 결과 요약 출력
    print("\n📊 결과 요약:")
    for p_name, data in results["platforms"].items():
        video = "✓" if data.get("video") else "✗"
        thumb = "✓" if data.get("thumbnail") else "✗"
        content = data.get("content", {})
        title_len = len(content.get("title", ""))
        print(f"  {p_name}: 영상{video} 썸네일{thumb} 제목{title_len}자")


if __name__ == "__main__":
    main()
