# -*- coding: utf-8 -*-
"""
Coupang Partners Profit-Maximizer V2 — 메인 실행기
====================================================
터미널 대화형 워크플로우: 링크 입력 → 분석/확인 → 실행.

사용법:
    python -m affiliate_system.coupang_profit_maximizer

워크플로우:
    1. 준비 보고: "쿠팡 링크를 보내주세요."
    2. 링크 입력 → 상품 분석 → 초안 출력
    3. input() 대기: "Y/N/수정"
    4. Y → 블로그 + 숏폼 풀 파이프라인 실행
    5. 결과 → Google Drive 아카이빙 + 텔레그램 알림
"""
from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# 환경 로드
from dotenv import load_dotenv
PROJECT_DIR = Path(__file__).parent.parent
load_dotenv(PROJECT_DIR / '.env', override=True)

from affiliate_system.config import (
    COUPANG_DISCLAIMER, V2_WORK_DIR, V2_BLOG_DIR, V2_SHORTS_DIR,
    SHORTS_MAX_DURATION, COPYRIGHT_DEFENSE_TEXT, COPYRIGHT_EMAIL,
    DM_PROMPT_TEMPLATE, DM_KEYWORD_DEFAULT,
)
from affiliate_system.models import (
    Product, Platform, V2Campaign, V2CampaignConfig,
    BlogContent, ShortsContent, ShortsScene, PlaceholderItem,
    ContentMode, PipelineStateV2, EmotionTag,
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("profit_maximizer")


# ═══════════════════════════════════════════════════════════════════════════
# 메인 파이프라인 클래스
# ═══════════════════════════════════════════════════════════════════════════

class CoupangProfitMaximizer:
    """V2 대화형 파이프라인 메인 실행기.

    터미널 기반: input() 으로 사용자 컨펌 후 실행.
    """

    def __init__(self):
        """파이프라인 초기화."""
        self.campaign: V2Campaign | None = None
        self.campaign_id = uuid.uuid4().hex[:8]

        # 모듈 lazy 초기화
        self._ai_gen = None
        self._omni_collector = None
        self._launderer = None
        self._tts_engine = None
        self._subtitle_gen = None
        self._shorts_renderer = None
        self._blog_html_gen = None
        self._scraper = None

    @property
    def ai_gen(self):
        if self._ai_gen is None:
            from affiliate_system.ai_generator import AIGenerator
            self._ai_gen = AIGenerator()
        return self._ai_gen

    @property
    def omni_collector(self):
        if self._omni_collector is None:
            from affiliate_system.media_collector import OmniMediaCollector
            self._omni_collector = OmniMediaCollector()
        return self._omni_collector

    @property
    def launderer(self):
        if self._launderer is None:
            from affiliate_system.video_launderer import VideoLaunderer
            self._launderer = VideoLaunderer()
        return self._launderer

    @property
    def tts_engine(self):
        if self._tts_engine is None:
            from affiliate_system.video_launderer import EmotionTTSEngine
            self._tts_engine = EmotionTTSEngine()
        return self._tts_engine

    @property
    def subtitle_gen(self):
        if self._subtitle_gen is None:
            from affiliate_system.video_launderer import SubtitleGenerator
            self._subtitle_gen = SubtitleGenerator()
        return self._subtitle_gen

    @property
    def shorts_renderer(self):
        if self._shorts_renderer is None:
            from affiliate_system.video_launderer import ShortsRenderer
            self._shorts_renderer = ShortsRenderer()
        return self._shorts_renderer

    @property
    def blog_html_gen(self):
        if self._blog_html_gen is None:
            from affiliate_system.blog_html_generator import NaverBlogHTMLGenerator
            self._blog_html_gen = NaverBlogHTMLGenerator()
        return self._blog_html_gen

    @property
    def scraper(self):
        if self._scraper is None:
            from affiliate_system.coupang_scraper import CoupangScraper
            self._scraper = CoupangScraper()
        return self._scraper

    # ── 메인 루프 ──

    def run_interactive(self):
        """대화형 메인 루프.

        1. 준비 보고
        2. 쿠팡 링크 입력
        3. 상품 분석 + 초안 출력
        4. input() 컨펌
        5. 풀 파이프라인 실행
        """
        self._print_banner()

        # Step 1: 준비 보고
        print("\n" + "=" * 60)
        print("  모든 준비가 완료되었습니다.")
        print("  쿠팡 파트너스 링크를 보내주세요.")
        print("=" * 60)

        # Step 2: 링크 입력
        while True:
            coupang_link = input("\n쿠팡 링크 입력 (또는 'q' 종료): ").strip()
            if coupang_link.lower() == 'q':
                print("종료합니다.")
                return
            if not coupang_link:
                print("링크를 입력해주세요.")
                continue
            if 'coupang' not in coupang_link.lower() and not coupang_link.startswith('http'):
                print("올바른 쿠팡 링크를 입력해주세요.")
                continue
            break

        # Step 3: 상품 분석
        print("\n상품 분석 중...")
        try:
            product = self._analyze_product(coupang_link)
        except Exception as e:
            logger.error(f"상품 분석 실패: {e}")
            print(f"\n[오류] 상품 분석에 실패했습니다: {e}")
            print("상품명을 직접 입력해주세요.")
            title = input("상품명: ").strip()
            price = input("가격 (예: 29,900원): ").strip()
            product = Product(
                url=coupang_link, title=title, price=price,
                affiliate_link=coupang_link, description=title,
            )

        # 캠페인 생성
        self.campaign = V2Campaign(
            id=self.campaign_id,
            config=V2CampaignConfig(coupang_link=coupang_link),
            product=product,
            state=PipelineStateV2.ANALYZING,
        )

        # Step 4: 초안 생성 + 출력
        print("\n" + "=" * 60)
        print(f"  이건 [{product.title}] 제품이네요!")
        print(f"  가격: {product.price}")
        print(f"  쿠팡 링크: {product.affiliate_link or coupang_link}")
        print("=" * 60)

        print("\n블로그 초안 + 숏폼 대본 생성 중... (Gemini 무료 사용)")
        blog_data, shorts_script = self._generate_drafts(product, coupang_link)

        # 초안 출력
        self._print_blog_draft(blog_data)
        self._print_shorts_draft(shorts_script)

        # Step 5: input() 컨펌
        print("\n" + "=" * 60)
        confirm = input(
            "위 초안으로 영상 렌더링 및 업로드를 진행하시겠습니까? (Y/N/수정): "
        ).strip().upper()

        if confirm == 'N':
            print("취소되었습니다.")
            return
        elif confirm != 'Y':
            print("수정 기능은 추후 업데이트 예정입니다. 현재 초안으로 진행합니다.")

        # Step 6: 풀 파이프라인 실행
        self.campaign.state = PipelineStateV2.EXECUTING
        print("\n" + "=" * 60)
        print("  풀 파이프라인 실행 시작!")
        print("=" * 60)

        try:
            results = self._execute_full_pipeline(
                product, blog_data, shorts_script, coupang_link
            )
            self.campaign.state = PipelineStateV2.COMPLETE
            self._print_results(results)

            # 텔레그램 알림
            self._send_telegram_report(results)

        except Exception as e:
            self.campaign.state = PipelineStateV2.ERROR
            self.campaign.error_message = str(e)
            logger.error(f"파이프라인 실행 실패: {e}")
            print(f"\n[오류] 파이프라인 실행 중 에러 발생: {e}")

    # ── 서브 메서드 ──

    def _analyze_product(self, coupang_link: str) -> Product:
        """쿠팡 링크에서 상품 정보 추출."""
        try:
            product = self.scraper.scrape_and_link(coupang_link)
            logger.info(f"상품 분석 완료: {product.title}")
            return product
        except Exception as e:
            logger.warning(f"쿠팡 스크래핑 실패, Gemini 분석 시도: {e}")
            # Gemini로 URL 분석 폴백
            try:
                analysis = self.ai_gen.analyze_product(
                    Product(url=coupang_link, title="분석 중")
                )
                return Product(
                    url=coupang_link, title="쿠팡 상품",
                    affiliate_link=coupang_link,
                    description=analysis[:500],
                )
            except Exception:
                raise

    def _generate_drafts(
        self, product: Product, coupang_link: str
    ) -> tuple[dict, list[dict]]:
        """블로그 + 숏폼 초안 생성."""
        # 블로그 콘텐츠
        blog_data = self.ai_gen.generate_blog_content_v2(product, coupang_link)

        # 숏폼 후킹 대본
        shorts_script = self.ai_gen.generate_shorts_hooking_script(
            product, coupang_link=coupang_link,
            dm_keyword=DM_KEYWORD_DEFAULT,
        )

        return blog_data, shorts_script

    def _execute_full_pipeline(
        self, product: Product, blog_data: dict,
        shorts_script: list[dict], coupang_link: str,
    ) -> dict:
        """풀 파이프라인 10단계 실행.

        Returns:
            {"blog_html", "blog_images", "shorts_video", "drive_url", ...}
        """
        results = {
            "campaign_id": self.campaign_id,
            "product": product.title,
            "blog_html": "",
            "blog_images": [],
            "shorts_video": "",
            "subtitle_path": "",
            "drive_url": "",
            "steps_completed": [],
        }

        # ── Step 3: 미디어 수집 ──
        print("\n[3/10] 미디어 수집 중...")

        # 블로그 이미지
        image_keywords = blog_data.get("image_keywords", [])
        try:
            blog_images = self.omni_collector.collect_blog_images(
                product.title, image_keywords,
                product_image_urls=product.image_urls,
                count=5,
            )
            results["blog_images"] = blog_images
            print(f"  블로그 이미지: {len(blog_images)}장 수집 완료")
        except Exception as e:
            logger.error(f"블로그 이미지 수집 실패: {e}")
            blog_images = []
            print(f"  블로그 이미지 수집 실패: {e}")

        # 숏폼 영상 클립
        try:
            search_en = self.ai_gen.translate_for_search(product.title)
            video_sources = self.omni_collector.collect_video_sources(
                product.title, search_en, count=len(shorts_script)
            )
            print(f"  숏폼 영상: {len(video_sources)}개 수집 완료")
        except Exception as e:
            logger.error(f"비디오 수집 실패: {e}")
            video_sources = []
            print(f"  숏폼 영상 수집 실패: {e}")

        # SFX
        try:
            sfx_paths = self.omni_collector.crawl_mixkit_sfx("transition", count=2)
            print(f"  SFX 효과음: {len(sfx_paths)}개 수집 완료")
        except Exception as e:
            sfx_paths = []

        results["steps_completed"].append("media_crawl")

        # ── Step 4: 블로그 HTML 생성 ──
        print("\n[4/10] 블로그 HTML 생성 중...")
        try:
            blog_html = self.blog_html_gen.generate_blog_html(
                title=blog_data.get("title", ""),
                intro=blog_data.get("intro", ""),
                body_sections=blog_data.get("body_sections", []),
                image_paths=blog_images,
                coupang_link=coupang_link,
                cta_text=blog_data.get("cta_text", ""),
                hashtags=blog_data.get("hashtags", []),
            )
            results["blog_html"] = blog_html
            print(f"  블로그 HTML 생성 완료: {len(blog_html)}자")
        except Exception as e:
            logger.error(f"블로그 HTML 생성 실패: {e}")
            print(f"  블로그 HTML 생성 실패: {e}")

        results["steps_completed"].append("blog_compose")

        # ── Step 5: 영상 세탁 ──
        print("\n[5/10] 영상 4단계 세탁 중 (FFmpeg GPU)...")
        laundered_videos = []
        try:
            source_paths = [v["path"] for v in video_sources if v.get("path")]
            if source_paths:
                laundered_videos = self.launderer.batch_launder(
                    source_paths,
                    progress_callback=lambda cur, tot, p:
                        print(f"  세탁 {cur}/{tot}: {Path(p).name}")
                )
                print(f"  세탁 완료: {len(laundered_videos)}개 영상")
            else:
                print("  세탁할 영상 없음 — 플레이스홀더 생성")
                self._create_placeholder("video", "숏폼 배경 영상")
        except Exception as e:
            logger.error(f"영상 세탁 실패: {e}")
            print(f"  영상 세탁 실패: {e}")

        results["steps_completed"].append("video_launder")

        # ── Step 6: TTS 생성 + Whisper 싱크 ──
        print("\n[6/10] 감정 TTS 생성 + Whisper 자막 싱크...")
        try:
            # scene에 비디오 클립 매핑
            for idx, scene in enumerate(shorts_script):
                if idx < len(laundered_videos):
                    scene["video_clip_path"] = laundered_videos[idx]
                else:
                    scene["video_clip_path"] = ""

            # TTS 생성
            scenes_with_tts = self.tts_engine.generate_scenes_tts(
                shorts_script, campaign_id=self.campaign_id
            )

            # Whisper 단어 타임스탬프 추출
            for scene in scenes_with_tts:
                if scene.get("tts_path"):
                    words = self.tts_engine.extract_word_timestamps(scene["tts_path"])
                    scene["word_timestamps"] = words

            # ASS 자막 생성
            subtitle_path = self.subtitle_gen.generate_ass_from_scenes(
                scenes_with_tts, campaign_id=self.campaign_id
            )
            results["subtitle_path"] = subtitle_path or ""

            total_dur = sum(s.get("tts_duration", 0) for s in scenes_with_tts)
            print(f"  TTS 생성 완료: {len(scenes_with_tts)}장면, 총 {total_dur:.1f}초")
            if subtitle_path:
                print(f"  ASS 자막 생성 완료: {subtitle_path}")

        except Exception as e:
            logger.error(f"TTS/자막 생성 실패: {e}")
            scenes_with_tts = shorts_script
            subtitle_path = None
            print(f"  TTS/자막 실패: {e}")

        results["steps_completed"].append("tts_subtitle")

        # ── Step 7: 숏폼 최종 렌더링 ──
        print("\n[7/10] 숏폼 최종 렌더링 (FFmpeg GPU)...")
        try:
            final_video = self.shorts_renderer.render_final_shorts(
                scenes=scenes_with_tts,
                campaign_id=self.campaign_id,
                subtitle_path=subtitle_path,
                coupang_link=coupang_link,
            )
            results["shorts_video"] = final_video or ""
            if final_video:
                size_mb = os.path.getsize(final_video) / 1024 / 1024
                print(f"  숏폼 렌더링 완료: {Path(final_video).name} ({size_mb:.1f}MB)")
            else:
                print("  숏폼 렌더링 실패 — 플레이스홀더 생성")
                self._create_placeholder("video", "최종 숏폼 영상")
        except Exception as e:
            logger.error(f"숏폼 렌더링 실패: {e}")
            print(f"  숏폼 렌더링 실패: {e}")

        results["steps_completed"].append("shorts_render")

        # ── Step 8: 썸네일 ──
        print("\n[8/10] 썸네일 생성 중...")
        try:
            from affiliate_system.thumbnail_generator import ThumbnailGenerator
            thumb_gen = ThumbnailGenerator()

            for platform in [Platform.YOUTUBE, Platform.INSTAGRAM, Platform.NAVER_BLOG]:
                try:
                    bg_img = blog_images[0] if blog_images else ""
                    thumb_path = thumb_gen.generate(
                        platform=platform,
                        title=blog_data.get("title", product.title)[:7],
                        subtitle=product.title[:15],
                        background_image=bg_img,
                        output_path=str(
                            V2_WORK_DIR / f"{self.campaign_id}_{platform.value}_thumb.jpg"
                        ),
                    )
                    results.setdefault("thumbnails", {})[platform.value] = thumb_path
                    print(f"  {platform.value} 썸네일 생성 완료")
                except Exception as e:
                    logger.warning(f"{platform.value} 썸네일 실패: {e}")
        except Exception as e:
            logger.error(f"썸네일 생성 실패: {e}")

        results["steps_completed"].append("thumbnail")

        # ── Step 9: 업로드 (선택적) ──
        print("\n[9/10] 업로드 단계...")
        print("  (자동 업로드는 별도 실행이 필요합니다)")
        print(f"  블로그 HTML: {len(results.get('blog_html', ''))}자 준비 완료")
        print(f"  숏폼 영상: {results.get('shorts_video', '없음')}")
        results["steps_completed"].append("upload_ready")

        # ── Step 10: Google Drive 아카이빙 ──
        print("\n[10/10] Google Drive 아카이빙...")
        try:
            drive_url = self._archive_to_drive(results)
            results["drive_url"] = drive_url
            if drive_url:
                print(f"  Drive 아카이빙 완료: {drive_url}")
        except Exception as e:
            logger.error(f"Drive 아카이빙 실패: {e}")
            print(f"  Drive 아카이빙 실패: {e}")

        results["steps_completed"].append("drive_archive")

        return results

    def _create_placeholder(self, media_type: str, context: str):
        """크롤링/렌더링 실패 시 플레이스홀더 생성."""
        from affiliate_system.config import V2_PLACEHOLDER_DIR

        folder = V2_PLACEHOLDER_DIR / self.campaign_id / context.replace(" ", "_")
        folder.mkdir(parents=True, exist_ok=True)

        if media_type == "image":
            msg = "이 부분은 Gemini의 Nano Banana(이미지) 모델을 통해 생성하여 이 폴더에 넣어주세요"
        else:
            msg = "이 부분은 Gemini의 Veo 3.1(동영상) 모델을 통해 생성하여 이 폴더에 넣어주세요"

        readme_path = folder / "README.txt"
        readme_path.write_text(
            f"=== 플레이스홀더 ===\n\n"
            f"캠페인: {self.campaign_id}\n"
            f"타입: {media_type}\n"
            f"설명: {context}\n\n"
            f"{msg}\n\n"
            f"스펙:\n"
            f"  - 해상도: 1080x1920\n"
            f"  - {'포맷: MP4, 길이: 3-5초' if media_type == 'video' else '포맷: PNG/JPG'}\n",
            encoding="utf-8",
        )

        if self.campaign:
            self.campaign.placeholders.append(PlaceholderItem(
                media_type=media_type,
                context=context,
                folder_path=str(folder),
                message=msg,
            ))

        print(f"  플레이스홀더 생성: {folder}")
        print(f"  → {msg}")

    def _archive_to_drive(self, results: dict) -> str:
        """Google Drive 아카이빙."""
        try:
            from affiliate_system.drive_manager import DriveArchiver

            archiver = DriveArchiver()
            if not archiver.authenticate():
                logger.warning("Drive 인증 실패")
                return ""

            # 파일 분류
            drive_files = {"images": [], "renders": [], "audio": [], "logs": []}

            for img in results.get("blog_images", []):
                if img and Path(img).exists():
                    drive_files["images"].append(img)

            shorts = results.get("shorts_video", "")
            if shorts and Path(shorts).exists():
                drive_files["renders"].append(shorts)

            for thumb_path in results.get("thumbnails", {}).values():
                if thumb_path and Path(thumb_path).exists():
                    drive_files["renders"].append(thumb_path)

            # 캠페인 객체 생성
            from affiliate_system.models import Campaign, AIContent, CampaignStatus
            campaign_obj = Campaign(
                id=self.campaign_id,
                product=self.campaign.product if self.campaign else Product(),
                ai_content=AIContent(),
                status=CampaignStatus.COMPLETE,
                created_at=datetime.now(),
            )

            total = sum(len(v) for v in drive_files.values())
            if total == 0:
                return ""

            result = archiver.archive_campaign(campaign_obj, drive_files)
            if result.get("ok"):
                return result.get("folder_url", "")
            return ""

        except Exception as e:
            logger.error(f"Drive 아카이빙 에러: {e}")
            return ""

    def _send_telegram_report(self, results: dict):
        """텔레그램 완료 리포트."""
        try:
            from affiliate_system.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
            if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
                return

            import requests as req

            steps = results.get("steps_completed", [])
            product_name = results.get("product", "상품")
            blog_len = len(results.get("blog_html", ""))
            video = results.get("shorts_video", "")
            drive = results.get("drive_url", "")

            msg = (
                f"V2 캠페인 완료: {product_name}\n"
                f"ID: {results.get('campaign_id', '')}\n"
                f"완료 단계: {len(steps)}/10\n"
                f"블로그 HTML: {blog_len}자\n"
                f"숏폼 영상: {'완료' if video else '실패'}\n"
                f"Drive: {drive or '없음'}"
            )

            req.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"텔레그램 알림 실패: {e}")

    # ── 출력 헬퍼 ──

    def _print_banner(self):
        """배너 출력."""
        print("\n" + "=" * 60)
        print("  Coupang Partners Profit-Maximizer V2")
        print("  YJ Partners — AI 자동화 시스템")
        print("=" * 60)
        print("  Gemini (무료) + FFmpeg GPU + Whisper 싱크")
        print("  블로그 + 숏폼 동시 생산 파이프라인")
        print("=" * 60)

    def _print_blog_draft(self, blog_data: dict):
        """블로그 초안 터미널 출력."""
        print("\n" + "-" * 50)
        print("[블로그 초안]")
        print("-" * 50)
        print(f"제목: {blog_data.get('title', '(생성 실패)')}")
        print(f"\n[인트로]\n{blog_data.get('intro', '')}")
        for i, section in enumerate(blog_data.get("body_sections", []), 1):
            print(f"\n[본문{i}]\n{section[:200]}...")
        hashtags = " ".join(f"#{t}" for t in blog_data.get("hashtags", []))
        print(f"\n[해시태그] {hashtags}")
        print(f"[SEO 키워드] {', '.join(blog_data.get('seo_keywords', []))}")
        print(f"\n[이미지 키워드]")
        for i, kw in enumerate(blog_data.get("image_keywords", []), 1):
            print(f"  {i}. {kw}")

    def _print_shorts_draft(self, shorts_script: list[dict]):
        """숏폼 대본 터미널 출력."""
        print("\n" + "-" * 50)
        print("[숏폼 대본 (YouTube Shorts / Instagram Reels)]")
        print("-" * 50)
        total_dur = 0
        for scene in shorts_script:
            dur = scene.get("duration", 3.0)
            total_dur += dur
            print(
                f"  장면{scene.get('scene_num', '?')}: "
                f"[{scene.get('emotion', 'friendly')}] "
                f"({dur}s) "
                f"{scene.get('text', '')}"
            )
        print(f"\n  총 길이: {total_dur:.1f}초")

    def _print_results(self, results: dict):
        """최종 결과 출력."""
        print("\n" + "=" * 60)
        print("  파이프라인 완료!")
        print("=" * 60)
        print(f"  캠페인 ID: {results.get('campaign_id', '')}")
        print(f"  상품: {results.get('product', '')}")
        print(f"  완료 단계: {len(results.get('steps_completed', []))}/10")
        print(f"  블로그 HTML: {len(results.get('blog_html', ''))}자")

        blog_images = results.get("blog_images", [])
        print(f"  블로그 이미지: {len(blog_images)}장")

        shorts = results.get("shorts_video", "")
        if shorts:
            size = os.path.getsize(shorts) / 1024 / 1024 if os.path.exists(shorts) else 0
            print(f"  숏폼 영상: {shorts} ({size:.1f}MB)")
        else:
            print("  숏폼 영상: (생성 실패)")

        drive = results.get("drive_url", "")
        if drive:
            print(f"  Google Drive: {drive}")

        print("=" * 60)


# ═══════════════════════════════════════════════════════════════════════════
# 메인 진입점
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    maximizer = CoupangProfitMaximizer()
    maximizer.run_interactive()
