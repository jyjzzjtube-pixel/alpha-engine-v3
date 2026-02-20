"""
Affiliate Marketing System — Media Source Collection
=====================================================
스톡 이미지/영상 API 통합 검색 및 소셜 미디어 영상 다운로드 모듈.

지원 플랫폼:
- Pexels (이미지 + 영상, 상업 이용 무료)
- Pixabay (이미지 + 영상, 상업 이용 무료)
- Unsplash (이미지 전용, 상업 이용 무료)
- 소셜 미디어 (YouTube, TikTok, Instagram, Facebook — yt-dlp 사용)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from affiliate_system.config import (
    PEXELS_API_KEY,
    PIXABAY_API_KEY,
    UNSPLASH_ACCESS_KEY,
    WORK_DIR,
    RENDER_OUTPUT_DIR,
)
from affiliate_system.utils import setup_logger, retry, ensure_dir

__all__ = ["MediaCollector"]

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MIN_IMAGE_SIZE = 5 * 1024  # 5 KB
_REQUEST_TIMEOUT = 30  # 초

# 플랫폼 감지 정규식
_PLATFORM_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("youtube",   re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)),
    ("tiktok",    re.compile(r"tiktok\.com", re.IGNORECASE)),
    ("instagram", re.compile(r"instagram\.com", re.IGNORECASE)),
    ("facebook",  re.compile(r"(facebook\.com|fb\.watch)", re.IGNORECASE)),
]


# ═══════════════════════════════════════════════════════════════════════════
# MediaCollector
# ═══════════════════════════════════════════════════════════════════════════

class MediaCollector:
    """미디어 소스 통합 수집기.

    Pexels, Pixabay, Unsplash 스톡 API를 통합 검색하고,
    yt-dlp를 사용하여 소셜 미디어 영상을 다운로드 + 워싱한다.
    """

    def __init__(self):
        self.logger = setup_logger("media_collector", "media_collector.log")
        self._download_dir = ensure_dir(WORK_DIR / "media_downloads")
        self.logger.info(
            "MediaCollector 초기화 (다운로드 경로: %s)", self._download_dir,
        )

    # ══════════════════════════════════════════════════════════════════════
    # 스톡 이미지 검색
    # ══════════════════════════════════════════════════════════════════════

    @retry(max_attempts=2, delay=1.0)
    def search_pexels_images(self, query: str, count: int = 10) -> list[dict]:
        """Pexels에서 이미지 검색.

        Returns:
            [{"id", "url", "thumb", "title", "photographer", "source", "license"}]
        """
        if not PEXELS_API_KEY:
            self.logger.debug("Pexels API 키 미설정 — 건너뜀")
            return []

        self.logger.info("Pexels 이미지 검색: query='%s', count=%d", query, count)
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": min(count, 80)},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[dict] = []
        for photo in data.get("photos", [])[:count]:
            src = photo.get("src", {})
            results.append({
                "id": str(photo.get("id", "")),
                "url": src.get("large") or src.get("original", ""),
                "thumb": src.get("medium") or src.get("small", ""),
                "title": photo.get("alt", ""),
                "photographer": photo.get("photographer", ""),
                "source": "pexels",
                "license": "Pexels License (free commercial use)",
            })

        self.logger.info("Pexels 결과: %d건", len(results))
        return results

    @retry(max_attempts=2, delay=1.0)
    def search_pixabay_images(self, query: str, count: int = 10) -> list[dict]:
        """Pixabay에서 이미지 검색.

        Returns:
            [{"id", "url", "thumb", "title", "photographer", "source", "license"}]
        """
        if not PIXABAY_API_KEY:
            self.logger.debug("Pixabay API 키 미설정 — 건너뜀")
            return []

        self.logger.info("Pixabay 이미지 검색: query='%s', count=%d", query, count)
        resp = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": PIXABAY_API_KEY,
                "q": query,
                "per_page": min(count, 200),
                "image_type": "photo",
                "safesearch": "true",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[dict] = []
        for hit in data.get("hits", [])[:count]:
            results.append({
                "id": str(hit.get("id", "")),
                "url": hit.get("largeImageURL", ""),
                "thumb": hit.get("previewURL") or hit.get("webformatURL", ""),
                "title": hit.get("tags", ""),
                "photographer": hit.get("user", ""),
                "source": "pixabay",
                "license": "Pixabay License (free commercial use)",
            })

        self.logger.info("Pixabay 결과: %d건", len(results))
        return results

    @retry(max_attempts=2, delay=1.0)
    def search_unsplash_images(self, query: str, count: int = 10) -> list[dict]:
        """Unsplash에서 이미지 검색.

        Returns:
            [{"id", "url", "thumb", "title", "photographer", "source", "license"}]
        """
        if not UNSPLASH_ACCESS_KEY:
            self.logger.debug("Unsplash API 키 미설정 — 건너뜀")
            return []

        self.logger.info("Unsplash 이미지 검색: query='%s', count=%d", query, count)
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            params={"query": query, "per_page": min(count, 30)},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[dict] = []
        for photo in data.get("results", [])[:count]:
            urls = photo.get("urls", {})
            user = photo.get("user", {})
            results.append({
                "id": str(photo.get("id", "")),
                "url": urls.get("regular") or urls.get("full", ""),
                "thumb": urls.get("small") or urls.get("thumb", ""),
                "title": photo.get("alt_description", "") or photo.get("description", "") or "",
                "photographer": user.get("name", ""),
                "source": "unsplash",
                "license": "Unsplash License (free commercial use)",
            })

        self.logger.info("Unsplash 결과: %d건", len(results))
        return results

    def search_images(
        self, query: str, count: int = 10, source: str = "all",
    ) -> list[dict]:
        """모든 플랫폼 통합 이미지 검색.

        Args:
            query: 검색어 (영문 권장)
            count: 플랫폼별 최대 결과 수
            source: 'all', 'pexels', 'pixabay', 'unsplash'

        Returns:
            통합 결과 리스트 (source 필드로 출처 구분)
        """
        self.logger.info(
            "통합 이미지 검색: query='%s', count=%d, source=%s",
            query, count, source,
        )
        results: list[dict] = []

        searchers: dict[str, callable] = {
            "pexels": self.search_pexels_images,
            "pixabay": self.search_pixabay_images,
            "unsplash": self.search_unsplash_images,
        }

        targets = (
            [source] if source != "all"
            else list(searchers.keys())
        )

        for name in targets:
            fn = searchers.get(name)
            if fn is None:
                self.logger.warning("알 수 없는 소스: %s", name)
                continue
            try:
                results.extend(fn(query, count))
            except Exception as exc:
                self.logger.warning("%s 이미지 검색 실패: %s", name, exc)

        self.logger.info("통합 이미지 검색 총 %d건 반환", len(results))
        return results

    # ══════════════════════════════════════════════════════════════════════
    # 스톡 영상 검색
    # ══════════════════════════════════════════════════════════════════════

    @retry(max_attempts=2, delay=1.0)
    def search_pexels_videos(self, query: str, count: int = 5) -> list[dict]:
        """Pexels에서 영상 검색.

        Returns:
            [{"id", "url", "thumb", "title", "photographer", "duration", "source", "license"}]
        """
        if not PEXELS_API_KEY:
            self.logger.debug("Pexels API 키 미설정 — 건너뜀")
            return []

        self.logger.info("Pexels 영상 검색: query='%s', count=%d", query, count)
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": min(count, 80)},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[dict] = []
        for video in data.get("videos", [])[:count]:
            # 가장 높은 품질 파일 선택
            video_files = video.get("video_files", [])
            best_url = ""
            best_width = 0
            for vf in video_files:
                w = vf.get("width", 0) or 0
                if w > best_width:
                    best_width = w
                    best_url = vf.get("link", "")

            # 썸네일: video_pictures 첫 번째 또는 빈 문자열
            thumb = ""
            pictures = video.get("video_pictures", [])
            if pictures:
                thumb = pictures[0].get("picture", "")

            user = video.get("user", {})
            results.append({
                "id": str(video.get("id", "")),
                "url": best_url,
                "thumb": thumb,
                "title": "",
                "photographer": user.get("name", ""),
                "duration": video.get("duration", 0),
                "source": "pexels",
                "license": "Pexels License (free commercial use)",
            })

        self.logger.info("Pexels 영상 결과: %d건", len(results))
        return results

    @retry(max_attempts=2, delay=1.0)
    def search_pixabay_videos(self, query: str, count: int = 5) -> list[dict]:
        """Pixabay에서 영상 검색.

        Returns:
            [{"id", "url", "thumb", "title", "photographer", "duration", "source", "license"}]
        """
        if not PIXABAY_API_KEY:
            self.logger.debug("Pixabay API 키 미설정 — 건너뜀")
            return []

        self.logger.info("Pixabay 영상 검색: query='%s', count=%d", query, count)
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params={
                "key": PIXABAY_API_KEY,
                "q": query,
                "per_page": min(count, 200),
                "safesearch": "true",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[dict] = []
        for hit in data.get("hits", [])[:count]:
            videos = hit.get("videos", {})
            # large > medium > small > tiny 우선순위
            best_url = ""
            for quality in ("large", "medium", "small", "tiny"):
                vdata = videos.get(quality, {})
                if vdata.get("url"):
                    best_url = vdata["url"]
                    break

            results.append({
                "id": str(hit.get("id", "")),
                "url": best_url,
                "thumb": hit.get("previewURL", ""),  # Pixabay 비디오 프리뷰 GIF가 없을 수 있음
                "title": hit.get("tags", ""),
                "photographer": hit.get("user", ""),
                "duration": hit.get("duration", 0),
                "source": "pixabay",
                "license": "Pixabay License (free commercial use)",
            })

        self.logger.info("Pixabay 영상 결과: %d건", len(results))
        return results

    def search_videos(
        self, query: str, count: int = 5, source: str = "all",
    ) -> list[dict]:
        """통합 영상 검색.

        Args:
            query: 검색어
            count: 플랫폼별 최대 결과 수
            source: 'all', 'pexels', 'pixabay'

        Returns:
            통합 결과 리스트
        """
        self.logger.info(
            "통합 영상 검색: query='%s', count=%d, source=%s",
            query, count, source,
        )
        results: list[dict] = []

        searchers: dict[str, callable] = {
            "pexels": self.search_pexels_videos,
            "pixabay": self.search_pixabay_videos,
        }

        targets = (
            [source] if source != "all"
            else list(searchers.keys())
        )

        for name in targets:
            fn = searchers.get(name)
            if fn is None:
                self.logger.warning("알 수 없는 영상 소스: %s", name)
                continue
            try:
                results.extend(fn(query, count))
            except Exception as exc:
                self.logger.warning("%s 영상 검색 실패: %s", name, exc)

        self.logger.info("통합 영상 검색 총 %d건 반환", len(results))
        return results

    # ══════════════════════════════════════════════════════════════════════
    # 다운로드
    # ══════════════════════════════════════════════════════════════════════

    def download_image(self, url: str, save_path: str | None = None) -> str:
        """이미지 URL을 다운로드하여 JPEG로 저장.

        - User-Agent 헤더로 차단 우회
        - 최소 5KB 검증
        - RGB 변환 후 JPEG 저장

        Args:
            url: 이미지 URL
            save_path: 저장 경로 (None이면 자동 생성)

        Returns:
            저장된 파일 경로

        Raises:
            ValueError: 이미지가 너무 작거나 유효하지 않을 때
            requests.RequestException: 다운로드 실패 시
        """
        if save_path is None:
            filename = f"img_{uuid.uuid4().hex[:12]}.jpg"
            save_path = str(self._download_dir / filename)

        self.logger.info("이미지 다운로드: %s", url)

        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
            stream=True,
        )
        resp.raise_for_status()

        # 임시 파일에 저장 후 검증
        raw_data = resp.content
        if len(raw_data) < _MIN_IMAGE_SIZE:
            raise ValueError(
                f"다운로드된 이미지가 너무 작습니다: {len(raw_data)} bytes (최소 {_MIN_IMAGE_SIZE})"
            )

        # PIL로 열어서 검증 + RGB 변환 + JPEG 저장
        import io
        try:
            img = Image.open(io.BytesIO(raw_data))
            img = img.convert("RGB")
        except Exception as exc:
            raise ValueError(f"유효하지 않은 이미지 데이터: {exc}") from exc

        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        img.save(save_path, "JPEG", quality=95)

        size_kb = os.path.getsize(save_path) / 1024
        self.logger.info("이미지 저장 완료: %s (%.1f KB)", save_path, size_kb)
        return save_path

    def download_video(self, url: str, save_path: str | None = None) -> str:
        """영상 URL을 직접 다운로드 (스톡 영상 등).

        Args:
            url: 영상 파일 URL
            save_path: 저장 경로 (None이면 자동 생성)

        Returns:
            저장된 파일 경로

        Raises:
            requests.RequestException: 다운로드 실패 시
        """
        if save_path is None:
            filename = f"vid_{uuid.uuid4().hex[:12]}.mp4"
            save_path = str(self._download_dir / filename)

        self.logger.info("영상 다운로드: %s", url)

        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=120,
            stream=True,
        )
        resp.raise_for_status()

        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

        downloaded = 0
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

        size_mb = downloaded / (1024 * 1024)
        self.logger.info("영상 저장 완료: %s (%.1f MB)", save_path, size_mb)
        return save_path

    def download_from_social(
        self,
        url: str,
        save_path: str | None = None,
        auto_wash: bool = True,
    ) -> str:
        """소셜 미디어 URL에서 yt-dlp로 영상 다운로드.

        TikTok, YouTube, Instagram Reels, Facebook을 지원한다.
        auto_wash=True이면 다운로드 후 VideoForge.wash_video()로 자동 세탁.

        Args:
            url: 소셜 미디어 영상 URL
            save_path: 최종 저장 경로 (None이면 자동 생성)
            auto_wash: 다운로드 후 자동 워싱 여부

        Returns:
            저장된 (또는 세탁된) 파일 경로

        Raises:
            RuntimeError: yt-dlp 미설치 또는 다운로드 실패 시
        """
        platform = self.detect_platform(url)
        self.logger.info(
            "소셜 미디어 다운로드: platform=%s, url=%s, auto_wash=%s",
            platform, url, auto_wash,
        )

        # 임시 다운로드 경로
        tmp_filename = f"social_{uuid.uuid4().hex[:8]}.mp4"
        tmp_path = str(self._download_dir / tmp_filename)

        if save_path is None:
            save_filename = f"social_{platform}_{uuid.uuid4().hex[:8]}.mp4"
            save_path = str(self._download_dir / save_filename)

        # yt-dlp 경로 결정
        ytdlp_cmd = self._find_ytdlp()

        cmd = [
            ytdlp_cmd,
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", tmp_path,
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            url,
        ]

        self.logger.info("yt-dlp 명령 실행: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                err_msg = result.stderr.strip() or "알 수 없는 오류"
                self.logger.error("yt-dlp 실패 (코드 %d): %s", result.returncode, err_msg)
                raise RuntimeError(f"yt-dlp 다운로드 실패: {err_msg}")
        except FileNotFoundError:
            raise RuntimeError(
                "yt-dlp가 설치되어 있지 않습니다. "
                "pip install yt-dlp 또는 시스템 패키지로 설치하세요."
            )

        if not os.path.exists(tmp_path):
            raise RuntimeError(f"다운로드된 파일을 찾을 수 없습니다: {tmp_path}")

        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        self.logger.info("소셜 영상 다운로드 완료: %.1f MB", size_mb)

        # 자동 워싱
        if auto_wash:
            self.logger.info("자동 워싱 시작 → %s", save_path)
            try:
                from affiliate_system.video_editor import VideoForge

                forge = VideoForge()
                result_path = forge.wash_video(tmp_path, save_path)

                # 임시 원본 삭제
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

                self.logger.info("워싱 완료: %s", result_path)
                return result_path

            except Exception as exc:
                self.logger.warning(
                    "워싱 실패 (원본 파일 유지): %s", exc,
                )
                # 워싱 실패 시 원본을 save_path로 이동
                if tmp_path != save_path:
                    os.replace(tmp_path, save_path)
                return save_path
        else:
            # 워싱 없이 그대로 저장
            if tmp_path != save_path:
                os.replace(tmp_path, save_path)
            return save_path

    # ══════════════════════════════════════════════════════════════════════
    # 이미지 처리
    # ══════════════════════════════════════════════════════════════════════

    def resize_for_shorts(
        self,
        image_path: str,
        width: int = 1080,
        height: int = 1920,
    ) -> str:
        """이미지를 Shorts 세로 포맷으로 리사이즈 (center crop + resize).

        원본 비율과 다르면 중앙 크롭 후 목표 해상도로 리사이즈한다.

        Args:
            image_path: 원본 이미지 경로
            width: 목표 너비 (기본 1080)
            height: 목표 높이 (기본 1920)

        Returns:
            리사이즈된 이미지 저장 경로
        """
        self.logger.info(
            "Shorts 리사이즈: %s → %dx%d", image_path, width, height,
        )

        img = Image.open(image_path).convert("RGB")
        iw, ih = img.size
        target_ratio = width / height

        current_ratio = iw / ih
        if current_ratio > target_ratio:
            # 좌우 크롭
            new_w = int(ih * target_ratio)
            left = (iw - new_w) // 2
            img = img.crop((left, 0, left + new_w, ih))
        else:
            # 상하 크롭
            new_h = int(iw / target_ratio)
            top = (ih - new_h) // 2
            img = img.crop((0, top, iw, top + new_h))

        img = img.resize((width, height), Image.LANCZOS)

        # 저장 (_shorts 접미어 추가)
        base, ext = os.path.splitext(image_path)
        output_path = f"{base}_shorts.jpg"
        img.save(output_path, "JPEG", quality=95)

        self.logger.info("Shorts 리사이즈 완료: %s", output_path)
        return output_path

    def batch_download_images(
        self, results: list[dict], count: int = 5,
    ) -> list[str]:
        """검색 결과에서 여러 이미지를 일괄 다운로드.

        실패한 이미지는 건너뛰고 성공한 것만 반환한다.

        Args:
            results: search_images() 등의 반환 결과 리스트
            count: 최대 다운로드 수

        Returns:
            저장된 파일 경로 리스트
        """
        self.logger.info(
            "일괄 다운로드 시작: 후보 %d건 중 최대 %d건",
            len(results), count,
        )
        downloaded: list[str] = []

        for item in results[:count]:
            url = item.get("url", "")
            if not url:
                continue
            try:
                source = item.get("source", "unknown")
                filename = f"{source}_{item.get('id', uuid.uuid4().hex[:8])}.jpg"
                save_path = str(self._download_dir / filename)
                path = self.download_image(url, save_path)
                downloaded.append(path)
            except Exception as exc:
                self.logger.warning(
                    "이미지 다운로드 실패 (id=%s): %s",
                    item.get("id", "?"), exc,
                )

        self.logger.info(
            "일괄 다운로드 완료: %d/%d 성공", len(downloaded), min(count, len(results)),
        )
        return downloaded

    # ══════════════════════════════════════════════════════════════════════
    # 유틸리티
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def detect_platform(url: str) -> str:
        """URL에서 플랫폼을 자동 감지한다.

        Returns:
            'youtube', 'tiktok', 'instagram', 'facebook', 또는 'unknown'
        """
        for name, pattern in _PLATFORM_PATTERNS:
            if pattern.search(url):
                return name
        return "unknown"

    def get_available_sources(self) -> dict:
        """사용 가능한 소스를 반환 (API 키 설정 여부).

        Returns:
            {
                "pexels":   {"available": bool, "types": ["image", "video"]},
                "pixabay":  {"available": bool, "types": ["image", "video"]},
                "unsplash": {"available": bool, "types": ["image"]},
                "ytdlp":    {"available": bool, "types": ["video"]},
            }
        """
        ytdlp_available = False
        try:
            ytdlp_cmd = self._find_ytdlp()
            result = subprocess.run(
                [ytdlp_cmd, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            ytdlp_available = result.returncode == 0
        except Exception:
            pass

        sources = {
            "pexels": {
                "available": bool(PEXELS_API_KEY),
                "types": ["image", "video"],
            },
            "pixabay": {
                "available": bool(PIXABAY_API_KEY),
                "types": ["image", "video"],
            },
            "unsplash": {
                "available": bool(UNSPLASH_ACCESS_KEY),
                "types": ["image"],
            },
            "ytdlp": {
                "available": ytdlp_available,
                "types": ["video"],
            },
        }

        available = [k for k, v in sources.items() if v["available"]]
        self.logger.info("사용 가능한 소스: %s", ", ".join(available) or "없음")
        return sources

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _find_ytdlp() -> str:
        """yt-dlp 실행 파일 경로를 찾는다.

        우선순위:
        1. PATH에 있는 yt-dlp
        2. sys.executable 기준 Scripts 폴더
        """
        # PATH에서 찾기
        import shutil
        found = shutil.which("yt-dlp")
        if found:
            return found

        # Python Scripts 폴더에서 찾기
        scripts_dir = Path(sys.executable).parent / "Scripts"
        ytdlp_path = scripts_dir / "yt-dlp.exe"
        if ytdlp_path.exists():
            return str(ytdlp_path)

        # Unix 계열 bin 폴더
        bin_dir = Path(sys.executable).parent
        ytdlp_path = bin_dir / "yt-dlp"
        if ytdlp_path.exists():
            return str(ytdlp_path)

        # 기본값 (PATH에서 찾도록)
        return "yt-dlp"


# ═══════════════════════════════════════════════════════════════════════════
# CLI 진입점 (테스트용)
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="MediaCollector CLI")
    sub = parser.add_subparsers(dest="command")

    # search-images
    si = sub.add_parser("search-images", help="이미지 검색")
    si.add_argument("query", help="검색어")
    si.add_argument("--count", type=int, default=5)
    si.add_argument("--source", default="all", choices=["all", "pexels", "pixabay", "unsplash"])

    # search-videos
    sv = sub.add_parser("search-videos", help="영상 검색")
    sv.add_argument("query", help="검색어")
    sv.add_argument("--count", type=int, default=5)
    sv.add_argument("--source", default="all", choices=["all", "pexels", "pixabay"])

    # download-image
    di = sub.add_parser("download-image", help="이미지 다운로드")
    di.add_argument("url", help="이미지 URL")
    di.add_argument("--output", default=None)

    # download-social
    ds = sub.add_parser("download-social", help="소셜 미디어 영상 다운로드")
    ds.add_argument("url", help="영상 URL")
    ds.add_argument("--output", default=None)
    ds.add_argument("--no-wash", action="store_true", help="워싱 비활성화")

    # sources
    sub.add_parser("sources", help="사용 가능한 소스 확인")

    args = parser.parse_args()
    mc = MediaCollector()

    if args.command == "search-images":
        results = mc.search_images(args.query, args.count, args.source)
        print(json.dumps(results, indent=2, ensure_ascii=False))

    elif args.command == "search-videos":
        results = mc.search_videos(args.query, args.count, args.source)
        print(json.dumps(results, indent=2, ensure_ascii=False))

    elif args.command == "download-image":
        path = mc.download_image(args.url, args.output)
        print(f"다운로드 완료: {path}")

    elif args.command == "download-social":
        path = mc.download_from_social(args.url, args.output, auto_wash=not args.no_wash)
        print(f"다운로드 완료: {path}")

    elif args.command == "sources":
        sources = mc.get_available_sources()
        print(json.dumps(sources, indent=2, ensure_ascii=False))

    else:
        parser.print_help()
