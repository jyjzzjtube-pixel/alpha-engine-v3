# -*- coding: utf-8 -*-
"""실시간 로그 뷰어"""
from datetime import datetime
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor


class LiveConsole(QTextEdit):
    """하단 실시간 콘솔 — 색상 코딩 로그 뷰어"""

    MAX_LINES = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(220)
        self.setStyleSheet("""
            QTextEdit {
                background: #0a0e1a;
                color: #94a3b8;
                border: 1px solid #1f2937;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }
        """)

    def log(self, message: str, level: str = "info"):
        colors = {
            "info": "#94a3b8",
            "success": "#22c55e",
            "warning": "#f59e0b",
            "error": "#ef4444",
            "system": "#6366f1",
        }
        color = colors.get(level, "#94a3b8")
        ts = datetime.now().strftime("%H:%M:%S")

        icons = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌", "system": "🔷"}
        icon = icons.get(level, "")

        html = (
            f'<span style="color:#4b5563;">[{ts}]</span> '
            f'<span style="color:{color};">{icon} {message}</span>'
        )
        self.append(html)

        # 라인 수 제한
        doc = self.document()
        if doc.blockCount() > self.MAX_LINES:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.KeepAnchor, 50)
            cursor.removeSelectedText()

        # 자동 스크롤
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_console(self):
        self.clear()
