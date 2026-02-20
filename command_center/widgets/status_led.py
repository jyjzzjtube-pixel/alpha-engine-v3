# -*- coding: utf-8 -*-
"""상태 LED 인디케이터"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt


class StatusLED(QFrame):
    """● 이름 — 상태 형태의 LED 표시기"""

    def __init__(self, name: str, connected: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self._name = name

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._dot.setStyleSheet(self._dot_style(connected))

        self._lbl_name = QLabel(name)
        self._lbl_name.setStyleSheet("color: #e2e8f0; font-size: 12px; font-weight: 600;")

        self._lbl_status = QLabel()
        self._lbl_status.setStyleSheet("color: #6b7280; font-size: 11px;")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._dot)
        layout.addWidget(self._lbl_name, 1)
        layout.addWidget(self._lbl_status)

        self.set_status(connected)

    def set_status(self, connected: bool, detail: str = ""):
        color = "#22c55e" if connected else "#ef4444"
        status_text = detail if detail else ("정상" if connected else "미연결")
        self._dot.setStyleSheet(self._dot_style(connected))
        self._lbl_status.setText(status_text)
        self._lbl_status.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")

    def set_warning(self, detail: str = ""):
        self._dot.setStyleSheet(
            "background: #f59e0b; border-radius: 5px; border: 2px solid #fbbf24;"
        )
        self._lbl_status.setText(detail or "경고")
        self._lbl_status.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: 600;")

    @staticmethod
    def _dot_style(connected: bool) -> str:
        if connected:
            return "background: #22c55e; border-radius: 5px; border: 2px solid #4ade80;"
        return "background: #ef4444; border-radius: 5px; border: 2px solid #f87171;"
