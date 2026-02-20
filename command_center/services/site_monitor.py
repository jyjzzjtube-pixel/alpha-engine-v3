# -*- coding: utf-8 -*-
"""
사이트 건강검진 서비스
"""
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from ..config import MANAGED_SITES
from ..models import SiteCheckResult, SiteStatus


class SiteMonitor:
    """HTTP 건강검진 + 상태 조회"""

    TIMEOUT = 8

    def check_site(self, site: dict) -> SiteCheckResult:
        """단일 사이트 건강검진"""
        url = site.get("health_url", site["url"])
        try:
            resp = requests.get(url, timeout=self.TIMEOUT, allow_redirects=True)
            status = SiteStatus.UP if resp.status_code < 400 else SiteStatus.DOWN
            return SiteCheckResult(
                site_id=site["id"],
                name=site["name"],
                url=site["url"],
                status=status,
                status_code=resp.status_code,
                response_time=round(resp.elapsed.total_seconds(), 2),
            )
        except requests.exceptions.Timeout:
            return SiteCheckResult(
                site_id=site["id"], name=site["name"], url=site["url"],
                status=SiteStatus.TIMEOUT, error="타임아웃",
            )
        except requests.exceptions.ConnectionError:
            return SiteCheckResult(
                site_id=site["id"], name=site["name"], url=site["url"],
                status=SiteStatus.DOWN, error="연결 실패",
            )
        except Exception as e:
            return SiteCheckResult(
                site_id=site["id"], name=site["name"], url=site["url"],
                status=SiteStatus.DOWN, error=str(e)[:100],
            )

    def check_all(self, sites: List[dict] = None) -> List[SiteCheckResult]:
        """모든 사이트 병렬 건강검진"""
        sites = sites or MANAGED_SITES
        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self.check_site, s): s for s in sites}
            for future in as_completed(futures):
                results.append(future.result())
        # 원래 순서 유지
        order = {s["id"]: i for i, s in enumerate(sites)}
        results.sort(key=lambda r: order.get(r.site_id, 999))
        return results

    def get_summary(self, results: List[SiteCheckResult]) -> dict:
        """건강검진 요약"""
        total = len(results)
        up = sum(1 for r in results if r.status == SiteStatus.UP)
        down = total - up
        avg_time = 0.0
        times = [r.response_time for r in results if r.response_time > 0]
        if times:
            avg_time = round(sum(times) / len(times), 2)
        return {"total": total, "up": up, "down": down, "avg_time": avg_time}
