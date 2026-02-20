# -*- coding: utf-8 -*-
"""사이트 상태 카드 위젯"""
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import pyqtSignal, Qt


class SiteCard(QFrame):
    """개별 사이트 상태 카드"""

    open_clicked = pyqtSignal(str)       # site_id
    deploy_clicked = pyqtSignal(str)     # site_id

    def __init__(self, site_id: str, name: str, url: str,
                 site_type: str = "netlify", parent=None):
        super().__init__(parent)
        self.site_id = site_id
        self.site_type = site_type
        self.setObjectName("card")
        self.setFixedHeight(150)
        self.setMinimumWidth(200)
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
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # 상단: LED + 이름
        top = QHBoxLayout()
        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._dot.setStyleSheet("background: #6b7280; border-radius: 5px;")

        self._lbl_name = QLabel(name)
        self._lbl_name.setStyleSheet("color: #e2e8f0; font-size: 14px; font-weight: 700;")
        top.addWidget(self._dot)
        top.addWidget(self._lbl_name, 1)
        layout.addLayout(top)

        # 응답시간
        self._lbl_time = QLabel("...")
        self._lbl_time.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self._lbl_time)

        # 마지막 배포
        self._lbl_deploy = QLabel("")
        self._lbl_deploy.setStyleSheet("color: #4b5563; font-size: 10px;")
        layout.addWidget(self._lbl_deploy)

        layout.addStretch()

        # 하단 버튼
        btns = QHBoxLayout()
        btns.setSpacing(6)

        btn_open = QPushButton("열기")
        btn_open.setFixedHeight(28)
        btn_open.setStyleSheet("""
            QPushButton { background: #1f2937; color: #94a3b8; border: 1px solid #374151;
                          border-radius: 6px; font-size: 11px; padding: 0 12px; }
            QPushButton:hover { background: #374151; color: #e2e8f0; }
        """)
        btn_open.clicked.connect(lambda: self.open_clicked.emit(self.site_id))
        btns.addWidget(btn_open)

        if site_type == "netlify":
            btn_deploy = QPushButton("배포")
            btn_deploy.setFixedHeight(28)
            btn_deploy.setObjectName("primaryBtn")
            btn_deploy.setStyleSheet("""
                QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #6366f1, stop:1 #a855f7);
                    color: white; border: none; border-radius: 6px;
                    font-size: 11px; font-weight: 600; padding: 0 12px; }
                QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #818cf8, stop:1 #c084fc); }
            """)
            btn_deploy.clicked.connect(lambda: self.deploy_clicked.emit(self.site_id))
            btns.addWidget(btn_deploy)

        layout.addLayout(btns)

    def set_status(self, up: bool, response_time: float = 0.0, detail: str = ""):
        if up:
            self._dot.setStyleSheet("background: #22c55e; border-radius: 5px; border: 2px solid #4ade80;")
            self._lbl_time.setText(f"{response_time:.1f}s" if response_time else "정상")
            self._lbl_time.setStyleSheet("color: #22c55e; font-size: 11px; font-weight: 600;")
        else:
            self._dot.setStyleSheet("background: #ef4444; border-radius: 5px; border: 2px solid #f87171;")
            self._lbl_time.setText(detail or "연결 실패")
            self._lbl_time.setStyleSheet("color: #ef4444; font-size: 11px; font-weight: 600;")

    def set_deploy_info(self, text: str):
        self._lbl_deploy.setText(text)
