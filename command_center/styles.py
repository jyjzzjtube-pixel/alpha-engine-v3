# -*- coding: utf-8 -*-
"""
다크 테마 스타일시트 — 기존 affiliate_system UI 통일
"""

# ── 컬러 팔레트 ──
COLORS = {
    "bg_primary": "#0a0e1a",
    "bg_card": "#111827",
    "bg_input": "#1a2332",
    "border": "#1f2937",
    "border_focus": "#6366f1",
    "text_primary": "#e2e8f0",
    "text_secondary": "#94a3b8",
    "text_muted": "#6b7280",
    "accent": "#6366f1",
    "accent_purple": "#a855f7",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "info": "#3b82f6",
}

DARK_STYLESHEET = """
/* ═══ Global ═══ */
QMainWindow, QWidget {
    background-color: #0a0e1a;
    color: #e2e8f0;
    font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
    font-size: 13px;
}

/* ═══ Tab Widget ═══ */
QTabWidget::pane {
    border: 1px solid #1f2937;
    background: #0a0e1a;
    border-radius: 8px;
}
QTabBar::tab {
    background: #111827;
    color: #94a3b8;
    padding: 10px 22px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    font-size: 13px;
}
QTabBar::tab:selected {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6366f1, stop:1 #a855f7);
    color: white;
}
QTabBar::tab:hover:!selected {
    background: #1f2937;
    color: #e2e8f0;
}

/* ═══ Scroll Area ═══ */
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #111827;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #374151;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #6366f1;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* ═══ Buttons ═══ */
QPushButton {
    background: #1f2937;
    color: #e2e8f0;
    border: 1px solid #374151;
    padding: 8px 18px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton:hover {
    background: #374151;
    border-color: #6366f1;
}
QPushButton:pressed {
    background: #6366f1;
}
QPushButton#primaryBtn {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6366f1, stop:1 #a855f7);
    border: none;
    color: white;
}
QPushButton#primaryBtn:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #818cf8, stop:1 #c084fc);
}
QPushButton#dangerBtn {
    background: #7f1d1d;
    border-color: #ef4444;
    color: #fca5a5;
}
QPushButton#dangerBtn:hover {
    background: #ef4444;
    color: white;
}
QPushButton#successBtn {
    background: #14532d;
    border-color: #22c55e;
    color: #86efac;
}
QPushButton#successBtn:hover {
    background: #22c55e;
    color: white;
}

/* ═══ Inputs ═══ */
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #1a2332;
    color: #e2e8f0;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 13px;
    selection-background-color: #6366f1;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #6366f1;
}

/* ═══ Table ═══ */
QTableWidget {
    background: #111827;
    alternate-background-color: #0f172a;
    border: 1px solid #1f2937;
    border-radius: 8px;
    gridline-color: #1f2937;
    color: #e2e8f0;
    font-size: 12px;
}
QTableWidget::item {
    padding: 6px 10px;
}
QTableWidget::item:selected {
    background: #1e3a5f;
    color: #e2e8f0;
}
QHeaderView::section {
    background: #1f2937;
    color: #94a3b8;
    border: none;
    padding: 8px 10px;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
}

/* ═══ ComboBox ═══ */
QComboBox {
    background: #1a2332;
    color: #e2e8f0;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
}
QComboBox::drop-down {
    border: none;
    width: 30px;
}
QComboBox QAbstractItemView {
    background: #1f2937;
    color: #e2e8f0;
    border: 1px solid #374151;
    selection-background-color: #6366f1;
}

/* ═══ CheckBox ═══ */
QCheckBox {
    color: #e2e8f0;
    spacing: 8px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #374151;
    background: #1a2332;
}
QCheckBox::indicator:checked {
    background: #6366f1;
    border-color: #6366f1;
}

/* ═══ Progress Bar ═══ */
QProgressBar {
    background: #1f2937;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    font-size: 10px;
    color: #94a3b8;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6366f1, stop:1 #a855f7);
    border-radius: 6px;
}

/* ═══ Labels ═══ */
QLabel#sectionTitle {
    color: #e2e8f0;
    font-size: 16px;
    font-weight: 700;
    padding: 4px 0;
}
QLabel#subtitle {
    color: #94a3b8;
    font-size: 12px;
}
QLabel#metricLabel {
    color: #6b7280;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
}
QLabel#metricValue {
    color: #f9fafb;
    font-size: 28px;
    font-weight: 900;
}

/* ═══ Frame / Card ═══ */
QFrame#card {
    background: #111827;
    border: 1px solid #1f2937;
    border-radius: 12px;
}

/* ═══ List Widget ═══ */
QListWidget {
    background: #111827;
    border: 1px solid #1f2937;
    border-radius: 8px;
    color: #e2e8f0;
    font-size: 12px;
    outline: none;
}
QListWidget::item {
    padding: 8px 12px;
    border-bottom: 1px solid #1f2937;
}
QListWidget::item:selected {
    background: #1e3a5f;
}
QListWidget::item:hover {
    background: #1f2937;
}

/* ═══ Splitter ═══ */
QSplitter::handle {
    background: #374151;
    height: 2px;
}

/* ═══ Group Box ═══ */
QGroupBox {
    border: 1px solid #1f2937;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 20px;
    font-weight: 600;
    color: #94a3b8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
}

/* ═══ ToolTip ═══ */
QToolTip {
    background: #1f2937;
    color: #e2e8f0;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ═══ Menu ═══ */
QMenu {
    background: #1f2937;
    color: #e2e8f0;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 8px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #6366f1;
}
"""
