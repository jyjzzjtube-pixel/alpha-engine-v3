"""
Affiliate Marketing System -- Google Drive 자동 아카이버

캠페인별 폴더 구조 자동 생성, 렌더링 결과물 업로드,
로컬 임시 파일 정리 등 Google Drive 연동 전담 모듈.

OAuth 2.0 인증은 YouTube 업로더와 동일한 클라이언트 자격증명 사용.
"""
from __future__ import annotations

import json
import mimetypes
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from affiliate_system.config import (
    DRIVE_CLIENT_ID,
    DRIVE_CLIENT_SECRET,
    RENDER_OUTPUT_DIR,
    WORK_DIR,
    PROJECT_DIR,
)
from affiliate_system.models import Campaign
from affiliate_system.utils import setup_logger, retry, ensure_dir

__all__ = ["DriveArchiver"]

# Google Drive 폴더 MIME 타입
_FOLDER_MIME = "application/vnd.google-apps.folder"

# 이력 업로드용 청크 크기 (5 MB)
_CHUNK_SIZE = 5 * 1024 * 1024

# 루트 폴더 이름
_ROOT_FOLDER_NAME = "YJ_Partners_MCN"

# 캠페인 하위 폴더 이름 매핑
_SUBFOLDER_NAMES = {
    "images": "원본_이미지",
    "renders": "렌더링_결과",
    "audio": "오디오",
    "logs": "업로드_로그",
}

# 스레드 안전을 위한 락
_lock = threading.Lock()


class DriveArchiver:
    """Google Drive 자동 아카이버.

    캠페인 렌더링 완료 후 결과물을 자동으로 Drive에 업로드하고,
    로컬 임시 파일을 정리하는 기능을 제공한다.

    스레드 세이프: QThread 워커에서 호출해도 안전하다.
    """

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]
    TOKEN_PATH = Path(__file__).parent / "workspace" / "drive_token.json"

    def __init__(self) -> None:
        self.logger = setup_logger("drive")
        self._service = None
        self._folder_cache: dict[str, str] = {}  # (name, parent) -> folder_id

    # ──────────────────────────── 인증 ────────────────────────────

    def authenticate(self) -> bool:
        """OAuth 2.0 인증을 수행하고 토큰을 캐시한다.

        Returns:
            True  -- 인증 성공
            False -- 인증 실패 (클라이언트 ID/Secret 미설정 등)
        """
        if not DRIVE_CLIENT_ID or not DRIVE_CLIENT_SECRET:
            self.logger.error("DRIVE_CLIENT_ID 또는 DRIVE_CLIENT_SECRET이 설정되지 않았습니다")
            return False

        creds: Optional[Credentials] = None

        # 기존 토큰 로드
        if self.TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.TOKEN_PATH), self.SCOPES
                )
            except Exception as exc:
                self.logger.warning("기존 토큰 로드 실패, 재인증 진행: %s", exc)
                creds = None

        # 토큰 갱신 또는 새로 발급
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.logger.info("토큰 자동 갱신 완료")
            except Exception as exc:
                self.logger.warning("토큰 갱신 실패, 재인증 진행: %s", exc)
                creds = None

        if not creds or not creds.valid:
            try:
                # credentials.json 파일이 있으면 우선 사용
                cred_file = PROJECT_DIR / "credentials.json"
                if cred_file.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(cred_file), self.SCOPES
                    )
                    self.logger.info("credentials.json 파일로 인증 진행")
                else:
                    client_config = {
                        "installed": {
                            "client_id": DRIVE_CLIENT_ID,
                            "client_secret": DRIVE_CLIENT_SECRET,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "redirect_uris": ["http://localhost"],
                        }
                    }
                    flow = InstalledAppFlow.from_client_config(
                        client_config, self.SCOPES
                    )
                creds = flow.run_local_server(port=0, open_browser=True)
                self.logger.info("새 OAuth 인증 완료")
            except Exception as exc:
                self.logger.error("OAuth 인증 실패: %s", exc)
                return False

        # 토큰 저장
        try:
            ensure_dir(self.TOKEN_PATH.parent)
            self.TOKEN_PATH.write_text(
                creds.to_json(), encoding="utf-8"
            )
        except Exception as exc:
            self.logger.warning("토큰 저장 실패 (계속 진행): %s", exc)

        # Drive 서비스 빌드
        try:
            self._service = build("drive", "v3", credentials=creds)
            self.logger.info("Google Drive 서비스 초기화 완료")
            return True
        except Exception as exc:
            self.logger.error("Drive 서비스 빌드 실패: %s", exc)
            return False

    # ──────────────────────── 폴더 관리 ────────────────────────

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    def _get_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        """기존 폴더를 검색하거나 없으면 새로 생성한다.

        Args:
            name:      폴더 이름
            parent_id: 부모 폴더 ID (None이면 루트에 생성)

        Returns:
            폴더 ID 문자열
        """
        cache_key = f"{name}|{parent_id or 'root'}"
        with _lock:
            if cache_key in self._folder_cache:
                return self._folder_cache[cache_key]

        # 기존 폴더 검색
        query_parts = [
            f"name = '{name}'",
            f"mimeType = '{_FOLDER_MIME}'",
            "trashed = false",
        ]
        if parent_id:
            query_parts.append(f"'{parent_id}' in parents")

        query = " and ".join(query_parts)
        results = (
            self._service.files()
            .list(q=query, fields="files(id, name)", pageSize=1)
            .execute()
        )
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
            self.logger.debug("기존 폴더 발견: %s (ID: %s)", name, folder_id)
        else:
            # 새 폴더 생성
            file_metadata: dict = {
                "name": name,
                "mimeType": _FOLDER_MIME,
            }
            if parent_id:
                file_metadata["parents"] = [parent_id]

            folder = (
                self._service.files()
                .create(body=file_metadata, fields="id")
                .execute()
            )
            folder_id = folder["id"]
            self.logger.info("폴더 생성: %s (ID: %s)", name, folder_id)

        with _lock:
            self._folder_cache[cache_key] = folder_id
        return folder_id

    def _ensure_folder_structure(self, campaign: Campaign) -> dict[str, str]:
        """캠페인용 전체 폴더 계층을 생성한다.

        구조::

            YJ_Partners_MCN/
            └── 2026-02/
                └── 20260220_브랜드_캠페인/
                    ├── 원본_이미지/
                    ├── 렌더링_결과/
                    ├── 오디오/
                    └── 업로드_로그/

        Args:
            campaign: 캠페인 데이터 객체

        Returns:
            폴더 ID 딕셔너리 {"root", "images", "renders", "audio", "logs"}
        """
        self._ensure_service()

        # 1) 루트 폴더: YJ_Partners_MCN
        root_id = self._get_or_create_folder(_ROOT_FOLDER_NAME)

        # 2) 월별 폴더: 2026-02
        created = campaign.created_at or datetime.now()
        month_name = created.strftime("%Y-%m")
        month_id = self._get_or_create_folder(month_name, root_id)

        # 3) 캠페인 폴더: 20260220_상품명_캠페인
        date_prefix = created.strftime("%Y%m%d")
        product_name = campaign.product.title or campaign.id or "미정"
        # 파일명에 사용 불가한 문자 제거
        safe_name = "".join(
            c for c in product_name if c not in r'\/:*?"<>|'
        ).strip()
        if len(safe_name) > 40:
            safe_name = safe_name[:40]
        campaign_folder_name = f"{date_prefix}_{safe_name}_캠페인"
        campaign_id = self._get_or_create_folder(campaign_folder_name, month_id)

        # 4) 하위 폴더들
        result = {"root": campaign_id}
        for key, folder_name in _SUBFOLDER_NAMES.items():
            result[key] = self._get_or_create_folder(folder_name, campaign_id)

        self.logger.info(
            "폴더 구조 준비 완료: %s (%d개 하위 폴더)",
            campaign_folder_name,
            len(_SUBFOLDER_NAMES),
        )
        return result

    # ──────────────────────── 파일 업로드 ────────────────────────

    @retry(max_attempts=3, delay=2.0, backoff=2.0)
    def upload_file(
        self,
        local_path: str,
        folder_id: str,
        mime_type: str | None = None,
    ) -> dict:
        """단일 파일을 Google Drive에 업로드한다 (재개 가능 업로드).

        Args:
            local_path:  로컬 파일 경로
            folder_id:   업로드 대상 Drive 폴더 ID
            mime_type:   MIME 타입 (None이면 자동 감지)

        Returns:
            {"ok": bool, "file_id": str, "web_link": str}
        """
        self._ensure_service()

        file_path = Path(local_path)
        if not file_path.exists():
            self.logger.error("파일이 존재하지 않습니다: %s", local_path)
            return {"ok": False, "file_id": "", "web_link": ""}

        # MIME 타입 자동 감지
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if not mime_type:
                mime_type = "application/octet-stream"

        file_size = file_path.stat().st_size
        file_name = file_path.name

        self.logger.info(
            "업로드 시작: %s (%.2f MB, %s)",
            file_name,
            file_size / (1024 * 1024),
            mime_type,
        )

        try:
            media = MediaFileUpload(
                str(file_path),
                mimetype=mime_type,
                resumable=True,
                chunksize=_CHUNK_SIZE,
            )
            file_metadata = {
                "name": file_name,
                "parents": [folder_id],
            }

            request = self._service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id,webViewLink",
            )

            # 청크 단위 업로드 (대용량 파일 대응)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    percent = int(status.progress() * 100)
                    self.logger.debug("업로드 진행률: %s — %d%%", file_name, percent)

            file_id = response.get("id", "")
            web_link = response.get("webViewLink", "")

            self.logger.info("업로드 완료: %s (ID: %s)", file_name, file_id)
            return {"ok": True, "file_id": file_id, "web_link": web_link}

        except Exception as exc:
            self.logger.error("업로드 실패: %s — %s", file_name, exc)
            raise

    # ──────────────────── 캠페인 아카이빙 ────────────────────

    def archive_campaign(
        self,
        campaign: Campaign,
        files: dict,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        """캠페인의 모든 파일을 Google Drive에 아카이빙한다.

        Args:
            campaign:          캠페인 데이터 객체
            files:             업로드할 파일 딕셔너리.
                               키: "images", "renders", "audio", "logs"
                               값: 로컬 파일 경로 리스트 (list[str])
            progress_callback: 진행 콜백 (current, total, filename)

        Returns:
            {"ok": bool, "folder_url": str, "files_uploaded": int,
             "errors": list[str]}
        """
        self._ensure_service()

        result = {
            "ok": False,
            "folder_url": "",
            "files_uploaded": 0,
            "errors": [],
        }

        # 폴더 구조 생성
        try:
            folders = self._ensure_folder_structure(campaign)
        except Exception as exc:
            msg = f"폴더 구조 생성 실패: {exc}"
            self.logger.error(msg)
            result["errors"].append(msg)
            return result

        # 루트 캠페인 폴더의 웹 링크 가져오기
        try:
            root_meta = (
                self._service.files()
                .get(fileId=folders["root"], fields="webViewLink")
                .execute()
            )
            result["folder_url"] = root_meta.get("webViewLink", "")
        except Exception:
            pass

        # 카테고리별 파일 업로드
        category_map = {
            "images": "images",
            "renders": "renders",
            "audio": "audio",
            "logs": "logs",
        }

        all_files: list[tuple[str, str]] = []  # (local_path, folder_id)
        for category, folder_key in category_map.items():
            file_list = files.get(category, [])
            if not file_list:
                continue
            target_folder_id = folders.get(folder_key)
            if not target_folder_id:
                continue
            for fp in file_list:
                all_files.append((fp, target_folder_id))

        total = len(all_files)
        if total == 0:
            self.logger.warning("업로드할 파일이 없습니다")
            result["ok"] = True
            return result

        self.logger.info("총 %d개 파일 업로드 시작", total)

        for idx, (file_path, folder_id) in enumerate(all_files, 1):
            file_name = Path(file_path).name
            if progress_callback:
                try:
                    progress_callback(idx, total, file_name)
                except Exception:
                    pass

            try:
                upload_result = self.upload_file(file_path, folder_id)
                if upload_result["ok"]:
                    result["files_uploaded"] += 1
                else:
                    result["errors"].append(f"업로드 실패: {file_name}")
            except Exception as exc:
                msg = f"업로드 예외: {file_name} — {exc}"
                self.logger.error(msg)
                result["errors"].append(msg)

        result["ok"] = result["files_uploaded"] == total
        # 폴더 ID 반환 (영상 자동 업로드 등에서 활용)
        result["folders"] = folders
        self.logger.info(
            "아카이빙 완료: %d/%d 파일 성공 (%d개 오류)",
            result["files_uploaded"],
            total,
            len(result["errors"]),
        )
        return result

    # ──────────────────── 로컬 파일 정리 ────────────────────

    def cleanup_local(
        self, campaign: Campaign, keep_video: bool = True
    ) -> int:
        """업로드 완료 후 로컬 임시 파일을 삭제한다.

        Args:
            campaign:   캠페인 데이터 객체
            keep_video: True면 최종 영상 파일(.mp4)은 유지

        Returns:
            삭제된 파일 수
        """
        deleted = 0
        dirs_to_clean = [RENDER_OUTPUT_DIR, WORK_DIR]

        campaign_prefix = campaign.id or ""
        if not campaign_prefix:
            self.logger.warning("캠페인 ID가 비어있어 정리를 건너뜁니다")
            return 0

        for target_dir in dirs_to_clean:
            if not target_dir.exists():
                continue
            for item in target_dir.iterdir():
                if not item.is_file():
                    continue
                # 캠페인 ID가 파일명에 포함된 것만 정리
                if campaign_prefix not in item.name:
                    continue
                # 최종 영상 보존 옵션
                if keep_video and item.suffix.lower() in (".mp4", ".mkv", ".mov"):
                    self.logger.debug("영상 파일 보존: %s", item.name)
                    continue
                try:
                    item.unlink()
                    deleted += 1
                    self.logger.debug("삭제: %s", item.name)
                except Exception as exc:
                    self.logger.warning("파일 삭제 실패: %s — %s", item.name, exc)

        self.logger.info(
            "로컬 정리 완료: %d개 파일 삭제 (캠페인: %s)", deleted, campaign_prefix
        )
        return deleted

    # ──────────────────── 조회 기능 ────────────────────

    @retry(max_attempts=2, delay=1.0, backoff=2.0)
    def list_campaigns(self) -> list[dict]:
        """아카이빙된 모든 캠페인 목록을 반환한다.

        Returns:
            [{"name": str, "id": str, "date": str, "size": int}, ...]
        """
        self._ensure_service()

        # 루트 폴더 찾기
        root_id = self._get_or_create_folder(_ROOT_FOLDER_NAME)

        # 월별 폴더 조회
        month_results = (
            self._service.files()
            .list(
                q=f"'{root_id}' in parents and mimeType = '{_FOLDER_MIME}' and trashed = false",
                fields="files(id, name)",
                orderBy="name desc",
            )
            .execute()
        )

        campaigns: list[dict] = []

        for month_folder in month_results.get("files", []):
            # 각 월별 폴더의 캠페인 폴더 조회
            campaign_results = (
                self._service.files()
                .list(
                    q=(
                        f"'{month_folder['id']}' in parents "
                        f"and mimeType = '{_FOLDER_MIME}' and trashed = false"
                    ),
                    fields="files(id, name, createdTime)",
                    orderBy="createdTime desc",
                )
                .execute()
            )

            for cf in campaign_results.get("files", []):
                # 캠페인 폴더 내 총 파일 크기 계산
                total_size = self._get_folder_size(cf["id"])
                campaigns.append(
                    {
                        "name": cf["name"],
                        "id": cf["id"],
                        "date": cf.get("createdTime", ""),
                        "size": total_size,
                    }
                )

        self.logger.info("캠페인 목록 조회 완료: %d개", len(campaigns))
        return campaigns

    @retry(max_attempts=2, delay=1.0, backoff=2.0)
    def get_storage_usage(self) -> dict:
        """Google Drive 저장용량 사용 현황을 반환한다.

        Returns:
            {"used_bytes": int, "total_bytes": int, "percent": float}
        """
        self._ensure_service()

        try:
            about = (
                self._service.about()
                .get(fields="storageQuota")
                .execute()
            )
            quota = about.get("storageQuota", {})

            used = int(quota.get("usage", 0))
            total = int(quota.get("limit", 0))
            percent = (used / total * 100) if total > 0 else 0.0

            self.logger.info(
                "저장용량: %.2f GB / %.2f GB (%.1f%%)",
                used / (1024**3),
                total / (1024**3),
                percent,
            )
            return {
                "used_bytes": used,
                "total_bytes": total,
                "percent": round(percent, 2),
            }
        except Exception as exc:
            self.logger.error("저장용량 조회 실패: %s", exc)
            return {"used_bytes": 0, "total_bytes": 0, "percent": 0.0}

    # ──────────────────── 내부 헬퍼 ────────────────────

    def _ensure_service(self) -> None:
        """Drive 서비스가 초기화되었는지 확인한다.

        초기화되지 않았으면 자동으로 인증을 시도한다.

        Raises:
            RuntimeError: 인증에 실패했을 때
        """
        if self._service is not None:
            return
        if not self.authenticate():
            raise RuntimeError(
                "Google Drive 인증 실패: DRIVE_CLIENT_ID / DRIVE_CLIENT_SECRET 설정을 확인하세요"
            )

    def _get_folder_size(self, folder_id: str) -> int:
        """폴더 내 모든 파일의 총 크기(바이트)를 계산한다.

        재귀적으로 하위 폴더까지 포함한다.

        Args:
            folder_id: 대상 폴더 ID

        Returns:
            총 바이트 수
        """
        total_size = 0
        try:
            results = (
                self._service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="files(id, size, mimeType)",
                )
                .execute()
            )
            for f in results.get("files", []):
                if f.get("mimeType") == _FOLDER_MIME:
                    total_size += self._get_folder_size(f["id"])
                else:
                    total_size += int(f.get("size", 0))
        except Exception as exc:
            self.logger.warning("폴더 크기 계산 중 오류: %s", exc)
        return total_size
