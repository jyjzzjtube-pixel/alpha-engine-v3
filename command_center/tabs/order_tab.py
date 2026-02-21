# -*- coding: utf-8 -*-
"""
오더/커맨드 센터 탭 — 자연어 명령 + 퀵 액션 + AI 채팅
"""
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLineEdit, QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QSplitter, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence

from ..widgets import LiveConsole
from ..services.order_engine import OrderEngine
from ..workers import OrderWorker, AIchatWorker


# ── 퀵 액션 정의 ──
QUICK_ACTIONS = [
    {"icon": "\U0001F504", "label": "전체 점검", "action": "health_check_all"},
    {"icon": "\U0001F680", "label": "전체 배포", "action": "deploy_all"},
    {"icon": "\U0001F4CA", "label": "비용 리포트", "action": "cost_report"},
    {"icon": "\U0001F916", "label": "봇 재시작", "action": "bot_restart"},
    {"icon": "\U0001F4DD", "label": "AI 리포트", "action": "ai_report"},
    {"icon": "\U0001F514", "label": "알림 확인", "action": "check_alerts"},
    {"icon": "\U0001F4F0", "label": "뉴스 검색", "action": "news_search"},
    {"icon": "\U0001F4B9", "label": "주식 조회", "action": "stock_query"},
    {"icon": "\u2699\uFE0F", "label": "상태 확인", "action": "status_all"},
]


class OrderTab(QWidget):
    """오더/커맨드 센터 — 자연어 명령 파싱 + 퀵 액션 + AI 채팅"""

    order_executed = pyqtSignal(str, str)   # (action, result)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = OrderEngine()
        self._order_worker: OrderWorker | None = None
        self._ai_worker: AIchatWorker | None = None
        self._init_ui()
        self._setup_shortcuts()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 명령 입력 영역 ──
        cmd_frame = QFrame()
        cmd_frame.setObjectName("card")
        cmd_frame.setStyleSheet("""
            QFrame#card {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 12px;
            }
        """)
        cmd_layout = QVBoxLayout(cmd_frame)
        cmd_layout.setContentsMargins(16, 14, 16, 14)
        cmd_layout.setSpacing(6)

        lbl_cmd = QLabel("명령 센터")
        lbl_cmd.setObjectName("sectionTitle")
        cmd_layout.addWidget(lbl_cmd)

        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText("명령 입력... (Ctrl+K)")
        self._cmd_input.setFixedHeight(42)
        self._cmd_input.setStyleSheet("""
            QLineEdit {
                background: #1a2332;
                color: #e2e8f0;
                border: 2px solid #374151;
                border-radius: 10px;
                padding: 0 16px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #6366f1;
            }
        """)
        self._cmd_input.returnPressed.connect(self._on_command_enter)
        cmd_layout.addWidget(self._cmd_input)

        lbl_hint = QLabel(
            "예: \"전체 점검\", \"배포 alpha-engine\", \"봇 재시작\", "
            "\"비용 분석\", \"상태 확인\" 또는 자유 질문"
        )
        lbl_hint.setStyleSheet("color: #4b5563; font-size: 11px;")
        lbl_hint.setWordWrap(True)
        cmd_layout.addWidget(lbl_hint)

        layout.addWidget(cmd_frame)

        # ── 퀵 액션 그리드 (3x3) ──
        lbl_quick = QLabel("퀵 액션")
        lbl_quick.setStyleSheet(
            "color: #6b7280; font-size: 11px; font-weight: 700; "
            "text-transform: uppercase; letter-spacing: 1px;"
        )
        layout.addWidget(lbl_quick)

        quick_grid = QGridLayout()
        quick_grid.setSpacing(8)

        for idx, qa in enumerate(QUICK_ACTIONS):
            btn = QPushButton(f"{qa['icon']} {qa['label']}")
            btn.setFixedHeight(40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: #111827;
                    color: #e2e8f0;
                    border: 1px solid #1f2937;
                    border-radius: 8px;
                    font-size: 13px;
                    font-weight: 600;
                    padding: 0 8px;
                }
                QPushButton:hover {
                    background: #1f2937;
                    border-color: #6366f1;
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 #6366f1, stop:1 #a855f7);
                    border: none;
                    color: white;
                }
            """)
            action_name = qa["action"]
            btn.clicked.connect(lambda checked, a=action_name: self._on_quick_action(a))

            row = idx // 3
            col = idx % 3
            quick_grid.addWidget(btn, row, col)

        layout.addLayout(quick_grid)

        # ── 메인 분할 영역: 오더 히스토리 + AI 채팅 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # 좌: 오더 히스토리
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(6)

        lbl_history = QLabel("오더 히스토리")
        lbl_history.setStyleSheet(
            "color: #6b7280; font-size: 11px; font-weight: 700; "
            "text-transform: uppercase; letter-spacing: 1px;"
        )
        history_layout.addWidget(lbl_history)

        self._order_list = QListWidget()
        self._order_list.setAlternatingRowColors(True)
        self._order_list.setStyleSheet("""
            QListWidget {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 8px;
                color: #e2e8f0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #1f2937;
            }
            QListWidget::item:selected {
                background: #1e3a5f;
            }
        """)
        history_layout.addWidget(self._order_list)

        splitter.addWidget(history_widget)

        # 우: AI 채팅
        ai_widget = QWidget()
        ai_layout = QVBoxLayout(ai_widget)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        ai_layout.setSpacing(6)

        lbl_ai = QLabel("AI 어시스턴트")
        lbl_ai.setStyleSheet(
            "color: #6b7280; font-size: 11px; font-weight: 700; "
            "text-transform: uppercase; letter-spacing: 1px;"
        )
        ai_layout.addWidget(lbl_ai)

        self._ai_display = QTextEdit()
        self._ai_display.setReadOnly(True)
        self._ai_display.setStyleSheet("""
            QTextEdit {
                background: #0f172a;
                color: #e2e8f0;
                border: 1px solid #1f2937;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        self._ai_display.setHtml(
            '<p style="color: #6b7280; font-style: italic;">'
            'AI 어시스턴트에게 자유롭게 질문하세요.<br>'
            '예: "현재 시스템 상태 분석해줘", "이번달 비용 절약 방법?"</p>'
        )
        ai_layout.addWidget(self._ai_display, 1)

        # AI 입력
        ai_input_row = QHBoxLayout()
        ai_input_row.setSpacing(6)

        self._ai_input = QLineEdit()
        self._ai_input.setPlaceholderText("AI에게 질문하기...")
        self._ai_input.setFixedHeight(36)
        self._ai_input.returnPressed.connect(self._on_ai_send)
        ai_input_row.addWidget(self._ai_input, 1)

        btn_ai_send = QPushButton("전송")
        btn_ai_send.setFixedSize(60, 36)
        btn_ai_send.setObjectName("primaryBtn")
        btn_ai_send.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #6366f1, stop:1 #a855f7);
                color: white; border: none; border-radius: 8px;
                font-size: 13px; font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #818cf8, stop:1 #c084fc);
            }
        """)
        btn_ai_send.clicked.connect(self._on_ai_send)
        ai_input_row.addWidget(btn_ai_send)

        ai_layout.addLayout(ai_input_row)

        splitter.addWidget(ai_widget)
        splitter.setSizes([400, 500])

        layout.addWidget(splitter, 1)

    def _setup_shortcuts(self):
        """키보드 단축키"""
        shortcut_k = QShortcut(QKeySequence("Ctrl+K"), self)
        shortcut_k.activated.connect(self._focus_command)

    def _focus_command(self):
        """명령 입력에 포커스"""
        self._cmd_input.setFocus()
        self._cmd_input.selectAll()

    # ── 명령 처리 ──

    def _on_command_enter(self):
        """명령 입력 → 파싱 → 실행"""
        text = self._cmd_input.text().strip()
        if not text:
            return

        self._cmd_input.clear()
        action, target = self._engine.parse_command(text)

        self._add_order_result(text, "실행 중...", "running")
        self._execute_action(text, action, target)

    def _on_quick_action(self, action: str):
        """퀵 액션 버튼 클릭"""
        label = action.replace("_", " ")
        self._add_order_result(label, "실행 중...", "running")
        self._execute_action(label, action, None)

    def _execute_action(self, command: str, action: str, target: str | None):
        """액션 실행 (워커 스레드)"""
        if self._order_worker and self._order_worker.isRunning():
            self._update_last_order("이전 명령이 실행 중입니다.", "warning")
            return

        self._order_worker = OrderWorker(
            command=command, action=action, target=target
        )
        self._order_worker.result_ready.connect(
            lambda result, status: self._on_order_done(command, result, status)
        )
        self._order_worker.error.connect(
            lambda err: self._on_order_done(command, f"오류: {err}", "error")
        )
        self._order_worker.start()

    def _on_order_done(self, command: str, result: str, status: str):
        """오더 완료 콜백"""
        self._update_last_order(result, status)
        self.order_executed.emit(command, result)

        # AI 쿼리 결과는 AI 디스플레이에도 표시
        action, _ = self._engine.parse_command(command)
        if action == "ai_query":
            self._append_ai_message("사용자", command)
            self._append_ai_message("AI", result)

    # ── AI 채팅 ──

    def _on_ai_send(self):
        """AI 채팅 메시지 전송"""
        text = self._ai_input.text().strip()
        if not text:
            return

        self._ai_input.clear()
        self._append_ai_message("사용자", text)

        if self._ai_worker and self._ai_worker.isRunning():
            self._append_ai_message("시스템", "이전 요청을 처리 중입니다. 잠시 기다려주세요.")
            return

        self._ai_worker = AIchatWorker(prompt=text)
        self._ai_worker.result_ready.connect(
            lambda resp: self._append_ai_message("AI", resp)
        )
        self._ai_worker.error.connect(
            lambda err: self._append_ai_message("시스템", f"오류: {err}")
        )
        self._ai_worker.start()

    def _append_ai_message(self, sender: str, message: str):
        """AI 채팅 디스플레이에 메시지 추가"""
        ts = datetime.now().strftime("%H:%M")
        colors = {
            "사용자": "#6366f1",
            "AI": "#22c55e",
            "시스템": "#f59e0b",
        }
        color = colors.get(sender, "#94a3b8")

        # 메시지 줄바꿈 처리
        msg_html = message.replace("\n", "<br>")

        html = (
            f'<div style="margin-bottom: 8px;">'
            f'<span style="color: #4b5563; font-size: 11px;">[{ts}]</span> '
            f'<span style="color: {color}; font-weight: 700;">{sender}</span>'
            f'<br>'
            f'<span style="color: #e2e8f0; font-size: 13px;">{msg_html}</span>'
            f'</div>'
        )
        self._ai_display.append(html)

        # 자동 스크롤
        scrollbar = self._ai_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ── 오더 히스토리 ──

    def _add_order_result(self, command: str, result: str, status: str = "success"):
        """오더 히스토리에 항목 추가"""
        ts = datetime.now().strftime("%H:%M")

        status_icons = {
            "success": "\u2705",
            "error": "\u274C",
            "warning": "\u26A0\uFE0F",
            "running": "\u23F3",
        }
        icon = status_icons.get(status, "\u25B6\uFE0F")

        # 결과 한 줄로 축약
        short_result = result.split("\n")[0][:60]

        text = f"{ts} {icon} {command} \u2192 {short_result}"

        item = QListWidgetItem(text)

        # 상태별 색상
        status_colors = {
            "success": "#22c55e",
            "error": "#ef4444",
            "warning": "#f59e0b",
            "running": "#6366f1",
        }
        color = status_colors.get(status, "#94a3b8")
        item.setForeground(
            __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(color)
        )

        self._order_list.insertItem(0, item)

        # 최대 50건 유지
        while self._order_list.count() > 50:
            self._order_list.takeItem(self._order_list.count() - 1)

    def _update_last_order(self, result: str, status: str):
        """마지막 오더 항목의 결과 업데이트"""
        if self._order_list.count() == 0:
            return

        item = self._order_list.item(0)
        old_text = item.text()

        # "실행 중..." 부분을 실제 결과로 교체
        if "\u2192 실행 중..." in old_text:
            short_result = result.split("\n")[0][:60]
            status_icons = {
                "success": "\u2705", "error": "\u274C",
                "warning": "\u26A0\uFE0F", "running": "\u23F3",
            }
            icon = status_icons.get(status, "\u25B6\uFE0F")

            # 기존 텍스트에서 아이콘+결과 교체
            parts = old_text.split(" \u2192 ")
            if len(parts) >= 2:
                # 시간 + 명령 부분에서 이전 아이콘 제거/교체
                cmd_part = parts[0]
                # 기존 아이콘 제거 (⏳)
                for old_icon in status_icons.values():
                    cmd_part = cmd_part.replace(f" {old_icon} ", f" {icon} ")
                new_text = f"{cmd_part} \u2192 {short_result}"
            else:
                new_text = f"{old_text} \u2192 {short_result}"

            item.setText(new_text)

        status_colors = {
            "success": "#22c55e", "error": "#ef4444",
            "warning": "#f59e0b", "running": "#6366f1",
        }
        color = status_colors.get(status, "#94a3b8")
        item.setForeground(
            __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(color)
        )
