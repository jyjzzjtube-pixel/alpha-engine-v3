# -*- coding: utf-8 -*-
"""
봇/서비스 프로세스 관리 탭
"""
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QFrame, QComboBox, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from ..widgets import StatusLED, LiveConsole
from ..config import MANAGED_BOTS
from ..services.bot_manager import BotManager


class BotPanel(QFrame):
    """개별 봇 상태 패널"""

    start_clicked = pyqtSignal(str)
    stop_clicked = pyqtSignal(str)
    restart_clicked = pyqtSignal(str)
    test_clicked = pyqtSignal(str)

    def __init__(self, bot_config: dict, parent=None):
        super().__init__(parent)
        self.bot_id = bot_config["id"]
        self.bot_type = bot_config.get("type", "")
        self.setObjectName("card")
        self.setMinimumHeight(170)
        self.setStyleSheet("""
            QFrame#card {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 12px;
            }
            QFrame#card:hover {
                border-color: #374151;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # ── 상단: 아이콘 + 이름 + LED ──
        top = QHBoxLayout()
        top.setSpacing(8)

        lbl_icon = QLabel(bot_config.get("icon", "\U0001F916"))
        lbl_icon.setStyleSheet("font-size: 20px;")
        top.addWidget(lbl_icon)

        lbl_name = QLabel(bot_config["name"])
        lbl_name.setStyleSheet(
            "color: #e2e8f0; font-size: 14px; font-weight: 700;"
        )
        top.addWidget(lbl_name, 1)

        self._led = QLabel()
        self._led.setFixedSize(10, 10)
        self._led.setStyleSheet(
            "background: #6b7280; border-radius: 5px;"
        )
        top.addWidget(self._led)

        layout.addLayout(top)

        # ── PID + 업타임 ──
        self._lbl_pid = QLabel("PID: -")
        self._lbl_pid.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self._lbl_pid)

        self._lbl_uptime = QLabel("업타임: -")
        self._lbl_uptime.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self._lbl_uptime)

        layout.addStretch()

        # ── 하단 버튼 ──
        btns = QHBoxLayout()
        btns.setSpacing(6)

        self._btn_toggle = QPushButton("시작")
        self._btn_toggle.setFixedHeight(28)
        self._btn_toggle.setObjectName("successBtn")
        self._btn_toggle.setStyleSheet("""
            QPushButton {
                background: #14532d; color: #86efac;
                border: 1px solid #22c55e; border-radius: 6px;
                font-size: 11px; font-weight: 600; padding: 0 10px;
            }
            QPushButton:hover { background: #22c55e; color: white; }
        """)
        self._btn_toggle.clicked.connect(self._on_toggle)
        btns.addWidget(self._btn_toggle)

        btn_restart = QPushButton("재시작")
        btn_restart.setFixedHeight(28)
        btn_restart.setStyleSheet("""
            QPushButton {
                background: #1f2937; color: #94a3b8;
                border: 1px solid #374151; border-radius: 6px;
                font-size: 11px; padding: 0 10px;
            }
            QPushButton:hover { background: #374151; color: #e2e8f0; }
        """)
        btn_restart.clicked.connect(lambda: self.restart_clicked.emit(self.bot_id))
        btns.addWidget(btn_restart)

        # 텔레그램 봇만 테스트 버튼
        if self.bot_type == "telegram":
            btn_test = QPushButton("테스트")
            btn_test.setFixedHeight(28)
            btn_test.setStyleSheet("""
                QPushButton {
                    background: #1e3a5f; color: #93c5fd;
                    border: 1px solid #3b82f6; border-radius: 6px;
                    font-size: 11px; padding: 0 10px;
                }
                QPushButton:hover { background: #3b82f6; color: white; }
            """)
            btn_test.clicked.connect(lambda: self.test_clicked.emit(self.bot_id))
            btns.addWidget(btn_test)

        layout.addLayout(btns)

        # 내부 상태
        self._running = False

    def update_status(self, running: bool, pid: int | None = None,
                      uptime: float = 0.0):
        """봇 상태 업데이트"""
        self._running = running

        if running:
            self._led.setStyleSheet(
                "background: #22c55e; border-radius: 5px; "
                "border: 2px solid #4ade80;"
            )
            self._lbl_pid.setText(f"PID: {pid or '-'}")
            self._lbl_pid.setStyleSheet("color: #22c55e; font-size: 11px;")

            # 업타임 포맷
            if uptime > 3600:
                ut = f"{uptime / 3600:.1f}시간"
            elif uptime > 60:
                ut = f"{uptime / 60:.0f}분"
            else:
                ut = f"{uptime:.0f}초"
            self._lbl_uptime.setText(f"업타임: {ut}")
            self._lbl_uptime.setStyleSheet("color: #94a3b8; font-size: 11px;")

            self._btn_toggle.setText("중지")
            self._btn_toggle.setStyleSheet("""
                QPushButton {
                    background: #7f1d1d; color: #fca5a5;
                    border: 1px solid #ef4444; border-radius: 6px;
                    font-size: 11px; font-weight: 600; padding: 0 10px;
                }
                QPushButton:hover { background: #ef4444; color: white; }
            """)
        else:
            self._led.setStyleSheet(
                "background: #6b7280; border-radius: 5px;"
            )
            self._lbl_pid.setText("PID: -")
            self._lbl_pid.setStyleSheet("color: #6b7280; font-size: 11px;")
            self._lbl_uptime.setText("업타임: -")
            self._lbl_uptime.setStyleSheet("color: #6b7280; font-size: 11px;")

            self._btn_toggle.setText("시작")
            self._btn_toggle.setStyleSheet("""
                QPushButton {
                    background: #14532d; color: #86efac;
                    border: 1px solid #22c55e; border-radius: 6px;
                    font-size: 11px; font-weight: 600; padding: 0 10px;
                }
                QPushButton:hover { background: #22c55e; color: white; }
            """)

    def _on_toggle(self):
        """시작/중지 토글"""
        if self._running:
            self.stop_clicked.emit(self.bot_id)
        else:
            self.start_clicked.emit(self.bot_id)


class BotTab(QWidget):
    """봇/서비스 프로세스 관리 탭"""

    bot_action = pyqtSignal(str, str)   # (bot_id, action: start/stop/restart)

    def __init__(self, bot_manager: BotManager = None, parent=None):
        super().__init__(parent)
        self._bot_manager = bot_manager or BotManager()
        self._panels: dict[str, BotPanel] = {}
        self._init_ui()
        self._setup_timers()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 제목 ──
        top = QHBoxLayout()
        lbl_title = QLabel("봇 / 서비스 관리")
        lbl_title.setObjectName("sectionTitle")
        top.addWidget(lbl_title)
        top.addStretch()

        self._lbl_summary = QLabel("")
        self._lbl_summary.setStyleSheet("color: #6b7280; font-size: 12px;")
        top.addWidget(self._lbl_summary)

        layout.addLayout(top)

        # ── 봇 패널 그리드 ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        grid_container = QWidget()
        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        for idx, bot_cfg in enumerate(MANAGED_BOTS):
            panel = BotPanel(bot_cfg)
            panel.start_clicked.connect(self._on_start)
            panel.stop_clicked.connect(self._on_stop)
            panel.restart_clicked.connect(self._on_restart)
            panel.test_clicked.connect(self._on_test_message)

            row = idx // 2
            col = idx % 2
            grid.addWidget(panel, row, col)
            self._panels[bot_cfg["id"]] = panel

        total_rows = (len(MANAGED_BOTS) + 1) // 2
        grid.setRowStretch(total_rows, 1)
        scroll.setWidget(grid_container)
        layout.addWidget(scroll, 1)

        # ── 로그 영역 ──
        log_header = QHBoxLayout()
        log_header.setSpacing(8)

        lbl_log = QLabel("봇 로그")
        lbl_log.setStyleSheet(
            "color: #6b7280; font-size: 11px; font-weight: 700; "
            "text-transform: uppercase; letter-spacing: 1px;"
        )
        log_header.addWidget(lbl_log)
        log_header.addStretch()

        self._combo_bot = QComboBox()
        self._combo_bot.setFixedWidth(180)
        self._combo_bot.setFixedHeight(30)
        for bot_cfg in MANAGED_BOTS:
            self._combo_bot.addItem(
                f"{bot_cfg.get('icon', '')} {bot_cfg['name']}",
                bot_cfg["id"],
            )
        self._combo_bot.currentIndexChanged.connect(self._on_bot_selected)
        log_header.addWidget(self._combo_bot)

        layout.addLayout(log_header)

        self._console = LiveConsole()
        layout.addWidget(self._console)

    def _setup_timers(self):
        """상태 갱신 + 로그 자동 새로고침 타이머"""
        # 상태 폴링: 5초
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(5000)

        # 로그 새로고침: 2초
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._refresh_log)
        self._log_timer.start(2000)

    # ── 공개 메서드 ──

    def update_status(self, statuses: dict):
        """모든 봇 상태 업데이트

        Args:
            statuses: {bot_id: {"running": bool, "pid": int, "uptime": float, "name": str}}
        """
        running_count = 0
        for bot_id, status in statuses.items():
            if bot_id in self._panels:
                self._panels[bot_id].update_status(
                    running=status.get("running", False),
                    pid=status.get("pid"),
                    uptime=status.get("uptime", 0.0),
                )
                if status.get("running"):
                    running_count += 1

        total = len(MANAGED_BOTS)
        self._lbl_summary.setText(
            f"{running_count}/{total} 실행 중 | "
            f"갱신: {datetime.now().strftime('%H:%M:%S')}"
        )

    # ── 슬롯 ──

    def _on_start(self, bot_id: str):
        """봇 시작"""
        self._console.log(f"'{bot_id}' 시작 중...", "system")
        ok = self._bot_manager.start(bot_id)
        if ok:
            self._console.log(f"'{bot_id}' 시작 완료", "success")
        else:
            self._console.log(f"'{bot_id}' 시작 실패", "error")
        self.bot_action.emit(bot_id, "start")
        self._refresh_status()

    def _on_stop(self, bot_id: str):
        """봇 중지"""
        self._console.log(f"'{bot_id}' 중지 중...", "system")
        ok = self._bot_manager.stop(bot_id)
        if ok:
            self._console.log(f"'{bot_id}' 중지 완료", "success")
        else:
            self._console.log(f"'{bot_id}' 중지 실패", "error")
        self.bot_action.emit(bot_id, "stop")
        self._refresh_status()

    def _on_restart(self, bot_id: str):
        """봇 재시작"""
        self._console.log(f"'{bot_id}' 재시작 중...", "system")
        ok = self._bot_manager.restart(bot_id)
        if ok:
            self._console.log(f"'{bot_id}' 재시작 완료", "success")
        else:
            self._console.log(f"'{bot_id}' 재시작 실패", "error")
        self.bot_action.emit(bot_id, "restart")
        self._refresh_status()

    def _on_test_message(self, bot_id: str):
        """텔레그램 테스트 메시지 전송"""
        self._console.log(f"'{bot_id}' 테스트 메시지 전송 중...", "info")
        ok = self._bot_manager.send_test_message(bot_id)
        if ok:
            self._console.log(f"'{bot_id}' 테스트 메시지 전송 완료", "success")
        else:
            self._console.log(
                f"'{bot_id}' 테스트 메시지 전송 실패 — 토큰/챗ID 확인",
                "error",
            )

    def _on_bot_selected(self):
        """로그 뷰어 봇 변경 시 즉시 로그 새로고침"""
        self._console.clear_console()
        self._refresh_log()

    def _refresh_status(self):
        """봇 상태 폴링"""
        statuses = self._bot_manager.get_all_status()
        self.update_status(statuses)

    def _refresh_log(self):
        """선택된 봇의 로그 버퍼를 콘솔에 표시"""
        bot_id = self._combo_bot.currentData()
        if not bot_id:
            return

        log_text = self._bot_manager.get_log(bot_id, lines=30)
        if not log_text:
            return

        # 콘솔 갱신 (마지막 로그만 추가)
        lines = log_text.strip().split("\n")
        # 현재 콘솔의 마지막 내용과 비교해서 새 줄만 추가
        current = self._console.toPlainText()
        current_lines = current.strip().split("\n") if current.strip() else []

        # 새로운 줄 감지 (단순 비교: 마지막 N줄이 다르면 전체 갱신)
        if not current_lines or lines[-1] not in current:
            for line in lines[-5:]:  # 최근 5줄만 추가
                if line.strip() and line not in current:
                    level = "error" if "[ERROR]" in line else (
                        "warning" if "[WARN]" in line else "info"
                    )
                    self._console.log(line, level)

    def cleanup(self):
        """탭 종료 시 타이머 정리"""
        self._status_timer.stop()
        self._log_timer.stop()
