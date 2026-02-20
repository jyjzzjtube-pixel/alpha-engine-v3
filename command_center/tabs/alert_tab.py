# -*- coding: utf-8 -*-
"""
알림 센터 탭 — 알림 이력, 필터, 설정 관리
"""
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QComboBox,
    QPushButton, QGroupBox, QCheckBox, QSpinBox,
    QFrame, QScrollArea, QGridLayout,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

from ..widgets import MetricCard, StatusLED, LiveConsole
from ..config import (
    ALERT_COST_THRESHOLD_KRW, ALERT_DESKTOP_ENABLED,
    ALERT_TELEGRAM_ENABLED, ALERT_CHECK_INTERVAL_MS,
)
from ..database import Database
from ..models import AlertType, Severity


class AlertTab(QWidget):
    """알림/통지 센터 탭"""

    settings_changed = pyqtSignal(dict)

    # 알림 타입 한글 매핑
    _TYPE_LABELS = {
        "all": "전체",
        AlertType.SITE_DOWN.value: "사이트 다운",
        AlertType.SITE_RECOVERED.value: "사이트 복구",
        AlertType.COST_WARN.value: "비용 경고",
        AlertType.BOT_ERROR.value: "봇 오류",
        AlertType.BOT_STARTED.value: "봇 시작",
        AlertType.BOT_STOPPED.value: "봇 중지",
        AlertType.DEPLOY_OK.value: "배포 완료",
        AlertType.DEPLOY_FAIL.value: "배포 실패",
        AlertType.HEALTH_CHECK.value: "건강 검진",
        AlertType.ORDER_COMPLETE.value: "명령 완료",
        AlertType.SYSTEM.value: "시스템",
    }

    _SEVERITY_ICONS = {
        "info": "\u2139\uFE0F",
        "warn": "\u26A0\uFE0F",
        "error": "\u274C",
        "critical": "\U0001F6A8",
    }

    _SEVERITY_COLORS = {
        "info": "#94a3b8",
        "warn": "#f59e0b",
        "error": "#ef4444",
        "critical": "#ef4444",
    }

    def __init__(self, db: Database = None, parent=None):
        super().__init__(parent)
        self._db = db or Database()
        self._all_alerts: list = []
        self._build_ui()

    # ──────────────────────────── UI 구성 ────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # ── 상단: 필터 행 ──
        filter_frame = QFrame()
        filter_frame.setObjectName("card")
        filter_frame.setStyleSheet("""
            QFrame#card {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 12px;
            }
        """)
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(16, 12, 16, 12)
        filter_layout.setSpacing(12)

        # 타입 필터
        lbl_type = QLabel("유형:")
        lbl_type.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600;")
        filter_layout.addWidget(lbl_type)

        self._combo_type = QComboBox()
        self._combo_type.setFixedHeight(42)
        self._combo_type.setMinimumWidth(140)
        for key, label in self._TYPE_LABELS.items():
            self._combo_type.addItem(label, key)
        self._combo_type.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self._combo_type)

        # 기간 필터
        lbl_period = QLabel("기간:")
        lbl_period.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600;")
        filter_layout.addWidget(lbl_period)

        self._combo_period = QComboBox()
        self._combo_period.setFixedHeight(42)
        self._combo_period.setMinimumWidth(120)
        self._combo_period.addItem("오늘", "today")
        self._combo_period.addItem("최근 3일", "3days")
        self._combo_period.addItem("최근 7일", "7days")
        self._combo_period.addItem("최근 30일", "30days")
        self._combo_period.addItem("전체", "all")
        self._combo_period.setCurrentIndex(2)  # 기본: 최근 7일
        self._combo_period.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self._combo_period)

        filter_layout.addStretch()

        # 알림 토글 버튼
        self._btn_desktop = QPushButton(
            "\U0001F514 데스크톱" if ALERT_DESKTOP_ENABLED else "\U0001F515 데스크톱"
        )
        self._btn_desktop.setFixedHeight(36)
        self._btn_desktop.setCheckable(True)
        self._btn_desktop.setChecked(ALERT_DESKTOP_ENABLED)
        self._btn_desktop.setStyleSheet(self._toggle_style(ALERT_DESKTOP_ENABLED))
        self._btn_desktop.clicked.connect(self._on_desktop_toggle)
        filter_layout.addWidget(self._btn_desktop)

        self._btn_telegram = QPushButton(
            "\u2709\uFE0F 텔레그램" if ALERT_TELEGRAM_ENABLED else "\U0001F4ED 텔레그램"
        )
        self._btn_telegram.setFixedHeight(36)
        self._btn_telegram.setCheckable(True)
        self._btn_telegram.setChecked(ALERT_TELEGRAM_ENABLED)
        self._btn_telegram.setStyleSheet(self._toggle_style(ALERT_TELEGRAM_ENABLED))
        self._btn_telegram.clicked.connect(self._on_telegram_toggle)
        filter_layout.addWidget(self._btn_telegram)

        # 전체 읽음 버튼
        self._btn_mark_read = QPushButton("전체 읽음")
        self._btn_mark_read.setFixedHeight(36)
        self._btn_mark_read.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mark_read.clicked.connect(self._on_mark_all_read)
        filter_layout.addWidget(self._btn_mark_read)

        # 새로고침 버튼
        self._btn_refresh = QPushButton("\U0001F504")
        self._btn_refresh.setFixedHeight(36)
        self._btn_refresh.setFixedWidth(42)
        self._btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh.setToolTip("알림 새로고침")
        self._btn_refresh.clicked.connect(self.refresh)
        filter_layout.addWidget(self._btn_refresh)

        layout.addWidget(filter_frame)

        # ── 메인: 알림 리스트 ──
        self._alert_list = QListWidget()
        self._alert_list.setAlternatingRowColors(True)
        self._alert_list.setMinimumHeight(300)
        self._alert_list.setStyleSheet("""
            QListWidget {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 8px;
                font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 10px 14px;
                border-bottom: 1px solid #1f2937;
            }
            QListWidget::item:hover {
                background: #1f2937;
            }
            QListWidget::item:selected {
                background: #1e3a5f;
            }
        """)
        layout.addWidget(self._alert_list, 1)

        # ── 하단: 알림 설정 패널 ──
        settings_group = QGroupBox("알림 설정")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setContentsMargins(16, 24, 16, 16)
        settings_layout.setSpacing(12)

        # 행 0: 알림 유형 체크박스
        lbl_types = QLabel("알림 유형")
        lbl_types.setStyleSheet(
            "color: #e2e8f0; font-size: 12px; font-weight: 700;"
        )
        settings_layout.addWidget(lbl_types, 0, 0, 1, 2)

        self._chk_site_down = QCheckBox("사이트 다운")
        self._chk_site_down.setChecked(True)
        settings_layout.addWidget(self._chk_site_down, 1, 0)

        self._chk_cost_warn = QCheckBox("비용 경고")
        self._chk_cost_warn.setChecked(True)
        settings_layout.addWidget(self._chk_cost_warn, 1, 1)

        self._chk_bot_error = QCheckBox("봇 오류")
        self._chk_bot_error.setChecked(True)
        settings_layout.addWidget(self._chk_bot_error, 1, 2)

        self._chk_deploy_complete = QCheckBox("배포 완료")
        self._chk_deploy_complete.setChecked(True)
        settings_layout.addWidget(self._chk_bot_error, 1, 2)
        settings_layout.addWidget(self._chk_deploy_complete, 1, 3)

        # 행 2: 알림 채널
        lbl_channels = QLabel("알림 채널")
        lbl_channels.setStyleSheet(
            "color: #e2e8f0; font-size: 12px; font-weight: 700;"
        )
        settings_layout.addWidget(lbl_channels, 2, 0, 1, 2)

        self._chk_desktop_noti = QCheckBox("데스크톱 알림")
        self._chk_desktop_noti.setChecked(ALERT_DESKTOP_ENABLED)
        self._chk_desktop_noti.toggled.connect(self._on_desktop_toggle_chk)
        settings_layout.addWidget(self._chk_desktop_noti, 3, 0)

        self._chk_telegram_noti = QCheckBox("텔레그램 알림")
        self._chk_telegram_noti.setChecked(ALERT_TELEGRAM_ENABLED)
        self._chk_telegram_noti.toggled.connect(self._on_telegram_toggle_chk)
        settings_layout.addWidget(self._chk_telegram_noti, 3, 1)

        # 행 4: 임계값 설정
        lbl_threshold = QLabel("비용 임계값")
        lbl_threshold.setStyleSheet(
            "color: #e2e8f0; font-size: 12px; font-weight: 700;"
        )
        settings_layout.addWidget(lbl_threshold, 4, 0)

        threshold_row = QHBoxLayout()
        self._spin_threshold = QSpinBox()
        self._spin_threshold.setFixedHeight(42)
        self._spin_threshold.setMinimumWidth(120)
        self._spin_threshold.setRange(100, 100_000)
        self._spin_threshold.setSingleStep(500)
        self._spin_threshold.setValue(ALERT_COST_THRESHOLD_KRW)
        self._spin_threshold.setPrefix("\u20a9")
        self._spin_threshold.setSuffix("")
        self._spin_threshold.setStyleSheet("""
            QSpinBox {
                background: #1a2332;
                color: #e2e8f0;
                border: 1px solid #374151;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 13px;
            }
            QSpinBox:focus {
                border-color: #6366f1;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 20px;
                background: #1f2937;
                border: 1px solid #374151;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background: #374151;
            }
        """)
        threshold_row.addWidget(self._spin_threshold)

        lbl_won = QLabel("초과 시 알림")
        lbl_won.setStyleSheet("color: #6b7280; font-size: 12px;")
        threshold_row.addWidget(lbl_won)
        threshold_row.addStretch()

        settings_layout.addLayout(threshold_row, 4, 1, 1, 2)

        # 점검 간격
        lbl_interval = QLabel("점검 간격")
        lbl_interval.setStyleSheet(
            "color: #e2e8f0; font-size: 12px; font-weight: 700;"
        )
        settings_layout.addWidget(lbl_interval, 5, 0)

        interval_row = QHBoxLayout()
        self._spin_interval = QSpinBox()
        self._spin_interval.setFixedHeight(42)
        self._spin_interval.setMinimumWidth(120)
        self._spin_interval.setRange(10, 600)
        self._spin_interval.setSingleStep(10)
        self._spin_interval.setValue(ALERT_CHECK_INTERVAL_MS // 1000)
        self._spin_interval.setSuffix("초")
        self._spin_interval.setStyleSheet("""
            QSpinBox {
                background: #1a2332;
                color: #e2e8f0;
                border: 1px solid #374151;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 13px;
            }
            QSpinBox:focus {
                border-color: #6366f1;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 20px;
                background: #1f2937;
                border: 1px solid #374151;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background: #374151;
            }
        """)
        interval_row.addWidget(self._spin_interval)

        lbl_sec = QLabel("마다 점검 실행")
        lbl_sec.setStyleSheet("color: #6b7280; font-size: 12px;")
        interval_row.addWidget(lbl_sec)
        interval_row.addStretch()

        settings_layout.addLayout(interval_row, 5, 1, 1, 2)

        # 설정 저장 버튼
        self._btn_save = QPushButton("설정 저장")
        self._btn_save.setObjectName("primaryBtn")
        self._btn_save.setFixedHeight(40)
        self._btn_save.setFixedWidth(140)
        self._btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save.clicked.connect(self._on_save_settings)
        settings_layout.addWidget(
            self._btn_save, 6, 3,
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        layout.addWidget(settings_group)

        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)

    # ──────────────────────────── Public API ────────────────────────────

    def refresh(self):
        """DB에서 알림 로드 후 리스트 갱신."""
        try:
            self._all_alerts = self._db.get_alerts(limit=200)
        except Exception:
            self._all_alerts = []
        self._apply_filter()

    @property
    def unread_count(self) -> int:
        """미읽은 알림 수."""
        try:
            return self._db.get_unread_count()
        except Exception:
            return 0

    def mark_all_read(self):
        """전체 읽음 처리."""
        try:
            self._db.mark_all_read()
        except Exception:
            pass
        self.refresh()

    def get_settings(self) -> dict:
        """현재 설정값 반환."""
        return {
            "alert_site_down": self._chk_site_down.isChecked(),
            "alert_cost_warn": self._chk_cost_warn.isChecked(),
            "alert_bot_error": self._chk_bot_error.isChecked(),
            "alert_deploy_complete": self._chk_deploy_complete.isChecked(),
            "desktop_enabled": self._chk_desktop_noti.isChecked(),
            "telegram_enabled": self._chk_telegram_noti.isChecked(),
            "cost_threshold_krw": self._spin_threshold.value(),
            "check_interval_sec": self._spin_interval.value(),
        }

    # ──────────────────────────── Internal ────────────────────────────

    def _apply_filter(self):
        """필터 조건에 맞게 알림 리스트 업데이트."""
        self._alert_list.clear()

        # 타입 필터
        selected_type = self._combo_type.currentData()

        # 기간 필터
        period = self._combo_period.currentData()
        now = datetime.now()
        if period == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "3days":
            cutoff = now - timedelta(days=3)
        elif period == "7days":
            cutoff = now - timedelta(days=7)
        elif period == "30days":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = None

        filtered = []
        for alert in self._all_alerts:
            # 타입 필터
            if selected_type != "all":
                a_type = (alert.alert_type.value
                          if hasattr(alert.alert_type, "value")
                          else str(alert.alert_type))
                if a_type != selected_type:
                    continue

            # 기간 필터
            if cutoff is not None:
                ts = alert.timestamp
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except ValueError:
                        continue
                if ts < cutoff:
                    continue

            filtered.append(alert)

        # 리스트 채우기
        for alert in filtered:
            sev_val = (alert.severity.value
                       if hasattr(alert.severity, "value")
                       else str(alert.severity))
            icon = self._SEVERITY_ICONS.get(sev_val, "\u2139\uFE0F")
            color = self._SEVERITY_COLORS.get(sev_val, "#94a3b8")

            ts = alert.timestamp
            if isinstance(ts, datetime):
                time_str = ts.strftime("%H:%M")
            elif isinstance(ts, str):
                try:
                    time_str = datetime.fromisoformat(ts).strftime("%H:%M")
                except ValueError:
                    time_str = ts[:5]
            else:
                time_str = "--:--"

            text = f"{icon}  {time_str}  {alert.title} \u2014 {alert.message}"

            item = QListWidgetItem(text)
            item.setForeground(QColor(color))

            # 미읽은 항목 볼드 표시
            if not alert.read:
                font = item.font()
                font.setBold(True)
                item.setFont(font)

            self._alert_list.addItem(item)

        # 빈 상태 메시지
        if self._alert_list.count() == 0:
            empty = QListWidgetItem("알림이 없습니다")
            empty.setForeground(QColor("#6b7280"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._alert_list.addItem(empty)

    def _on_mark_all_read(self):
        """전체 읽음 버튼 클릭."""
        self.mark_all_read()

    def _on_desktop_toggle(self):
        """데스크톱 토글 버튼."""
        checked = self._btn_desktop.isChecked()
        self._btn_desktop.setText(
            "\U0001F514 데스크톱" if checked else "\U0001F515 데스크톱"
        )
        self._btn_desktop.setStyleSheet(self._toggle_style(checked))
        self._chk_desktop_noti.setChecked(checked)

    def _on_telegram_toggle(self):
        """텔레그램 토글 버튼."""
        checked = self._btn_telegram.isChecked()
        self._btn_telegram.setText(
            "\u2709\uFE0F 텔레그램" if checked else "\U0001F4ED 텔레그램"
        )
        self._btn_telegram.setStyleSheet(self._toggle_style(checked))
        self._chk_telegram_noti.setChecked(checked)

    def _on_desktop_toggle_chk(self, checked: bool):
        """체크박스 연동."""
        self._btn_desktop.setChecked(checked)
        self._btn_desktop.setText(
            "\U0001F514 데스크톱" if checked else "\U0001F515 데스크톱"
        )
        self._btn_desktop.setStyleSheet(self._toggle_style(checked))

    def _on_telegram_toggle_chk(self, checked: bool):
        """체크박스 연동."""
        self._btn_telegram.setChecked(checked)
        self._btn_telegram.setText(
            "\u2709\uFE0F 텔레그램" if checked else "\U0001F4ED 텔레그램"
        )
        self._btn_telegram.setStyleSheet(self._toggle_style(checked))

    def _on_save_settings(self):
        """설정 저장 시그널 발행."""
        self.settings_changed.emit(self.get_settings())

    @staticmethod
    def _toggle_style(active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background: #14532d;
                    border: 1px solid #22c55e;
                    color: #86efac;
                    border-radius: 8px;
                    font-weight: 600;
                    font-size: 12px;
                    padding: 4px 12px;
                }
                QPushButton:hover {
                    background: #22c55e;
                    color: white;
                }
            """
        return """
            QPushButton {
                background: #1f2937;
                border: 1px solid #374151;
                color: #6b7280;
                border-radius: 8px;
                font-weight: 600;
                font-size: 12px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: #374151;
                color: #94a3b8;
            }
        """
