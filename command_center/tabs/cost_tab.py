# -*- coding: utf-8 -*-
"""
비용 모니터링 탭 — API 사용 비용 추적 및 시각화
"""
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QFrame, QScrollArea, QPushButton,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

from ..widgets import MetricCard, StatusLED, LiveConsole
from ..config import BUDGET_LIMIT_KRW, COST_REFRESH_INTERVAL_MS
from ..workers import CostRefreshWorker


class CostTab(QWidget):
    """API 비용 모니터링 탭"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: CostRefreshWorker | None = None
        self._build_ui()
        self._setup_timer()

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

        self._card_today = MetricCard(
            "오늘 비용", "\u20a90", "$0.000", accent="#6366f1",
        )
        self._card_monthly = MetricCard(
            "이번 달", "\u20a90", "$0.000", accent="#a855f7",
        )
        self._card_alltime = MetricCard(
            "전체 누적", "\u20a90", "$0.000", accent="#3b82f6",
        )
        self._card_budget = MetricCard(
            "예산 사용률", "0%",
            f"\u20a9{BUDGET_LIMIT_KRW:,} 한도",
            accent="#22c55e",
        )

        for card in (self._card_today, self._card_monthly,
                     self._card_alltime, self._card_budget):
            cards_row.addWidget(card)

        layout.addLayout(cards_row)

        # ── 예산 프로그레스 바 ──
        budget_frame = QFrame()
        budget_frame.setObjectName("card")
        budget_frame.setStyleSheet("""
            QFrame#card {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 12px;
                padding: 12px;
            }
        """)
        budget_layout = QVBoxLayout(budget_frame)
        budget_layout.setContentsMargins(16, 12, 16, 12)
        budget_layout.setSpacing(8)

        budget_header = QHBoxLayout()
        lbl_budget = QLabel("월간 예산 진행률")
        lbl_budget.setStyleSheet(
            "color: #e2e8f0; font-size: 13px; font-weight: 700;"
        )
        self._lbl_budget_detail = QLabel(
            f"\u20a90 / \u20a9{BUDGET_LIMIT_KRW:,}"
        )
        self._lbl_budget_detail.setStyleSheet(
            "color: #94a3b8; font-size: 12px;"
        )
        self._lbl_budget_detail.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        budget_header.addWidget(lbl_budget)
        budget_header.addWidget(self._lbl_budget_detail)
        budget_layout.addLayout(budget_header)

        self._progress_budget = QProgressBar()
        self._progress_budget.setFixedHeight(16)
        self._progress_budget.setRange(0, 100)
        self._progress_budget.setValue(0)
        self._progress_budget.setTextVisible(True)
        self._progress_budget.setFormat("%p%")
        budget_layout.addWidget(self._progress_budget)

        layout.addWidget(budget_frame)

        # ── 모델별 분류 테이블 ──
        lbl_models = QLabel("모델별 비용 분류")
        lbl_models.setObjectName("sectionTitle")
        layout.addWidget(lbl_models)

        self._tbl_models = QTableWidget()
        self._tbl_models.setColumnCount(5)
        self._tbl_models.setHorizontalHeaderLabels([
            "모델", "호출 수", "입력 토큰", "출력 토큰", "비용 \u20a9",
        ])
        self._tbl_models.setAlternatingRowColors(True)
        self._tbl_models.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl_models.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_models.setMaximumHeight(220)
        self._tbl_models.verticalHeader().setVisible(False)

        header = self._tbl_models.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._tbl_models)

        # ── 일별 추이 바 차트 ──
        lbl_trend = QLabel("일별 비용 추이")
        lbl_trend.setObjectName("sectionTitle")
        layout.addWidget(lbl_trend)

        self._trend_frame = QFrame()
        self._trend_frame.setObjectName("card")
        self._trend_frame.setStyleSheet("""
            QFrame#card {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 12px;
            }
        """)
        self._trend_layout = QHBoxLayout(self._trend_frame)
        self._trend_layout.setContentsMargins(16, 12, 16, 12)
        self._trend_layout.setSpacing(4)
        self._trend_layout.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft
        )
        self._trend_frame.setFixedHeight(180)
        layout.addWidget(self._trend_frame)

        # ── 최근 사용 내역 테이블 ──
        header_row = QHBoxLayout()
        lbl_records = QLabel("최근 사용 내역")
        lbl_records.setObjectName("sectionTitle")
        header_row.addWidget(lbl_records)
        header_row.addStretch()

        self._btn_refresh = QPushButton("\U0001F504  새로고침")
        self._btn_refresh.setFixedHeight(36)
        self._btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh.clicked.connect(self.refresh)
        header_row.addWidget(self._btn_refresh)
        layout.addLayout(header_row)

        self._tbl_records = QTableWidget()
        self._tbl_records.setColumnCount(4)
        self._tbl_records.setHorizontalHeaderLabels([
            "시간", "프로젝트", "모델", "비용 \u20a9",
        ])
        self._tbl_records.setAlternatingRowColors(True)
        self._tbl_records.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl_records.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_records.setMinimumHeight(200)
        self._tbl_records.verticalHeader().setVisible(False)

        rec_header = self._tbl_records.horizontalHeader()
        rec_header.setStretchLastSection(True)
        for i in range(4):
            rec_header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._tbl_records)

        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(COST_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

    # ──────────────────────────── Public API ────────────────────────────

    def refresh(self):
        """비용 데이터 전체 새로고침 (워커 기반)."""
        if self._worker and self._worker.isRunning():
            return

        self._btn_refresh.setEnabled(False)
        self._btn_refresh.setText("갱신 중...")

        self._worker = CostRefreshWorker()
        self._worker.result_ready.connect(self._on_summary)
        self._worker.models_ready.connect(self._on_models)
        self._worker.daily_ready.connect(self._on_daily)
        self._worker.records_ready.connect(self._on_records)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def start_auto_refresh(self):
        """자동 갱신 시작."""
        self.refresh()
        self._timer.start()

    def stop_auto_refresh(self):
        """자동 갱신 중지."""
        self._timer.stop()

    # ──────────────────────────── Callbacks ────────────────────────────

    def _on_summary(self, data: dict):
        """비용 요약 카드 업데이트."""
        today_krw = data.get("today_krw", 0)
        today_usd = data.get("today_usd", 0)
        monthly_krw = data.get("monthly_krw", 0)
        monthly_usd = data.get("monthly_usd", 0)
        alltime_krw = data.get("alltime_krw", 0)
        alltime_usd = data.get("alltime_usd", 0)
        budget_pct = data.get("budget_pct", 0)
        budget_status = data.get("budget_status", "ok")
        budget_limit = data.get("budget_limit", BUDGET_LIMIT_KRW)

        self._card_today.set_value(
            f"\u20a9{today_krw:,}", f"${today_usd:.4f}",
        )
        self._card_monthly.set_value(
            f"\u20a9{monthly_krw:,}", f"${monthly_usd:.4f}",
        )
        self._card_alltime.set_value(
            f"\u20a9{alltime_krw:,}", f"${alltime_usd:.4f}",
        )
        self._card_budget.set_value(
            f"{budget_pct:.1f}%",
            f"\u20a9{monthly_krw:,} / \u20a9{budget_limit:,}",
        )

        # 예산 상태별 색상
        if budget_status == "over":
            self._card_budget.set_accent("#ef4444")
            bar_style = self._budget_bar_style("#ef4444", "#dc2626")
        elif budget_status == "warn":
            self._card_budget.set_accent("#f59e0b")
            bar_style = self._budget_bar_style("#f59e0b", "#d97706")
        else:
            self._card_budget.set_accent("#22c55e")
            bar_style = self._budget_bar_style("#6366f1", "#a855f7")

        self._progress_budget.setValue(min(int(budget_pct), 100))
        self._progress_budget.setStyleSheet(bar_style)
        self._lbl_budget_detail.setText(
            f"\u20a9{monthly_krw:,} / \u20a9{budget_limit:,}"
        )

    def _on_models(self, models: list):
        """모델별 분류 테이블 업데이트."""
        self._tbl_models.setRowCount(0)
        self._tbl_models.setRowCount(len(models))

        for row, m in enumerate(models):
            items = [
                QTableWidgetItem(m.get("model", "")),
                QTableWidgetItem(f'{m.get("calls", 0):,}'),
                QTableWidgetItem(f'{m.get("input_tokens", 0):,}'),
                QTableWidgetItem(f'{m.get("output_tokens", 0):,}'),
                QTableWidgetItem(f'\u20a9{m.get("cost_krw", 0):,}'),
            ]
            # 우측 정렬 (숫자 열)
            for i in range(1, 5):
                items[i].setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            # 비용이 높은 모델 강조
            cost_krw = m.get("cost_krw", 0)
            if cost_krw >= 10000:
                items[4].setForeground(QColor("#ef4444"))
            elif cost_krw >= 1000:
                items[4].setForeground(QColor("#f59e0b"))
            else:
                items[4].setForeground(QColor("#22c55e"))

            for col, item in enumerate(items):
                self._tbl_models.setItem(row, col, item)

    def _on_daily(self, daily: list):
        """일별 추이 바 차트 업데이트."""
        # 기존 바 제거
        while self._trend_layout.count():
            child = self._trend_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not daily:
            lbl = QLabel("데이터 없음")
            lbl.setStyleSheet("color: #6b7280; font-size: 12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._trend_layout.addWidget(lbl)
            return

        max_cost = max((d.get("cost_krw", 0) for d in daily), default=1) or 1
        max_bar_h = 120

        # 최근 14일만 표시
        display_days = daily[-14:]

        for d in display_days:
            cost_krw = d.get("cost_krw", 0)
            date_str = d.get("date", "")
            bar_h = max(4, int((cost_krw / max_cost) * max_bar_h))

            col = QVBoxLayout()
            col.setSpacing(2)
            col.setAlignment(Qt.AlignmentFlag.AlignBottom)

            # 비용 라벨
            lbl_cost = QLabel(f"\u20a9{cost_krw:,}" if cost_krw > 0 else "")
            lbl_cost.setStyleSheet("color: #94a3b8; font-size: 9px;")
            lbl_cost.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_cost.setFixedHeight(14)
            col.addWidget(lbl_cost)

            # 바
            bar = QFrame()
            bar.setFixedWidth(24)
            bar.setFixedHeight(bar_h)

            # 비용에 따른 색상
            if cost_krw >= 5000:
                bar_color = "#ef4444"
            elif cost_krw >= 1000:
                bar_color = "#f59e0b"
            else:
                bar_color = "#6366f1"

            bar.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0,y1:1,x2:0,y2:0,
                        stop:0 {bar_color}, stop:1 {bar_color}88);
                    border-radius: 4px;
                }}
            """)
            col.addWidget(bar, alignment=Qt.AlignmentFlag.AlignHCenter)

            # 날짜 라벨 (MM/DD)
            short_date = date_str[5:] if len(date_str) >= 10 else date_str
            lbl_date = QLabel(short_date)
            lbl_date.setStyleSheet("color: #6b7280; font-size: 9px;")
            lbl_date.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_date.setFixedHeight(14)
            col.addWidget(lbl_date)

            container = QWidget()
            container.setLayout(col)
            self._trend_layout.addWidget(container)

        self._trend_layout.addStretch()

    def _on_records(self, records: list):
        """최근 사용 내역 테이블 업데이트."""
        self._tbl_records.setRowCount(0)
        self._tbl_records.setRowCount(len(records))

        for row, r in enumerate(records):
            ts = r.get("timestamp", "")
            if isinstance(ts, str) and len(ts) >= 16:
                time_str = ts[11:16]  # HH:MM
            else:
                time_str = str(ts)

            items = [
                QTableWidgetItem(time_str),
                QTableWidgetItem(r.get("project", "")),
                QTableWidgetItem(r.get("model", "")),
                QTableWidgetItem(f'\u20a9{r.get("cost_krw", 0):,}'),
            ]

            items[3].setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            cost_krw = r.get("cost_krw", 0)
            if cost_krw >= 100:
                items[3].setForeground(QColor("#ef4444"))
            elif cost_krw >= 10:
                items[3].setForeground(QColor("#f59e0b"))
            else:
                items[3].setForeground(QColor("#94a3b8"))

            for col, item in enumerate(items):
                self._tbl_records.setItem(row, col, item)

    def _on_error(self, msg: str):
        """워커 에러 처리."""
        self._card_today.set_value("오류", msg[:30])
        self._card_today.set_accent("#ef4444")

    def _on_finished(self):
        """워커 완료 후 정리."""
        self._btn_refresh.setEnabled(True)
        self._btn_refresh.setText("\U0001F504  새로고침")

    def update_summary(self, summary: dict):
        """main.py에서 호출하는 공개 메서드 — 비용 요약 카드만 업데이트."""
        self._on_summary(summary)

    # ──────────────────────────── Helpers ────────────────────────────

    @staticmethod
    def _budget_bar_style(color1: str, color2: str) -> str:
        return f"""
            QProgressBar {{
                background: #1f2937;
                border: none;
                border-radius: 8px;
                height: 16px;
                text-align: center;
                font-size: 11px;
                font-weight: 700;
                color: #e2e8f0;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {color1}, stop:1 {color2});
                border-radius: 8px;
            }}
        """
