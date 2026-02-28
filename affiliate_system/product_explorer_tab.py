# -*- coding: utf-8 -*-
"""
쿠팡 상품 탐색 탭
===================
쿠팡파트너스 API로 상품 검색/탐색 → 쇼핑쇼츠 탭으로 전달
인기 카테고리 브라우징 + 키워드 검색 + 상품 상세 보기
"""
from __future__ import annotations

import os
import sys
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QProgressBar, QComboBox, QGroupBox,
    QFrame, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QSize
from PyQt6.QtGui import QFont, QColor, QPixmap, QImage

from affiliate_system.config import (
    COUPANG_ACCESS_KEY, COUPANG_SECRET_KEY, COUPANG_PARTNER_ID,
)


# ── 인기 검색 카테고리 (쿠팡 트렌딩) ──
TRENDING_CATEGORIES = [
    {"name": "전체 인기상품", "keyword": "인기상품", "icon": "🔥"},
    {"name": "뷰티/미용", "keyword": "뷰티 인기상품", "icon": "💄"},
    {"name": "가전/디지털", "keyword": "가전 인기상품", "icon": "📱"},
    {"name": "식품/건강", "keyword": "건강식품 인기", "icon": "🥗"},
    {"name": "생활/주방", "keyword": "주방용품 인기", "icon": "🏠"},
    {"name": "패션/의류", "keyword": "패션 인기상품", "icon": "👗"},
    {"name": "유아/출산", "keyword": "육아용품 인기", "icon": "👶"},
    {"name": "스포츠/아웃도어", "keyword": "스포츠용품 인기", "icon": "⚽"},
    {"name": "반려동물", "keyword": "반려동물 인기상품", "icon": "🐶"},
    {"name": "다이어트", "keyword": "다이어트 보조제", "icon": "💪"},
    {"name": "헤어/바디", "keyword": "헤어케어 인기", "icon": "💇"},
    {"name": "홈인테리어", "keyword": "인테리어 인기", "icon": "🛋️"},
]


# ── 검색 워커 ──
class ProductSearchWorker(QThread):
    """쿠팡 상품 검색 백그라운드 워커"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)  # Product 리스트
    error = pyqtSignal(str)

    def __init__(self, keyword: str, limit: int = 20):
        super().__init__()
        self.keyword = keyword
        self.limit = limit

    def run(self):
        try:
            self.progress.emit(f"'{self.keyword}' 검색 중...")
            from affiliate_system.coupang_scraper import CoupangScraper
            scraper = CoupangScraper()

            # search_products는 자동으로 API → 웹 스크래핑 → 네이버 쇼핑 폴백
            products = scraper.search_products(self.keyword, limit=self.limit)

            if products:
                self.progress.emit(f"✅ {len(products)}개 상품 발견")
                # Product 객체를 dict로 변환
                result = []
                for p in products:
                    result.append({
                        "title": p.title or "제목 없음",
                        "price": p.price or "가격 미정",
                        "image_url": p.image_urls[0] if p.image_urls else "",
                        "affiliate_link": p.affiliate_link or p.url or "",
                        "url": p.url or "",
                        "description": p.description or "",
                    })
                self.finished.emit(result)
            else:
                self.progress.emit("검색 결과 없음 — 다른 키워드를 시도해보세요")
                self.finished.emit([])

        except Exception as e:
            self.error.emit(f"검색 에러: {e}")


# ── 이미지 다운로드 워커 ──
class ImageDownloadWorker(QThread):
    """상품 이미지 다운로드"""
    finished = pyqtSignal(int, QPixmap)  # row, pixmap

    def __init__(self, row: int, url: str):
        super().__init__()
        self.row = row
        self.url = url

    def run(self):
        try:
            import requests
            resp = requests.get(self.url, timeout=10)
            if resp.status_code == 200:
                img = QImage()
                img.loadFromData(resp.content)
                if not img.isNull():
                    pix = QPixmap.fromImage(img).scaled(
                        80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.finished.emit(self.row, pix)
        except Exception:
            pass


class ProductExplorerTab(QWidget):
    """쿠팡 상품 탐색 탭 — 상품 검색 → 쇼핑쇼츠 연동"""

    # 시그널: 쇼핑쇼츠 탭으로 상품 전달
    product_selected = pyqtSignal(dict)  # {title, price, affiliate_link, ...}

    def __init__(self):
        super().__init__()
        self._worker = None
        self._img_workers = []
        self._products = []  # 현재 검색 결과
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ── 헤더 ──
        header = QLabel("🛒 쿠팡 상품 탐색")
        header.setStyleSheet(
            "font-size: 22px; font-weight: 900; color: #f9fafb; "
            "background: transparent; padding: 0; margin-bottom: 2px;"
        )
        sub = QLabel("쿠팡파트너스 인기상품 검색 → 상품 선택 → 쇼핑쇼츠/블로그 자동 생성")
        sub.setStyleSheet("font-size: 12px; color: #6b7280; background: transparent;")
        layout.addWidget(header)
        layout.addWidget(sub)

        # ── 메인 스플리터 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ===== 왼쪽: 카테고리 + 검색 =====
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        # 검색 바
        search_group = QGroupBox("상품 검색")
        search_group.setStyleSheet(self._group_style())
        sg = QVBoxLayout(search_group)
        sg.setSpacing(8)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("상품명, 키워드 검색 (예: 에어팟 프로, 다이슨)")
        self.search_input.setStyleSheet(self._input_style())
        self.search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.search_input, 1)

        self.btn_search = QPushButton("🔍 검색")
        self.btn_search.setFixedSize(90, 36)
        self.btn_search.setStyleSheet(self._btn_accent_style())
        self.btn_search.clicked.connect(self._do_search)
        search_row.addWidget(self.btn_search)
        sg.addLayout(search_row)

        # 검색 개수
        count_row = QHBoxLayout()
        count_row.addWidget(self._make_label("결과 수"))
        self.limit_combo = QComboBox()
        self.limit_combo.addItems(["10", "20", "30", "50"])
        self.limit_combo.setCurrentIndex(1)  # 20개 기본
        self.limit_combo.setStyleSheet(self._input_style())
        self.limit_combo.setFixedWidth(80)
        count_row.addWidget(self.limit_combo)
        count_row.addStretch()
        sg.addLayout(count_row)

        left_layout.addWidget(search_group)

        # 인기 카테고리 버튼들
        cat_label = QLabel("📊 인기 카테고리")
        cat_label.setStyleSheet(
            "color: #e5e7eb; font-weight: 700; font-size: 13px; "
            "background: transparent; margin-top: 4px;"
        )
        left_layout.addWidget(cat_label)

        # 카테고리 그리드 (스크롤 가능)
        cat_scroll = QScrollArea()
        cat_scroll.setWidgetResizable(True)
        cat_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
        """)
        cat_widget = QWidget()
        cat_grid = QVBoxLayout(cat_widget)
        cat_grid.setContentsMargins(0, 0, 0, 0)
        cat_grid.setSpacing(4)

        for cat in TRENDING_CATEGORIES:
            btn = QPushButton(f"{cat['icon']}  {cat['name']}")
            btn.setFixedHeight(36)
            btn.setStyleSheet("""
                QPushButton {
                    background: #111827; color: #d1d5db;
                    border: 1px solid #1f2937; border-radius: 8px;
                    font-weight: 600; font-size: 12px;
                    text-align: left; padding-left: 14px;
                }
                QPushButton:hover {
                    background: #1e293b; border-color: #6366f1;
                    color: #f9fafb;
                }
            """)
            btn.clicked.connect(lambda checked, kw=cat["keyword"]: self._search_category(kw))
            cat_grid.addWidget(btn)

        cat_grid.addStretch()
        cat_scroll.setWidget(cat_widget)
        left_layout.addWidget(cat_scroll, 1)

        # API 상태 — 웹 스크래핑 폴백이 있으므로 항상 사용 가능
        api_label = QLabel("🟢 API 연결됨" if COUPANG_ACCESS_KEY else "🔵 웹 검색 모드")
        api_label.setStyleSheet(
            f"color: {'#10b981' if COUPANG_ACCESS_KEY else '#60a5fa'}; "
            "font-size: 11px; font-weight: 600; background: transparent;"
        )
        left_layout.addWidget(api_label)

        splitter.addWidget(left)

        # ===== 오른쪽: 상품 목록 + 상세 =====
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        # 상태바
        self.status_label = QLabel("카테고리를 선택하거나 키워드를 검색하세요")
        self.status_label.setStyleSheet(
            "color: #9ca3af; font-size: 12px; font-weight: 600; background: transparent;"
        )
        right_layout.addWidget(self.status_label)

        # 프로그레스
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, 0)  # 무한 로딩
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { background: #1f2937; border: none; border-radius: 2px; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #6366f1, stop:1 #a78bfa);
                border-radius: 2px;
            }
        """)
        right_layout.addWidget(self.progress_bar)

        # 상품 테이블
        self.product_table = QTableWidget()
        self.product_table.setColumnCount(5)
        self.product_table.setHorizontalHeaderLabels([
            "상품명", "가격", "제휴링크", "쇼츠 생성", "블로그 생성"
        ])
        self.product_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.product_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.product_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.product_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.product_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.setShowGrid(False)
        self.product_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.product_table.setAlternatingRowColors(True)
        self.product_table.setStyleSheet("""
            QTableWidget {
                background: #111827; color: #e5e7eb;
                border: 1px solid #1f2937; border-radius: 8px;
                font-size: 12px; gridline-color: #1f2937;
            }
            QTableWidget::item {
                padding: 8px 6px; border-bottom: 1px solid #1a1f35;
            }
            QTableWidget::item:selected {
                background: #1e293b; color: #f9fafb;
            }
            QTableWidget::item:alternate { background: #0d1117; }
            QHeaderView::section {
                background: #0a0e1a; color: #9ca3af;
                border: none; padding: 10px 6px;
                font-weight: 700; font-size: 12px;
                border-bottom: 2px solid #6366f1;
            }
        """)
        self.product_table.setRowCount(0)
        right_layout.addWidget(self.product_table, 1)

        # 선택 상품 상세 정보
        detail_group = QGroupBox("선택 상품 정보")
        detail_group.setStyleSheet(self._group_style())
        dg = QVBoxLayout(detail_group)
        dg.setSpacing(6)

        self.detail_title = QLabel("상품을 선택하세요")
        self.detail_title.setStyleSheet(
            "font-size: 15px; font-weight: 800; color: #f9fafb; background: transparent;"
        )
        self.detail_title.setWordWrap(True)
        dg.addWidget(self.detail_title)

        detail_row = QHBoxLayout()
        self.detail_price = QLabel("")
        self.detail_price.setStyleSheet(
            "font-size: 18px; font-weight: 900; color: #f472b6; background: transparent;"
        )
        detail_row.addWidget(self.detail_price)
        detail_row.addStretch()

        self.detail_link = QLabel("")
        self.detail_link.setStyleSheet(
            "font-size: 11px; color: #818cf8; background: transparent;"
        )
        self.detail_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_row.addWidget(self.detail_link)
        dg.addLayout(detail_row)

        # 액션 버튼
        action_row = QHBoxLayout()
        self.btn_to_shorts = QPushButton("🎬 쇼핑쇼츠 만들기")
        self.btn_to_shorts.setFixedHeight(42)
        self.btn_to_shorts.setEnabled(False)
        self.btn_to_shorts.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6366f1, stop:1 #8b5cf6);
                color: white; border: none; border-radius: 10px;
                font-weight: 800; font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c7ff7, stop:1 #a78bfa);
            }
            QPushButton:disabled { background: #374151; color: #6b7280; }
        """)
        self.btn_to_shorts.clicked.connect(self._send_to_shorts)
        action_row.addWidget(self.btn_to_shorts)

        self.btn_to_blog = QPushButton("📝 블로그 글 만들기")
        self.btn_to_blog.setFixedHeight(42)
        self.btn_to_blog.setEnabled(False)
        self.btn_to_blog.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #10b981, stop:1 #059669);
                color: white; border: none; border-radius: 10px;
                font-weight: 800; font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #34d399, stop:1 #10b981);
            }
            QPushButton:disabled { background: #374151; color: #6b7280; }
        """)
        self.btn_to_blog.clicked.connect(self._send_to_blog)
        action_row.addWidget(self.btn_to_blog)

        self.btn_copy_link = QPushButton("🔗 링크 복사")
        self.btn_copy_link.setFixedHeight(42)
        self.btn_copy_link.setFixedWidth(120)
        self.btn_copy_link.setEnabled(False)
        self.btn_copy_link.setStyleSheet(self._btn_secondary_style() + """
            QPushButton { font-size: 13px; font-weight: 700; border-radius: 10px; }
        """)
        self.btn_copy_link.clicked.connect(self._copy_link)
        action_row.addWidget(self.btn_copy_link)

        dg.addLayout(action_row)
        right_layout.addWidget(detail_group)

        splitter.addWidget(right)
        splitter.setSizes([280, 620])
        layout.addWidget(splitter, 1)

        # 테이블 선택 시그널
        self.product_table.itemSelectionChanged.connect(self._on_product_selected)

    # ── 검색 실행 ──
    def _do_search(self):
        keyword = self.search_input.text().strip()
        if not keyword:
            QMessageBox.warning(self, "입력 오류", "검색어를 입력하세요.")
            return
        self._execute_search(keyword)

    def _search_category(self, keyword: str):
        """카테고리 버튼 클릭 → 검색"""
        self.search_input.setText(keyword)
        self._execute_search(keyword)

    def _execute_search(self, keyword: str):
        """검색 실행"""
        if self._worker and self._worker.isRunning():
            return

        limit = int(self.limit_combo.currentText())

        self.btn_search.setEnabled(False)
        self.btn_search.setText("⏳")
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"'{keyword}' 검색 중...")
        self.product_table.setRowCount(0)
        self._products = []

        self._worker = ProductSearchWorker(keyword, limit)
        self._worker.progress.connect(self._on_search_progress)
        self._worker.finished.connect(self._on_search_done)
        self._worker.error.connect(self._on_search_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_search_progress(self, msg):
        self.status_label.setText(msg)

    @pyqtSlot(list)
    def _on_search_done(self, products: list):
        self._products = products
        self.btn_search.setEnabled(True)
        self.btn_search.setText("🔍 검색")
        self.progress_bar.setVisible(False)

        if not products:
            self.status_label.setText("검색 결과 없음 — 다른 키워드를 시도하세요")
            self.product_table.setRowCount(0)
            return

        self.status_label.setText(
            f"✅ {len(products)}개 상품 (클릭하여 선택 → 쇼츠/블로그 생성)"
        )
        self._populate_table(products)

    @pyqtSlot(str)
    def _on_search_error(self, msg):
        self.btn_search.setEnabled(True)
        self.btn_search.setText("🔍 검색")
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"⚠️ {msg}")

    def _populate_table(self, products: list):
        """검색 결과를 테이블에 표시"""
        self.product_table.setRowCount(len(products))

        for i, p in enumerate(products):
            # 상품명
            title_item = QTableWidgetItem(p["title"])
            title_item.setToolTip(p["title"])
            self.product_table.setItem(i, 0, title_item)

            # 가격
            price_item = QTableWidgetItem(p["price"])
            price_item.setForeground(QColor("#f472b6"))
            price_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.product_table.setItem(i, 1, price_item)

            # 제휴링크 (축약)
            link = p.get("affiliate_link", "")
            link_short = link[:40] + "..." if len(link) > 40 else link
            link_item = QTableWidgetItem(link_short)
            link_item.setForeground(QColor("#818cf8"))
            link_item.setToolTip(link)
            self.product_table.setItem(i, 2, link_item)

            # 쇼츠 생성 버튼
            shorts_btn = QPushButton("🎬 쇼츠")
            shorts_btn.setStyleSheet("""
                QPushButton {
                    background: #4f46e5; color: white;
                    border: none; border-radius: 6px;
                    font-weight: 700; font-size: 11px; padding: 4px 10px;
                }
                QPushButton:hover { background: #6366f1; }
            """)
            shorts_btn.clicked.connect(
                lambda checked, idx=i: self._quick_send_shorts(idx)
            )
            self.product_table.setCellWidget(i, 3, shorts_btn)

            # 블로그 생성 버튼
            blog_btn = QPushButton("📝 블로그")
            blog_btn.setStyleSheet("""
                QPushButton {
                    background: #059669; color: white;
                    border: none; border-radius: 6px;
                    font-weight: 700; font-size: 11px; padding: 4px 10px;
                }
                QPushButton:hover { background: #10b981; }
            """)
            blog_btn.clicked.connect(
                lambda checked, idx=i: self._quick_send_blog(idx)
            )
            self.product_table.setCellWidget(i, 4, blog_btn)

        # 행 높이
        for i in range(len(products)):
            self.product_table.setRowHeight(i, 48)

    # ── 상품 선택 ──
    def _on_product_selected(self):
        """테이블에서 상품 선택 시 상세 정보 표시"""
        rows = self.product_table.selectionModel().selectedRows()
        if not rows:
            return

        idx = rows[0].row()
        if idx < 0 or idx >= len(self._products):
            return

        p = self._products[idx]
        self.detail_title.setText(p["title"])
        self.detail_price.setText(p["price"])

        link = p.get("affiliate_link", "")
        self.detail_link.setText(link[:80] + "..." if len(link) > 80 else link)

        self.btn_to_shorts.setEnabled(True)
        self.btn_to_blog.setEnabled(True)
        self.btn_copy_link.setEnabled(True)

    def _get_selected_product(self) -> Optional[dict]:
        """현재 선택된 상품 반환"""
        rows = self.product_table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._products):
            return self._products[idx]
        return None

    # ── 쇼핑쇼츠 전달 ──
    def _send_to_shorts(self):
        """선택 상품 → 쇼핑쇼츠 탭으로 전달"""
        p = self._get_selected_product()
        if not p:
            QMessageBox.warning(self, "선택 오류", "상품을 먼저 선택하세요.")
            return
        self.product_selected.emit({
            "action": "shorts",
            "title": p["title"],
            "price": p["price"],
            "affiliate_link": p.get("affiliate_link", ""),
            "description": p.get("description", ""),
            "image_url": p.get("image_url", ""),
        })
        self.status_label.setText(f"✅ '{p['title'][:30]}' → 쇼핑쇼츠 탭으로 전달됨")

    def _quick_send_shorts(self, idx: int):
        """테이블 내 쇼츠 버튼 클릭"""
        if 0 <= idx < len(self._products):
            p = self._products[idx]
            self.product_selected.emit({
                "action": "shorts",
                "title": p["title"],
                "price": p["price"],
                "affiliate_link": p.get("affiliate_link", ""),
                "description": p.get("description", ""),
                "image_url": p.get("image_url", ""),
            })
            self.status_label.setText(f"✅ '{p['title'][:30]}' → 쇼핑쇼츠 탭으로 전달됨")

    # ── 블로그 전달 ──
    def _send_to_blog(self):
        """선택 상품 → 블로그 생성 (작업센터 연동)"""
        p = self._get_selected_product()
        if not p:
            QMessageBox.warning(self, "선택 오류", "상품을 먼저 선택하세요.")
            return
        self.product_selected.emit({
            "action": "blog",
            "title": p["title"],
            "price": p["price"],
            "affiliate_link": p.get("affiliate_link", ""),
            "description": p.get("description", ""),
            "image_url": p.get("image_url", ""),
        })
        self.status_label.setText(f"✅ '{p['title'][:30]}' → 블로그 생성 준비")

    def _quick_send_blog(self, idx: int):
        """테이블 내 블로그 버튼 클릭"""
        if 0 <= idx < len(self._products):
            p = self._products[idx]
            self.product_selected.emit({
                "action": "blog",
                "title": p["title"],
                "price": p["price"],
                "affiliate_link": p.get("affiliate_link", ""),
                "description": p.get("description", ""),
                "image_url": p.get("image_url", ""),
            })
            self.status_label.setText(f"✅ '{p['title'][:30]}' → 블로그 생성 준비")

    # ── 링크 복사 ──
    def _copy_link(self):
        """제휴 링크 클립보드 복사"""
        p = self._get_selected_product()
        if not p:
            return
        link = p.get("affiliate_link", "")
        if link:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(link)
            self.status_label.setText("📋 제휴 링크가 클립보드에 복사되었습니다")

    # ── 스타일 헬퍼 ──
    def _make_label(self, text):
        lbl = QLabel(text)
        lbl.setFixedWidth(65)
        lbl.setStyleSheet(
            "color: #9ca3af; font-weight: 700; font-size: 13px; background: transparent;"
        )
        return lbl

    def _group_style(self):
        return """
            QGroupBox {
                font-weight: 700; font-size: 13px; color: #e5e7eb;
                border: 1px solid #1f2937; border-radius: 10px;
                padding: 18px 14px 14px 14px; margin-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 14px;
                padding: 0 6px; color: #818cf8;
            }
        """

    def _input_style(self):
        return """
            QLineEdit, QComboBox {
                background: #111827; color: #f9fafb;
                border: 1px solid #374151; border-radius: 8px;
                padding: 8px 12px; font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus { border-color: #6366f1; }
        """

    def _btn_accent_style(self):
        return """
            QPushButton {
                background: #4f46e5; color: white;
                border: none; border-radius: 8px;
                font-weight: 700; font-size: 13px;
            }
            QPushButton:hover { background: #6366f1; }
            QPushButton:disabled { background: #374151; color: #6b7280; }
        """

    def _btn_secondary_style(self):
        return """
            QPushButton {
                background: #1f2937; color: #e5e7eb;
                border: 1px solid #374151; border-radius: 8px;
                font-weight: 600; font-size: 12px; padding: 6px 12px;
            }
            QPushButton:hover { background: #374151; }
            QPushButton:disabled { color: #4b5563; }
        """
