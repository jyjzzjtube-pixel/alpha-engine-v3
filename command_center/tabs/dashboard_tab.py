# -*- coding: utf-8 -*-
"""
대시보드 탭 — 전체 현황 한눈에 보기
"""
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

from ..widgets import MetricCard, StatusLED, LiveConsole
from ..config import MANAGED_SITES, MANAGED_BOTS


class DashboardTab(QWidget):
    """메인 대시보드 — 사이트, 봇, 비용, 알림 종합 현황"""

    health_check_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._site_leds: dict[str, StatusLED] = {}
        self._bot_leds: dict[str, StatusLED] = {}
        self._build_ui()

    # ──────────────────────────── UI 구성 ────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # ── 스크롤 영역 ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # ── 상단: 메트릭 카드 4개 ──
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self._card_sites = MetricCard(
            "사이트 UP", "0/12", "모니터링 대기 중", accent="#22c55e",
        )
        self._card_cost = MetricCard(
            "오늘 비용", "\u20a90", "$0.000", accent="#6366f1",
        )
        self._card_bots = MetricCard(
            "활성 봇", "0/4", "전체 중지", accent="#a855f7",
        )
        self._card_alerts = MetricCard(
            "새 알림", "0", "알림 없음", accent="#f59e0b",
        )

        for card in (self._card_sites, self._card_cost,
                     self._card_bots, self._card_alerts):
            cards_row.addWidget(card)

        layout.addLayout(cards_row)

        # ── 중간: StatusLED 그리드 (4열) ──
        lbl_status = QLabel("서비스 상태 모니터")
        lbl_status.setObjectName("sectionTitle")
        layout.addWidget(lbl_status)

        grid_frame = QFrame()
        grid_frame.setObjectName("card")
        grid_frame.setStyleSheet("""
            QFrame#card {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 12px;
                padding: 8px;
            }
        """)
        grid = QGridLayout(grid_frame)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setSpacing(6)

        # 사이트 LED 배치 (활성 사이트만)
        all_items = []
        for site in MANAGED_SITES:
            if not site.get("enabled", True):
                continue
            led = StatusLED(site["name"])
            self._site_leds[site["id"]] = led
            all_items.append(led)

        for bot in MANAGED_BOTS:
            led = StatusLED(f'{bot["icon"]} {bot["name"]}')
            self._bot_leds[bot["id"]] = led
            all_items.append(led)

        cols = 4
        for idx, led in enumerate(all_items):
            row = idx // cols
            col = idx % cols
            grid.addWidget(led, row, col)

        layout.addWidget(grid_frame)

        # ── 하단: 최근 알림 + 전체 점검 버튼 ──
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        # 알림 피드
        alert_frame = QVBoxLayout()
        alert_frame.setSpacing(6)

        lbl_alerts = QLabel("최근 알림")
        lbl_alerts.setObjectName("sectionTitle")
        alert_frame.addWidget(lbl_alerts)

        self._alert_list = QListWidget()
        self._alert_list.setMaximumHeight(260)
        self._alert_list.setAlternatingRowColors(True)
        self._alert_list.setStyleSheet("""
            QListWidget {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 8px;
                font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #1f2937;
            }
            QListWidget::item:hover {
                background: #1f2937;
            }
        """)
        alert_frame.addWidget(self._alert_list)

        bottom_row.addLayout(alert_frame, 3)

        # 우측 액션 패널
        action_panel = QVBoxLayout()
        action_panel.setSpacing(10)

        self._btn_health = QPushButton("\U0001F50D  \uc804\uccb4 \uc810\uac80")
        self._btn_health.setObjectName("primaryBtn")
        self._btn_health.setFixedHeight(44)
        self._btn_health.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_health.clicked.connect(self.health_check_requested.emit)
        action_panel.addWidget(self._btn_health)

        self._lbl_last_check = QLabel("마지막 점검: -")
        self._lbl_last_check.setObjectName("subtitle")
        self._lbl_last_check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_panel.addWidget(self._lbl_last_check)

        action_panel.addStretch()

        bottom_row.addLayout(action_panel, 1)

        layout.addLayout(bottom_row)
        layout.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

    # ──────────────────────────── Public API ────────────────────────────

    def update_sites(self, results: list):
        """건강검진 결과로 사이트 LED 업데이트.

        Args:
            results: List[SiteCheckResult] 또는 동등 dict 목록
        """
        up_count = 0
        total = len(results)

        for r in results:
            site_id = r.site_id if hasattr(r, "site_id") else r.get("site_id", "")
            status = r.status if hasattr(r, "status") else r.get("status")
            resp_time = r.response_time if hasattr(r, "response_time") else r.get("response_time", 0)

            # SiteStatus enum 비교
            status_val = status.value if hasattr(status, "value") else str(status)
            is_up = status_val == "up"

            if is_up:
                up_count += 1

            led = self._site_leds.get(site_id)
            if led:
                detail = f"{resp_time:.0f}ms" if is_up else status_val
                led.set_status(is_up, detail)

        # 메트릭 카드 업데이트
        self._card_sites.set_value(
            f"{up_count}/{total}",
            f"{total - up_count}개 사이트 이상" if up_count < total else "전체 정상",
        )
        if up_count < total:
            self._card_sites.set_accent("#ef4444")
        else:
            self._card_sites.set_accent("#22c55e")

        self._lbl_last_check.setText(
            f'마지막 점검: {datetime.now().strftime("%H:%M:%S")}'
        )

    def update_cost(self, summary: dict):
        """비용 요약 데이터로 카드 업데이트.

        Args:
            summary: CostService.get_summary() 반환 dict
        """
        today_krw = summary.get("today_krw", 0)
        today_usd = summary.get("today_usd", 0)
        budget_pct = summary.get("budget_pct", 0)

        self._card_cost.set_value(
            f"\u20a9{today_krw:,}",
            f"${today_usd:.4f} | 예산 {budget_pct}%",
        )

        if budget_pct >= 100:
            self._card_cost.set_accent("#ef4444")
        elif budget_pct >= 80:
            self._card_cost.set_accent("#f59e0b")
        else:
            self._card_cost.set_accent("#6366f1")

    def update_bots(self, statuses: dict):
        """봇 상태 업데이트.

        Args:
            statuses: {bot_id: BotStatus} 또는 {bot_id: dict}
        """
        active = 0
        total = len(MANAGED_BOTS)

        for bot_id, st in statuses.items():
            running = st.running if hasattr(st, "running") else st.get("running", False)
            name = st.name if hasattr(st, "name") else st.get("name", bot_id)

            if running:
                active += 1

            led = self._bot_leds.get(bot_id)
            if led:
                if running:
                    uptime = st.uptime_seconds if hasattr(st, "uptime_seconds") else st.get("uptime", st.get("uptime_seconds", 0))
                    mins = int(uptime // 60)
                    detail = f"실행 중 ({mins}분)" if mins > 0 else "실행 중"
                    led.set_status(True, detail)
                else:
                    error = st.error if hasattr(st, "error") else st.get("error", "")
                    if error:
                        led.set_warning(error[:20])
                    else:
                        led.set_status(False, "중지됨")

        self._card_bots.set_value(
            f"{active}/{total}",
            f"{active}개 봇 활성" if active > 0 else "전체 중지",
        )
        if active == 0:
            self._card_bots.set_accent("#6b7280")
        elif active < total:
            self._card_bots.set_accent("#f59e0b")
        else:
            self._card_bots.set_accent("#a855f7")

    def update_alerts(self, alerts: list):
        """알림 목록 전체 교체.

        Args:
            alerts: List[Alert] 또는 dict 목록
        """
        self._alert_list.clear()
        unread = 0

        for alert in alerts[:10]:
            title = alert.title if hasattr(alert, "title") else alert.get("title", "")
            message = alert.message if hasattr(alert, "message") else alert.get("message", "")
            severity = alert.severity if hasattr(alert, "severity") else alert.get("severity", "info")
            timestamp = alert.timestamp if hasattr(alert, "timestamp") else alert.get("timestamp")
            read = alert.read if hasattr(alert, "read") else alert.get("read", True)

            sev_val = severity.value if hasattr(severity, "value") else str(severity)

            if not read:
                unread += 1

            if isinstance(timestamp, datetime):
                time_str = timestamp.strftime("%H:%M")
            elif isinstance(timestamp, str):
                try:
                    time_str = datetime.fromisoformat(timestamp).strftime("%H:%M")
                except ValueError:
                    time_str = timestamp[:5]
            else:
                time_str = "--:--"

            self.add_alert_item(f"[{time_str}] {title} \u2014 {message}", sev_val)

        self._card_alerts.set_value(
            str(unread),
            f"{unread}개 미확인" if unread > 0 else "알림 없음",
        )
        if unread > 0:
            self._card_alerts.set_accent("#f59e0b")
        else:
            self._card_alerts.set_accent("#22c55e")

    def update_alert_count(self, unread: int):
        """미확인 알림 수 카드만 업데이트.

        Args:
            unread: 미확인 알림 수
        """
        self._card_alerts.set_value(
            str(unread),
            f"{unread}개 미확인" if unread > 0 else "알림 없음",
        )
        if unread > 0:
            self._card_alerts.set_accent("#f59e0b")
        else:
            self._card_alerts.set_accent("#22c55e")

    def add_alert_item(self, text: str, level: str = "info"):
        """알림 리스트에 색상 코딩된 항목 추가.

        Args:
            text: 표시할 텍스트
            level: info / warn / error / critical
        """
        colors = {
            "info": "#94a3b8",
            "warn": "#f59e0b",
            "error": "#ef4444",
            "critical": "#ef4444",
        }
        icons = {
            "info": "\u2139\uFE0F",
            "warn": "\u26A0\uFE0F",
            "error": "\u274C",
            "critical": "\U0001F6A8",
        }

        icon = icons.get(level, "\u2139\uFE0F")
        color = colors.get(level, "#94a3b8")

        item = QListWidgetItem(f"{icon}  {text}")
        item.setForeground(QColor(color))

        if self._alert_list.count() >= 10:
            self._alert_list.takeItem(self._alert_list.count() - 1)

        self._alert_list.insertItem(0, item)
