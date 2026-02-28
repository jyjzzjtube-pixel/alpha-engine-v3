# -*- coding: utf-8 -*-
"""
쇼핑쇼츠 팩토리 GUI 탭
========================
PyQt6 기반 쇼핑쇼츠 생성 UI
소스영상 다운로드(도우인/틱톡) + AI대본 + TTS + 자막 → 쇼츠 완성
"""
from __future__ import annotations

import os
import sys
import glob
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QProgressBar, QFileDialog, QSplitter,
    QComboBox, QGroupBox, QCheckBox, QFrame, QMessageBox,
    QListWidget, QListWidgetItem, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QSize
from PyQt6.QtGui import QFont, QIcon, QColor


# ── 다운로드 워커 ──
class VideoDownloadWorker(QThread):
    """URL에서 영상 다운로드 (yt-dlp + snapdouyin 폴백)

    레퍼런스 영상 방법:
    1차: yt-dlp (범용, 도우인/틱톡/유튜브 등)
    2차: snapdouyin.app API (도우인 워터마크 제거 전문)
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)  # 다운로드된 파일 경로
    error = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            self.progress.emit(f"다운로드 시작: {self.url[:60]}...")

            # 1차: yt-dlp (범용)
            path = self._try_ytdlp()
            if path:
                return

            # 2차: 도우인 URL이면 snapdouyin 폴백
            if self._is_douyin_url(self.url):
                self.progress.emit("  ⚡ yt-dlp 실패 → snapdouyin.app 폴백 시도...")
                path = self._try_snapdouyin()
                if path:
                    return

            self.error.emit("다운로드 실패 — URL을 확인하세요")
        except Exception as e:
            self.error.emit(f"다운로드 에러: {e}")

    def _try_ytdlp(self) -> str | None:
        """yt-dlp 기반 다운로드"""
        try:
            from affiliate_system.dual_deployer import VideoExtractor
            extractor = VideoExtractor()
            platform = extractor.detect_platform(self.url)
            self.progress.emit(f"  플랫폼: {platform} (yt-dlp)")

            path = extractor.extract_video(self.url)
            if path and os.path.exists(path):
                sz = os.path.getsize(path) / (1024 * 1024)
                self.progress.emit(f"  ✅ 다운로드 완료: {Path(path).name} ({sz:.1f}MB)")
                self.finished.emit(path)
                return path
        except Exception as e:
            self.progress.emit(f"  ⚠ yt-dlp 실패: {e}")
        return None

    def _try_snapdouyin(self) -> str | None:
        """snapdouyin.app API 폴백 (도우인 워터마크 제거)"""
        try:
            import requests
            self.progress.emit("  snapdouyin.app에서 워터마크 제거 URL 요청 중...")

            # snapdouyin API 호출
            api_url = "https://api.snapdouyin.app/tiktok"
            resp = requests.post(
                api_url,
                json={"url": self.url},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                video_url = data.get("video_url") or data.get("nwm_video_url") or ""
                if video_url:
                    # 영상 다운로드
                    from affiliate_system.config import WORK_DIR
                    from affiliate_system.utils import ensure_dir
                    import uuid
                    out_dir = ensure_dir(WORK_DIR / "extracted_videos")
                    out_path = str(out_dir / f"douyin_{uuid.uuid4().hex[:8]}.mp4")

                    self.progress.emit("  영상 데이터 다운로드 중...")
                    vid_resp = requests.get(video_url, timeout=60, stream=True)
                    with open(out_path, 'wb') as f:
                        for chunk in vid_resp.iter_content(chunk_size=8192):
                            f.write(chunk)

                    if os.path.exists(out_path):
                        sz = os.path.getsize(out_path) / (1024 * 1024)
                        if sz > 0.1:  # 100KB 이상이면 유효
                            self.progress.emit(
                                f"  ✅ snapdouyin 완료: {Path(out_path).name} ({sz:.1f}MB)"
                            )
                            self.finished.emit(out_path)
                            return out_path
        except Exception as e:
            self.progress.emit(f"  ⚠ snapdouyin 폴백 실패: {e}")
        return None

    @staticmethod
    def _is_douyin_url(url: str) -> bool:
        """도우인 URL 판별"""
        douyin_patterns = ['douyin.com', 'v.douyin.com', 'iesdouyin.com']
        return any(p in url.lower() for p in douyin_patterns)


# ── 제품 실제 영상/이미지 자동 수집 워커 ──
class ProductMediaWorker(QThread):
    """상품명으로 유튜브 실제 리뷰영상 + 구글 실제 제품이미지를 자동 수집한다.

    핵심: 스톡영상이 아닌 **정확한 제품**의 실제 콘텐츠를 찾는다.
    - 유튜브: yt-dlp로 제품명 검색 → 리뷰/언박싱 영상 다운로드
    - 구글 이미지: 제품명 검색 → 실제 제품 사진 다운로드
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)  # 다운로드된 파일 경로 리스트
    error = pyqtSignal(str)

    def __init__(self, keyword: str, video_count: int = 3, image_count: int = 5):
        super().__init__()
        self.keyword = keyword
        self.video_count = video_count
        self.image_count = image_count

    def run(self):
        try:
            from affiliate_system.config import WORK_DIR
            from affiliate_system.utils import ensure_dir
            import uuid

            self.progress.emit(f"🎯 제품 미디어 수집: '{self.keyword}'")
            downloaded = []

            # ── 1단계: 틱톡/도우인에서 실제 쇼핑 영상 검색 ──
            self.progress.emit("")
            self.progress.emit("📱 [1/3] 틱톡/도우인 쇼핑영상 검색 중...")
            tiktok_paths = self._search_tiktok_videos()
            downloaded.extend(tiktok_paths)

            # ── 2단계: 유튜브에서 실제 리뷰영상 검색 + 다운로드 ──
            self.progress.emit("")
            self.progress.emit("🎬 [2/3] 유튜브 리뷰영상 검색 중...")
            yt_paths = self._search_youtube_videos()
            downloaded.extend(yt_paths)

            # ── 3단계: 구글에서 실제 제품 이미지 다운로드 ──
            self.progress.emit("")
            self.progress.emit("🖼️ [3/3] 구글 실제 제품이미지 검색 중...")
            img_paths = self._search_google_images()

            if not downloaded and not img_paths:
                self.error.emit(
                    f"'{self.keyword}'에 대한 영상/이미지를 찾지 못했습니다.\n"
                    "상품명을 정확히 입력해보세요."
                )
                return

            # 이미지도 리스트에 포함 (영상이 메인, 이미지는 보조)
            if img_paths:
                self.progress.emit(f"  📁 제품 이미지 {len(img_paths)}장 저장됨")

            self.progress.emit("")
            self.progress.emit(
                f"🎉 수집 완료! "
                f"틱톡 {len(tiktok_paths)}개 + 유튜브 {len(yt_paths)}개"
                + (f" + 이미지 {len(img_paths)}장" if img_paths else "")
            )
            self.finished.emit(downloaded)

        except Exception as e:
            self.error.emit(f"제품 미디어 수집 오류: {e}")

    def _search_tiktok_videos(self) -> list:
        """구글 검색으로 틱톡/도우인 제품영상 URL을 찾고 yt-dlp로 다운로드한다.

        방법: "site:tiktok.com 제품명" 구글 검색 → 틱톡 URL 추출 → yt-dlp 다운로드
        도우인도 동일하게 "site:douyin.com 제품명" 검색.
        """
        try:
            import yt_dlp
        except ImportError:
            self.progress.emit("  ⚠ yt-dlp 미설치 — 틱톡 검색 건너뜀")
            return []

        try:
            from curl_cffi import requests as cf_requests
        except ImportError:
            self.progress.emit("  ⚠ curl_cffi 미설치 — 틱톡 검색 건너뜀")
            return []

        import re
        import urllib.parse
        import uuid
        from affiliate_system.config import WORK_DIR
        from affiliate_system.utils import ensure_dir
        from bs4 import BeautifulSoup

        out_dir = ensure_dir(WORK_DIR / "extracted_videos")
        downloaded = []
        tiktok_urls = []

        # ── 구글에서 틱톡 영상 URL 검색 ──
        for site, label in [("tiktok.com", "틱톡"), ("douyin.com", "도우인")]:
            try:
                query = f"site:{site} {self.keyword}"
                search_url = (
                    f"https://www.google.com/search?"
                    f"q={urllib.parse.quote(query)}&hl=ko&num=10"
                )
                self.progress.emit(f"  🔍 구글에서 {label} 영상 검색...")
                session = cf_requests.Session(impersonate="chrome131")
                resp = session.get(search_url, timeout=15)

                if resp.status_code != 200:
                    self.progress.emit(f"    ⚠ 구글 응답 {resp.status_code}")
                    continue

                # 틱톡/도우인 URL 추출
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    # 구글 리다이렉트 URL에서 실제 URL 추출
                    if "/url?q=" in href:
                        href = href.split("/url?q=")[1].split("&")[0]
                        href = urllib.parse.unquote(href)
                    if site in href and "/video/" in href:
                        if href not in tiktok_urls:
                            tiktok_urls.append(href)

                # 정규식으로도 추출 (href 외에 텍스트 안에 있는 경우)
                url_pattern = rf'https?://(?:www\.)?{re.escape(site)}/[^\s"<>]+/video/\d+'
                for match in re.findall(url_pattern, resp.text):
                    clean_url = match.split("&")[0].split('"')[0]
                    if clean_url not in tiktok_urls:
                        tiktok_urls.append(clean_url)

                self.progress.emit(f"    {label}: {len([u for u in tiktok_urls if site in u])}개 URL 발견")

            except Exception as e:
                self.progress.emit(f"    ⚠ {label} 검색 실패: {e}")

        if not tiktok_urls:
            self.progress.emit("  ⚠ 틱톡/도우인 영상을 찾지 못함 → 유튜브로 진행")
            return []

        # ── 찾은 URL을 yt-dlp로 다운로드 ──
        to_dl = tiktok_urls[:self.video_count]
        self.progress.emit(f"  ⬇ {len(to_dl)}개 틱톡/도우인 영상 다운로드...")

        for i, url in enumerate(to_dl, 1):
            source = "도우인" if "douyin" in url else "틱톡"
            self.progress.emit(f"  [{i}/{len(to_dl)}] {source}: {url[:60]}...")

            try:
                out_path = str(
                    out_dir / f"tiktok_{uuid.uuid4().hex[:8]}.mp4"
                )
                dl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'outtmpl': out_path.replace('.mp4', '.%(ext)s'),
                    'format': 'best[ext=mp4]/best',
                    'merge_output_format': 'mp4',
                }
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    ydl.download([url])

                # 다운로드된 파일 찾기
                import glob as g
                pattern = out_path.replace('.mp4', '.*')
                found = g.glob(pattern)
                actual_path = found[0] if found else out_path

                if os.path.exists(actual_path):
                    sz = os.path.getsize(actual_path) / (1024 * 1024)
                    if sz > 0.3:
                        downloaded.append(actual_path)
                        self.progress.emit(f"    ✅ {sz:.1f}MB 다운로드 완료")
                    else:
                        self.progress.emit(f"    ⚠ 파일 크기 미달 ({sz:.1f}MB)")
                else:
                    self.progress.emit(f"    ⚠ 파일 생성 실패")

            except Exception as e:
                self.progress.emit(f"    ⚠ 다운로드 실패: {e}")

        self.progress.emit(f"  📱 틱톡/도우인 영상 {len(downloaded)}개 확보")
        return downloaded

    def _search_youtube_videos(self) -> list:
        """유튜브에서 제품 리뷰/언박싱 영상을 검색하고 다운로드한다."""
        try:
            import yt_dlp
        except ImportError:
            self.progress.emit("  ⚠ yt-dlp 미설치 — 유튜브 검색 건너뜀")
            return []

        from affiliate_system.config import WORK_DIR
        from affiliate_system.utils import ensure_dir
        import uuid

        out_dir = ensure_dir(WORK_DIR / "extracted_videos")
        downloaded = []

        try:
            # 유튜브 검색 (제품명 + 리뷰)
            search_query = f"ytsearch{self.video_count * 2}:{self.keyword} 리뷰"
            self.progress.emit(f"  검색: '{self.keyword} 리뷰'")

            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                results = ydl.extract_info(search_query, download=False)
                entries = results.get('entries', [])

            self.progress.emit(f"  {len(entries)}개 영상 발견")

            if not entries:
                self.progress.emit("  ⚠ 유튜브 검색 결과 없음")
                return []

            # 쇼츠 길이에 적합한 영상 우선 (60초~600초)
            # 너무 짧거나 너무 긴 영상 제외
            suitable = []
            for e in entries:
                dur = e.get('duration', 0) or 0
                title = e.get('title', '')
                vid_id = e.get('id') or e.get('url', '')
                if vid_id and vid_id.startswith('http'):
                    # URL에서 ID 추출
                    if 'v=' in vid_id:
                        vid_id = vid_id.split('v=')[-1].split('&')[0]
                suitable.append({
                    'id': vid_id,
                    'title': title,
                    'duration': dur,
                    'url': f"https://www.youtube.com/watch?v={vid_id}",
                })

            # 최대 video_count개 다운로드
            to_dl = suitable[:self.video_count]
            self.progress.emit(f"  ⬇ {len(to_dl)}개 영상 다운로드 시작...")

            for i, vid in enumerate(to_dl, 1):
                title = vid['title'][:50]
                dur = vid['duration']
                self.progress.emit(f"  [{i}/{len(to_dl)}] {title} ({dur}s)")

                try:
                    safe_name = "".join(
                        c for c in vid['title'] if c.isalnum() or c in " _-가-힣"
                    )[:40]
                    out_path = str(
                        out_dir / f"yt_{safe_name}_{uuid.uuid4().hex[:6]}.mp4"
                    )

                    dl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'outtmpl': out_path.replace('.mp4', '.%(ext)s'),
                        'format': 'best[height<=1080][ext=mp4]/best[ext=mp4]/best',
                        'merge_output_format': 'mp4',
                        # 최대 5분만 다운로드 (쇼츠 소스로 충분)
                        'download_ranges': yt_dlp.utils.download_range_func(
                            None, [(0, min(dur, 300))] if dur > 300 else None
                        ) if dur > 300 else None,
                    }

                    with yt_dlp.YoutubeDL(dl_opts) as ydl:
                        ydl.download([vid['url']])

                    # 다운로드된 파일 찾기 (확장자가 다를 수 있음)
                    import glob as g
                    pattern = out_path.replace('.mp4', '.*')
                    found = g.glob(pattern)
                    actual_path = found[0] if found else out_path

                    if os.path.exists(actual_path):
                        sz = os.path.getsize(actual_path) / (1024 * 1024)
                        if sz > 0.5:  # 500KB 이상
                            downloaded.append(actual_path)
                            self.progress.emit(f"    ✅ {sz:.1f}MB 다운로드 완료")
                        else:
                            self.progress.emit(f"    ⚠ 파일 크기 미달 ({sz:.1f}MB)")
                    else:
                        self.progress.emit(f"    ⚠ 파일 생성 실패")

                except Exception as e:
                    self.progress.emit(f"    ⚠ 다운로드 실패: {e}")

        except Exception as e:
            self.progress.emit(f"  ⚠ 유튜브 검색 실패: {e}")

        self.progress.emit(f"  📹 유튜브 영상 {len(downloaded)}개 확보")
        return downloaded

    def _search_google_images(self) -> list:
        """구글에서 실제 제품 이미지를 검색하고 다운로드한다."""
        try:
            from curl_cffi import requests as cf_requests
        except ImportError:
            self.progress.emit("  ⚠ curl_cffi 미설치 — 이미지 검색 건너뜀")
            return []

        import re
        import urllib.parse
        import requests
        import uuid
        from affiliate_system.config import WORK_DIR
        from affiliate_system.utils import ensure_dir

        out_dir = ensure_dir(WORK_DIR / "product_images")
        downloaded = []

        try:
            # 구글 이미지 검색
            search_url = (
                f"https://www.google.com/search?"
                f"q={urllib.parse.quote(self.keyword)}&tbm=isch&hl=ko"
            )
            session = cf_requests.Session(impersonate="chrome131")
            resp = session.get(search_url, timeout=15)

            if resp.status_code != 200:
                self.progress.emit(f"  ⚠ 구글 응답 {resp.status_code}")
                return []

            # HTML 내 script 태그에서 이미지 URL 추출
            # 패턴: ["https://...jpg",width,height]
            img_urls = re.findall(
                r'\["(https?://[^"]+\.(?:jpg|jpeg|png|webp))",(\d+),(\d+)\]',
                resp.text
            )

            # 고해상도(300px+) 이미지만, 중복 제거
            seen = set()
            unique_imgs = []
            for url, w, h in img_urls:
                if int(w) >= 300 and url not in seen and 'encrypted' not in url:
                    seen.add(url)
                    unique_imgs.append((url, int(w), int(h)))

            self.progress.emit(f"  {len(unique_imgs)}개 제품 이미지 발견")

            # 최대 image_count개 다운로드
            for i, (img_url, w, h) in enumerate(unique_imgs[:self.image_count], 1):
                try:
                    self.progress.emit(f"  [{i}] {w}x{h} 이미지 다운로드...")
                    img_resp = requests.get(
                        img_url, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.google.com/"}
                    )
                    if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                        ext = "jpg"
                        if ".png" in img_url:
                            ext = "png"
                        elif ".webp" in img_url:
                            ext = "webp"
                        fname = f"product_{uuid.uuid4().hex[:8]}.{ext}"
                        out_path = str(out_dir / fname)
                        with open(out_path, "wb") as f:
                            f.write(img_resp.content)
                        sz = len(img_resp.content) / 1024
                        downloaded.append(out_path)
                        self.progress.emit(f"    ✅ {w}x{h} ({sz:.0f}KB)")
                except Exception as e:
                    self.progress.emit(f"    ⚠ 이미지 실패: {e}")

        except Exception as e:
            self.progress.emit(f"  ⚠ 구글 이미지 검색 실패: {e}")

        return downloaded


# ── 파이프라인 워커 ──
class ShortsPipelineWorker(QThread):
    """쇼핑쇼츠 파이프라인 백그라운드 실행"""
    progress = pyqtSignal(str)
    step_update = pyqtSignal(int)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, product_name, video_path, product_info, voice, rate,
                 bgm_genre="lofi", bgm_enabled=True, keep_original_audio=False,
                 script_mode="direct", anti_duplicate=True):
        super().__init__()
        self.product_name = product_name
        self.video_path = video_path
        self.product_info = product_info
        self.voice = voice
        self.rate = rate
        self.bgm_genre = bgm_genre
        self.bgm_enabled = bgm_enabled
        self.keep_original_audio = keep_original_audio
        self.script_mode = script_mode          # 대본 모드 (direct/story/bestof)
        self.anti_duplicate = anti_duplicate    # 중복도 ZERO 편집

    def run(self):
        try:
            self.progress.emit("파이프라인 초기화 중...")
            self.step_update.emit(5)

            import uuid
            from affiliate_system.shopping_shorts_factory import (
                ShoppingScriptGenerator, EdgeTTSWithSRT, ShoppingFFmpegComposer,
            )
            from affiliate_system.config import RENDER_OUTPUT_DIR, WORK_DIR
            from affiliate_system.utils import ensure_dir

            campaign_id = uuid.uuid4().hex[:8]
            campaign_dir = ensure_dir(WORK_DIR / f"shorts_{campaign_id}")

            # Step 1: 소스 영상
            self.progress.emit("[1/4] 소스 영상 확인...")
            self.step_update.emit(15)
            if not self.video_path or not os.path.exists(self.video_path):
                self.error.emit("소스 영상 파일이 없습니다")
                return
            sz = os.path.getsize(self.video_path) / (1024 * 1024)
            self.progress.emit(f"  소스: {Path(self.video_path).name} ({sz:.1f}MB)")
            self.step_update.emit(20)

            # Step 2: AI 대본
            mode_label = {"direct": "직접홍보", "story": "간접홍보(썰)", "bestof": "베스트추천", "beforeafter": "비포/애프터", "pricecompare": "최저가vs최고가"}
            self.progress.emit(f"[2/4] AI 대본 생성 중 ({mode_label.get(self.script_mode, '직접')})...")
            self.step_update.emit(25)
            script_gen = ShoppingScriptGenerator()
            script = script_gen.generate(self.product_name, self.product_info, mode=self.script_mode)
            self.progress.emit(f"  훅: {script['hook']}")
            self.progress.emit(f"  대본: {len(script['script'])}문장")
            for i, line in enumerate(script['script']):
                self.progress.emit(f"    [{i+1}] {line}")
            self.step_update.emit(40)

            # Step 3: TTS + SRT
            self.progress.emit(f"[3/4] TTS 나레이션 생성 (배속: {self.rate})...")
            self.step_update.emit(45)
            tts_gen = EdgeTTSWithSRT(
                voice=self.voice or "ko-KR-SunHiNeural",
                rate=self.rate,
            )
            tts_result = tts_gen.generate(
                script_lines=script["script"],
                output_dir=str(campaign_dir),
                filename_prefix=f"tts_{campaign_id}",
            )
            self.progress.emit(
                f"  오디오: {Path(tts_result['audio_path']).name} "
                f"({tts_result['duration']:.1f}초, words={len(tts_result['word_timings'])})"
            )
            self.step_update.emit(65)

            # Step 4: FFmpeg 합성
            self.progress.emit("[4/4] FFmpeg 합성 중...")
            self.step_update.emit(70)
            output_dir = ensure_dir(RENDER_OUTPUT_DIR)
            output_path = str(output_dir / f"shorts_{campaign_id}.mp4")

            composer = ShoppingFFmpegComposer(anti_duplicate=self.anti_duplicate)
            self.progress.emit(f"  인코더: {composer.encoder}")
            self.progress.emit(
                f"  BGM: {self.bgm_genre if self.bgm_enabled else '없음'} | "
                f"원본오디오: {'유지' if self.keep_original_audio else '제거'} | "
                f"중복도ZERO: {'✅' if self.anti_duplicate else '❌'}"
            )
            final_video = composer.compose(
                source_video=self.video_path,
                tts_audio=tts_result["audio_path"],
                srt_file=tts_result["srt_path"],
                output_path=output_path,
                max_duration=59.0,
                bgm_enabled=self.bgm_enabled,
                bgm_genre=self.bgm_genre,
                keep_original_audio=self.keep_original_audio,
            )
            self.step_update.emit(95)

            if final_video and os.path.exists(final_video):
                sz = os.path.getsize(final_video) / (1024 * 1024)
                self.progress.emit(f"  ✅ 완성: {Path(final_video).name} ({sz:.1f}MB)")
                self.step_update.emit(100)
                self.finished.emit({
                    "video_path": final_video,
                    "srt_path": tts_result["srt_path"],
                    "audio_path": tts_result["audio_path"],
                    "script": script,
                    "duration": tts_result["duration"],
                    "campaign_id": campaign_id,
                    "campaign_dir": str(campaign_dir),
                })
            else:
                self.error.emit("FFmpeg 합성 실패")

        except Exception as e:
            import traceback
            self.error.emit(f"에러: {e}\n{traceback.format_exc()}")


class ShoppingShortsTab(QWidget):
    """쇼핑쇼츠 팩토리 GUI 탭"""

    def __init__(self):
        super().__init__()
        self._worker = None
        self._dl_worker = None
        self._last_result = None
        self._coupang_link = ""  # 쿠팡 파트너스 링크 (상품 탐색 탭에서 수신)
        self._init_ui()
        # 시작 시 라이브러리 로드
        self._refresh_library()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ── 헤더 ──
        header = QLabel("🎬 쇼핑쇼츠 팩토리")
        header.setStyleSheet(
            "font-size: 22px; font-weight: 900; color: #f9fafb; "
            "background: transparent; padding: 0; margin-bottom: 2px;"
        )
        sub = QLabel("소스영상 다운로드 → AI대본 → TTS나레이션 → 자막 → YouTube 쇼츠")
        sub.setStyleSheet("font-size: 12px; color: #6b7280; background: transparent;")
        layout.addWidget(header)
        layout.addWidget(sub)

        # ── 메인 스플리터 (왼쪽: 라이브러리 / 오른쪽: 설정+로그) ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ===== 왼쪽: 소스영상 라이브러리 =====
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        # URL 다운로드
        dl_group = QGroupBox("영상 다운로드")
        dl_group.setStyleSheet(self._group_style())
        dl_layout = QVBoxLayout(dl_group)
        dl_layout.setSpacing(8)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("도우인/틱톡/유튜브 URL 붙여넣기")
        self.url_input.setStyleSheet(self._input_style())
        url_row.addWidget(self.url_input, 1)
        self.btn_download = QPushButton("⬇ 다운로드")
        self.btn_download.setFixedSize(100, 36)
        self.btn_download.setStyleSheet(self._btn_accent_style())
        self.btn_download.clicked.connect(self._start_download)
        url_row.addWidget(self.btn_download)
        dl_layout.addLayout(url_row)

        # 도우인 검색 + AI 자동검색 + 쿠팡 간편링크
        douyin_row = QHBoxLayout()
        douyin_row.setSpacing(6)

        self.btn_douyin_search = QPushButton("🔍 도우인 검색")
        self.btn_douyin_search.setFixedHeight(30)
        self.btn_douyin_search.setMinimumWidth(100)
        self.btn_douyin_search.setStyleSheet("""
            QPushButton {
                background: #1a1f35; color: #f59e0b;
                border: 1px solid #f59e0b; border-radius: 6px;
                font-weight: 700; font-size: 11px; padding: 0 10px;
            }
            QPushButton:hover { background: #2d2810; }
        """)
        self.btn_douyin_search.setToolTip("상품명으로 도우인에서 소스영상 검색 (브라우저)")
        self.btn_douyin_search.clicked.connect(self._open_douyin_search)
        douyin_row.addWidget(self.btn_douyin_search)

        # AI 자동검색 버튼 — Claude가 크롬으로 직접 영상을 찾아줌
        self.btn_ai_find = QPushButton("🤖 AI 자동검색")
        self.btn_ai_find.setFixedHeight(30)
        self.btn_ai_find.setMinimumWidth(110)
        self.btn_ai_find.setStyleSheet("""
            QPushButton {
                background: #1a1f35; color: #a78bfa;
                border: 1px solid #a78bfa; border-radius: 6px;
                font-weight: 700; font-size: 11px; padding: 0 10px;
            }
            QPushButton:hover { background: #1e1040; border-color: #c4b5fd; }
        """)
        self.btn_ai_find.setToolTip(
            "Claude AI가 크롬 브라우저에서 직접 도우인/틱톡 영상을 검색하여\n"
            "소스영상 URL을 자동으로 찾아줍니다"
        )
        self.btn_ai_find.clicked.connect(self._request_ai_find)
        douyin_row.addWidget(self.btn_ai_find)

        # 제품 실제 영상 자동 수집 버튼 — 틱톡/도우인 + 유튜브 + 구글이미지
        self.btn_stock_video = QPushButton("🎯 실제영상 수집")
        self.btn_stock_video.setFixedHeight(30)
        self.btn_stock_video.setMinimumWidth(115)
        self.btn_stock_video.setStyleSheet("""
            QPushButton {
                background: #1a1f35; color: #34d399;
                border: 1px solid #34d399; border-radius: 6px;
                font-weight: 700; font-size: 11px; padding: 0 10px;
            }
            QPushButton:hover { background: #0d2818; border-color: #6ee7b7; }
        """)
        self.btn_stock_video.setToolTip(
            "상품명으로 실제 제품 영상/이미지 자동 수집\n"
            "① 틱톡/도우인 쇼핑영상 ② 유튜브 리뷰 ③ 구글 제품사진\n"
            "정확한 제품의 실제 콘텐츠만 수집합니다"
        )
        self.btn_stock_video.clicked.connect(self._search_stock_videos)
        douyin_row.addWidget(self.btn_stock_video)

        # 쿠팡 간편 링크 버튼
        self.btn_simple_link = QPushButton("🔗 쿠팡 간편링크")
        self.btn_simple_link.setFixedHeight(30)
        self.btn_simple_link.setMinimumWidth(115)
        self.btn_simple_link.setStyleSheet("""
            QPushButton {
                background: #1a1f35; color: #ef4444;
                border: 1px solid #ef4444; border-radius: 6px;
                font-weight: 700; font-size: 11px; padding: 0 10px;
            }
            QPushButton:hover { background: #2d1010; }
        """)
        self.btn_simple_link.setToolTip(
            "상품명으로 쿠팡 검색 URL → 파트너스 링크 자동 생성\n"
            "(직접 상품 대신 검색 페이지 연결 — 품절 리스크 없음)"
        )
        self.btn_simple_link.clicked.connect(self._generate_simple_link)
        douyin_row.addWidget(self.btn_simple_link)

        platforms = QLabel("틱톡 · 도우인 · 유튜브 · 구글이미지 (yt-dlp + curl_cffi 자동 수집)")
        platforms.setStyleSheet("color: #4b5563; font-size: 10px; background: transparent;")
        platforms.setWordWrap(True)
        douyin_row.addWidget(platforms, 1)
        dl_layout.addLayout(douyin_row)
        left_layout.addWidget(dl_group)

        # 소스영상 라이브러리
        lib_label = QLabel("📁 소스영상 라이브러리")
        lib_label.setStyleSheet(
            "color: #e5e7eb; font-weight: 700; font-size: 13px; "
            "background: transparent; margin-top: 4px;"
        )
        left_layout.addWidget(lib_label)

        self.video_list = QListWidget()
        self.video_list.setStyleSheet("""
            QListWidget {
                background: #111827; color: #e5e7eb;
                border: 1px solid #1f2937; border-radius: 8px;
                font-size: 12px; padding: 4px;
            }
            QListWidget::item {
                padding: 8px 10px; border-radius: 6px;
                margin: 2px 0;
            }
            QListWidget::item:selected {
                background: #1e293b; color: #f9fafb;
                border: 1px solid #6366f1;
            }
            QListWidget::item:hover:!selected {
                background: #1a1f35;
            }
        """)
        self.video_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.video_list.itemClicked.connect(self._on_library_select)
        left_layout.addWidget(self.video_list, 1)

        # 라이브러리 버튼
        lib_btns = QHBoxLayout()
        self.btn_refresh = QPushButton("🔄 새로고침")
        self.btn_refresh.setStyleSheet(self._btn_secondary_style())
        self.btn_refresh.clicked.connect(self._refresh_library)
        lib_btns.addWidget(self.btn_refresh)

        self.btn_browse = QPushButton("📂 파일 추가")
        self.btn_browse.setStyleSheet(self._btn_secondary_style())
        self.btn_browse.clicked.connect(self._browse_video)
        lib_btns.addWidget(self.btn_browse)

        self.btn_open_folder = QPushButton("📁 폴더 열기")
        self.btn_open_folder.setStyleSheet(self._btn_secondary_style())
        self.btn_open_folder.clicked.connect(self._open_library_folder)
        lib_btns.addWidget(self.btn_open_folder)
        left_layout.addLayout(lib_btns)

        splitter.addWidget(left)

        # ===== 오른쪽: 설정 + 실행 + 로그 =====
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        # 상품 설정
        prod_group = QGroupBox("상품 설정")
        prod_group.setStyleSheet(self._group_style())
        pg = QVBoxLayout(prod_group)
        pg.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(self._make_label("상품명"))
        self.product_input = QLineEdit()
        self.product_input.setPlaceholderText("예: 베베숲 오리지널 물티슈 100매 6팩")
        self.product_input.setStyleSheet(self._input_style())
        row1.addWidget(self.product_input, 1)
        pg.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(self._make_label("상품정보"))
        self.info_input = QLineEdit()
        self.info_input.setPlaceholderText("99.9% 정제수, 무향, 캡형, 쿠팡 로켓배송 (선택)")
        self.info_input.setStyleSheet(self._input_style())
        row2.addWidget(self.info_input, 1)
        pg.addLayout(row2)

        # 선택된 영상 표시
        row3 = QHBoxLayout()
        row3.addWidget(self._make_label("소스영상"))
        self.video_input = QLineEdit()
        self.video_input.setPlaceholderText("← 왼쪽 라이브러리에서 선택 또는 파일 추가")
        self.video_input.setReadOnly(True)
        self.video_input.setStyleSheet(self._input_style() + """
            QLineEdit { background: #0d1117; }
        """)
        row3.addWidget(self.video_input, 1)
        pg.addLayout(row3)

        # 옵션 행 1: 음성 + 배속
        row4 = QHBoxLayout()
        row4.addWidget(self._make_label("음성"))
        self.voice_combo = QComboBox()
        self.voice_combo.addItems(["여성 (SunHi)", "남성 (InJoon)"])
        self.voice_combo.setStyleSheet(self._input_style())
        self.voice_combo.setFixedWidth(150)
        row4.addWidget(self.voice_combo)
        row4.addSpacing(16)
        row4.addWidget(self._make_label("배속"))
        self.rate_combo = QComboBox()
        self.rate_combo.addItems(["+0%", "+5%", "+10%", "+15%", "+20%", "+25%"])
        self.rate_combo.setCurrentIndex(4)  # +20% 기본 (1.2배속, 레퍼런스 영상 설정)
        self.rate_combo.setStyleSheet(self._input_style())
        self.rate_combo.setFixedWidth(90)
        row4.addWidget(self.rate_combo)
        row4.addStretch()
        pg.addLayout(row4)

        # 옵션 행 2: 대본 모드 + BGM
        row5 = QHBoxLayout()
        row5.addWidget(self._make_label("대본"))
        self.script_mode_combo = QComboBox()
        self.script_mode_combo.addItems([
            "📢 직접 홍보 (상품 리뷰)",
            "🎭 간접 홍보 (썰/꿀팁)",
            "🏆 베스트 추천 (TOP N)",
            "🔄 비포/애프터 비교",
            "💰 최저가 vs 최고가",
        ])
        self.script_mode_combo.setStyleSheet(self._input_style())
        self.script_mode_combo.setFixedWidth(200)
        self.script_mode_combo.setToolTip(
            "직접: 상품 리뷰 스타일\n"
            "간접: 썰/꿀팁으로 자연스럽게 (알고리즘 최적화)\n"
            "베스트: 추천/비교 콘텐츠\n"
            "비포/애프터: 사용 전/후 극적 비교 (4탄)\n"
            "최저가vs최고가: 가격 비교 충격 (3탄)"
        )
        row5.addWidget(self.script_mode_combo)
        row5.addStretch()
        pg.addLayout(row5)

        # 옵션 행 3: BGM + 중복도 편집
        row6 = QHBoxLayout()
        row6.addWidget(self._make_label("BGM"))
        self.bgm_combo = QComboBox()
        self.bgm_combo.addItems(["Lo-Fi 힙합", "Upbeat 팝", "Chill 앰비언트", "없음"])
        self.bgm_combo.setStyleSheet(self._input_style())
        self.bgm_combo.setFixedWidth(150)
        row6.addWidget(self.bgm_combo)
        row6.addSpacing(16)
        self.bgm_check = QCheckBox("원본 오디오 유지")
        self.bgm_check.setStyleSheet("color: #9ca3af; font-size: 12px;")
        row6.addWidget(self.bgm_check)
        row6.addSpacing(16)
        self.anti_dup_check = QCheckBox("중복도ZERO 편집")
        self.anti_dup_check.setChecked(True)  # 기본 활성화
        self.anti_dup_check.setStyleSheet("color: #f59e0b; font-size: 12px; font-weight: 700;")
        self.anti_dup_check.setToolTip(
            "미세확대 + 미러링 + 색보정으로 중복도 제로\n"
            "(튜브렌즈 3탄: 확대/축소, 미러링, 색보정 자동 적용)"
        )
        row6.addWidget(self.anti_dup_check)
        row6.addStretch()
        pg.addLayout(row6)

        right_layout.addWidget(prod_group)

        # 실행 버튼
        btn_row = QHBoxLayout()
        self.btn_generate = QPushButton("🚀 쇼츠 생성 시작")
        self.btn_generate.setFixedHeight(48)
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6366f1, stop:1 #8b5cf6);
                color: white; border: none; border-radius: 12px;
                font-weight: 800; font-size: 15px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c7ff7, stop:1 #a78bfa);
            }
            QPushButton:disabled { background: #374151; color: #6b7280; }
        """)
        self.btn_generate.clicked.connect(self._start_generation)
        btn_row.addWidget(self.btn_generate)

        self.btn_open = QPushButton("📁 결과 열기")
        self.btn_open.setFixedHeight(48)
        self.btn_open.setFixedWidth(120)
        self.btn_open.setEnabled(False)
        self.btn_open.setStyleSheet(self._btn_secondary_style() + """
            QPushButton { font-size: 13px; font-weight: 700; border-radius: 12px; }
        """)
        self.btn_open.clicked.connect(self._open_result)
        btn_row.addWidget(self.btn_open)
        right_layout.addLayout(btn_row)

        # 프로그레스
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { background: #1f2937; border: none; border-radius: 3px; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #6366f1, stop:1 #a78bfa);
                border-radius: 3px;
            }
        """)
        right_layout.addWidget(self.progress_bar)

        # 로그
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background: #0d1117; color: #c9d1d9;
                border: 1px solid #1f2937; border-radius: 8px;
                font-family: 'Consolas', 'D2Coding', monospace;
                font-size: 12px; padding: 10px;
            }
        """)
        self.log_output.setPlaceholderText(
            "사용법:\n"
            "1. 도우인/틱톡 URL 붙여넣고 ⬇ 다운로드\n"
            "2. 소스영상 라이브러리에서 영상 선택\n"
            "3. 상품명 입력\n"
            "4. 🚀 쇼츠 생성 시작\n"
            "5. AI대본 → TTS → 자막 → 영상합성 자동 완료"
        )
        right_layout.addWidget(self.log_output, 1)

        splitter.addWidget(right)
        splitter.setSizes([320, 580])  # 왼쪽 좁게, 오른쪽 넓게
        layout.addWidget(splitter, 1)

    # ── 스타일 헬퍼 ──
    def _make_label(self, text):
        lbl = QLabel(text)
        lbl.setFixedWidth(65)
        lbl.setStyleSheet(
            "color: #9ca3af; font-weight: 700; font-size: 13px; background: transparent;"
        )
        return lbl

    def _group_style(self):
        return """
            QGroupBox {
                font-weight: 700; font-size: 13px; color: #e5e7eb;
                border: 1px solid #1f2937; border-radius: 10px;
                padding: 18px 14px 14px 14px; margin-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 14px;
                padding: 0 6px; color: #818cf8;
            }
        """

    def _input_style(self):
        return """
            QLineEdit, QComboBox {
                background: #111827; color: #f9fafb;
                border: 1px solid #374151; border-radius: 8px;
                padding: 8px 12px; font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus { border-color: #6366f1; }
        """

    def _btn_secondary_style(self):
        return """
            QPushButton {
                background: #1f2937; color: #e5e7eb;
                border: 1px solid #374151; border-radius: 8px;
                font-weight: 600; font-size: 12px; padding: 6px 12px;
            }
            QPushButton:hover { background: #374151; }
            QPushButton:disabled { color: #4b5563; }
        """

    def _btn_accent_style(self):
        return """
            QPushButton {
                background: #4f46e5; color: white;
                border: none; border-radius: 8px;
                font-weight: 700; font-size: 13px;
            }
            QPushButton:hover { background: #6366f1; }
            QPushButton:disabled { background: #374151; color: #6b7280; }
        """

    # ── 라이브러리 ──
    def _get_library_dir(self) -> Path:
        """소스영상 저장 디렉토리"""
        from affiliate_system.config import WORK_DIR
        d = WORK_DIR / "extracted_videos"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _refresh_library(self):
        """소스영상 라이브러리 새로고침"""
        self.video_list.clear()
        lib_dir = self._get_library_dir()

        # renders 폴더의 완성영상도 포함
        from affiliate_system.config import RENDER_OUTPUT_DIR

        videos = []
        # 소스영상 (다운로드한 것)
        for ext in ('*.mp4', '*.avi', '*.mov', '*.mkv', '*.webm'):
            videos.extend(lib_dir.glob(ext))
        # 완성영상
        if RENDER_OUTPUT_DIR.exists():
            for ext in ('*.mp4',):
                videos.extend(RENDER_OUTPUT_DIR.glob(ext))

        # 수정 시간순 정렬 (최신 먼저)
        videos.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        for vf in videos:
            try:
                sz = vf.stat().st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(vf.stat().st_mtime)
                # 소스영상 vs 완성영상 구분
                if "renders" in str(vf):
                    prefix = "🎬"
                    category = "완성"
                else:
                    prefix = "📹"
                    category = "소스"

                label = f"{prefix} [{category}] {vf.name}  ({sz:.1f}MB · {mtime:%m/%d %H:%M})"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, str(vf))
                # 완성영상은 살짝 다른 색
                if category == "완성":
                    item.setForeground(QColor("#a78bfa"))
                self.video_list.addItem(item)
            except Exception:
                continue

        if not videos:
            item = QListWidgetItem("  (영상 없음 — URL을 붙여넣고 다운로드하세요)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#4b5563"))
            self.video_list.addItem(item)

    def _on_library_select(self, item: QListWidgetItem):
        """라이브러리에서 영상 선택"""
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            self.video_input.setText(path)

    def _open_library_folder(self):
        """소스영상 폴더 열기"""
        lib_dir = self._get_library_dir()
        os.startfile(str(lib_dir))

    # ── 다운로드 ──
    def _start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "입력 오류", "영상 URL을 입력하세요.")
            return

        self.btn_download.setEnabled(False)
        self.btn_download.setText("⏳ ...")
        self._log(f"━━━ 영상 다운로드 ━━━")

        self._dl_worker = VideoDownloadWorker(url)
        self._dl_worker.progress.connect(self._on_progress)
        self._dl_worker.finished.connect(self._on_download_done)
        self._dl_worker.error.connect(self._on_download_error)
        self._dl_worker.start()

    @pyqtSlot(str)
    def _on_download_done(self, path):
        self.btn_download.setEnabled(True)
        self.btn_download.setText("⬇ 다운로드")
        self.url_input.clear()
        self.video_input.setText(path)
        self._refresh_library()
        # 리스트에서 방금 다운받은 항목 선택
        for i in range(self.video_list.count()):
            item = self.video_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self.video_list.setCurrentItem(item)
                break

    @pyqtSlot(str)
    def _on_download_error(self, msg):
        self.btn_download.setEnabled(True)
        self.btn_download.setText("⬇ 다운로드")
        self._log(f"❌ {msg}")

    # ── 파일 추가 ──
    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "소스 영상 선택", "",
            "동영상 (*.mp4 *.avi *.mov *.mkv *.webm);;모든 파일 (*)"
        )
        if path:
            self.video_input.setText(path)

    # ── 쇼츠 생성 ──
    def _start_generation(self):
        product = self.product_input.text().strip()
        video = self.video_input.text().strip()

        if not product:
            QMessageBox.warning(self, "입력 오류", "상품명을 입력하세요.")
            return
        if not video or not os.path.exists(video):
            QMessageBox.warning(self, "입력 오류",
                                "소스 영상을 선택하세요.\n"
                                "왼쪽 라이브러리에서 선택하거나 URL로 다운로드하세요.")
            return

        voice_map = {0: "ko-KR-SunHiNeural", 1: "ko-KR-InJoonNeural"}
        voice = voice_map.get(self.voice_combo.currentIndex(), "ko-KR-SunHiNeural")
        rate = self.rate_combo.currentText()
        info = self.info_input.text().strip()

        # BGM 설정
        bgm_idx = self.bgm_combo.currentIndex()
        bgm_map = {0: "lofi", 1: "upbeat", 2: "chill", 3: None}
        bgm_genre = bgm_map.get(bgm_idx, "lofi")
        bgm_enabled = bgm_genre is not None
        keep_orig = self.bgm_check.isChecked()

        # 대본 모드
        script_mode_map = {0: "direct", 1: "story", 2: "bestof", 3: "beforeafter", 4: "pricecompare"}
        script_mode = script_mode_map.get(self.script_mode_combo.currentIndex(), "direct")
        script_mode_label = self.script_mode_combo.currentText()

        # 중복도 ZERO 편집
        anti_duplicate = self.anti_dup_check.isChecked()

        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.btn_generate.setEnabled(False)
        self.btn_generate.setText("⏳ 생성 중...")
        self.btn_open.setEnabled(False)
        self._log(f"━━━ 쇼핑쇼츠 생성 시작 ━━━")
        self._log(f"상품: {product}")
        self._log(f"영상: {Path(video).name}")
        self._log(f"음성: {voice} | 배속: {rate}")
        self._log(f"대본: {script_mode_label}")
        self._log(f"BGM: {bgm_genre or '없음'} | 원본오디오: {'유지' if keep_orig else '제거'}")
        self._log(f"중복도ZERO: {'✅ 활성' if anti_duplicate else '❌ 비활성'}")
        self._log("")

        self._worker = ShortsPipelineWorker(
            product_name=product, video_path=video,
            product_info=info, voice=voice, rate=rate,
            bgm_genre=bgm_genre or "lofi",
            bgm_enabled=bgm_enabled,
            keep_original_audio=keep_orig,
            script_mode=script_mode,
            anti_duplicate=anti_duplicate,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.step_update.connect(self._on_step)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _open_result(self):
        if self._last_result and self._last_result.get("video_path"):
            path = self._last_result["video_path"]
            if os.path.exists(path):
                os.startfile(path)

    # ── 시그널 핸들러 ──
    @pyqtSlot(str)
    def _on_progress(self, msg):
        self._log(msg)

    @pyqtSlot(int)
    def _on_step(self, val):
        self.progress_bar.setValue(val)

    @pyqtSlot(dict)
    def _on_finished(self, result):
        self._last_result = result
        self._log("")
        self._log(f"━━━ 쇼핑쇼츠 완성! ━━━")
        self._log(f"📹 {result.get('video_path', '')}")
        self.btn_generate.setEnabled(True)
        self.btn_generate.setText("🚀 쇼츠 생성 시작")
        self.btn_open.setEnabled(True)
        self.progress_bar.setValue(100)
        # 라이브러리에 완성영상 반영
        self._refresh_library()

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._log(f"\n❌ {msg}")
        self.btn_generate.setEnabled(True)
        self.btn_generate.setText("🚀 쇼츠 생성 시작")
        self.progress_bar.setValue(0)

    def _log(self, msg):
        self.log_output.append(msg)
        sb = self.log_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── 쿠팡 간편 링크 생성 (4탄 핵심) ──
    def _generate_simple_link(self):
        """쿠팡 간편 링크 생성 — 검색 결과 페이지를 파트너스 링크로 변환

        4탄 핵심 전략:
        - 직접 상품 URL 대신 검색 URL 사용
        - 품절 리스크 없음 (검색 결과에서 아무 상품이나 구매해도 수수료)
        - 24시간 쿠키로 수수료 범위 넓음
        """
        keyword = self.product_input.text().strip()
        if not keyword:
            QMessageBox.information(
                self, "쿠팡 간편 링크",
                "상품명을 먼저 입력하세요.\n"
                "상품 탐색 탭에서 상품을 선택하면 자동 입력됩니다."
            )
            return

        self._log(f"🔗 쿠팡 간편 링크 생성 중: '{keyword}'...")
        try:
            from affiliate_system.coupang_scraper import CoupangScraper
            scraper = CoupangScraper()
            link = scraper.generate_simple_link(keyword)
            if link:
                self._coupang_link = link
                self._log(f"  ✅ 간편 링크 생성 완료!")
                self._log(f"  🔗 {link}")
                self._log(f"  → 검색 페이지 연결 (품절 리스크 없음)")
                # 클립보드에 복사
                try:
                    from PyQt6.QtWidgets import QApplication
                    clipboard = QApplication.clipboard()
                    clipboard.setText(link)
                    self._log(f"  📋 클립보드에 복사됨!")
                except Exception:
                    pass
            else:
                self._log(f"  ⚠ 간편 링크 생성 실패 (API 키 확인)")
                self._log(f"  → 수동: partners.coupang.com → 링크 생성 → 간편 링크 만들기")
        except Exception as e:
            self._log(f"  ❌ 오류: {e}")
        self._log("")

    # ── 제품 실제 영상/이미지 수집 ──
    def _search_stock_videos(self):
        """상품명으로 틱톡/도우인 + 유튜브 + 구글이미지에서 실제 제품 영상/사진을 수집한다.

        스톡영상이 아닌, 정확한 제품의 리뷰/쇼핑 영상과 실제 사진을 자동 수집.
        """
        keyword = self.product_input.text().strip()
        if not keyword:
            QMessageBox.information(
                self, "제품 영상 수집",
                "상품명을 먼저 입력하세요.\n"
                "상품 탐색 탭에서 상품을 선택하면 자동 입력됩니다."
            )
            return

        self.btn_stock_video.setEnabled(False)
        self.btn_stock_video.setText("⏳ 수집중...")
        self._log(f"━━━ 제품 실제 영상 수집 ━━━")

        self._stock_worker = ProductMediaWorker(keyword, video_count=3, image_count=5)
        self._stock_worker.progress.connect(self._on_progress)
        self._stock_worker.finished.connect(self._on_stock_done)
        self._stock_worker.error.connect(self._on_stock_error)
        self._stock_worker.start()

    @pyqtSlot(list)
    def _on_stock_done(self, paths: list):
        """제품 영상 수집 완료 처리"""
        self.btn_stock_video.setEnabled(True)
        self.btn_stock_video.setText("🎯 실제영상 수집")

        # 첫 번째 영상을 소스영상으로 자동 설정
        if paths:
            self.video_input.setText(paths[0])
        self._refresh_library()

        # 리스트에서 다운받은 첫 항목 선택
        if paths:
            for i in range(self.video_list.count()):
                item = self.video_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == paths[0]:
                    self.video_list.setCurrentItem(item)
                    break

        self._log(f"  📁 소스영상 라이브러리에 {len(paths)}개 추가됨")
        self._log(f"  💡 원하는 영상을 라이브러리에서 선택 후 🚀 쇼츠 생성")
        self._log("")

    @pyqtSlot(str)
    def _on_stock_error(self, msg: str):
        """제품 영상 수집 실패"""
        self.btn_stock_video.setEnabled(True)
        self.btn_stock_video.setText("🎯 실제영상 수집")
        self._log(f"  ❌ {msg}")
        self._log("")

    # ── 도우인 검색 ──
    def _open_douyin_search(self):
        """도우인에서 상품 키워드 검색 (브라우저 열기)

        레퍼런스 영상 워크플로우:
        1. 도우인에서 상품 관련 영상 검색
        2. 마음에 드는 영상 URL 복사
        3. 여기에 붙여넣고 다운로드
        """
        import webbrowser
        keyword = self.product_input.text().strip()
        if not keyword:
            QMessageBox.information(
                self, "도우인 검색",
                "상품명을 먼저 입력하세요.\n"
                "상품 탐색 탭에서 상품을 선택하면 자동 입력됩니다."
            )
            return

        # 도우인 검색 URL 생성 (중국어 키워드가 효과적)
        import urllib.parse
        search_url = f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}"
        webbrowser.open(search_url)

        self._log(f"🔍 도우인 검색: {keyword}")
        self._log(f"  → 브라우저에서 마음에 드는 영상 URL을 복사하세요")
        self._log(f"  → 복사한 URL을 위 입력란에 붙여넣고 ⬇ 다운로드")
        self._log("")

    def _request_ai_find(self):
        """AI(Claude)에게 도우인/틱톡 소스영상 검색을 요청한다.

        클립보드에 검색 요청 메시지를 복사하고,
        사용자가 Claude에게 전달하면 Claude가 크롬으로 직접 검색해줌.
        """
        keyword = self.product_input.text().strip()
        if not keyword:
            QMessageBox.information(
                self, "AI 자동검색",
                "상품명을 먼저 입력하세요.\n"
                "상품 탐색 탭에서 상품을 선택하면 자동 입력됩니다."
            )
            return

        # 클립보드에 Claude 요청 메시지 복사
        request_msg = (
            f"도우인에서 '{keyword}' 관련 쇼핑쇼츠 소스영상을 찾아서 "
            f"URL을 프로그램에 넣고 다운로드까지 해줘"
        )

        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(request_msg)

        self._log(f"🤖 AI 자동검색 요청: '{keyword}'")
        self._log(f"  → 클립보드에 Claude 요청 메시지가 복사되었습니다")
        self._log(f"  → Claude Code 채팅창에 붙여넣기(Ctrl+V) 하세요")
        self._log(f"  → Claude가 크롬에서 직접 영상을 찾아 다운로드합니다")
        self._log("")

        QMessageBox.information(
            self, "AI 자동검색",
            f"Claude 요청 메시지가 클립보드에 복사되었습니다.\n\n"
            f"Claude Code 채팅창에 Ctrl+V로 붙여넣기하면\n"
            f"Claude가 크롬에서 '{keyword}' 영상을 찾아줍니다."
        )

    # ── 외부 연동: 상품 탐색 탭에서 상품 정보 수신 ──
    def set_product_info(self, title: str, info: str = "", link: str = ""):
        """상품 탐색 탭에서 선택된 상품 정보를 자동 입력

        워크플로우:
        1. 상품 탐색 탭에서 쿠팡 상품 선택 → 여기로 자동 전환
        2. 상품명/정보 자동 입력
        3. 🔍 도우인 검색 버튼으로 소스영상 찾기
        4. URL 붙여넣기 → 다운로드 → 🚀 쇼츠 생성
        """
        self.product_input.setText(title)
        if info:
            self.info_input.setText(info)
        elif link:
            self.info_input.setText(f"쿠팡 로켓배송 | {link[:60]}")

        # 쿠팡 링크 저장 (나중에 업로드 시 사용)
        self._coupang_link = link

        self._log(f"━━━ 상품 정보 수신 ━━━")
        self._log(f"  상품: {title}")
        if link:
            self._log(f"  링크: {link[:80]}")
        self._log("")
        self._log("  📋 다음 단계:")
        self._log("  1️⃣ 📹 스톡영상 (원클릭 자동) 또는 🔍 도우인 검색")
        self._log("  2️⃣ 소스영상 라이브러리에서 영상 선택")
        self._log("  3️⃣ 🚀 쇼츠 생성 시작")
        self._log("")
