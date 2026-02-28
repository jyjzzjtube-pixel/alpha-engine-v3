# -*- coding: utf-8 -*-
"""
알고리즘 맞춤형 듀얼 배포 시스템 (Dual Deployer)
=================================================
쿠팡파트너스 → 영상(Shorts) + 이미지(블로그) 분리 수집
→ 안티어뷰즈 데이터 세탁 (EXIF 제거 + 1-2% 리사이즈)
→ AI 플랫폼별 텍스트 생성
→ Playwright 3플랫폼 업로드 (네이버 블로그, YouTube Shorts, Instagram Reels)
→ page.pause()로 수동 확인 후 발행

Usage:
    python -m affiliate_system.dual_deployer "https://www.coupang.com/vp/products/123"
    python -m affiliate_system.dual_deployer "베베숲 물티슈" --skip-upload
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import random
import struct
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env", override=True)

from affiliate_system.config import (
    RENDER_OUTPUT_DIR, WORK_DIR, NAVER_BLOG_ID,
    BLOG_CHAR_MIN, BLOG_CHAR_MAX,
    BLOG_IMAGE_RESIZE_WIDTH,
    COUPANG_DISCLAIMER,
)
from affiliate_system.models import (
    Product, AIContent, Campaign, Platform,
    RenderConfig, PLATFORM_PRESETS,
    CampaignStatus,
)
from affiliate_system.utils import setup_logger, ensure_dir, send_telegram

__all__ = ["DualDeployer", "ImageLaunderer", "VideoExtractor", "AliScraper"]

log = setup_logger("dual_deployer", "dual_deployer.log")


# ═══════════════════════════════════════════════════════════════════════════
# 1. 이미지 세탁기 (EXIF 제거 + 1-2% 리사이즈 + 해시 변경)
# ═══════════════════════════════════════════════════════════════════════════

class ImageLaunderer:
    """안티어뷰즈 이미지 세탁 - EXIF 스트리핑 + 미세 리사이즈.

    구글/네이버/인스타 중복 감지 알고리즘 우회:
      1. EXIF 메타데이터 완전 제거 (GPS, 카메라 정보 등)
      2. 1-2% 랜덤 리사이즈 (pHash 변경)
      3. 미세 JPEG 품질 변동 (파일 해시 변경)
      4. 선택적 미세 색상 조정
    """

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir) if output_dir else (
            WORK_DIR / "laundered_images"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        log.info("ImageLaunderer 초기화 - 출력: %s", self.output_dir)

    def strip_exif(self, image_path: str) -> str:
        """EXIF 메타데이터를 완전히 제거한 새 이미지를 반환한다.

        Args:
            image_path: 원본 이미지 경로

        Returns:
            EXIF 제거된 새 이미지 경로
        """
        from PIL import Image

        img = Image.open(image_path)

        # RGB로 변환 (RGBA → RGB, P → RGB 등)
        if img.mode in ("RGBA", "P", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 새 이미지 (EXIF 없이) 저장
        clean = Image.new("RGB", img.size)
        clean.putdata(list(img.getdata()))

        stem = Path(image_path).stem
        out_path = self.output_dir / f"{stem}_clean.jpg"
        clean.save(str(out_path), "JPEG", quality=95)

        log.info("EXIF 제거: %s -> %s", Path(image_path).name, out_path.name)
        return str(out_path)

    def micro_resize(self, image_path: str, pct_range: tuple = (1.0, 2.0)) -> str:
        """1-2% 미세 리사이즈로 pHash를 변경한다.

        Args:
            image_path: 입력 이미지 경로
            pct_range: 리사이즈 비율 범위 (%, 기본 1~2%)

        Returns:
            리사이즈된 새 이미지 경로
        """
        from PIL import Image

        img = Image.open(image_path)
        w, h = img.size

        # 랜덤 1-2% 확대 또는 축소
        direction = random.choice([-1, 1])
        pct = random.uniform(pct_range[0], pct_range[1]) / 100.0
        factor = 1.0 + (direction * pct)

        new_w = int(w * factor)
        new_h = int(h * factor)

        # Lanczos 리샘플링 (최고 품질)
        img_resized = img.resize((new_w, new_h), Image.LANCZOS)

        stem = Path(image_path).stem
        suffix = Path(image_path).suffix or ".jpg"
        out_path = self.output_dir / f"{stem}_resized{suffix}"

        # JPEG 품질도 미세 변동 (93-97)
        quality = random.randint(93, 97)
        if suffix.lower() in (".jpg", ".jpeg"):
            img_resized.save(str(out_path), "JPEG", quality=quality)
        else:
            img_resized.save(str(out_path), "PNG")

        log.info("미세 리사이즈: %dx%d -> %dx%d (%.1f%%)",
                 w, h, new_w, new_h, (factor - 1) * 100)
        return str(out_path)

    def micro_color_shift(self, image_path: str) -> str:
        """미세 색상 조정 (밝기/채도 +-1-3%).

        이미지 해시 변경을 더 강화하기 위한 선택적 단계.
        """
        from PIL import Image, ImageEnhance

        img = Image.open(image_path)

        # 밝기 +-1-3%
        brightness = 1.0 + random.uniform(-0.03, 0.03)
        img = ImageEnhance.Brightness(img).enhance(brightness)

        # 채도 +-1-3%
        saturation = 1.0 + random.uniform(-0.03, 0.03)
        img = ImageEnhance.Color(img).enhance(saturation)

        # 대비 +-1-2%
        contrast = 1.0 + random.uniform(-0.02, 0.02)
        img = ImageEnhance.Contrast(img).enhance(contrast)

        stem = Path(image_path).stem
        out_path = self.output_dir / f"{stem}_shifted.jpg"
        img.save(str(out_path), "JPEG", quality=random.randint(93, 97))

        log.info("색상 미세 조정: brightness=%.3f, saturation=%.3f", brightness, saturation)
        return str(out_path)

    def launder_image(self, image_path: str, full_wash: bool = True) -> str:
        """이미지 풀 세탁: EXIF 제거 → 미세 리사이즈 → 색상 조정.

        Args:
            image_path: 원본 이미지 경로
            full_wash: True면 색상 조정까지, False면 EXIF+리사이즈만

        Returns:
            세탁 완료된 이미지 경로
        """
        if not os.path.exists(image_path):
            log.warning("이미지 파일 없음: %s", image_path)
            return image_path

        # Step 1: EXIF 제거
        clean_path = self.strip_exif(image_path)

        # Step 2: 1-2% 미세 리사이즈
        resized_path = self.micro_resize(clean_path)

        # Step 3: 색상 미세 조정 (선택)
        if full_wash:
            final_path = self.micro_color_shift(resized_path)
        else:
            final_path = resized_path

        # 중간 파일 정리
        for tmp in [clean_path, resized_path]:
            if tmp != final_path and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

        log.info("이미지 세탁 완료: %s -> %s",
                 Path(image_path).name, Path(final_path).name)
        return final_path

    def launder_batch(self, image_paths: list[str], full_wash: bool = True) -> list[str]:
        """여러 이미지를 일괄 세탁한다.

        Args:
            image_paths: 원본 이미지 경로 리스트
            full_wash: 풀 세탁 여부

        Returns:
            세탁된 이미지 경로 리스트
        """
        results = []
        for i, path in enumerate(image_paths):
            log.info("배치 세탁 [%d/%d]: %s", i + 1, len(image_paths), Path(path).name)
            laundered = self.launder_image(path, full_wash=full_wash)
            results.append(laundered)
        log.info("배치 세탁 완료: %d개", len(results))
        return results


# ═══════════════════════════════════════════════════════════════════════════
# 2. 도우인/틱톡 영상 추출기 (yt-dlp 기반)
# ═══════════════════════════════════════════════════════════════════════════

class VideoExtractor:
    """도우인(Douyin), 틱톡(TikTok), YouTube 등 영상 추출기.

    yt-dlp의 1864개 추출기를 활용하여 거의 모든 플랫폼에서 영상을 다운로드한다.
    워터마크 제거, 최고 화질 선택, 메타데이터 제거를 자동 수행.
    """

    SUPPORTED_PLATFORMS = {
        "douyin": ["douyin.com", "v.douyin.com"],
        "tiktok": ["tiktok.com", "vm.tiktok.com"],
        "youtube": ["youtube.com", "youtu.be"],
        "instagram": ["instagram.com"],
        "facebook": ["facebook.com", "fb.watch"],
        "twitter": ["twitter.com", "x.com"],
        "bilibili": ["bilibili.com"],
    }

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir) if output_dir else (
            WORK_DIR / "extracted_videos"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        log.info("VideoExtractor 초기화 - 출력: %s", self.output_dir)

    def detect_platform(self, url: str) -> str:
        """URL에서 플랫폼을 감지한다."""
        url_lower = url.lower()
        for platform, domains in self.SUPPORTED_PLATFORMS.items():
            for domain in domains:
                if domain in url_lower:
                    return platform
        return "unknown"

    def extract_video(
        self,
        url: str,
        filename: str = None,
        remove_watermark: bool = True,
        max_resolution: int = 1920,
    ) -> Optional[str]:
        """URL에서 영상을 추출한다.

        Args:
            url: 영상 URL (도우인, 틱톡, 유튜브 등)
            filename: 저장 파일명 (없으면 자동)
            remove_watermark: 워터마크 제거 시도 (도우인/틱톡)
            max_resolution: 최대 해상도

        Returns:
            다운로드된 영상 파일 경로, 실패 시 None
        """
        try:
            import yt_dlp
        except ImportError:
            log.error("yt-dlp 미설치! pip install yt-dlp")
            return None

        platform = self.detect_platform(url)
        log.info("영상 추출 시작: %s (%s)", url[:60], platform)

        if not filename:
            ts = int(time.time())
            filename = f"{platform}_{ts}"

        output_template = str(self.output_dir / f"{filename}.%(ext)s")

        # yt-dlp 옵션 구성
        ydl_opts = {
            "outtmpl": output_template,
            "format": f"best[height<={max_resolution}]/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            # 메타데이터 제거
            "postprocessors": [
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": False,
                },
            ],
            # 봇 감지 우회
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Referer": url,
            },
        }

        # 도우인/틱톡 워터마크 없는 버전 시도
        if platform in ("douyin", "tiktok") and remove_watermark:
            ydl_opts["format"] = "best[format_note!=watermarked]/best"

        # 쿠키 파일 있으면 사용 (로그인 필요한 콘텐츠)
        cookies_path = ROOT / "cookies.txt"
        if cookies_path.exists():
            ydl_opts["cookiefile"] = str(cookies_path)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    log.error("영상 정보 추출 실패: %s", url)
                    return None

                # 다운로드된 파일 찾기
                downloaded = ydl.prepare_filename(info)
                # 확장자가 바뀔 수 있으므로 mp4로 확인
                mp4_path = Path(downloaded).with_suffix(".mp4")
                if mp4_path.exists():
                    downloaded = str(mp4_path)
                elif os.path.exists(downloaded):
                    pass
                else:
                    # glob으로 찾기
                    import glob
                    found = glob.glob(str(self.output_dir / f"{filename}.*"))
                    if found:
                        downloaded = found[0]
                    else:
                        log.error("다운로드 파일 찾기 실패")
                        return None

                file_size = os.path.getsize(downloaded) / (1024 * 1024)
                duration = info.get("duration", 0)
                title = info.get("title", "")[:50]
                log.info("영상 추출 완료: %s (%.1fMB, %ds) - %s",
                         Path(downloaded).name, file_size, duration, title)
                return downloaded

        except Exception as e:
            log.error("영상 추출 실패 (%s): %s", platform, e)
            return None

    def extract_douyin(self, url: str, filename: str = None) -> Optional[str]:
        """도우인 영상 전용 추출 (워터마크 제거 최적화)."""
        return self.extract_video(url, filename=filename, remove_watermark=True)

    def extract_tiktok(self, url: str, filename: str = None) -> Optional[str]:
        """틱톡 영상 전용 추출."""
        return self.extract_video(url, filename=filename, remove_watermark=True)

    def extract_batch(self, urls: list[str]) -> list[str]:
        """여러 URL에서 영상을 일괄 추출한다."""
        results = []
        for i, url in enumerate(urls):
            log.info("배치 추출 [%d/%d]: %s", i + 1, len(urls), url[:60])
            path = self.extract_video(url)
            if path:
                results.append(path)
            time.sleep(random.uniform(2, 5))  # 봇 감지 회피 딜레이
        log.info("배치 추출 완료: %d/%d 성공", len(results), len(urls))
        return results

    def get_video_info(self, url: str) -> Optional[dict]:
        """영상 메타정보만 추출한다 (다운로드 없이).

        Returns:
            {"title", "duration", "view_count", "thumbnail", "uploader", "platform"}
        """
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    return {
                        "title": info.get("title", ""),
                        "duration": info.get("duration", 0),
                        "view_count": info.get("view_count", 0),
                        "thumbnail": info.get("thumbnail", ""),
                        "uploader": info.get("uploader", ""),
                        "platform": self.detect_platform(url),
                        "url": url,
                    }
        except Exception as e:
            log.warning("영상 정보 추출 실패: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 3. 알리익스프레스/1688 소싱 (기본 스크래퍼)
# ═══════════════════════════════════════════════════════════════════════════

class AliScraper:
    """알리익스프레스/1688 상품 스크래퍼.

    Playwright로 상품 페이지를 렌더링하고 정보를 추출한다.
    """

    SUPPORTED = {
        "aliexpress": ["aliexpress.com", "ko.aliexpress.com"],
        "1688": ["1688.com"],
    }

    def detect_platform(self, url: str) -> str:
        """URL 플랫폼 감지."""
        url_lower = url.lower()
        for platform, domains in self.SUPPORTED.items():
            for domain in domains:
                if domain in url_lower:
                    return platform
        return "unknown"

    @staticmethod
    def is_ali_url(url: str) -> bool:
        """알리/1688 URL인지 확인."""
        url_lower = url.lower()
        return any(d in url_lower for d in [
            "aliexpress.com", "1688.com"
        ])

    def scrape_product(self, url: str) -> Product:
        """알리/1688 상품 정보를 스크래핑한다.

        Args:
            url: 상품 URL

        Returns:
            Product 객체
        """
        platform = self.detect_platform(url)
        log.info("알리/1688 스크래핑: %s (%s)", url[:60], platform)

        # 1차: requests + BeautifulSoup (빠름)
        product = self._scrape_requests(url)
        if product and product.title:
            return product

        # 2차: Playwright (JS 렌더링 필요시)
        product = self._scrape_playwright(url)
        if product and product.title:
            return product

        # 폴백
        return Product(
            url=url,
            title=url.split("/")[-1][:50],
            description="",
            scraped_at=datetime.now(),
        )

    def _scrape_requests(self, url: str) -> Optional[Product]:
        """requests로 기본 스크래핑."""
        try:
            import requests
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            }
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            title = ""
            price = ""
            image_urls = []
            description = ""

            # OG 태그
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content", "")

            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                description = og_desc.get("content", "")

            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_urls.append(og_image["content"])

            # 가격 추출 시도
            price_el = soup.select_one(
                "[class*='price'], [class*='Price'], "
                "[data-spm*='price']"
            )
            if price_el:
                price = price_el.get_text(strip=True)

            if not title:
                t = soup.find("title")
                title = t.get_text(strip=True) if t else ""

            # 추가 이미지
            for img in soup.select("img[src*='alicdn'], img[src*='1688']"):
                src = img.get("src", "")
                if src and src not in image_urls and "http" in src:
                    image_urls.append(src)
                if len(image_urls) >= 8:
                    break

            if title:
                return Product(
                    url=url, title=title, price=price,
                    image_urls=image_urls, description=description,
                    scraped_at=datetime.now(),
                )
        except Exception as e:
            log.warning("알리 requests 스크래핑 실패: %s", e)
        return None

    def _scrape_playwright(self, url: str) -> Optional[Product]:
        """Playwright로 JS 렌더링 후 스크래핑."""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                    ),
                    locale="ko-KR",
                )
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)

                title = page.title() or ""
                # OG 태그 추출
                og_title = page.locator("meta[property='og:title']").first
                try:
                    title = og_title.get_attribute("content") or title
                except Exception:
                    pass

                # 이미지 추출
                image_urls = []
                images = page.locator("img[src*='alicdn'], img[src*='1688']")
                for i in range(min(images.count(), 8)):
                    src = images.nth(i).get_attribute("src")
                    if src:
                        if src.startswith("//"):
                            src = "https:" + src
                        image_urls.append(src)

                # 가격
                price = ""
                try:
                    price_el = page.locator("[class*='price']").first
                    price = price_el.text_content() or ""
                except Exception:
                    pass

                browser.close()

                if title:
                    return Product(
                        url=url, title=title, price=price,
                        image_urls=image_urls,
                        scraped_at=datetime.now(),
                    )
        except Exception as e:
            log.warning("알리 Playwright 스크래핑 실패: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 4. Playwright 기반 3플랫폼 업로더
# ═══════════════════════════════════════════════════════════════════════════

class PlaywrightUploader:
    """Playwright + Chrome user_data_dir 기반 3플랫폼 업로더.

    기존 Chrome 로그인 세션을 재사용하여 봇 감지를 회피한다.
    page.pause()로 발행 직전 수동 확인 가능.
    """

    # Chrome 사용자 데이터 경로 (Windows)
    CHROME_USER_DATA = os.path.expandvars(
        r"%LOCALAPPDATA%\Google\Chrome\User Data"
    )

    def __init__(self, headless: bool = False, manual_review: bool = True):
        """
        Args:
            headless: True면 헤드리스 모드 (디버깅 불가)
            manual_review: True면 발행 전 page.pause()로 수동 확인
        """
        self.headless = headless
        self.manual_review = manual_review
        self._browser = None
        self._context = None
        log.info("PlaywrightUploader 초기화 (headless=%s, manual_review=%s)",
                 headless, manual_review)

    def _ensure_browser(self):
        """Playwright 브라우저를 Chrome user_data_dir로 실행한다."""
        if self._context is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Playwright 미설치! pip install playwright && playwright install chromium")
            raise

        self._pw = sync_playwright().start()

        # Chrome user_data_dir 사용 → 기존 로그인 세션 재활용
        chrome_path = self.CHROME_USER_DATA
        if not os.path.exists(chrome_path):
            log.warning("Chrome user_data 없음: %s - 새 프로필로 시작", chrome_path)
            chrome_path = None

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        try:
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=chrome_path or "",
                headless=self.headless,
                args=launch_args,
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )
            log.info("Playwright 브라우저 시작 (Chrome user_data_dir)")
        except Exception as e:
            log.error("Playwright 시작 실패: %s", e)
            # 폴백: user_data 없이 시작
            log.info("폴백: 일반 Chromium 브라우저로 시작")
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir="",
                headless=self.headless,
                args=launch_args,
                viewport={"width": 1280, "height": 900},
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )

    def _new_page(self):
        """새 탭을 생성한다."""
        self._ensure_browser()
        return self._context.new_page()

    def close(self):
        """브라우저를 안전하게 종료한다."""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if hasattr(self, "_pw") and self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._context = None
        log.info("Playwright 브라우저 종료")

    # ────────────────────────────────────────────
    # 네이버 블로그 업로드
    # ────────────────────────────────────────────

    def upload_naver_blog(
        self,
        title: str,
        content_html: str,
        images: list[str] = None,
        tags: list[str] = None,
    ) -> dict:
        """네이버 블로그에 글을 작성한다.

        Args:
            title: 블로그 제목
            content_html: 본문 HTML
            images: 이미지 경로 리스트 (본문에 삽입)
            tags: 해시태그 리스트

        Returns:
            {"ok": bool, "post_url": str, "reason": str}
        """
        page = None
        try:
            page = self._new_page()
            blog_id = NAVER_BLOG_ID

            # 네이버 블로그 에디터 열기
            editor_url = f"https://blog.naver.com/{blog_id}/postwrite"
            log.info("네이버 블로그 에디터 접속: %s", editor_url)
            page.goto(editor_url, wait_until="networkidle", timeout=30000)
            time.sleep(3)

            # 로그인 확인
            if "nid.naver.com" in page.url:
                log.warning("네이버 로그인 필요! 수동으로 로그인해주세요.")
                if self.manual_review:
                    print("\n[!] 네이버 로그인이 필요합니다. 브라우저에서 로그인 후 Enter를 누르세요.")
                    page.pause()
                else:
                    return {"ok": False, "reason": "네이버 로그인 필요"}

            # SE 에디터 (iframe 내부)
            time.sleep(2)

            # 제목 입력
            try:
                # Smart Editor ONE (se-component)
                title_el = page.locator(".se-title-text .se-text-paragraph")
                if title_el.count() > 0:
                    title_el.first.click()
                    time.sleep(0.5)
                    page.keyboard.type(title, delay=30)
                    log.info("제목 입력 완료: %s", title[:30])
                else:
                    # 폴백: contenteditable 제목
                    page.locator("[class*='title'] [contenteditable]").first.click()
                    page.keyboard.type(title, delay=30)
            except Exception as e:
                log.warning("제목 입력 실패: %s", e)

            time.sleep(1)

            # 본문 입력 (HTML 붙여넣기)
            try:
                body_el = page.locator(".se-component-content .se-text-paragraph")
                if body_el.count() > 0:
                    body_el.first.click()
                    time.sleep(0.5)
                    # HTML을 텍스트로 변환하여 입력 (에디터 호환)
                    from html import unescape
                    import re
                    plain_text = re.sub(r'<[^>]+>', '\n', content_html)
                    plain_text = unescape(plain_text).strip()
                    # 줄 단위로 입력
                    for line in plain_text.split('\n'):
                        line = line.strip()
                        if line:
                            page.keyboard.type(line, delay=10)
                            page.keyboard.press("Enter")
                    log.info("본문 입력 완료 (%d자)", len(plain_text))
            except Exception as e:
                log.warning("본문 입력 실패: %s", e)

            # 이미지 첨부 (파일 업로드 다이얼로그)
            if images:
                try:
                    # 이미지 버튼 클릭
                    img_btn = page.locator("[class*='image'], [data-name='image']")
                    if img_btn.count() > 0:
                        img_btn.first.click()
                        time.sleep(1)
                        # 파일 업로드
                        file_input = page.locator("input[type='file']")
                        if file_input.count() > 0:
                            file_input.first.set_input_files(images)
                            time.sleep(len(images) * 2)  # 이미지당 2초 대기
                            # 확인 버튼
                            confirm_btn = page.locator("button:has-text('등록'), button:has-text('확인')")
                            if confirm_btn.count() > 0:
                                confirm_btn.first.click()
                            log.info("이미지 %d개 업로드 완료", len(images))
                except Exception as e:
                    log.warning("이미지 업로드 실패: %s", e)

            # 태그 입력
            if tags:
                try:
                    tag_input = page.locator("[class*='tag'] input, [placeholder*='태그']")
                    if tag_input.count() > 0:
                        for tag in tags[:10]:
                            tag_input.first.fill(tag)
                            page.keyboard.press("Enter")
                            time.sleep(0.3)
                        log.info("태그 %d개 입력", len(tags[:10]))
                except Exception as e:
                    log.warning("태그 입력 실패: %s", e)

            # ★ 발행 전 수동 확인
            if self.manual_review:
                print("\n" + "=" * 50)
                print("[네이버 블로그] 발행 전 수동 확인")
                print("브라우저에서 내용을 확인하고 Playwright Inspector에서 Resume을 누르세요.")
                print("=" * 50)
                page.pause()

            # 발행 버튼 클릭
            try:
                publish_btn = page.locator(
                    "button:has-text('발행'), "
                    "button:has-text('등록'), "
                    "[class*='publish'] button"
                )
                if publish_btn.count() > 0:
                    publish_btn.first.click()
                    time.sleep(3)

                    # 공개 설정 → 발행 확인
                    confirm = page.locator("button:has-text('발행'), button:has-text('확인')")
                    if confirm.count() > 0:
                        confirm.first.click()
                        time.sleep(3)

                    log.info("네이버 블로그 발행 완료")
                    return {
                        "ok": True,
                        "post_url": page.url,
                        "reason": "발행 성공",
                    }
            except Exception as e:
                log.error("발행 실패: %s", e)
                return {"ok": False, "reason": str(e)}

            return {"ok": False, "reason": "발행 버튼 찾기 실패"}

        except Exception as e:
            log.error("네이버 블로그 업로드 에러: %s", e)
            return {"ok": False, "reason": str(e)}
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    # ────────────────────────────────────────────
    # YouTube Shorts 업로드
    # ────────────────────────────────────────────

    def upload_youtube_shorts(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str] = None,
    ) -> dict:
        """YouTube Shorts에 영상을 업로드한다.

        Args:
            video_path: 영상 파일 경로
            title: 영상 제목
            description: 설명 (어필리에이트 링크 포함)
            tags: 태그 리스트

        Returns:
            {"ok": bool, "video_url": str, "reason": str}
        """
        page = None
        try:
            page = self._new_page()

            # YouTube Studio 업로드 페이지
            log.info("YouTube Studio 접속")
            page.goto("https://studio.youtube.com", wait_until="networkidle", timeout=30000)
            time.sleep(3)

            # 로그인 확인
            if "accounts.google.com" in page.url:
                log.warning("YouTube 로그인 필요!")
                if self.manual_review:
                    print("\n[!] YouTube 로그인이 필요합니다. 브라우저에서 로그인 후 Resume을 누르세요.")
                    page.pause()
                else:
                    return {"ok": False, "reason": "YouTube 로그인 필요"}

            # 업로드 버튼 클릭 (Create → Upload video)
            try:
                create_btn = page.locator("#create-icon, [id='create-icon']")
                if create_btn.count() > 0:
                    create_btn.first.click()
                    time.sleep(1)

                upload_menu = page.locator(
                    "tp-yt-paper-item:has-text('Upload'), "
                    "tp-yt-paper-item:has-text('동영상 업로드'), "
                    "[id='text-item-0']"
                )
                if upload_menu.count() > 0:
                    upload_menu.first.click()
                    time.sleep(2)
            except Exception as e:
                log.warning("업로드 메뉴 클릭 실패: %s", e)
                # 직접 업로드 URL로 이동
                page.goto("https://studio.youtube.com/channel/UC/videos/upload",
                          wait_until="networkidle", timeout=30000)
                time.sleep(3)

            # 파일 선택 (input[type=file])
            try:
                file_input = page.locator("input[type='file']")
                if file_input.count() > 0:
                    file_input.first.set_input_files(video_path)
                    log.info("영상 파일 업로드 시작: %s", Path(video_path).name)
                    time.sleep(5)  # 업로드 시작 대기
                else:
                    log.error("파일 입력 요소 없음")
                    return {"ok": False, "reason": "파일 입력 요소 없음"}
            except Exception as e:
                log.error("파일 선택 실패: %s", e)
                return {"ok": False, "reason": str(e)}

            # 제목 입력
            time.sleep(3)
            try:
                title_input = page.locator(
                    "#textbox[aria-label*='title'], "
                    "#textbox[aria-label*='제목'], "
                    "[id='textbox']"
                ).first
                title_input.click()
                # 기존 텍스트 전체 선택 후 덮어쓰기
                page.keyboard.press("Control+a")
                page.keyboard.type(title[:100], delay=20)
                log.info("제목 입력: %s", title[:30])
            except Exception as e:
                log.warning("제목 입력 실패: %s", e)

            # 설명 입력
            try:
                desc_inputs = page.locator(
                    "#textbox[aria-label*='description'], "
                    "#textbox[aria-label*='설명']"
                )
                if desc_inputs.count() > 0:
                    desc_inputs.first.click()
                    page.keyboard.type(description[:5000], delay=5)
                    log.info("설명 입력 완료 (%d자)", len(description[:5000]))
            except Exception as e:
                log.warning("설명 입력 실패: %s", e)

            # Shorts 태그 설정 (아동용 아님)
            try:
                not_for_kids = page.locator(
                    "#offRadio, "
                    "[name='NOT_MADE_FOR_KIDS'], "
                    "tp-yt-paper-radio-button:has-text('아니요')"
                )
                if not_for_kids.count() > 0:
                    not_for_kids.first.click()
                    log.info("'아동용 아님' 설정")
            except Exception:
                pass

            # 업로드 완료 대기 (최대 5분)
            log.info("영상 업로드 처리 대기중...")
            for _ in range(60):
                try:
                    progress = page.locator("[class*='progress']")
                    done_text = page.locator(
                        ":has-text('처리 완료'), "
                        ":has-text('Checks complete'), "
                        ":has-text('Upload complete')"
                    )
                    if done_text.count() > 0:
                        log.info("업로드 처리 완료")
                        break
                except Exception:
                    pass
                time.sleep(5)

            # ★ 발행 전 수동 확인
            if self.manual_review:
                print("\n" + "=" * 50)
                print("[YouTube Shorts] 발행 전 수동 확인")
                print("브라우저에서 내용을 확인하고 Playwright Inspector에서 Resume을 누르세요.")
                print("=" * 50)
                page.pause()

            # Next 버튼 눌러서 마지막 단계까지
            for step in range(3):
                try:
                    next_btn = page.locator(
                        "#next-button, "
                        "button:has-text('다음'), "
                        "button:has-text('Next')"
                    )
                    if next_btn.count() > 0:
                        next_btn.first.click()
                        time.sleep(2)
                except Exception:
                    break

            # 공개 설정 → 비공개(기본)
            try:
                # 비공개 또는 일부공개 라디오
                private_radio = page.locator(
                    "#privacy-radios tp-yt-paper-radio-button:first-child, "
                    "[name='PRIVATE']"
                )
                if private_radio.count() > 0:
                    private_radio.first.click()
            except Exception:
                pass

            # 게시 버튼
            try:
                publish_btn = page.locator(
                    "#done-button, "
                    "button:has-text('게시'), "
                    "button:has-text('Publish'), "
                    "button:has-text('완료')"
                )
                if publish_btn.count() > 0:
                    publish_btn.first.click()
                    time.sleep(5)
                    log.info("YouTube 영상 발행 완료")
                    return {
                        "ok": True,
                        "video_url": page.url,
                        "reason": "발행 성공",
                    }
            except Exception as e:
                log.error("YouTube 발행 실패: %s", e)
                return {"ok": False, "reason": str(e)}

            return {"ok": False, "reason": "발행 버튼 찾기 실패"}

        except Exception as e:
            log.error("YouTube 업로드 에러: %s", e)
            return {"ok": False, "reason": str(e)}
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    # ────────────────────────────────────────────
    # Instagram Reels 업로드
    # ────────────────────────────────────────────

    def upload_instagram_reels(
        self,
        video_path: str,
        caption: str,
        cover_image: str = None,
    ) -> dict:
        """Instagram Reels에 영상을 업로드한다.

        Args:
            video_path: 영상 파일 경로
            caption: 캡션 (해시태그 포함)
            cover_image: 커버 이미지 경로 (선택)

        Returns:
            {"ok": bool, "post_url": str, "reason": str}
        """
        page = None
        try:
            page = self._new_page()

            # Instagram 접속
            log.info("Instagram 접속")
            page.goto("https://www.instagram.com/", wait_until="networkidle", timeout=30000)
            time.sleep(3)

            # 로그인 확인
            login_form = page.locator("input[name='username']")
            if login_form.count() > 0:
                log.warning("Instagram 로그인 필요!")
                if self.manual_review:
                    print("\n[!] Instagram 로그인이 필요합니다. 브라우저에서 로그인 후 Resume을 누르세요.")
                    page.pause()
                else:
                    return {"ok": False, "reason": "Instagram 로그인 필요"}

            # 새 게시물 버튼
            time.sleep(2)
            try:
                create_btn = page.locator(
                    "[aria-label='새 게시물'], "
                    "[aria-label='New post'], "
                    "svg[aria-label='새 게시물']"
                ).first
                create_btn.click()
                time.sleep(2)
            except Exception:
                # 사이드바 새 게시물
                try:
                    page.locator("a[href='/create/select/']").click()
                    time.sleep(2)
                except Exception as e:
                    log.error("새 게시물 버튼 클릭 실패: %s", e)
                    return {"ok": False, "reason": "새 게시물 버튼 없음"}

            # 파일 선택
            try:
                file_input = page.locator("input[type='file']")
                if file_input.count() > 0:
                    file_input.first.set_input_files(video_path)
                    log.info("영상 파일 선택: %s", Path(video_path).name)
                    time.sleep(5)
                else:
                    # "컴퓨터에서 선택" 클릭
                    select_btn = page.locator(
                        "button:has-text('컴퓨터에서 선택'), "
                        "button:has-text('Select from computer')"
                    )
                    if select_btn.count() > 0:
                        select_btn.first.click()
                        time.sleep(1)
                        file_input = page.locator("input[type='file']")
                        file_input.first.set_input_files(video_path)
                        time.sleep(5)
            except Exception as e:
                log.error("파일 선택 실패: %s", e)
                return {"ok": False, "reason": str(e)}

            # Reel 모드 선택 (있다면)
            try:
                reel_tab = page.locator(
                    "[role='tab']:has-text('릴스'), "
                    "[role='tab']:has-text('Reel')"
                )
                if reel_tab.count() > 0:
                    reel_tab.first.click()
                    time.sleep(1)
            except Exception:
                pass

            # 다음 버튼 (자르기 → 편집 → 캡션)
            for step in range(3):
                try:
                    next_btn = page.locator(
                        "button:has-text('다음'), "
                        "button:has-text('Next'), "
                        "[aria-label='다음']"
                    )
                    if next_btn.count() > 0:
                        next_btn.first.click()
                        time.sleep(2)
                except Exception:
                    break

            # 캡션 입력
            try:
                caption_input = page.locator(
                    "[aria-label='문구를 입력하세요...'], "
                    "[aria-label='Write a caption...'], "
                    "[contenteditable='true']"
                )
                if caption_input.count() > 0:
                    caption_input.first.click()
                    # 캡션 입력 (2200자 제한)
                    page.keyboard.type(caption[:2200], delay=5)
                    log.info("캡션 입력 완료 (%d자)", len(caption[:2200]))
            except Exception as e:
                log.warning("캡션 입력 실패: %s", e)

            # ★ 발행 전 수동 확인
            if self.manual_review:
                print("\n" + "=" * 50)
                print("[Instagram Reels] 발행 전 수동 확인")
                print("브라우저에서 내용을 확인하고 Playwright Inspector에서 Resume을 누르세요.")
                print("=" * 50)
                page.pause()

            # 공유 버튼
            try:
                share_btn = page.locator(
                    "button:has-text('공유하기'), "
                    "button:has-text('Share'), "
                    "button:has-text('공유')"
                )
                if share_btn.count() > 0:
                    share_btn.first.click()
                    time.sleep(10)  # 업로드 처리 대기
                    log.info("Instagram Reels 발행 완료")
                    return {
                        "ok": True,
                        "post_url": page.url,
                        "reason": "발행 성공",
                    }
            except Exception as e:
                log.error("Instagram 발행 실패: %s", e)
                return {"ok": False, "reason": str(e)}

            return {"ok": False, "reason": "공유 버튼 찾기 실패"}

        except Exception as e:
            log.error("Instagram 업로드 에러: %s", e)
            return {"ok": False, "reason": str(e)}
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════
# 3. 듀얼 배포 오케스트레이터
# ═══════════════════════════════════════════════════════════════════════════

class DualDeployer:
    """쿠팡파트너스 듀얼 배포 시스템 (영상 + 블로그 동시 배포).

    파이프라인:
      1. 쿠팡 상품 소싱 (scrape + affiliate link)
      2. 이미지 수집 (브라우저 캡처 / 스크래핑)
      3. 이미지 세탁 (EXIF 제거 + 1-2% 리사이즈)
      4. AI 텍스트 생성 (네이버 블로그 1500자 / YouTube 3초 훅 / Instagram 3줄 캡션)
      5. 영상 렌더링 (YouTube Shorts + Instagram Reels)
      6. 블로그 HTML 생성
      7. Playwright 3플랫폼 업로드

    Usage:
        deployer = DualDeployer()
        result = deployer.run("https://www.coupang.com/vp/products/123")
    """

    def __init__(
        self,
        manual_review: bool = True,
        skip_upload: bool = False,
        headless: bool = False,
    ):
        """
        Args:
            manual_review: 업로드 전 page.pause() 활성화
            skip_upload: True면 콘텐츠 생성만 (업로드 스킵)
            headless: Playwright 헤드리스 모드
        """
        self.manual_review = manual_review
        self.skip_upload = skip_upload
        self.headless = headless

        # 작업 디렉토리
        self._campaign_dir = None
        self._output_dir = ensure_dir(RENDER_OUTPUT_DIR)
        self._extracted_video = None  # 도우인/틱톡 추출 영상

        log.info("DualDeployer 초기화 (manual_review=%s, skip_upload=%s)",
                 manual_review, skip_upload)

    def run(
        self,
        coupang_url_or_keyword: str,
        platforms: list[str] = None,
        brand: str = "",
        persona: str = "",
        browser_images: list[str] = None,
        local_images: list[str] = None,
        video_urls: list[str] = None,
    ) -> dict:
        """듀얼 배포 풀 파이프라인을 실행한다.

        Args:
            coupang_url_or_keyword: 쿠팡 상품 URL 또는 검색 키워드
            platforms: 배포 플랫폼 ["naver_blog", "youtube", "instagram"] (기본: 전부)
            brand: 브랜드명
            persona: AI 페르소나
            browser_images: Chrome에서 캡처한 이미지 URL 리스트
            local_images: 로컬 이미지 파일 경로 리스트
            video_urls: 도우인/틱톡/유튜브 영상 URL 리스트 (추출용)

        Returns:
            {
                "product": Product,
                "images_raw": [str],
                "images_laundered": [str],
                "ai_contents": {platform: dict},
                "video_paths": {platform: str},
                "blog_html": str,
                "upload_results": {platform: dict},
            }
        """
        platforms = platforms or ["naver_blog", "youtube", "instagram"]
        campaign_id = uuid.uuid4().hex[:8]
        self._campaign_dir = ensure_dir(WORK_DIR / f"dual_{campaign_id}")
        start_time = time.time()

        print("\n" + "=" * 60)
        print("  듀얼 배포 시스템 v1.0 - 쿠팡파트너스")
        print("=" * 60)
        print(f"  캠페인 ID : {campaign_id}")
        print(f"  입력      : {coupang_url_or_keyword[:50]}")
        print(f"  플랫폼    : {', '.join(platforms)}")
        print("=" * 60 + "\n")

        result = {
            "campaign_id": campaign_id,
            "product": None,
            "images_raw": [],
            "images_laundered": [],
            "extracted_videos": [],
            "ai_contents": {},
            "video_paths": {},
            "blog_html": "",
            "upload_results": {},
        }

        # ── Step 1: 쿠팡 상품 소싱 ──
        print("[1/7] 쿠팡 상품 소싱...")
        product = self._source_product(coupang_url_or_keyword)
        result["product"] = product
        print(f"  > 상품: {product.title}")
        print(f"  > 가격: {product.price or '-'}")
        print(f"  > 어필리에이트 링크: {product.affiliate_link or '(없음)'}")
        print(f"  > 이미지 URL: {len(product.image_urls)}개")

        # ── Step 2: 이미지 수집 ──
        print("\n[2/7] 이미지 수집...")
        raw_images = self._collect_images(
            product, browser_images, local_images
        )
        result["images_raw"] = raw_images
        print(f"  > 수집된 이미지: {len(raw_images)}개")

        if not raw_images:
            print("  [!] 이미지 없음 - 계속 진행 (텍스트만)")

        # ── Step 2.5: 도우인/틱톡 영상 추출 (있으면) ──
        extracted_videos = []
        if video_urls:
            print(f"\n[2.5/7] 도우인/틱톡 영상 추출 ({len(video_urls)}개)...")
            extractor = VideoExtractor(
                output_dir=str(self._campaign_dir / "extracted_videos")
            )
            extracted_videos = extractor.extract_batch(video_urls)
            result["extracted_videos"] = extracted_videos
            print(f"  > 추출 성공: {len(extracted_videos)}개")
        elif self._extracted_video:
            # _source_product에서 이미 추출한 영상
            extracted_videos = [self._extracted_video]
            result["extracted_videos"] = extracted_videos
            print(f"\n[2.5/7] 소싱 단계에서 추출된 영상 1개 발견")

        # ── Step 3: 이미지 세탁 (EXIF 제거 + 리사이즈) ──
        print("\n[3/7] 이미지 세탁 (EXIF 제거 + 미세 리사이즈)...")
        if raw_images:
            launderer = ImageLaunderer(
                output_dir=str(self._campaign_dir / "laundered")
            )
            laundered = launderer.launder_batch(raw_images, full_wash=True)
            result["images_laundered"] = laundered
            print(f"  > 세탁 완료: {len(laundered)}개")
        else:
            laundered = []

        # ── Step 4: AI 텍스트 생성 ──
        print("\n[4/7] AI 플랫폼별 텍스트 생성...")
        ai_contents = self._generate_ai_contents(
            product, platforms, persona, brand
        )
        result["ai_contents"] = ai_contents
        for p, content in ai_contents.items():
            title = content.get("title", "")[:30]
            body_len = len(content.get("body", ""))
            narr_count = len(content.get("narration", []))
            print(f"  > {p}: 제목={title}... 본문={body_len}자 나레이션={narr_count}장면")

        # ── Step 5: 영상 렌더링 (YouTube Shorts + Instagram Reels) ──
        video_platforms = [p for p in platforms if p in ("youtube", "instagram")]
        if video_platforms and laundered:
            print(f"\n[5/7] 영상 렌더링 ({', '.join(video_platforms)})...")
            videos = self._render_videos(
                video_platforms, ai_contents, laundered, brand, campaign_id
            )
            result["video_paths"] = videos
            for p, path in videos.items():
                if path and os.path.exists(path):
                    sz = os.path.getsize(path) / (1024 * 1024)
                    print(f"  > {p}: {Path(path).name} ({sz:.1f}MB)")
                else:
                    print(f"  > {p}: 렌더링 실패")
        else:
            print("\n[5/7] 영상 렌더링 건너뜀 (이미지 없음 또는 영상 플랫폼 미선택)")

        # ── Step 6: 블로그 HTML 생성 ──
        if "naver_blog" in platforms:
            print("\n[6/7] 블로그 HTML 생성...")
            blog_html = self._generate_blog_html(
                product, ai_contents.get("naver_blog", {}), laundered
            )
            result["blog_html"] = blog_html
            print(f"  > HTML 길이: {len(blog_html)}자")

            # HTML 파일 저장
            html_path = self._campaign_dir / f"{campaign_id}_blog.html"
            html_path.write_text(blog_html, encoding="utf-8")
            print(f"  > 저장: {html_path.name}")
        else:
            print("\n[6/7] 블로그 HTML 건너뜀")

        # ── Step 7: 3플랫폼 업로드 ──
        if not self.skip_upload:
            print(f"\n[7/7] 3플랫폼 업로드...")
            upload_results = self._upload_all(
                platforms, result, ai_contents
            )
            result["upload_results"] = upload_results
            for p, res in upload_results.items():
                status = "성공" if res.get("ok") else "실패"
                reason = res.get("reason", "")
                print(f"  > {p}: {status} - {reason}")
        else:
            print("\n[7/7] 업로드 건너뜀 (--skip-upload)")

        # ── 완료 ──
        elapsed = time.time() - start_time
        print(f"\n{'=' * 60}")
        print(f"  듀얼 배포 완료! (소요시간: {elapsed:.1f}초)")
        print(f"  캠페인 디렉토리: {self._campaign_dir}")
        print(f"{'=' * 60}\n")

        return result

    # ────────────────────────────────────────────
    # Step 1: 상품 소싱
    # ────────────────────────────────────────────

    def _source_product(self, input_str: str) -> Product:
        """쿠팡/알리/1688 URL 또는 키워드로 상품 정보를 소싱한다."""
        from affiliate_system.coupang_scraper import CoupangScraper

        scraper = CoupangScraper()

        # 쿠팡 URL
        if CoupangScraper.is_coupang_url(input_str):
            log.info("쿠팡 URL 감지 - 스크래핑 + 어필리에이트 링크 생성")
            return scraper.scrape_and_link(input_str)

        # 알리익스프레스/1688 URL
        if AliScraper.is_ali_url(input_str):
            log.info("알리/1688 URL 감지 - 스크래핑")
            ali = AliScraper()
            return ali.scrape_product(input_str)

        # 도우인/틱톡 URL → 영상 정보 추출
        extractor = VideoExtractor()
        platform = extractor.detect_platform(input_str)
        if platform != "unknown" and input_str.startswith("http"):
            log.info("%s URL 감지 - 영상 정보 추출", platform)
            info = extractor.get_video_info(input_str)
            if info:
                # 영상 다운로드 + Product 생성
                video_path = extractor.extract_video(input_str)
                self._extracted_video = video_path  # 나중에 렌더링에서 사용
                return Product(
                    url=input_str,
                    title=info.get("title", ""),
                    description=f"[{platform}] {info.get('uploader', '')}",
                    image_urls=[info.get("thumbnail", "")] if info.get("thumbnail") else [],
                    scraped_at=datetime.now(),
                )

        # 일반 URL
        if input_str.startswith("http"):
            log.info("일반 URL 감지 - OG 태그 스크래핑")
            try:
                import requests
                from bs4 import BeautifulSoup
                resp = requests.get(input_str, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                }, timeout=15)
                soup = BeautifulSoup(resp.text, "html.parser")
                title = (soup.find("meta", property="og:title") or {}).get("content", input_str)
                desc = (soup.find("meta", property="og:description") or {}).get("content", "")
                img = (soup.find("meta", property="og:image") or {}).get("content", "")
                return Product(
                    url=input_str, title=title, description=desc,
                    image_urls=[img] if img else [],
                    scraped_at=datetime.now(),
                )
            except Exception as e:
                log.warning("URL 스크래핑 실패: %s", e)

        # 키워드 검색
        log.info("키워드 검색: %s", input_str)
        try:
            products = scraper.search_products(input_str, limit=1)
            if products:
                return products[0]
        except Exception as e:
            log.warning("쿠팡 검색 실패: %s", e)

        # 폴백: 텍스트 기반 Product
        return Product(
            title=input_str,
            description=input_str,
            scraped_at=datetime.now(),
        )

    # ────────────────────────────────────────────
    # Step 2: 이미지 수집
    # ────────────────────────────────────────────

    def _collect_images(
        self,
        product: Product,
        browser_images: list[str] = None,
        local_images: list[str] = None,
    ) -> list[str]:
        """이미지를 수집한다 (브라우저 캡처 > 로컬 > 스크래핑)."""
        collected = []

        # 1. 로컬 이미지 (이미 있는 파일)
        if local_images:
            for path in local_images:
                if os.path.exists(path):
                    collected.append(path)
            if collected:
                log.info("로컬 이미지 %d개 로드", len(collected))
                return collected

        # 2. 브라우저 캡처 이미지 (Chrome DOM 추출)
        if browser_images:
            from affiliate_system.video_editor import MediaExtractor
            extractor = MediaExtractor()
            captured = extractor.capture_browser_images(
                browser_images, product.title or "product"
            )
            if captured:
                log.info("브라우저 캡처 이미지 %d개", len(captured))
                return captured

        # 3. 쿠팡 이미지 자동 추출
        from affiliate_system.coupang_scraper import CoupangScraper
        if product.url and CoupangScraper.is_coupang_url(product.url):
            try:
                from affiliate_system.video_editor import MediaExtractor
                extractor = MediaExtractor()
                images = extractor.get_coupang_images(
                    product_url=product.url,
                    product_name=product.title or "coupang",
                    max_images=8,
                )
                if images:
                    return images
            except Exception as e:
                log.warning("쿠팡 이미지 자동 추출 실패: %s", e)

        # 4. 상품 자체 이미지 다운로드
        if product.image_urls:
            from affiliate_system.media_collector import MediaCollector
            collector = MediaCollector()
            for url in product.image_urls[:6]:
                try:
                    path = collector.download_image(url)
                    if path:
                        collected.append(path)
                except Exception:
                    pass

        return collected

    # ────────────────────────────────────────────
    # Step 4: AI 텍스트 생성
    # ────────────────────────────────────────────

    def _generate_ai_contents(
        self,
        product: Product,
        platforms: list[str],
        persona: str = "",
        brand: str = "",
    ) -> dict:
        """플랫폼별 AI 콘텐츠를 생성한다."""
        from affiliate_system.ai_generator import AIGenerator

        gen = AIGenerator()
        platform_map = {
            "youtube": Platform.YOUTUBE,
            "instagram": Platform.INSTAGRAM,
            "naver_blog": Platform.NAVER_BLOG,
        }

        results = {}
        for p_name in platforms:
            platform = platform_map.get(p_name)
            if not platform:
                continue
            try:
                content = gen.generate_platform_content(
                    product, platform, persona=persona, brand=brand,
                )
                results[p_name] = content
                log.info("AI 콘텐츠 생성 완료: %s", p_name)
            except Exception as e:
                log.error("AI 생성 실패 (%s): %s", p_name, e)
                # 폴백 콘텐츠
                results[p_name] = {
                    "title": product.title,
                    "body": product.description or product.title,
                    "hashtags": [],
                    "narration": [product.title],
                    "cta": product.affiliate_link or "",
                    "thumbnail_text": product.title[:7] if product.title else "",
                }

        cost = gen.get_session_cost()
        log.info("AI 생성 비용: $%.6f", cost)
        return results

    # ────────────────────────────────────────────
    # Step 5: 영상 렌더링
    # ────────────────────────────────────────────

    def _render_videos(
        self,
        platforms: list[str],
        contents: dict,
        images: list[str],
        brand: str,
        campaign_id: str,
    ) -> dict:
        """플랫폼별 영상을 렌더링한다."""
        from affiliate_system.video_editor import VideoForge

        platform_map = {
            "youtube": Platform.YOUTUBE,
            "instagram": Platform.INSTAGRAM,
        }

        videos = {}
        for p_name in platforms:
            platform = platform_map.get(p_name)
            if not platform:
                continue

            content = contents.get(p_name, {})
            narrations = content.get("narration", [])
            cta = content.get("cta", "")
            body = content.get("body", "")

            output_path = str(
                self._output_dir / f"dual_{campaign_id}_{p_name}.mp4"
            )

            try:
                preset = PLATFORM_PRESETS[platform]
                config = RenderConfig.from_platform_preset(preset, brand=brand)
                forge = VideoForge(config=config)

                result = forge.render_for_platform(
                    platform=platform,
                    images=images[:6],
                    narrations=narrations,
                    output_path=output_path,
                    subtitle_text="\n".join(narrations) if narrations else body[:200],
                    brand=brand,
                    cta_text=cta,
                )
                videos[p_name] = result
                log.info("영상 렌더링 완료: %s -> %s", p_name, result)
            except Exception as e:
                log.error("영상 렌더링 실패 (%s): %s", p_name, e)
                videos[p_name] = ""

        return videos

    # ────────────────────────────────────────────
    # Step 6: 블로그 HTML 생성
    # ────────────────────────────────────────────

    def _generate_blog_html(
        self,
        product: Product,
        blog_content: dict,
        images: list[str],
    ) -> str:
        """네이버 블로그용 HTML을 생성한다."""
        try:
            from affiliate_system.blog_html_generator import NaverBlogHTMLGenerator
            gen = NaverBlogHTMLGenerator()

            title = blog_content.get("title", product.title)
            body = blog_content.get("body", "")
            hashtags = blog_content.get("hashtags", [])
            cta = blog_content.get("cta", "")
            affiliate_link = product.affiliate_link or ""

            # body를 섹션으로 분할 (NaverBlogHTMLGenerator 시그니처에 맞게)
            body_sections = [s.strip() for s in body.split("\n") if s.strip()]
            if len(body_sections) < 2:
                # 한 덩어리면 4개로 분할
                words = body.split()
                chunk_size = max(len(words) // 4, 1)
                body_sections = []
                for i in range(0, len(words), chunk_size):
                    body_sections.append(" ".join(words[i:i + chunk_size]))

            # 인트로 = 첫 섹션, 나머지 = 본문 섹션
            intro = body_sections[0] if body_sections else ""
            sections = body_sections[1:] if len(body_sections) > 1 else body_sections

            html = gen.generate_blog_html(
                title=title,
                intro=intro,
                body_sections=sections,
                image_paths=images[:7],
                coupang_link=affiliate_link,
                cta_text=cta,
                hashtags=hashtags,
                disclaimer=COUPANG_DISCLAIMER,
            )
            return html

        except Exception as e:
            log.warning("블로그 HTML 생성기 사용 실패: %s - 폴백 HTML 생성", e)

            # 폴백: 직접 HTML 생성
            body = blog_content.get("body", product.description or "")
            title = blog_content.get("title", product.title)
            hashtags = blog_content.get("hashtags", [])
            affiliate_link = product.affiliate_link or ""

            html_parts = [
                f'<div style="font-family: Pretendard, sans-serif; line-height: 1.8; max-width: 860px; margin: 0 auto;">',
            ]

            # 본문
            for paragraph in body.split("\n"):
                paragraph = paragraph.strip()
                if paragraph:
                    html_parts.append(f'<p style="margin: 16px 0; font-size: 16px;">{paragraph}</p>')

            # 이미지
            for img_path in images[:5]:
                img_name = Path(img_path).name
                html_parts.append(
                    f'<div style="text-align: center; margin: 24px 0;">'
                    f'<img src="{img_path}" alt="{title}" '
                    f'style="max-width: 100%; border-radius: 8px;">'
                    f'</div>'
                )

            # CTA + 어필리에이트 링크
            if affiliate_link:
                html_parts.append(
                    f'<div style="text-align: center; margin: 32px 0;">'
                    f'<a href="{affiliate_link}" target="_blank" '
                    f'style="display: inline-block; padding: 16px 32px; '
                    f'background: #FF6B35; color: white; font-size: 18px; '
                    f'font-weight: bold; text-decoration: none; border-radius: 8px;">'
                    f'최저가 확인하기'
                    f'</a>'
                    f'</div>'
                )

            # 쿠팡 면책 조항
            html_parts.append(
                f'<p style="margin-top: 40px; font-size: 12px; color: #888;">'
                f'{COUPANG_DISCLAIMER}'
                f'</p>'
            )

            # 해시태그
            if hashtags:
                tag_str = " ".join(f"#{t}" for t in hashtags)
                html_parts.append(
                    f'<p style="margin-top: 16px; font-size: 14px; color: #1a73e8;">'
                    f'{tag_str}'
                    f'</p>'
                )

            html_parts.append('</div>')
            return "\n".join(html_parts)

    # ────────────────────────────────────────────
    # Step 7: 3플랫폼 업로드
    # ────────────────────────────────────────────

    def _upload_all(
        self,
        platforms: list[str],
        result: dict,
        ai_contents: dict,
    ) -> dict:
        """Playwright로 3플랫폼에 업로드한다."""
        upload_results = {}
        uploader = None

        try:
            uploader = PlaywrightUploader(
                headless=self.headless,
                manual_review=self.manual_review,
            )

            product = result.get("product", Product())

            # 네이버 블로그
            if "naver_blog" in platforms and result.get("blog_html"):
                print("\n  >> 네이버 블로그 업로드...")
                blog_content = ai_contents.get("naver_blog", {})
                blog_result = uploader.upload_naver_blog(
                    title=blog_content.get("title", product.title),
                    content_html=result["blog_html"],
                    images=result.get("images_laundered", [])[:5],
                    tags=blog_content.get("hashtags", []),
                )
                upload_results["naver_blog"] = blog_result

            # YouTube Shorts
            yt_video = result.get("video_paths", {}).get("youtube", "")
            if "youtube" in platforms and yt_video and os.path.exists(yt_video):
                print("\n  >> YouTube Shorts 업로드...")
                yt_content = ai_contents.get("youtube", {})
                # 설명에 어필리에이트 링크 삽입
                desc = yt_content.get("body", "")
                if product.affiliate_link:
                    desc += f"\n\n{product.affiliate_link}"
                desc += f"\n\n{COUPANG_DISCLAIMER}"
                hashtag_str = " ".join(f"#{t}" for t in yt_content.get("hashtags", [])[:10])
                if hashtag_str:
                    desc += f"\n\n{hashtag_str}"

                yt_result = uploader.upload_youtube_shorts(
                    video_path=yt_video,
                    title=yt_content.get("title", product.title)[:100],
                    description=desc[:5000],
                    tags=yt_content.get("hashtags", []),
                )
                upload_results["youtube"] = yt_result

            # Instagram Reels
            ig_video = result.get("video_paths", {}).get("instagram", "")
            if "instagram" in platforms and ig_video and os.path.exists(ig_video):
                print("\n  >> Instagram Reels 업로드...")
                ig_content = ai_contents.get("instagram", {})
                # 캡션 = 본문 + 해시태그
                caption = ig_content.get("body", "")[:1500]
                hashtag_str = " ".join(f"#{t}" for t in ig_content.get("hashtags", [])[:25])
                if hashtag_str:
                    caption += f"\n\n{hashtag_str}"
                if product.affiliate_link:
                    caption += f"\n\n링크는 프로필 참고"

                ig_result = uploader.upload_instagram_reels(
                    video_path=ig_video,
                    caption=caption[:2200],
                )
                upload_results["instagram"] = ig_result

        except Exception as e:
            log.error("업로드 과정 에러: %s", e)
            upload_results["error"] = {"ok": False, "reason": str(e)}

        finally:
            if uploader:
                uploader.close()

        return upload_results


# ═══════════════════════════════════════════════════════════════════════════
# CLI 진입점
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="쿠팡파트너스 듀얼 배포 시스템 - 영상 + 블로그 동시 배포",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s "https://www.coupang.com/vp/products/123"
  %(prog)s "베베숲 물티슈" --skip-upload
  %(prog)s "https://www.coupang.com/vp/products/123" --platforms youtube naver_blog
  %(prog)s "다이어트 보충제" --headless --no-review
        """,
    )
    parser.add_argument("input", help="쿠팡 상품 URL 또는 검색 키워드")
    parser.add_argument("--brand", default="", help="브랜드명")
    parser.add_argument("--persona", default="", help="AI 페르소나")
    parser.add_argument(
        "--platforms", nargs="+",
        choices=["youtube", "instagram", "naver_blog"],
        default=None,
        help="배포 플랫폼 (기본: 3개 모두)",
    )
    parser.add_argument("--skip-upload", action="store_true",
                        help="업로드 건너뛰기 (콘텐츠 생성만)")
    parser.add_argument("--headless", action="store_true",
                        help="헤드리스 모드")
    parser.add_argument("--no-review", action="store_true",
                        help="수동 확인 비활성화 (자동 발행)")
    parser.add_argument("--local-images", nargs="+", default=None,
                        help="로컬 이미지 파일 경로")
    parser.add_argument("--video-urls", nargs="+", default=None,
                        help="도우인/틱톡/유튜브 영상 URL (추출용)")

    args = parser.parse_args()

    deployer = DualDeployer(
        manual_review=not args.no_review,
        skip_upload=args.skip_upload,
        headless=args.headless,
    )

    result = deployer.run(
        coupang_url_or_keyword=args.input,
        platforms=args.platforms,
        brand=args.brand,
        persona=args.persona,
        local_images=args.local_images,
        video_urls=args.video_urls,
    )

    # 텔레그램 리포트
    try:
        product = result.get("product")
        title = product.title if product else args.input
        uploads = result.get("upload_results", {})
        ok_count = sum(1 for v in uploads.values() if isinstance(v, dict) and v.get("ok"))
        extracted = len(result.get("extracted_videos", []))

        report = (
            f"듀얼 배포 완료: {title[:30]}\n"
            f"이미지: {len(result.get('images_laundered', []))}개 세탁\n"
            f"영상 추출: {extracted}개\n"
            f"영상 렌더링: {len(result.get('video_paths', {}))}개\n"
            f"업로드: {ok_count}/{len(uploads)}개 성공"
        )
        send_telegram(report)
    except Exception:
        pass


if __name__ == "__main__":
    main()
