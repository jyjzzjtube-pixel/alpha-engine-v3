# -*- coding: utf-8 -*-
"""
사이트 관리 탭 — 전체 사이트 상태 모니터링 + 배포
"""
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea,
    QGridLayout, QLabel, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices

from ..widgets import SiteCard, LiveConsole
from ..config import MANAGED_SITES
from ..workers import HealthCheckWorker, DeployWorker
from ..models import SiteCheckResult, SiteStatus


class SiteTab(QWidget):
    """사이트 관리 탭 — 건강검진 + 배포"""

    deploy_requested = pyqtSignal(str)      # site_id
    health_check_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._site_cards: dict[str, SiteCard] = {}
        self._health_worker: HealthCheckWorker | None = None
        self._deploy_worker: DeployWorker | None = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 상단 툴바 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        lbl_title = QLabel("사이트 관리")
        lbl_title.setObjectName("sectionTitle")
        toolbar.addWidget(lbl_title)
        toolbar.addStretch()

        self._lbl_summary = QLabel("")
        self._lbl_summary.setStyleSheet("color: #6b7280; font-size: 12px;")
        toolbar.addWidget(self._lbl_summary)

        btn_check_all = QPushButton("\U0001F504 전체 점검")
        btn_check_all.setObjectName("primaryBtn")
        btn_check_all.setFixedHeight(36)
        btn_check_all.clicked.connect(self._on_health_check_all)
        toolbar.addWidget(btn_check_all)

        btn_deploy_all = QPushButton("\U0001F680 전체 배포")
        btn_deploy_all.setFixedHeight(36)
        btn_deploy_all.clicked.connect(self._on_deploy_all)
        toolbar.addWidget(btn_deploy_all)

        layout.addLayout(toolbar)

        # ── 사이트 카드 그리드 (스크롤 가능) ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        grid_container = QWidget()
        self._grid = QGridLayout(grid_container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)

        active_sites = [s for s in MANAGED_SITES if s.get("enabled", True)]
        for idx, site in enumerate(active_sites):
            card = SiteCard(
                site_id=site["id"],
                name=site["name"],
                url=site["url"],
                site_type=site["type"],
            )
            card.open_clicked.connect(self._on_open_site)
            card.deploy_clicked.connect(self._on_deploy)

            row = idx // 3
            col = idx % 3
            self._grid.addWidget(card, row, col)
            self._site_cards[site["id"]] = card

        # 빈 칸 스트레치
        total_rows = (len(active_sites) + 2) // 3
        self._grid.setRowStretch(total_rows, 1)

        scroll.setWidget(grid_container)
        layout.addWidget(scroll, 1)

        # ── 하단 콘솔 ──
        lbl_console = QLabel("배포 / 점검 로그")
        lbl_console.setStyleSheet(
            "color: #6b7280; font-size: 11px; font-weight: 700; "
            "text-transform: uppercase; letter-spacing: 1px; margin-top: 4px;"
        )
        layout.addWidget(lbl_console)

        self._console = LiveConsole()
        layout.addWidget(self._console)

    # ── 공개 메서드 ──

    def update_sites(self, results: list):
        """건강검진 결과로 모든 사이트 카드 업데이트

        Args:
            results: List[SiteCheckResult]
        """
        up_count = 0
        for r in results:
            if r.site_id in self._site_cards:
                card = self._site_cards[r.site_id]
                is_up = r.status == SiteStatus.UP
                if is_up:
                    up_count += 1
                card.set_status(
                    up=is_up,
                    response_time=r.response_time,
                    detail=r.error,
                )

        total = len(results)
        self._lbl_summary.setText(
            f"{up_count}/{total} 정상 | "
            f"마지막 점검: {datetime.now().strftime('%H:%M:%S')}"
        )

    # ── 내부 슬롯 ──

    def _on_open_site(self, site_id: str):
        """사이트 브라우저로 열기"""
        for site in MANAGED_SITES:
            if site["id"] == site_id:
                QDesktopServices.openUrl(QUrl(site["url"]))
                self._log(f"'{site['name']}' 열기 → {site['url']}", "info")
                return

    def _on_deploy(self, site_id: str):
        """개별 사이트 배포 시작"""
        site = self._find_site(site_id)
        if not site:
            self._log(f"사이트 '{site_id}'를 찾을 수 없습니다.", "error")
            return

        if site["type"] != "netlify":
            self._log(f"'{site['name']}'은(는) Netlify 사이트가 아닙니다.", "warning")
            return

        if self._deploy_worker and self._deploy_worker.isRunning():
            self._log("이미 배포가 진행 중입니다. 완료 후 다시 시도하세요.", "warning")
            return

        self._log(f"'{site['name']}' 배포 시작...", "system")
        self.deploy_requested.emit(site_id)

        self._deploy_worker = DeployWorker(
            site_name=site["id"],
            source_dir=site.get("source_dir", ""),
        )
        self._deploy_worker.progress.connect(
            lambda msg: self._log(msg, "info")
        )
        self._deploy_worker.finished_ok.connect(
            lambda result: self._on_deploy_done(site["name"], result)
        )
        self._deploy_worker.error.connect(
            lambda err: self._log(f"배포 실패: {err}", "error")
        )
        self._deploy_worker.start()

    def _on_deploy_done(self, name: str, result: dict):
        """배포 완료 콜백"""
        deploy_id = result.get("deploy_id", "N/A")
        url = result.get("url", "")
        self._log(
            f"'{name}' 배포 완료! ID: {deploy_id}",
            "success",
        )
        # 카드에 배포 정보 표시
        for site in MANAGED_SITES:
            if site["name"] == name and site["id"] in self._site_cards:
                self._site_cards[site["id"]].set_deploy_info(
                    f"배포: {datetime.now().strftime('%m/%d %H:%M')}"
                )
                break

    def _on_deploy_all(self):
        """Netlify 사이트 전체 배포"""
        netlify_sites = [s for s in MANAGED_SITES if s["type"] == "netlify" and s.get("enabled", True)]
        if not netlify_sites:
            self._log("배포 가능한 Netlify 사이트가 없습니다.", "warning")
            return
        self._log(
            f"전체 배포 시작 — {len(netlify_sites)}개 Netlify 사이트",
            "system",
        )
        # 순차적으로 배포 (첫 번째부터)
        self._deploy_queue = list(netlify_sites)
        self._deploy_next()

    def _deploy_next(self):
        """배포 큐에서 다음 사이트 배포"""
        if not hasattr(self, '_deploy_queue') or not self._deploy_queue:
            self._log("전체 배포 완료!", "success")
            return

        site = self._deploy_queue.pop(0)
        self._log(f"[{len(self._deploy_queue)}건 남음] '{site['name']}' 배포 중...", "system")

        self._deploy_worker = DeployWorker(
            site_name=site["id"],
            source_dir=site.get("source_dir", ""),
        )
        self._deploy_worker.progress.connect(
            lambda msg: self._log(msg, "info")
        )
        self._deploy_worker.finished_ok.connect(
            lambda result, n=site["name"]: (
                self._on_deploy_done(n, result),
                QTimer.singleShot(500, self._deploy_next),
            )
        )
        self._deploy_worker.error.connect(
            lambda err, n=site["name"]: (
                self._log(f"'{n}' 배포 실패: {err}", "error"),
                QTimer.singleShot(500, self._deploy_next),
            )
        )
        self._deploy_worker.start()

    def _on_health_check_all(self):
        """전체 사이트 건강검진"""
        if self._health_worker and self._health_worker.isRunning():
            self._log("이미 점검이 진행 중입니다.", "warning")
            return

        self._log("전체 사이트 건강검진 시작...", "system")
        self.health_check_requested.emit()

        self._health_worker = HealthCheckWorker(sites=MANAGED_SITES)
        self._health_worker.progress.connect(
            lambda msg: self._log(msg, "info")
        )
        self._health_worker.result_ready.connect(self._on_health_results)
        self._health_worker.error.connect(
            lambda err: self._log(f"점검 오류: {err}", "error")
        )
        self._health_worker.start()

    def _on_health_results(self, results: list):
        """건강검진 결과 수신"""
        self.update_sites(results)
        up = sum(1 for r in results if r.status == SiteStatus.UP)
        total = len(results)
        down = total - up

        if down == 0:
            self._log(f"건강검진 완료: {total}개 사이트 모두 정상", "success")
        else:
            self._log(
                f"건강검진 완료: {up}/{total} 정상, {down}개 장애",
                "warning",
            )
            # 장애 사이트 상세
            for r in results:
                if r.status != SiteStatus.UP:
                    self._log(
                        f"  ▸ {r.name} — {r.error or r.status.value}",
                        "error",
                    )

    def _log(self, msg: str, level: str = "info"):
        """콘솔에 로그 기록"""
        self._console.log(msg, level)

    @staticmethod
    def _find_site(site_id: str) -> dict | None:
        """MANAGED_SITES에서 site_id로 사이트 찾기"""
        for site in MANAGED_SITES:
            if site["id"] == site_id:
                return site
        return None
