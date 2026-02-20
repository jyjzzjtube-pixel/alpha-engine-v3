# -*- coding: utf-8 -*-
"""
Netlify 배포 자동화 — deploy_v2.py 로직 재사용
"""
import hashlib
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable, Optional

from ..config import NETLIFY_TOKEN, NETLIFY_ACCOUNT


class NetlifyDeployer:
    """Netlify REST API 배포"""

    API_BASE = "https://api.netlify.com/api/v1"

    def __init__(self, on_progress: Optional[Callable] = None):
        self.on_progress = on_progress or (lambda msg: None)

    def deploy(self, site_name: str, source_dir: str) -> dict:
        """사이트 배포"""
        source = Path(source_dir)
        if not source.is_dir():
            return {"success": False, "error": f"디렉토리 없음: {source_dir}"}

        self.on_progress(f"📦 {site_name} 배포 시작...")

        # 1. 파일 해싱
        files = {}
        file_contents = {}
        for fp in source.rglob("*"):
            if fp.is_file() and not fp.name.startswith("."):
                rel = "/" + fp.relative_to(source).as_posix()
                content = fp.read_bytes()
                sha1 = hashlib.sha1(content).hexdigest()
                files[rel] = sha1
                file_contents[rel] = content

        self.on_progress(f"🔍 파일 {len(files)}개 해싱 완료")

        # 2. 사이트 ID 조회
        site_id = self._get_site_id(site_name)
        if not site_id:
            return {"success": False, "error": f"사이트 '{site_name}' 찾을 수 없음"}

        # 3. Deploy 생성
        deploy_data = json.dumps({"files": files}).encode()
        try:
            req = urllib.request.Request(
                f"{self.API_BASE}/sites/{site_id}/deploys",
                data=deploy_data,
                headers=self._headers("application/json"),
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                deploy_info = json.loads(resp.read())
        except Exception as e:
            return {"success": False, "error": f"Deploy 생성 실패: {e}"}

        deploy_id = deploy_info["id"]
        required = deploy_info.get("required", [])
        self.on_progress(f"📤 업로드 필요: {len(required)}개 / {len(files)}개")

        # 4. 필요한 파일 업로드
        uploaded = 0
        for rel_path, sha1 in files.items():
            if sha1 in required:
                try:
                    req = urllib.request.Request(
                        f"{self.API_BASE}/deploys/{deploy_id}/files{rel_path}",
                        data=file_contents[rel_path],
                        headers=self._headers("application/octet-stream"),
                        method="PUT",
                    )
                    urllib.request.urlopen(req)
                    uploaded += 1
                    self.on_progress(f"⬆️ 업로드 중... {uploaded}/{len(required)}")
                except Exception as e:
                    self.on_progress(f"⚠️ 업로드 실패: {rel_path} — {e}")

        self.on_progress(f"✅ {site_name} 배포 완료 (deploy: {deploy_id[:8]})")
        return {
            "success": True,
            "deploy_id": deploy_id,
            "file_count": len(files),
            "uploaded": uploaded,
        }

    def _get_site_id(self, site_name: str) -> Optional[str]:
        """사이트 이름으로 ID 조회"""
        try:
            req = urllib.request.Request(
                f"{self.API_BASE}/{NETLIFY_ACCOUNT}/sites",
                headers=self._headers(),
            )
            with urllib.request.urlopen(req) as resp:
                sites = json.loads(resp.read())
            for s in sites:
                if s.get("name") == site_name or s.get("subdomain") == site_name:
                    return s["id"]
        except Exception:
            pass
        return None

    def list_sites(self) -> list:
        """모든 Netlify 사이트 목록"""
        try:
            req = urllib.request.Request(
                f"{self.API_BASE}/{NETLIFY_ACCOUNT}/sites",
                headers=self._headers(),
            )
            with urllib.request.urlopen(req) as resp:
                sites = json.loads(resp.read())
            return [
                {
                    "id": s["id"],
                    "name": s.get("name", ""),
                    "url": s.get("ssl_url") or s.get("url", ""),
                    "updated_at": s.get("updated_at", ""),
                }
                for s in sites
            ]
        except Exception:
            return []

    def _headers(self, content_type: str = None) -> dict:
        h = {"Authorization": f"Bearer {NETLIFY_TOKEN}"}
        if content_type:
            h["Content-Type"] = content_type
        return h
