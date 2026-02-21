# -*- coding: utf-8 -*-
"""재사용 MetricCard 위젯"""
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class MetricCard(QFrame):
    """대시보드 메트릭 카드 — 좌측 컬러 악센트 + 제목/값/부제"""

    def __init__(self, title: str, value: str = "0", subtitle: str = "",
                 accent: str = "#6366f1", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedHeight(130)
        self.setStyleSheet(f"""
            QFrame#card {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #111827, stop:1 #0f172a);
                border-left: 4px solid {accent};
                border-radius: 12px;
                border: 1px solid #1f2937;
                border-left: 4px solid {accent};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(4)

        self._lbl_title = QLabel(title)
        self._lbl_title.setObjectName("metricLabel")
        self._lbl_title.setStyleSheet("color: #6b7280; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;")

        self._lbl_value = QLabel(value)
        self._lbl_value.setObjectName("metricValue")
        self._lbl_value.setStyleSheet("color: #f9fafb; font-size: 28px; font-weight: 900;")

        self._lbl_sub = QLabel(subtitle)
        self._lbl_sub.setStyleSheet("color: #94a3b8; font-size: 11px;")

        layout.addWidget(self._lbl_title)
        layout.addWidget(self._lbl_value)
        layout.addWidget(self._lbl_sub)
        layout.addStretch()

    def set_value(self, value: str, subtitle: str = None):
        self._lbl_value.setText(value)
        if subtitle is not None:
            self._lbl_sub.setText(subtitle)

    def set_accent(self, color: str):
        self.setStyleSheet(f"""
            QFrame#card {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #111827, stop:1 #0f172a);
                border: 1px solid #1f2937;
                border-left: 4px solid {color};
                border-radius: 12px;
            }}
        """)
