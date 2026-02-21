# -*- coding: utf-8 -*-
"""
통합 검색 탭 — 코드, API 사용, 알림, 오더, 배포 통합 검색
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QSplitter, QLabel
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence, QColor

from ..workers import SearchWorker
from ..models import SearchResult


# ── 검색 소스 정의 ──
SEARCH_SOURCES = [
    {"key": "code", "label": "코드", "icon": "\U0001F4C1"},
    {"key": "api_usage", "label": "API사용", "icon": "\U0001F4CA"},
    {"key": "alerts", "label": "알림", "icon": "\U0001F514"},
    {"key": "orders", "label": "오더", "icon": "\U0001F4CB"},
    {"key": "deploys", "label": "배포", "icon": "\U0001F680"},
]


class SearchTab(QWidget):
    """통합 검색 탭 — 디바운스 + 필터 + 프리뷰"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_worker: SearchWorker | None = None
        self._all_results: dict = {}
        self._filter_checks: dict[str, QCheckBox] = {}
        self._init_ui()
        self._setup_shortcuts()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 제목 ──
        top = QHBoxLayout()
        lbl_title = QLabel("통합 검색")
        lbl_title.setObjectName("sectionTitle")
        top.addWidget(lbl_title)
        top.addStretch()

        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet("color: #6b7280; font-size: 12px;")
        top.addWidget(self._lbl_count)

        layout.addLayout(top)

        # ── 검색 입력 ──
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("검색어 입력... (Ctrl+F)")
        self._search_input.setFixedHeight(42)
        self._search_input.setStyleSheet("""
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
        self._search_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._search_input)

        # ── 필터 체크박스 ──
        filter_row = QHBoxLayout()
        filter_row.setSpacing(16)

        lbl_filter = QLabel("필터:")
        lbl_filter.setStyleSheet("color: #6b7280; font-size: 12px;")
        filter_row.addWidget(lbl_filter)

        for src in SEARCH_SOURCES:
            cb = QCheckBox(f"{src['icon']} {src['label']}")
            cb.setChecked(True)
            cb.setStyleSheet("""
                QCheckBox {
                    color: #e2e8f0;
                    font-size: 12px;
                    spacing: 4px;
                }
                QCheckBox::indicator {
                    width: 16px; height: 16px;
                    border-radius: 3px;
                    border: 2px solid #374151;
                    background: #1a2332;
                }
                QCheckBox::indicator:checked {
                    background: #6366f1;
                    border-color: #6366f1;
                }
            """)
            cb.stateChanged.connect(self._update_filters)
            filter_row.addWidget(cb)
            self._filter_checks[src["key"]] = cb

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # ── 디바운스 타이머 (400ms) ──
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(400)
        self._debounce_timer.timeout.connect(self._on_search)

        # ── 결과 영역: 트리 + 프리뷰 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # 좌: 검색 결과 트리
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["검색 결과"])
        self._tree.setColumnCount(1)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 8px;
                color: #e2e8f0;
                font-size: 12px;
                outline: none;
            }
            QTreeWidget::item {
                padding: 4px 8px;
                border-bottom: 1px solid #0f172a;
            }
            QTreeWidget::item:selected {
                background: #1e3a5f;
            }
            QTreeWidget::item:hover {
                background: #1f2937;
            }
            QTreeWidget::branch {
                background: #111827;
            }
            QHeaderView::section {
                background: #1f2937;
                color: #94a3b8;
                border: none;
                padding: 8px 12px;
                font-weight: 700;
                font-size: 11px;
                text-transform: uppercase;
            }
        """)
        self._tree.currentItemChanged.connect(self._on_item_selected)
        splitter.addWidget(self._tree)

        # 우: 프리뷰 패널
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setStyleSheet("""
            QTextEdit {
                background: #0f172a;
                color: #e2e8f0;
                border: 1px solid #1f2937;
                border-radius: 8px;
                padding: 12px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        self._preview.setHtml(
            '<p style="color: #6b7280; font-style: italic;">'
            '검색 결과를 선택하면 상세 내용이 여기에 표시됩니다.</p>'
        )
        splitter.addWidget(self._preview)
        splitter.setSizes([500, 400])

        layout.addWidget(splitter, 1)

    def _setup_shortcuts(self):
        """키보드 단축키"""
        shortcut_f = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_f.activated.connect(self._focus_search)

    def _focus_search(self):
        """검색 입력에 포커스"""
        self._search_input.setFocus()
        self._search_input.selectAll()

    # ── 검색 로직 ──

    def _on_text_changed(self):
        """입력 변경 시 디바운스 타이머 리셋"""
        self._debounce_timer.stop()
        self._debounce_timer.start()

    def _on_search(self):
        """검색 실행 (디바운스 후)"""
        keyword = self._search_input.text().strip()
        if len(keyword) < 2:
            self._tree.clear()
            self._lbl_count.setText("")
            self._preview.setHtml(
                '<p style="color: #6b7280;">2글자 이상 입력하세요.</p>'
            )
            return

        # 활성 필터 확인
        active_sources = [
            key for key, cb in self._filter_checks.items() if cb.isChecked()
        ]
        if not active_sources:
            self._tree.clear()
            self._lbl_count.setText("필터를 선택하세요")
            return

        # 이전 워커 정리
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.quit()
            self._search_worker.wait(1000)

        self._lbl_count.setText("검색 중...")
        self._search_worker = SearchWorker(keyword=keyword, sources=active_sources)
        self._search_worker.result_ready.connect(self._on_results)
        self._search_worker.error.connect(
            lambda err: self._lbl_count.setText(f"오류: {err}")
        )
        self._search_worker.start()

    def _on_results(self, results: dict):
        """검색 결과 수신 → 트리 업데이트"""
        self._all_results = results
        self._populate_tree(results)

    def _populate_tree(self, results: dict):
        """검색 결과를 트리에 채우기"""
        self._tree.clear()
        total = 0

        # 소스별 아이콘/라벨 매핑
        source_meta = {s["key"]: s for s in SEARCH_SOURCES}

        for source_key, items in results.items():
            if not items:
                continue

            # 필터 확인
            if source_key in self._filter_checks:
                if not self._filter_checks[source_key].isChecked():
                    continue

            meta = source_meta.get(source_key, {})
            icon = meta.get("icon", "")
            label = meta.get("label", source_key)
            count = len(items)
            total += count

            # 카테고리 노드
            cat_item = QTreeWidgetItem(self._tree)
            cat_item.setText(0, f"{icon} {label} ({count}건)")
            cat_item.setForeground(0, QColor("#94a3b8"))
            cat_item.setExpanded(True)
            cat_item.setData(0, Qt.ItemDataRole.UserRole, None)

            # 개별 결과
            for sr in items:
                child = QTreeWidgetItem(cat_item)
                child.setText(0, f"{sr.title} \u2014 {sr.detail[:80]}")

                # 소스별 색상
                color_map = {
                    "code": "#6366f1",
                    "api_usage": "#a855f7",
                    "alerts": "#f59e0b",
                    "orders": "#22c55e",
                    "deploys": "#3b82f6",
                }
                child.setForeground(
                    0, QColor(color_map.get(source_key, "#e2e8f0"))
                )
                child.setData(0, Qt.ItemDataRole.UserRole, sr)

        self._lbl_count.setText(f"{total}건 검색됨")

        if total == 0:
            empty = QTreeWidgetItem(self._tree)
            empty.setText(0, "검색 결과가 없습니다.")
            empty.setForeground(0, QColor("#6b7280"))

    def _on_item_selected(self, current: QTreeWidgetItem, previous: QTreeWidgetItem):
        """트리 아이템 선택 → 프리뷰 업데이트"""
        if not current:
            return

        sr = current.data(0, Qt.ItemDataRole.UserRole)
        if sr is None:
            # 카테고리 노드 선택
            self._preview.setHtml(
                '<p style="color: #6b7280;">개별 항목을 선택하세요.</p>'
            )
            return

        if not isinstance(sr, SearchResult):
            return

        # 코드 검색인 경우: 파일 내용 + 하이라이팅
        if sr.source == "code" and sr.file_path:
            self._show_code_preview(sr)
        else:
            self._show_general_preview(sr)

    def _show_code_preview(self, sr: SearchResult):
        """코드 검색 결과 프리뷰 — 주변 줄 표시"""
        file_path = sr.file_path
        line_num = sr.line_number

        html_parts = [
            f'<p style="color: #6366f1; font-weight: 700; margin-bottom: 8px;">'
            f'{sr.title}</p>',
            f'<p style="color: #6b7280; font-size: 11px; margin-bottom: 12px;">'
            f'{file_path}</p>',
        ]

        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()

            start = max(0, line_num - 6)
            end = min(len(lines), line_num + 5)

            html_parts.append('<pre style="margin: 0; line-height: 1.6;">')
            for i in range(start, end):
                ln = i + 1
                line_text = lines[i].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                is_match = (ln == line_num)

                if is_match:
                    html_parts.append(
                        f'<span style="background: #1e3a5f; display: block; '
                        f'border-left: 3px solid #6366f1; padding-left: 8px;">'
                        f'<span style="color: #f59e0b; min-width: 40px; '
                        f'display: inline-block;">{ln:4d}</span> '
                        f'<span style="color: #e2e8f0; font-weight: 700;">'
                        f'{line_text}</span></span>'
                    )
                else:
                    html_parts.append(
                        f'<span style="color: #4b5563;">{ln:4d}</span> '
                        f'<span style="color: #94a3b8;">{line_text}</span><br>'
                    )

            html_parts.append("</pre>")

        except Exception as e:
            html_parts.append(
                f'<p style="color: #ef4444;">파일 읽기 실패: {e}</p>'
            )

        self._preview.setHtml("".join(html_parts))

    def _show_general_preview(self, sr: SearchResult):
        """일반 검색 결과 프리뷰"""
        source_labels = {
            "api_usage": "API 사용 내역",
            "alerts": "알림",
            "orders": "오더",
            "deploys": "배포",
        }
        source_colors = {
            "api_usage": "#a855f7",
            "alerts": "#f59e0b",
            "orders": "#22c55e",
            "deploys": "#3b82f6",
        }

        source_label = source_labels.get(sr.source, sr.source)
        source_color = source_colors.get(sr.source, "#94a3b8")

        html = (
            f'<p style="color: {source_color}; font-weight: 700; '
            f'font-size: 13px; margin-bottom: 8px;">'
            f'{sr.icon} {source_label}</p>'
            f'<div style="background: #111827; border-radius: 8px; '
            f'padding: 12px; margin-bottom: 8px;">'
            f'<p style="color: #e2e8f0; font-size: 14px; font-weight: 600; '
            f'margin-bottom: 4px;">{sr.title}</p>'
            f'<p style="color: #94a3b8; font-size: 12px;">{sr.detail}</p>'
            f'</div>'
        )

        if sr.timestamp:
            html += (
                f'<p style="color: #6b7280; font-size: 11px;">'
                f'시간: {sr.timestamp}</p>'
            )

        self._preview.setHtml(html)

    def _update_filters(self):
        """필터 변경 시 결과 재필터링"""
        if self._all_results:
            self._populate_tree(self._all_results)
