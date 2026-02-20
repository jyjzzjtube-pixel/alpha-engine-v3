"""
Affiliate Marketing System — Stealth Multi-Platform Uploader & DM Bot

YouTube Shorts (OAuth 2.0), Naver Blog (CDP Selenium), Instagram Reels (instagrapi)
인간화 딜레이 + 세션 캐싱 + 그레이스풀 에러 핸들링
"""

import json
import os
import random
import time
from pathlib import Path
from typing import Callable, Optional

from affiliate_system.config import (
    DRIVE_CLIENT_ID,
    DRIVE_CLIENT_SECRET,
    INSTAGRAM_USERNAME,
    INSTAGRAM_PASSWORD,
    NAVER_BLOG_ID,
    CDP_URL,
    HUMANIZER_DELAY_MIN,
    HUMANIZER_DELAY_MAX,
    INSTAGRAM_DM_BATCH,
    INSTAGRAM_DM_DELAY,
    RENDER_OUTPUT_DIR,
    PROJECT_DIR,
)
from affiliate_system.models import Campaign, Platform
from affiliate_system.utils import setup_logger, retry

__all__ = [
    "StealthUploader",
]

# ── Constants ──
_YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
_YT_TOKEN_PATH = Path(__file__).parent / "workspace" / "youtube_token.json"
_IG_SESSION_PATH = Path(__file__).parent / "workspace" / "ig_session.json"
_YT_OAUTH_PORT = 8091
_YT_CHUNK_SIZE = 1024 * 1024  # 1 MB


class StealthUploader:
    """멀티플랫폼 스텔스 업로더

    YouTube Shorts, Naver Blog, Instagram Reels 업로드 +
    Instagram DM 자동 응답 봇을 하나의 파이프라인으로 통합.
    """

    def __init__(self):
        self.logger = setup_logger("uploader")
        self._yt_service = None
        self._ig_client = None
        self._naver_driver = None

    # ================================================================
    #  YouTube — OAuth 2.0 + Resumable Upload
    # ================================================================

    def youtube_auth(self) -> bool:
        """YouTube Data API v3 OAuth 2.0 인증.

        토큰을 ``workspace/youtube_token.json`` 에 캐싱하여
        재인증 없이 재사용한다.

        Returns:
            ``True`` 인증 성공, ``False`` 실패.
        """
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            self.logger.error("YouTube 라이브러리 미설치 (google-api-python-client, google-auth-oauthlib)")
            return False

        creds = None

        # ── 캐싱된 토큰 로드 ──
        if _YT_TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_info(
                    json.loads(_YT_TOKEN_PATH.read_text(encoding="utf-8")),
                    _YT_SCOPES,
                )
            except Exception:
                self.logger.warning("기존 YouTube 토큰 파싱 실패, 재인증 진행")
                creds = None

        # ── 토큰 갱신 ──
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.logger.info("YouTube 토큰 갱신 완료")
            except Exception:
                self.logger.warning("YouTube 토큰 갱신 실패, 재인증 진행")
                creds = None

        # ── 신규 인증 ──
        if not creds or not creds.valid:
            if not DRIVE_CLIENT_ID or not DRIVE_CLIENT_SECRET:
                self.logger.error("YouTube OAuth Client ID/Secret 미설정")
                return False
            client_config = {
                "installed": {
                    "client_id": DRIVE_CLIENT_ID,
                    "client_secret": DRIVE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [f"http://localhost:{_YT_OAUTH_PORT}/"],
                }
            }
            try:
                flow = InstalledAppFlow.from_client_config(client_config, _YT_SCOPES)
                creds = flow.run_local_server(port=_YT_OAUTH_PORT, open_browser=True)
                self.logger.info("YouTube OAuth 인증 완료")
            except Exception as exc:
                self.logger.error("YouTube OAuth 인증 실패: %s", exc)
                return False

        # ── 토큰 저장 ──
        _YT_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _YT_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

        # ── 서비스 객체 빌드 ──
        try:
            self._yt_service = build("youtube", "v3", credentials=creds)
            self.logger.info("YouTube 서비스 초기화 성공")
            return True
        except Exception as exc:
            self.logger.error("YouTube 서비스 빌드 실패: %s", exc)
            return False

    @retry(max_attempts=2, delay=5.0)
    def youtube_upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        privacy: str = "private",
    ) -> dict:
        """YouTube Shorts 리줌어블 업로드.

        Args:
            video_path: 업로드할 동영상 파일 경로.
            title: 영상 제목 (최대 100자).
            description: 영상 설명 (어필리에이트 링크 포함).
            tags: 태그 리스트.
            privacy: ``"private"`` | ``"unlisted"`` | ``"public"``.

        Returns:
            ``{"ok": True, "video_id": ..., "url": ...}`` 또는
            ``{"ok": False, "reason": ...}``.
        """
        if not os.path.isfile(video_path):
            return {"ok": False, "reason": f"파일 없음: {video_path}"}

        # 인증 확인
        if self._yt_service is None:
            if not self.youtube_auth():
                return {"ok": False, "reason": "YouTube 인증 실패"}

        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError:
            return {"ok": False, "reason": "google-api-python-client 미설치"}

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags or [],
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
                "shorts": {"shortsEligibility": "eligible"},
            },
        }

        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=_YT_CHUNK_SIZE,
        )

        self.logger.info("YouTube 업로드 시작: %s", os.path.basename(video_path))

        try:
            request = self._yt_service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    self.logger.info("YouTube 업로드 진행: %d%%", pct)

            video_id = response.get("id", "")
            url = f"https://youtube.com/shorts/{video_id}"
            self.logger.info("YouTube 업로드 완료: %s", url)
            return {"ok": True, "video_id": video_id, "url": url}

        except Exception as exc:
            self.logger.error("YouTube 업로드 실패: %s", exc)
            return {"ok": False, "reason": str(exc)}

    # ================================================================
    #  Naver Blog — CDP Selenium
    # ================================================================

    def _get_naver_driver(self):
        """기존 Chrome 디버깅 세션(localhost:9222)에 연결."""
        if self._naver_driver is not None:
            try:
                # 세션 살아있는지 확인
                _ = self._naver_driver.title
                return self._naver_driver
            except Exception:
                self._naver_driver = None

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            self.logger.error("Selenium 미설치 (pip install selenium)")
            return None

        # CDP_URL 에서 호스트:포트 파싱
        host_port = CDP_URL.replace("http://", "").replace("https://", "")
        options = Options()
        options.add_experimental_option("debuggerAddress", host_port)

        try:
            driver = webdriver.Chrome(options=options)
            self.logger.info("Chrome CDP 세션 연결 성공 (%s)", host_port)
            self._naver_driver = driver
            return driver
        except Exception as exc:
            self.logger.error("Chrome CDP 연결 실패: %s", exc)
            return None

    @retry(max_attempts=2, delay=3.0)
    def naver_blog_post(
        self,
        title: str,
        content_html: str,
        images: Optional[list[str]] = None,
    ) -> dict:
        """네이버 블로그 글 작성 (CDP Selenium).

        Chrome 이 ``localhost:9222`` 디버깅 모드로 실행 중이어야 하며,
        네이버 로그인 상태여야 한다.

        Args:
            title: 블로그 글 제목 (SEO 최적화).
            content_html: 본문 HTML.
            images: 삽입할 이미지 파일 경로 리스트.

        Returns:
            ``{"ok": True, "post_url": ...}`` 또는
            ``{"ok": False, "reason": ...}``.
        """
        driver = self._get_naver_driver()
        if driver is None:
            return {"ok": False, "reason": "Chrome CDP 연결 불가"}

        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys
        except ImportError:
            return {"ok": False, "reason": "Selenium 미설치"}

        blog_id = NAVER_BLOG_ID
        editor_url = f"https://blog.naver.com/{blog_id}/postwrite"
        wait = WebDriverWait(driver, 20)

        try:
            # ── 에디터 페이지 이동 ──
            driver.get(editor_url)
            self.logger.info("네이버 블로그 에디터 이동: %s", editor_url)
            time.sleep(3)

            # ── SmartEditor iframe 전환 ──
            # 네이버 블로그 에디터는 iframe 안에 있음
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            editor_iframe = None
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                if "editor" in src.lower() or "smarteditor" in src.lower():
                    editor_iframe = iframe
                    break

            if editor_iframe:
                driver.switch_to.frame(editor_iframe)
                self.logger.debug("에디터 iframe 전환 완료")

            # ── 제목 입력 ──
            try:
                title_el = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "span.se-placeholder.__se_placeholder"))
                )
                title_el.click()
                time.sleep(0.5)

                active = driver.switch_to.active_element
                active.send_keys(title)
                self.logger.info("제목 입력 완료: %s", title[:30])
            except Exception:
                # 대체: title textarea
                try:
                    title_area = driver.find_element(By.CSS_SELECTOR, "textarea.se-title-textarea")
                    title_area.clear()
                    title_area.send_keys(title)
                except Exception:
                    self.logger.warning("제목 입력 요소를 찾을 수 없음, JavaScript 로 시도")
                    driver.execute_script(
                        "document.querySelector('[class*=\"title\"]').innerText = arguments[0];",
                        title,
                    )

            time.sleep(1)

            # ── 본문 입력 ──
            try:
                body_el = driver.find_element(By.CSS_SELECTOR, "div.se-component-content p.se-text-paragraph")
                body_el.click()
                time.sleep(0.5)

                active = driver.switch_to.active_element
                # HTML 을 텍스트로 변환하여 입력 (SmartEditor 제한)
                plain_text = content_html.replace("<br>", "\n").replace("<br/>", "\n")
                # 간단한 태그 제거
                import re
                plain_text = re.sub(r"<[^>]+>", "", plain_text)
                active.send_keys(plain_text)
                self.logger.info("본문 입력 완료 (%d자)", len(plain_text))
            except Exception:
                self.logger.warning("본문 직접 입력 실패, JavaScript 삽입 시도")
                driver.execute_script(
                    """
                    var editor = document.querySelector('[class*="content"]');
                    if (editor) editor.innerHTML = arguments[0];
                    """,
                    content_html,
                )

            # ── 이미지 업로드 ──
            if images:
                for img_path in images:
                    if not os.path.isfile(img_path):
                        self.logger.warning("이미지 파일 없음: %s", img_path)
                        continue
                    try:
                        # 이미지 추가 버튼 클릭
                        img_btn = driver.find_element(
                            By.CSS_SELECTOR, "button.se-image-toolbar-button"
                        )
                        img_btn.click()
                        time.sleep(1)

                        # 파일 input 에 경로 전달
                        file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                        file_input.send_keys(os.path.abspath(img_path))
                        self.logger.info("이미지 업로드: %s", os.path.basename(img_path))
                        time.sleep(3)
                    except Exception as img_exc:
                        self.logger.warning("이미지 업로드 실패 (%s): %s", img_path, img_exc)

            # ── iframe 복귀 ──
            driver.switch_to.default_content()

            # ── 발행 버튼 클릭 ──
            time.sleep(1)
            try:
                publish_btn = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button.publish_btn__Y4pat"))
                )
                publish_btn.click()
                self.logger.info("발행 버튼 클릭")
                time.sleep(2)

                # 발행 확인 다이얼로그
                confirm_btn = driver.find_element(
                    By.CSS_SELECTOR, "button.confirm_btn__WEaBq"
                )
                confirm_btn.click()
                self.logger.info("발행 확인 완료")
                time.sleep(3)
            except Exception:
                self.logger.warning("발행 버튼 자동 클릭 실패, JavaScript 발행 시도")
                driver.execute_script(
                    "document.querySelector('[class*=\"publish\"]')?.click();"
                )
                time.sleep(3)

            # ── 발행된 URL 확인 ──
            current_url = driver.current_url
            if blog_id in current_url and "/postwrite" not in current_url:
                post_url = current_url
            else:
                post_url = f"https://blog.naver.com/{blog_id}"

            self.logger.info("네이버 블로그 발행 완료: %s", post_url)
            return {"ok": True, "post_url": post_url}

        except Exception as exc:
            driver.switch_to.default_content()
            self.logger.error("네이버 블로그 작성 실패: %s", exc)
            return {"ok": False, "reason": str(exc)}

    # ================================================================
    #  Instagram — instagrapi
    # ================================================================

    def instagram_auth(self) -> bool:
        """instagrapi 로그인 + 세션 캐싱.

        세션 파일(``workspace/ig_session.json``)이 존재하면 재사용,
        없으면 신규 로그인 후 저장.

        Returns:
            ``True`` 인증 성공, ``False`` 실패.
        """
        try:
            from instagrapi import Client
        except ImportError:
            self.logger.error("instagrapi 미설치 (pip install instagrapi)")
            return False

        if self._ig_client is not None:
            try:
                self._ig_client.get_timeline_feed()
                return True
            except Exception:
                self._ig_client = None

        client = Client()

        # ── 세션 캐시 로드 ──
        _IG_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _IG_SESSION_PATH.exists():
            try:
                session_data = json.loads(
                    _IG_SESSION_PATH.read_text(encoding="utf-8")
                )
                client.set_settings(session_data)
                client.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                self._ig_client = client
                self.logger.info("Instagram 세션 캐시 로그인 성공")
                return True
            except Exception:
                self.logger.warning("Instagram 세션 캐시 만료, 재로그인 진행")

        # ── 신규 로그인 ──
        if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
            self.logger.error("Instagram 계정 정보 미설정")
            return False

        try:
            client.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            # 세션 저장
            _IG_SESSION_PATH.write_text(
                json.dumps(client.get_settings(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._ig_client = client
            self.logger.info("Instagram 로그인 성공: @%s", INSTAGRAM_USERNAME)
            return True
        except Exception as exc:
            self.logger.error("Instagram 로그인 실패: %s", exc)
            return False

    @retry(max_attempts=2, delay=10.0)
    def instagram_upload_reel(self, video_path: str, caption: str) -> dict:
        """Instagram Reel 업로드.

        Args:
            video_path: 업로드할 동영상 파일 경로.
            caption: 캡션 (해시태그 포함).

        Returns:
            ``{"ok": True, "media_id": ...}`` 또는
            ``{"ok": False, "reason": ...}``.
        """
        if not os.path.isfile(video_path):
            return {"ok": False, "reason": f"파일 없음: {video_path}"}

        if self._ig_client is None:
            if not self.instagram_auth():
                return {"ok": False, "reason": "Instagram 인증 실패"}

        try:
            self.logger.info("Instagram Reel 업로드 시작: %s", os.path.basename(video_path))
            media = self._ig_client.clip_upload(
                Path(video_path),
                caption=caption,
            )
            media_id = str(media.pk)

            # 세션 갱신 저장
            try:
                _IG_SESSION_PATH.write_text(
                    json.dumps(self._ig_client.get_settings(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

            self.logger.info("Instagram Reel 업로드 완료: media_id=%s", media_id)
            return {"ok": True, "media_id": media_id}

        except Exception as exc:
            self.logger.error("Instagram Reel 업로드 실패: %s", exc)
            return {"ok": False, "reason": str(exc)}

    def instagram_dm_bot(
        self,
        media_id: str,
        keywords: list[str],
        reply_text: str,
        batch_size: int = INSTAGRAM_DM_BATCH,
    ) -> int:
        """댓글 키워드 기반 Instagram DM 자동 응답 봇.

        지정한 게시물의 댓글을 모니터링하여, 키워드가 포함된
        댓글 작성자에게 DM 을 전송한다.

        기본 키워드 매핑:
        - ``"링크"`` -> 어필리에이트 링크 DM 전송
        - ``"상권"`` -> 프랜차이즈 상담 정보 DM 전송

        Args:
            media_id: 모니터링 대상 게시물 ID.
            keywords: 감지할 키워드 리스트 (예: ``["링크", "상권"]``).
            reply_text: DM 으로 보낼 텍스트.
            batch_size: 한 번에 처리할 DM 수 (기본 20).

        Returns:
            전송된 DM 수.
        """
        if self._ig_client is None:
            if not self.instagram_auth():
                self.logger.error("Instagram DM 봇: 인증 실패")
                return 0

        dm_sent = 0
        already_sent: set[str] = set()

        try:
            # ── 댓글 가져오기 ──
            self.logger.info("Instagram DM 봇 시작: media_id=%s, 키워드=%s", media_id, keywords)
            comments = self._ig_client.media_comments(media_id, amount=200)

            # ── 키워드 매칭 댓글 필터링 ──
            matched_users: list[tuple[str, str]] = []  # (user_id, comment_text)
            for comment in comments:
                text = comment.text or ""
                user_id = str(comment.user.pk)
                if user_id in already_sent:
                    continue
                for kw in keywords:
                    if kw in text:
                        matched_users.append((user_id, text))
                        already_sent.add(user_id)
                        break

            if not matched_users:
                self.logger.info("키워드 매칭 댓글 없음")
                return 0

            self.logger.info("키워드 매칭 사용자 %d명 발견", len(matched_users))

            # ── 배치 DM 전송 ──
            batch_count = 0
            for user_id, comment_text in matched_users:
                if batch_count >= batch_size:
                    self.logger.info("배치 한도 도달 (%d/%d), 중단", batch_count, batch_size)
                    break

                try:
                    self._ig_client.direct_send(reply_text, user_ids=[int(user_id)])
                    dm_sent += 1
                    batch_count += 1
                    self.logger.debug("DM 전송 완료: user_id=%s", user_id)
                except Exception as dm_exc:
                    self.logger.warning("DM 전송 실패 (user_id=%s): %s", user_id, dm_exc)

                # ── 인간화 딜레이 (3-8초) ──
                delay_min, delay_max = INSTAGRAM_DM_DELAY
                delay = random.uniform(delay_min, delay_max)
                self.logger.debug("DM 딜레이: %.1f초", delay)
                time.sleep(delay)

            # 세션 갱신 저장
            try:
                _IG_SESSION_PATH.write_text(
                    json.dumps(self._ig_client.get_settings(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

            self.logger.info("Instagram DM 봇 완료: %d건 전송", dm_sent)

        except Exception as exc:
            self.logger.error("Instagram DM 봇 오류: %s", exc)

        return dm_sent

    # ================================================================
    #  Humanizer Delay
    # ================================================================

    @staticmethod
    def humanizer_delay(
        min_sec: Optional[int] = None,
        max_sec: Optional[int] = None,
    ):
        """안티 디텍션 랜덤 딜레이.

        플랫폼 간 업로드 사이에 호출하여 봇 탐지를 회피한다.

        Args:
            min_sec: 최소 대기 시간(초). 기본 ``HUMANIZER_DELAY_MIN`` (900초=15분).
            max_sec: 최대 대기 시간(초). 기본 ``HUMANIZER_DELAY_MAX`` (2700초=45분).
        """
        lo = min_sec if min_sec is not None else HUMANIZER_DELAY_MIN
        hi = max_sec if max_sec is not None else HUMANIZER_DELAY_MAX
        delay = random.uniform(lo, hi)
        logger = setup_logger("uploader")
        logger.info("인간화 딜레이: %.0f초 (%.1f분) 대기 중...", delay, delay / 60)
        time.sleep(delay)

    # ================================================================
    #  Campaign Upload Pipeline
    # ================================================================

    def upload_campaign(
        self,
        campaign: Campaign,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> dict:
        """캠페인의 모든 타겟 플랫폼에 업로드.

        하나의 플랫폼이 실패해도 나머지 플랫폼은 계속 진행한다.
        플랫폼 간에는 인간화 딜레이를 삽입한다.

        Args:
            campaign: 업로드할 캠페인 객체.
            progress_callback: ``(platform_name, status_message)`` 콜백.

        Returns:
            ``{Platform.YOUTUBE: {"ok": ...}, Platform.NAVER_BLOG: {...}, ...}``
        """
        results: dict = {}
        targets = campaign.target_platforms
        if not targets:
            self.logger.warning("캠페인 타겟 플랫폼 없음: %s", campaign.id)
            return results

        self.logger.info(
            "캠페인 업로드 시작: id=%s, 플랫폼=%s",
            campaign.id,
            [p.value for p in targets],
        )

        def _notify(platform_name: str, msg: str):
            if progress_callback:
                try:
                    progress_callback(platform_name, msg)
                except Exception:
                    pass

        for idx, platform in enumerate(targets):
            # ── 플랫폼 간 인간화 딜레이 (첫 번째 제외) ──
            if idx > 0:
                _notify(platform.value, "인간화 딜레이 대기 중...")
                self.humanizer_delay()

            # ── YouTube Shorts ──
            if platform == Platform.YOUTUBE:
                _notify("youtube", "YouTube 업로드 시작")
                self.logger.info("[%s] YouTube 업로드 진행", campaign.id)

                description = campaign.ai_content.body_text
                if campaign.product.affiliate_link:
                    description = (
                        f"{campaign.product.affiliate_link}\n\n{description}"
                    )

                result = self.youtube_upload(
                    video_path=campaign.video_path,
                    title=campaign.ai_content.hook_text or campaign.product.title,
                    description=description,
                    tags=campaign.ai_content.hashtags,
                    privacy="private",
                )
                results[Platform.YOUTUBE] = result
                _notify("youtube", "완료" if result["ok"] else f"실패: {result.get('reason', '')}")

            # ── Naver Blog ──
            elif platform == Platform.NAVER_BLOG:
                _notify("naver_blog", "네이버 블로그 작성 시작")
                self.logger.info("[%s] 네이버 블로그 작성 진행", campaign.id)

                blog_title = campaign.ai_content.hook_text or campaign.product.title
                blog_content = self._build_naver_content(campaign)

                result = self.naver_blog_post(
                    title=blog_title,
                    content_html=blog_content,
                    images=campaign.product.image_urls if campaign.product.image_urls else None,
                )
                results[Platform.NAVER_BLOG] = result
                _notify("naver_blog", "완료" if result["ok"] else f"실패: {result.get('reason', '')}")

            # ── Instagram Reels ──
            elif platform == Platform.INSTAGRAM:
                _notify("instagram", "Instagram Reel 업로드 시작")
                self.logger.info("[%s] Instagram Reel 업로드 진행", campaign.id)

                caption_parts = [
                    campaign.ai_content.hook_text,
                    "",
                    campaign.ai_content.body_text,
                ]
                if campaign.product.affiliate_link:
                    caption_parts.append("")
                    caption_parts.append(campaign.product.affiliate_link)
                if campaign.ai_content.hashtags:
                    caption_parts.append("")
                    caption_parts.append(
                        " ".join(f"#{tag}" for tag in campaign.ai_content.hashtags)
                    )
                caption = "\n".join(caption_parts)

                result = self.instagram_upload_reel(
                    video_path=campaign.video_path,
                    caption=caption,
                )
                results[Platform.INSTAGRAM] = result
                _notify("instagram", "완료" if result["ok"] else f"실패: {result.get('reason', '')}")

        self.logger.info(
            "캠페인 업로드 완료: id=%s, 결과=%s",
            campaign.id,
            {p.value: r.get("ok") for p, r in results.items()},
        )
        return results

    def upload_queue(
        self,
        campaigns: list[Campaign],
        progress_callback: Optional[Callable[[str, str, str], None]] = None,
    ) -> list[dict]:
        """캠페인 큐 순차 처리.

        캠페인 사이에 인간화 딜레이를 삽입하여 봇 탐지를 회피한다.

        Args:
            campaigns: 업로드할 캠페인 리스트.
            progress_callback: ``(campaign_id, platform_name, status)`` 콜백.

        Returns:
            각 캠페인의 결과 dict 리스트.
        """
        all_results: list[dict] = []

        self.logger.info("업로드 큐 시작: %d개 캠페인", len(campaigns))

        for idx, campaign in enumerate(campaigns):
            self.logger.info(
                "큐 진행: [%d/%d] 캠페인 id=%s",
                idx + 1,
                len(campaigns),
                campaign.id,
            )

            # ── 캠페인 간 인간화 딜레이 (첫 번째 제외) ──
            if idx > 0:
                self.logger.info("캠페인 간 인간화 딜레이 적용")
                self.humanizer_delay()

            # ── 캠페인별 progress_callback 래핑 ──
            def _cb(platform: str, msg: str, _cid: str = campaign.id):
                if progress_callback:
                    try:
                        progress_callback(_cid, platform, msg)
                    except Exception:
                        pass

            try:
                result = self.upload_campaign(campaign, progress_callback=_cb)
                campaign.upload_results = result
                all_results.append(
                    {"campaign_id": campaign.id, "results": result, "ok": True}
                )
            except Exception as exc:
                self.logger.error("캠페인 처리 실패: id=%s, 오류=%s", campaign.id, exc)
                all_results.append(
                    {
                        "campaign_id": campaign.id,
                        "results": {},
                        "ok": False,
                        "reason": str(exc),
                    }
                )

        self.logger.info("업로드 큐 완료: %d개 캠페인 처리", len(campaigns))
        return all_results

    # ================================================================
    #  Internal Helpers
    # ================================================================

    @staticmethod
    def _build_naver_content(campaign: Campaign) -> str:
        """Campaign 데이터를 네이버 블로그 HTML 본문으로 변환."""
        parts: list[str] = []

        # 후크
        if campaign.ai_content.hook_text:
            parts.append(f"<h2>{campaign.ai_content.hook_text}</h2>")

        # 본문
        if campaign.ai_content.body_text:
            paragraphs = campaign.ai_content.body_text.split("\n")
            for p in paragraphs:
                p = p.strip()
                if p:
                    parts.append(f"<p>{p}</p>")

        # 제품 정보
        if campaign.product.title:
            parts.append(f"<h3>{campaign.product.title}</h3>")
        if campaign.product.price:
            parts.append(f"<p><b>가격:</b> {campaign.product.price}</p>")

        # 어필리에이트 링크
        if campaign.product.affiliate_link:
            parts.append(
                f'<p><a href="{campaign.product.affiliate_link}" '
                f'target="_blank">제품 상세 보기</a></p>'
            )

        # 해시태그
        if campaign.ai_content.hashtags:
            tags_str = " ".join(f"#{tag}" for tag in campaign.ai_content.hashtags)
            parts.append(f"<p>{tags_str}</p>")

        return "\n".join(parts)

    def close(self):
        """모든 세션 및 드라이버 정리."""
        if self._naver_driver is not None:
            try:
                # CDP 연결이므로 quit() 하지 않음 (기존 Chrome 세션 유지)
                self._naver_driver = None
                self.logger.info("네이버 드라이버 연결 해제")
            except Exception:
                pass

        if self._ig_client is not None:
            try:
                _IG_SESSION_PATH.write_text(
                    json.dumps(self._ig_client.get_settings(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self.logger.info("Instagram 세션 저장 완료")
            except Exception:
                pass
            self._ig_client = None

        self._yt_service = None
        self.logger.info("StealthUploader 종료")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
