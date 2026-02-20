# -*- coding: utf-8 -*-
"""
이미지/동영상 편집 탭 -- YJ Partners MCN & F&B Automation
========================================================
마이크로 이미지 편집기, 비디오 타임라인 프리뷰, 레퍼런스 관리, 장면 관리자.
캔버스 위에 마커/영역을 배치하고 AI 명령어를 연결하는 통합 편집 모듈.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QFileDialog, QComboBox, QGroupBox, QSplitter,
    QScrollArea, QFrame, QGridLayout, QListWidget, QListWidgetItem, QSlider,
    QSpinBox, QDoubleSpinBox, QMessageBox, QToolBar, QSizePolicy, QToolButton,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, pyqtSlot, QPoint, QRect, QSize, QTimer, QMimeData,
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QPen, QBrush, QFont, QImage,
    QDragEnterEvent, QDropEvent, QMouseEvent, QWheelEvent, QAction, QIcon,
    QKeyEvent,
)

__all__ = ["EditorTab"]

# ── 경로 설정 ──
WORKSPACE = Path(__file__).parent / "workspace"
SCENES_DIR = WORKSPACE / "scenes"
REFS_DIR = WORKSPACE / "references"

for _d in (WORKSPACE, SCENES_DIR, REFS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── 색상 팔레트 ──
_MARKER_COLORS = [
    "#6366f1", "#f43f5e", "#22c55e", "#f59e0b", "#06b6d4",
    "#a855f7", "#ec4899", "#14b8a6", "#f97316", "#3b82f6",
]
_REF_CATEGORIES = ["배경", "인물", "음식", "제품", "효과", "기타"]
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}
_ALL_MEDIA_EXTS = _IMAGE_EXTS | _VIDEO_EXTS


# ══════════════════════════════════════════════════════════════
#  마커 / 영역 데이터 모델
# ══════════════════════════════════════════════════════════════

class MarkerData:
    """단일 마커(점) 데이터."""

    def __init__(self, uid: int, x: int, y: int):
        self.uid = uid
        self.x = x
        self.y = y
        self.command = ""

    def to_dict(self) -> dict:
        return {"type": "marker", "uid": self.uid,
                "x": self.x, "y": self.y, "command": self.command}

    @classmethod
    def from_dict(cls, d: dict) -> "MarkerData":
        m = cls(d["uid"], d["x"], d["y"])
        m.command = d.get("command", "")
        return m


class RegionData:
    """사각 영역 데이터."""

    def __init__(self, uid: int, x: int, y: int, w: int, h: int):
        self.uid = uid
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.command = ""

    def to_dict(self) -> dict:
        return {"type": "region", "uid": self.uid,
                "x": self.x, "y": self.y, "w": self.w, "h": self.h,
                "command": self.command}

    @classmethod
    def from_dict(cls, d: dict) -> "RegionData":
        r = cls(d["uid"], d["x"], d["y"], d["w"], d["h"])
        r.command = d.get("command", "")
        return r


# ══════════════════════════════════════════════════════════════
#  이미지 캔버스 위젯
# ══════════════════════════════════════════════════════════════

class ImageCanvas(QLabel):
    """마이크로 이미지 편집 캔버스 -- 클릭/드래그로 마커 및 영역을 배치한다."""

    marker_added = pyqtSignal(object)     # MarkerData
    region_added = pyqtSignal(object)     # RegionData
    selection_changed = pyqtSignal(int)   # selected uid

    MODE_MARKER = "marker"
    MODE_REGION = "region"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background-color: #0d1117; border: 1px solid #1f2937; "
            "border-radius: 8px;"
        )

        self._source_pixmap: Optional[QPixmap] = None
        self._zoom: float = 1.0
        self._offset = QPoint(0, 0)

        self._markers: list[MarkerData] = []
        self._regions: list[RegionData] = []
        self._next_uid: int = 1
        self._undo_stack: list[dict] = []

        self._mode: str = self.MODE_MARKER
        self._drawing_region = False
        self._region_start = QPoint()
        self._region_current = QPoint()
        self._selected_uid: int = -1
        self._dragging_marker: Optional[MarkerData] = None
        self._drag_offset = QPoint()

        self.setMouseTracking(True)
        self._cursor_pos = QPoint()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Pan
        self._panning = False
        self._pan_start = QPoint()

    # ── 공개 API ──

    def load_image(self, path: str):
        pm = QPixmap(path)
        if pm.isNull():
            return
        self._source_pixmap = pm
        self._zoom = 1.0
        self._offset = QPoint(0, 0)
        self.update()

    def get_source_pixmap(self) -> Optional[QPixmap]:
        return self._source_pixmap

    def set_mode(self, mode: str):
        self._mode = mode

    def set_zoom(self, factor: float):
        self._zoom = max(0.1, min(5.0, factor))
        self.update()

    def zoom_in(self):
        self.set_zoom(self._zoom * 1.25)

    def zoom_out(self):
        self.set_zoom(self._zoom / 1.25)

    def clear_all(self):
        self._push_undo()
        self._markers.clear()
        self._regions.clear()
        self._next_uid = 1
        self._selected_uid = -1
        self.update()

    def undo(self):
        if not self._undo_stack:
            return
        state = self._undo_stack.pop()
        self._markers = [MarkerData.from_dict(d) for d in state.get("markers", [])]
        self._regions = [RegionData.from_dict(d) for d in state.get("regions", [])]
        self._next_uid = state.get("next_uid", 1)
        self.update()

    def get_markers(self) -> list[MarkerData]:
        return list(self._markers)

    def get_regions(self) -> list[RegionData]:
        return list(self._regions)

    def set_items(self, markers: list[MarkerData], regions: list[RegionData]):
        self._markers = markers
        self._regions = regions
        if markers or regions:
            all_uids = [m.uid for m in markers] + [r.uid for r in regions]
            self._next_uid = max(all_uids) + 1
        else:
            self._next_uid = 1
        self.update()

    def select_item(self, uid: int):
        self._selected_uid = uid
        self.update()

    # ── 내부 헬퍼 ──

    def _push_undo(self):
        state = {
            "markers": [m.to_dict() for m in self._markers],
            "regions": [r.to_dict() for r in self._regions],
            "next_uid": self._next_uid,
        }
        self._undo_stack.append(state)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def _to_image_coords(self, pos: QPoint) -> QPoint:
        """위젯 좌표 -> 원본 이미지 좌표."""
        if not self._source_pixmap:
            return pos
        cw, ch = self.width(), self.height()
        iw = self._source_pixmap.width() * self._zoom
        ih = self._source_pixmap.height() * self._zoom
        ox = (cw - iw) / 2 + self._offset.x()
        oy = (ch - ih) / 2 + self._offset.y()
        ix = int((pos.x() - ox) / self._zoom)
        iy = int((pos.y() - oy) / self._zoom)
        return QPoint(ix, iy)

    def _to_widget_coords(self, ix: int, iy: int) -> QPoint:
        """원본 이미지 좌표 -> 위젯 좌표."""
        if not self._source_pixmap:
            return QPoint(ix, iy)
        cw, ch = self.width(), self.height()
        iw = self._source_pixmap.width() * self._zoom
        ih = self._source_pixmap.height() * self._zoom
        ox = (cw - iw) / 2 + self._offset.x()
        oy = (ch - ih) / 2 + self._offset.y()
        return QPoint(int(ox + ix * self._zoom), int(oy + iy * self._zoom))

    def _find_marker_at(self, pos: QPoint, radius: int = 14) -> Optional[MarkerData]:
        for m in reversed(self._markers):
            wp = self._to_widget_coords(m.x, m.y)
            if (wp - pos).manhattanLength() < radius:
                return m
        return None

    # ── 마우스 이벤트 ──

    def mousePressEvent(self, ev: QMouseEvent):
        if not self._source_pixmap:
            return
        if ev.button() == Qt.MouseButton.RightButton or ev.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = ev.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return

        # 마커 드래그 체크
        hit = self._find_marker_at(ev.pos())
        if hit and self._mode == self.MODE_MARKER:
            self._dragging_marker = hit
            wp = self._to_widget_coords(hit.x, hit.y)
            self._drag_offset = ev.pos() - wp
            self._selected_uid = hit.uid
            self.selection_changed.emit(hit.uid)
            return

        if self._mode == self.MODE_MARKER:
            self._push_undo()
            img_pt = self._to_image_coords(ev.pos())
            mk = MarkerData(self._next_uid, img_pt.x(), img_pt.y())
            self._next_uid += 1
            self._markers.append(mk)
            self._selected_uid = mk.uid
            self.marker_added.emit(mk)
            self.selection_changed.emit(mk.uid)
            self.update()
        elif self._mode == self.MODE_REGION:
            self._drawing_region = True
            self._region_start = ev.pos()
            self._region_current = ev.pos()

    def mouseMoveEvent(self, ev: QMouseEvent):
        self._cursor_pos = ev.pos()
        if self._panning:
            delta = ev.pos() - self._pan_start
            self._offset = QPoint(self._offset.x() + delta.x(), self._offset.y() + delta.y())
            self._pan_start = ev.pos()
            self.update()
            return
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self._dragging_marker:
            img_pt = self._to_image_coords(ev.pos() - self._drag_offset
                                           + QPoint(0, 0))
            # 단순화: ev.pos()를 이미지 좌표로 변환
            img_pt = self._to_image_coords(ev.pos())
            self._dragging_marker.x = img_pt.x()
            self._dragging_marker.y = img_pt.y()
            self.update()
        elif self._drawing_region:
            self._region_current = ev.pos()
            self.update()

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if self._dragging_marker:
            self._push_undo()
            self._dragging_marker = None
            self.update()
            return

        if self._drawing_region and self._mode == self.MODE_REGION:
            self._drawing_region = False
            self._push_undo()
            p1 = self._to_image_coords(self._region_start)
            p2 = self._to_image_coords(self._region_current)
            x = min(p1.x(), p2.x())
            y = min(p1.y(), p2.y())
            w = abs(p2.x() - p1.x())
            h = abs(p2.y() - p1.y())
            if w > 5 and h > 5:
                rg = RegionData(self._next_uid, x, y, w, h)
                self._next_uid += 1
                self._regions.append(rg)
                self._selected_uid = rg.uid
                self.region_added.emit(rg)
                self.selection_changed.emit(rg.uid)
            self.update()

    def keyPressEvent(self, ev: QKeyEvent):
        """Arrow keys to pan when zoomed."""
        step = 30
        if ev.key() == Qt.Key.Key_Left:
            self._offset = QPoint(self._offset.x() + step, self._offset.y())
            self.update()
        elif ev.key() == Qt.Key.Key_Right:
            self._offset = QPoint(self._offset.x() - step, self._offset.y())
            self.update()
        elif ev.key() == Qt.Key.Key_Up:
            self._offset = QPoint(self._offset.x(), self._offset.y() + step)
            self.update()
        elif ev.key() == Qt.Key.Key_Down:
            self._offset = QPoint(self._offset.x(), self._offset.y() - step)
            self.update()
        else:
            super().keyPressEvent(ev)

    def wheelEvent(self, ev: QWheelEvent):
        delta = ev.angleDelta().y()
        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    # ── 페인트 ──

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 배경
        painter.fillRect(self.rect(), QColor("#0d1117"))

        if self._source_pixmap:
            cw, ch = self.width(), self.height()
            iw = int(self._source_pixmap.width() * self._zoom)
            ih = int(self._source_pixmap.height() * self._zoom)
            ox = int((cw - iw) / 2 + self._offset.x())
            oy = int((ch - ih) / 2 + self._offset.y())

            scaled = self._source_pixmap.scaled(
                iw, ih,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(ox, oy, scaled)

            # 영역 그리기
            for rg in self._regions:
                color = QColor(_MARKER_COLORS[(rg.uid - 1) % len(_MARKER_COLORS)])
                wp = self._to_widget_coords(rg.x, rg.y)
                rw = int(rg.w * self._zoom)
                rh = int(rg.h * self._zoom)

                fill = QColor(color)
                fill.setAlpha(40)
                painter.fillRect(wp.x(), wp.y(), rw, rh, fill)

                pen_color = QColor(color)
                pen_width = 3 if rg.uid == self._selected_uid else 2
                painter.setPen(QPen(pen_color, pen_width, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(wp.x(), wp.y(), rw, rh)

                # 라벨
                font = QFont("Malgun Gothic", 9, QFont.Weight.Bold)
                painter.setFont(font)
                painter.setPen(QPen(Qt.GlobalColor.white))
                label_bg = QColor(color)
                label_bg.setAlpha(200)
                label_rect = QRect(wp.x(), wp.y() - 20, 80, 18)
                painter.fillRect(label_rect, label_bg)
                painter.drawText(label_rect,
                                 Qt.AlignmentFlag.AlignCenter,
                                 f"영역 {rg.uid}")

            # 마커 그리기
            for mk in self._markers:
                color = QColor(_MARKER_COLORS[(mk.uid - 1) % len(_MARKER_COLORS)])
                wp = self._to_widget_coords(mk.x, mk.y)
                r = 12 if mk.uid == self._selected_uid else 10

                # 그림자
                shadow = QColor(0, 0, 0, 80)
                painter.setBrush(shadow)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(wp, r + 2, r + 2)

                # 원형 마커
                painter.setBrush(QBrush(color))
                outline = QColor(Qt.GlobalColor.white)
                painter.setPen(QPen(outline, 2))
                painter.drawEllipse(wp, r, r)

                # 번호
                font = QFont("Segoe UI", 8, QFont.Weight.Bold)
                painter.setFont(font)
                painter.setPen(QPen(Qt.GlobalColor.white))
                painter.drawText(
                    QRect(wp.x() - r, wp.y() - r, r * 2, r * 2),
                    Qt.AlignmentFlag.AlignCenter,
                    str(mk.uid),
                )

            # 영역 드래그 프리뷰
            if self._drawing_region:
                preview_color = QColor("#6366f1")
                preview_color.setAlpha(50)
                x1 = min(self._region_start.x(), self._region_current.x())
                y1 = min(self._region_start.y(), self._region_current.y())
                pw = abs(self._region_current.x() - self._region_start.x())
                ph = abs(self._region_current.y() - self._region_start.y())
                painter.fillRect(x1, y1, pw, ph, preview_color)
                painter.setPen(QPen(QColor("#6366f1"), 2, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(x1, y1, pw, ph)
        else:
            # 빈 상태 안내 텍스트
            painter.setPen(QPen(QColor("#4b5563")))
            font = QFont("Malgun Gothic", 14)
            painter.setFont(font)
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "이미지를 불러오세요\n(도구모음에서 '이미지 열기' 클릭)"
            )

        # 줌 표시
        painter.setPen(QPen(QColor("#6b7280")))
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        painter.drawText(10, self.height() - 10,
                         f"줌: {self._zoom:.0%}")
        painter.end()


# ══════════════════════════════════════════════════════════════
#  레퍼런스 드래그 앤 드롭 패널
# ══════════════════════════════════════════════════════════════

class ReferenceDropZone(QFrame):
    """미디어 파일을 드래그 앤 드롭으로 수집하는 패널."""

    file_dropped = pyqtSignal(str)  # 파일 경로

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(100)
        self.setStyleSheet(
            "ReferenceDropZone {"
            "  background-color: #111827;"
            "  border: 2px dashed #1f2937;"
            "  border-radius: 10px;"
            "}"
            "ReferenceDropZone:hover {"
            "  border-color: #6366f1;"
            "  background-color: #0d1117;"
            "}"
        )
        layout = QVBoxLayout(self)
        lbl = QLabel("여기에 파일을 드래그하세요\nPNG, JPG, GIF, MP4, MOV, WEBP")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #4b5563; font-size: 12px; border: none;")
        layout.addWidget(lbl)

    def dragEnterEvent(self, ev: QDragEnterEvent):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            self.setStyleSheet(
                "ReferenceDropZone {"
                "  background-color: rgba(99, 102, 241, 0.08);"
                "  border: 2px dashed #6366f1;"
                "  border-radius: 10px;"
                "}"
            )

    def dragLeaveEvent(self, ev):
        self.setStyleSheet(
            "ReferenceDropZone {"
            "  background-color: #111827;"
            "  border: 2px dashed #1f2937;"
            "  border-radius: 10px;"
            "}"
        )

    def dropEvent(self, ev: QDropEvent):
        self.setStyleSheet(
            "ReferenceDropZone {"
            "  background-color: #111827;"
            "  border: 2px dashed #1f2937;"
            "  border-radius: 10px;"
            "}"
        )
        for url in ev.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in _ALL_MEDIA_EXTS:
                self.file_dropped.emit(path)


# ══════════════════════════════════════════════════════════════
#  레퍼런스 아이템 위젯
# ══════════════════════════════════════════════════════════════

class ReferenceItem:
    """레퍼런스 하나에 대한 메타데이터."""

    def __init__(self, path: str, category: str = "기타"):
        self.path = path
        self.category = category
        self.analysis = ""
        self.prompt = ""
        self.uid = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        return {
            "path": self.path, "category": self.category,
            "analysis": self.analysis, "prompt": self.prompt,
            "uid": self.uid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReferenceItem":
        item = cls(d["path"], d.get("category", "기타"))
        item.analysis = d.get("analysis", "")
        item.prompt = d.get("prompt", "")
        item.uid = d.get("uid", str(uuid.uuid4())[:8])
        return item


# ══════════════════════════════════════════════════════════════
#  장면 데이터
# ══════════════════════════════════════════════════════════════

class SceneData:
    """하나의 장면 상태를 저장/로드하는 컨테이너."""

    def __init__(self, name: str = ""):
        self.name = name or f"장면_{datetime.now().strftime('%H%M%S')}"
        self.uid = str(uuid.uuid4())[:8]
        self.image_path: str = ""
        self.markers: list[dict] = []
        self.regions: list[dict] = []
        self.references: list[dict] = []
        self.created_at: str = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "name": self.name, "uid": self.uid,
            "image_path": self.image_path,
            "markers": self.markers, "regions": self.regions,
            "references": self.references,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SceneData":
        s = cls(d.get("name", ""))
        s.uid = d.get("uid", str(uuid.uuid4())[:8])
        s.image_path = d.get("image_path", "")
        s.markers = d.get("markers", [])
        s.regions = d.get("regions", [])
        s.references = d.get("references", [])
        s.created_at = d.get("created_at", "")
        return s

    def save(self):
        path = SCENES_DIR / f"{self.uid}.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")

    @staticmethod
    def load(uid: str) -> Optional["SceneData"]:
        path = SCENES_DIR / f"{uid}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return SceneData.from_dict(data)

    @staticmethod
    def list_all() -> list["SceneData"]:
        scenes = []
        for p in sorted(SCENES_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime,
                        reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                scenes.append(SceneData.from_dict(data))
            except Exception:
                continue
        return scenes

    @staticmethod
    def delete(uid: str):
        path = SCENES_DIR / f"{uid}.json"
        if path.exists():
            path.unlink()


# ══════════════════════════════════════════════════════════════
#  메인 에디터 탭
# ══════════════════════════════════════════════════════════════

class EditorTab(QWidget):
    """이미지/동영상 편집 탭 -- MCN 자동화 파이프라인의 비주얼 에디터."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_image_path: str = ""
        self._references: list[ReferenceItem] = []
        self._init_ui()
        self._refresh_scene_list()

    # ── UI 구성 ──

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 10)
        root.setSpacing(6)

        # ── 도구 모음 ──
        toolbar = self._build_toolbar()
        root.addWidget(toolbar)

        # ── 메인 분할 (캔버스 + 마커 패널 | 장면 패널) ──
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setHandleWidth(3)

        # 왼쪽: 캔버스 + 하단 패널
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setHandleWidth(3)

        # 캔버스 + 마커목록 (가로 분할)
        canvas_splitter = QSplitter(Qt.Orientation.Horizontal)
        canvas_splitter.setHandleWidth(3)

        self.canvas = ImageCanvas()
        self.canvas.marker_added.connect(self._on_marker_added)
        self.canvas.region_added.connect(self._on_region_added)
        self.canvas.selection_changed.connect(self._on_selection_changed)
        canvas_splitter.addWidget(self.canvas)

        # 마커/영역 목록 패널
        marker_panel = self._build_marker_panel()
        canvas_splitter.addWidget(marker_panel)
        canvas_splitter.setStretchFactor(0, 3)
        canvas_splitter.setStretchFactor(1, 1)

        left_splitter.addWidget(canvas_splitter)

        # 하단: 레퍼런스 패널 + 비디오 타임라인
        bottom_widget = self._build_bottom_panel()
        left_splitter.addWidget(bottom_widget)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 1)

        main_splitter.addWidget(left_splitter)

        # 오른쪽: 장면 관리자
        scene_panel = self._build_scene_panel()
        main_splitter.addWidget(scene_panel)
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)

        root.addWidget(main_splitter)

    # ── 도구 모음 빌드 ──

    def _build_toolbar(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #111827; border: 1px solid #1f2937; "
            "border-radius: 10px; }"
        )
        frame.setFixedHeight(52)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        buttons = [
            ("이미지 열기", self._on_open_image, "#6366f1"),
            ("저장", self._on_save_image, "#1f2937"),
            ("마커 모드", self._on_marker_mode, "#6366f1"),
            ("영역 모드", self._on_region_mode, "#6366f1"),
            ("실행하기", self._on_execute_commands, "#16a34a"),
            ("미리보기", self._on_preview_commands, "#f59e0b"),
            ("지우기", self._on_clear, "#dc2626"),
            ("실행취소", self._on_undo, "#1f2937"),
        ]
        for text, slot, color in buttons:
            btn = QPushButton(text)
            btn.setFixedHeight(36)
            btn.clicked.connect(slot)
            if color == "#1f2937":
                btn.setObjectName("secondaryBtn")
            elif color == "#dc2626":
                btn.setObjectName("dangerBtn")
            elif color == "#16a34a":
                btn.setObjectName("successBtn")
            elif color == "#f59e0b":
                btn.setStyleSheet(
                    "QPushButton { background: #f59e0b; color: #000; border: none; "
                    "border-radius: 10px; padding: 11px 22px; font-weight: 700; font-size: 13px; }"
                    "QPushButton:hover { background: #d97706; }"
                )
            layout.addWidget(btn)

        self._mode_label = QLabel("모드: 마커")
        self._mode_label.setStyleSheet(
            "color: #6366f1; font-weight: 700; font-size: 12px; "
            "padding: 0 8px; border: none;"
        )
        layout.addWidget(self._mode_label)

        layout.addStretch()

        # 줌 컨트롤
        btn_zoom_out = QPushButton("-")
        btn_zoom_out.setFixedSize(36, 36)
        btn_zoom_out.setObjectName("secondaryBtn")
        btn_zoom_out.clicked.connect(self._on_zoom_out)
        layout.addWidget(btn_zoom_out)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet(
            "color: #9ca3af; font-size: 12px; min-width: 44px; "
            "qproperty-alignment: AlignCenter; border: none;"
        )
        layout.addWidget(self._zoom_label)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedSize(36, 36)
        btn_zoom_in.setObjectName("secondaryBtn")
        btn_zoom_in.clicked.connect(self._on_zoom_in)
        layout.addWidget(btn_zoom_in)

        return frame

    # ── 마커/영역 패널 ──

    def _build_marker_panel(self) -> QFrame:
        frame = QFrame()
        frame.setMinimumWidth(260)
        frame.setStyleSheet(
            "QFrame { background: #111827; border: 1px solid #1f2937; "
            "border-radius: 10px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("마커/영역 목록")
        title.setStyleSheet(
            "font-size: 14px; font-weight: 800; color: #f9fafb; "
            "border: none; padding: 2px 0;"
        )
        layout.addWidget(title)

        # 스크롤 가능한 항목 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._marker_list_widget = QWidget()
        self._marker_list_layout = QVBoxLayout(self._marker_list_widget)
        self._marker_list_layout.setContentsMargins(0, 0, 0, 0)
        self._marker_list_layout.setSpacing(4)
        self._marker_list_layout.addStretch()
        scroll.setWidget(self._marker_list_widget)
        layout.addWidget(scroll)

        return frame

    def _rebuild_marker_list(self):
        """마커/영역 목록 UI 를 새로 그린다."""
        # 기존 위젯 제거
        while self._marker_list_layout.count() > 0:
            item = self._marker_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        items: list[MarkerData | RegionData] = []
        items.extend(self.canvas.get_markers())
        items.extend(self.canvas.get_regions())
        items.sort(key=lambda x: x.uid)

        for it in items:
            card = self._make_item_card(it)
            self._marker_list_layout.addWidget(card)

        self._marker_list_layout.addStretch()

    def _make_item_card(self, item: MarkerData | RegionData) -> QFrame:
        color = _MARKER_COLORS[(item.uid - 1) % len(_MARKER_COLORS)]
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: #0a0e1a; border: 1px solid #1f2937; "
            f"border-left: 3px solid {color}; border-radius: 6px; }}"
        )
        card.setProperty("item_uid", item.uid)
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        vl = QVBoxLayout(card)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(4)

        # 헤더
        header = QHBoxLayout()
        if isinstance(item, MarkerData):
            lbl = QLabel(f"마커 {item.uid}  ({item.x}, {item.y})")
        else:
            lbl = QLabel(f"영역 {item.uid}  ({item.x},{item.y} {item.w}x{item.h})")
        lbl.setStyleSheet(
            f"font-weight: 700; font-size: 12px; color: {color}; border: none;"
        )
        header.addWidget(lbl)

        btn_del = QPushButton("x")
        btn_del.setFixedSize(22, 22)
        btn_del.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; "
            "border-radius: 4px; font-size: 11px; font-weight: 700; padding: 0; }"
            "QPushButton:hover { background: #b91c1c; }"
        )
        btn_del.clicked.connect(lambda _, uid=item.uid: self._delete_item(uid))
        header.addWidget(btn_del)
        vl.addLayout(header)

        # 명령어 텍스트
        cmd = QTextEdit()
        cmd.setPlaceholderText("AI 명령어를 입력하세요...")
        cmd.setFixedHeight(60)
        cmd.setStyleSheet(
            "QTextEdit { background: #111827; border: 1px solid #1f2937; "
            "border-radius: 6px; color: #e5e7eb; font-size: 12px; padding: 6px; }"
            "QTextEdit:focus { border-color: #6366f1; }"
        )
        cmd.setPlainText(item.command)
        cmd.textChanged.connect(
            lambda uid=item.uid, te=cmd: self._update_command(uid, te.toPlainText())
        )
        vl.addWidget(cmd)

        return card

    # ── 하단 패널: 레퍼런스 + 비디오 ──

    def _build_bottom_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame#bottomPanel { background: #111827; border: 1px solid #1f2937; "
            "border-radius: 10px; }"
        )
        frame.setObjectName("bottomPanel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # 탭 전환 헤더
        header = QHBoxLayout()
        self._btn_ref_tab = QPushButton("레퍼런스 패널")
        self._btn_ref_tab.setObjectName("ghostBtn")
        self._btn_ref_tab.setCheckable(True)
        self._btn_ref_tab.setChecked(True)
        self._btn_ref_tab.clicked.connect(lambda: self._switch_bottom_tab(0))
        header.addWidget(self._btn_ref_tab)

        self._btn_video_tab = QPushButton("비디오 타임라인")
        self._btn_video_tab.setObjectName("ghostBtn")
        self._btn_video_tab.setCheckable(True)
        self._btn_video_tab.clicked.connect(lambda: self._switch_bottom_tab(1))
        header.addWidget(self._btn_video_tab)
        header.addStretch()
        layout.addLayout(header)

        # 레퍼런스 패널
        self._ref_panel = self._build_reference_panel()
        layout.addWidget(self._ref_panel)

        # 비디오 타임라인 패널
        self._video_panel = self._build_video_panel()
        self._video_panel.setVisible(False)
        layout.addWidget(self._video_panel)

        return frame

    def _switch_bottom_tab(self, idx: int):
        self._btn_ref_tab.setChecked(idx == 0)
        self._btn_video_tab.setChecked(idx == 1)
        self._ref_panel.setVisible(idx == 0)
        self._video_panel.setVisible(idx == 1)

    # ── 레퍼런스 패널 ──

    def _build_reference_panel(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 드롭존
        self._drop_zone = ReferenceDropZone()
        self._drop_zone.file_dropped.connect(self._add_reference)
        layout.addWidget(self._drop_zone)

        # 썸네일 스크롤 영역
        thumb_scroll = QScrollArea()
        thumb_scroll.setWidgetResizable(True)
        thumb_scroll.setFixedHeight(120)
        thumb_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        thumb_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        thumb_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        self._thumb_container = QWidget()
        self._thumb_layout = QHBoxLayout(self._thumb_container)
        self._thumb_layout.setContentsMargins(0, 0, 0, 0)
        self._thumb_layout.setSpacing(6)
        self._thumb_layout.addStretch()
        thumb_scroll.setWidget(self._thumb_container)
        layout.addWidget(thumb_scroll)

        # 버튼 행
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_browse = QPushButton("파일 추가")
        btn_browse.setObjectName("secondaryBtn")
        btn_browse.setFixedHeight(34)
        btn_browse.clicked.connect(self._browse_references)
        btn_row.addWidget(btn_browse)

        self._ref_category = QComboBox()
        self._ref_category.addItems(_REF_CATEGORIES)
        self._ref_category.setFixedHeight(34)
        self._ref_category.setFixedWidth(100)
        btn_row.addWidget(self._ref_category)

        btn_ai = QPushButton("AI 분석")
        btn_ai.setFixedHeight(34)
        btn_ai.clicked.connect(self._ai_analyze_reference)
        btn_row.addWidget(btn_ai)

        btn_prompt = QPushButton("프롬프트화")
        btn_prompt.setFixedHeight(34)
        btn_prompt.setObjectName("secondaryBtn")
        btn_prompt.clicked.connect(self._promptify_reference)
        btn_row.addWidget(btn_prompt)

        btn_save_scene = QPushButton("장면 저장")
        btn_save_scene.setFixedHeight(34)
        btn_save_scene.setObjectName("successBtn")
        btn_save_scene.clicked.connect(self._save_scene)
        btn_row.addWidget(btn_save_scene)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # AI 분석 결과 영역
        self._ref_analysis = QTextEdit()
        self._ref_analysis.setPlaceholderText(
            "레퍼런스를 선택하고 'AI 분석'을 클릭하면 결과가 여기에 표시됩니다..."
        )
        self._ref_analysis.setFixedHeight(80)
        self._ref_analysis.setStyleSheet(
            "QTextEdit { background: #0a0e1a; border: 1px solid #1f2937; "
            "border-radius: 8px; color: #9ca3af; font-size: 12px; padding: 8px; }"
        )
        layout.addWidget(self._ref_analysis)

        return w

    # ── 비디오 타임라인 패널 ──

    def _build_video_panel(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 영상 불러오기
        top_row = QHBoxLayout()
        btn_load = QPushButton("영상 불러오기")
        btn_load.setFixedHeight(34)
        btn_load.clicked.connect(self._load_video)
        top_row.addWidget(btn_load)

        self._video_path_label = QLabel("영상 없음")
        self._video_path_label.setStyleSheet(
            "color: #6b7280; font-size: 12px; border: none;"
        )
        top_row.addWidget(self._video_path_label)
        top_row.addStretch()
        layout.addLayout(top_row)

        # 프레임 썸네일 스크롤
        frame_scroll = QScrollArea()
        frame_scroll.setWidgetResizable(True)
        frame_scroll.setFixedHeight(90)
        frame_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        frame_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        frame_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._frame_container = QWidget()
        self._frame_layout = QHBoxLayout(self._frame_container)
        self._frame_layout.setContentsMargins(0, 0, 0, 0)
        self._frame_layout.setSpacing(4)
        self._frame_layout.addStretch()
        frame_scroll.setWidget(self._frame_container)
        layout.addWidget(frame_scroll)

        # 트림/속도 컨트롤
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        ctrl_row.addWidget(QLabel("시작:"))
        self._trim_start = QDoubleSpinBox()
        self._trim_start.setRange(0, 9999)
        self._trim_start.setSuffix(" 초")
        self._trim_start.setDecimals(1)
        self._trim_start.setFixedWidth(100)
        ctrl_row.addWidget(self._trim_start)

        ctrl_row.addWidget(QLabel("끝:"))
        self._trim_end = QDoubleSpinBox()
        self._trim_end.setRange(0, 9999)
        self._trim_end.setSuffix(" 초")
        self._trim_end.setDecimals(1)
        self._trim_end.setFixedWidth(100)
        ctrl_row.addWidget(self._trim_end)

        ctrl_row.addWidget(QLabel("속도:"))
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(50, 200)
        self._speed_slider.setValue(100)
        self._speed_slider.setFixedWidth(140)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        ctrl_row.addWidget(self._speed_slider)

        self._speed_label = QLabel("1.0x")
        self._speed_label.setStyleSheet(
            "color: #6366f1; font-weight: 700; font-size: 13px; "
            "min-width: 40px; border: none;"
        )
        ctrl_row.addWidget(self._speed_label)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        return w

    # ── 장면 관리자 패널 ──

    def _build_scene_panel(self) -> QFrame:
        frame = QFrame()
        frame.setMinimumWidth(220)
        frame.setStyleSheet(
            "QFrame { background: #111827; border: 1px solid #1f2937; "
            "border-radius: 10px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("장면 관리자")
        title.setStyleSheet(
            "font-size: 14px; font-weight: 800; color: #f9fafb; "
            "border: none; padding: 2px 0;"
        )
        layout.addWidget(title)

        self._scene_list = QListWidget()
        self._scene_list.setStyleSheet(
            "QListWidget { background: #0a0e1a; border: 1px solid #1f2937; "
            "border-radius: 8px; color: #e5e7eb; font-size: 13px; }"
            "QListWidget::item { padding: 8px 10px; border-bottom: 1px solid #111827; }"
            "QListWidget::item:selected { background: rgba(99, 102, 241, 0.2); "
            "color: #f9fafb; }"
            "QListWidget::item:hover { background: rgba(99, 102, 241, 0.1); }"
        )
        layout.addWidget(self._scene_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_load = QPushButton("불러오기")
        btn_load.setFixedHeight(34)
        btn_load.clicked.connect(self._load_scene)
        btn_row.addWidget(btn_load)

        btn_del = QPushButton("삭제")
        btn_del.setFixedHeight(34)
        btn_del.setObjectName("dangerBtn")
        btn_del.clicked.connect(self._delete_scene)
        btn_row.addWidget(btn_del)

        layout.addLayout(btn_row)

        btn_refresh = QPushButton("새로고침")
        btn_refresh.setFixedHeight(34)
        btn_refresh.setObjectName("secondaryBtn")
        btn_refresh.clicked.connect(self._refresh_scene_list)
        layout.addWidget(btn_refresh)

        return frame

    # ══════════════════════════════════════════════════════════════
    #  슬롯 / 이벤트 핸들러
    # ══════════════════════════════════════════════════════════════

    # ── 도구 모음 ──

    def _on_execute_commands(self):
        """마커/영역의 AI 명령어를 Gemini로 실행하고 결과를 미리보기에 표시한다."""
        markers = self.canvas.get_markers()
        regions = self.canvas.get_regions()
        commands = []
        for m in markers:
            if m.command.strip():
                commands.append(f"[마커 {m.uid}] 좌표({m.x},{m.y}): {m.command}")
        for r in regions:
            if r.command.strip():
                commands.append(
                    f"[영역 {r.uid}] 좌표({r.x},{r.y}) 크기({r.w}x{r.h}): {r.command}")

        if not commands:
            QMessageBox.information(self, "알림",
                "실행할 명령어가 없습니다.\n마커/영역에 AI 명령어를 입력하세요.")
            return

        # 확인 다이얼로그 — 미리보기 먼저 보여주기
        preview_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(commands))
        reply = QMessageBox.question(
            self, "AI 명령어 실행 확인",
            f"{len(commands)}개 명령어를 AI에게 실행합니다:\n\n"
            f"{preview_text}\n\n실행하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._ref_analysis.setPlainText("⏳ AI 처리 중... 잠시 기다려주세요.")
        QApplication.processEvents()

        try:
            from affiliate_system.ai_generator import AIGenerator
            gen = AIGenerator()

            # 이미지가 있으면 이미지 컨텍스트와 함께 분석
            image_context = ""
            if self._current_image_path:
                image_context = f"\n[이미지 파일]: {Path(self._current_image_path).name}"

            prompt = (
                "당신은 이미지 편집 AI 어시스턴트입니다. "
                "사용자가 이미지 위에 마커/영역을 설정하고 각각에 편집 명령어를 지정했습니다.\n"
                "각 명령어를 분석하고 구체적인 편집 지시사항을 한국어로 반환하세요.\n"
                "각 항목에 대해 다음을 포함해주세요:\n"
                "1. 명령어 해석\n"
                "2. 구체적 편집 방법 (도구, 파라미터)\n"
                "3. 예상 결과 설명\n"
                "4. 추천 설정값 (있으면)\n\n"
                f"{image_context}\n\n"
                "[편집 명령어 목록]\n" + "\n".join(commands)
            )
            result = gen.generate_content(prompt, max_tokens=4096, temperature=0.5)

            if result:
                self._ref_analysis.setPlainText(
                    f"✅ AI 실행 결과 ({len(commands)}개 명령어)\n"
                    f"{'='*50}\n\n{result}")
                QMessageBox.information(self, "실행 완료",
                    f"✅ {len(commands)}개 명령어 AI 처리 완료!\n"
                    "하단 분석 결과 패널에서 결과를 확인하세요.")
            else:
                self._ref_analysis.setPlainText(
                    "⚠️ AI 응답이 비어있습니다. API 키를 확인하세요.")

        except Exception as e:
            error_msg = str(e)
            self._ref_analysis.setPlainText(
                f"❌ AI 실행 오류\n{'='*50}\n\n{error_msg}\n\n"
                "[명령어 목록 (대기 중)]\n" + "\n".join(commands))
            QMessageBox.warning(self, "실행 오류",
                f"AI 처리 중 오류가 발생했습니다:\n{error_msg[:200]}\n\n"
                "설정 탭에서 API 키를 확인해주세요.")

    def _on_preview_commands(self):
        """마커/영역 명령어를 미리보기로 표시 + 캔버스에 명령어 라벨 오버레이."""
        markers = self.canvas.get_markers()
        regions = self.canvas.get_regions()

        total = len(markers) + len(regions)
        with_cmd = sum(1 for m in markers if m.command.strip()) + \
                   sum(1 for r in regions if r.command.strip())
        without_cmd = total - with_cmd

        lines = []
        lines.append("┌─────────────────────────────────────┐")
        lines.append("│       📋 명령어 미리보기 대시보드       │")
        lines.append("└─────────────────────────────────────┘")
        lines.append("")
        lines.append(f"  📊 전체: {total}개  |  ✅ 입력됨: {with_cmd}개  |  ⬜ 미입력: {without_cmd}개")
        lines.append("")

        if markers:
            lines.append("── 🔴 마커 ──")
            for m in markers:
                status = "✅" if m.command.strip() else "⬜"
                lines.append(f"  {status} 마커 {m.uid}  ({m.x}, {m.y})")
                if m.command.strip():
                    cmd_preview = m.command[:80] + ("..." if len(m.command) > 80 else "")
                    lines.append(f"      → {cmd_preview}")
                else:
                    lines.append("      → (명령어 미입력)")
                lines.append("")

        if regions:
            lines.append("── 🟦 영역 ──")
            for r in regions:
                status = "✅" if r.command.strip() else "⬜"
                lines.append(f"  {status} 영역 {r.uid}  ({r.x},{r.y}) {r.w}×{r.h}px")
                if r.command.strip():
                    cmd_preview = r.command[:80] + ("..." if len(r.command) > 80 else "")
                    lines.append(f"      → {cmd_preview}")
                else:
                    lines.append("      → (명령어 미입력)")
                lines.append("")

        if total == 0:
            lines.append("  ⚠️ 마커 또는 영역이 없습니다.")
            lines.append("  캔버스에서 마커/영역 모드로 클릭하여 추가하세요.")
        elif with_cmd == 0:
            lines.append("  ⚠️ 명령어가 입력된 항목이 없습니다.")
            lines.append("  오른쪽 패널에서 각 마커/영역에 AI 명령어를 입력하세요.")
        else:
            lines.append("  ✅ '실행하기' 버튼을 눌러 AI에게 명령어를 전송하세요.")
            lines.append(f"  사용 AI: Gemini 2.5 Flash (우선) + Claude 3 Haiku (폴백)")

        self._ref_analysis.setPlainText("\n".join(lines))

        # 캔버스 갱신 (마커/영역 하이라이트 강조)
        self.canvas.update()

    def _on_open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "이미지 열기", "",
            "이미지 파일 (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;모든 파일 (*)"
        )
        if path:
            self._current_image_path = path
            self.canvas.load_image(path)

    def _on_save_image(self):
        pm = self.canvas.get_source_pixmap()
        if not pm:
            QMessageBox.warning(self, "저장 실패", "저장할 이미지가 없습니다.")
            return
        # 마커가 그려진 상태로 저장
        result = QPixmap(self.canvas.size())
        self.canvas.render(result)
        path, _ = QFileDialog.getSaveFileName(
            self, "이미지 저장", "",
            "PNG (*.png);;JPEG (*.jpg);;모든 파일 (*)"
        )
        if path:
            result.save(path)

    def _on_marker_mode(self):
        self.canvas.set_mode(ImageCanvas.MODE_MARKER)
        self._mode_label.setText("모드: 마커")

    def _on_region_mode(self):
        self.canvas.set_mode(ImageCanvas.MODE_REGION)
        self._mode_label.setText("모드: 영역")

    def _on_clear(self):
        reply = QMessageBox.question(
            self, "초기화 확인",
            "모든 마커와 영역을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.canvas.clear_all()
            self._rebuild_marker_list()

    def _on_undo(self):
        self.canvas.undo()
        self._rebuild_marker_list()

    def _on_zoom_in(self):
        self.canvas.zoom_in()
        self._zoom_label.setText(f"{self.canvas._zoom:.0%}")

    def _on_zoom_out(self):
        self.canvas.zoom_out()
        self._zoom_label.setText(f"{self.canvas._zoom:.0%}")

    # ── 마커/영역 이벤트 ──

    def _on_marker_added(self, marker: MarkerData):
        self._rebuild_marker_list()

    def _on_region_added(self, region: RegionData):
        self._rebuild_marker_list()

    def _on_selection_changed(self, uid: int):
        self.canvas.select_item(uid)
        # 해당 카드를 시각적으로 하이라이트 (스크롤 내 위치)
        for i in range(self._marker_list_layout.count()):
            w = self._marker_list_layout.itemAt(i).widget()
            if w and hasattr(w, 'property'):
                if w.property("item_uid") == uid:
                    w.setStyleSheet(
                        w.styleSheet().replace(
                            "border: 1px solid #1f2937",
                            "border: 1px solid #6366f1"
                        )
                    )
                else:
                    current = w.styleSheet()
                    if "#6366f1" in current and "border-left" not in current.split("#6366f1")[0][-15:]:
                        w.setStyleSheet(
                            current.replace(
                                "border: 1px solid #6366f1",
                                "border: 1px solid #1f2937"
                            )
                        )

    def _update_command(self, uid: int, text: str):
        for m in self.canvas.get_markers():
            if m.uid == uid:
                m.command = text
                return
        for r in self.canvas.get_regions():
            if r.uid == uid:
                r.command = text
                return

    def _delete_item(self, uid: int):
        self.canvas._push_undo()
        self.canvas._markers = [m for m in self.canvas._markers if m.uid != uid]
        self.canvas._regions = [r for r in self.canvas._regions if r.uid != uid]
        self.canvas.update()
        self._rebuild_marker_list()

    # ── 레퍼런스 ──

    def _add_reference(self, path: str):
        # 파일을 워크스페이스에 복사
        dest = REFS_DIR / f"{uuid.uuid4().hex[:8]}_{Path(path).name}"
        try:
            shutil.copy2(path, dest)
        except Exception:
            dest = Path(path)  # 복사 실패 시 원본 사용

        category = self._ref_category.currentText()
        ref = ReferenceItem(str(dest), category)
        self._references.append(ref)
        self._add_reference_thumb(ref)

    def _browse_references(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "레퍼런스 파일 선택", "",
            "미디어 파일 (*.png *.jpg *.jpeg *.gif *.webp *.mp4 *.mov);;모든 파일 (*)"
        )
        for p in paths:
            self._add_reference(p)

    def _add_reference_thumb(self, ref: ReferenceItem):
        """썸네일을 레퍼런스 패널에 추가."""
        # stretch 제거 후 추가하고 다시 stretch
        if self._thumb_layout.count() > 0:
            last = self._thumb_layout.itemAt(self._thumb_layout.count() - 1)
            if last and last.widget() is None:
                self._thumb_layout.takeAt(self._thumb_layout.count() - 1)

        card = QFrame()
        card.setFixedSize(100, 110)
        card.setStyleSheet(
            "QFrame { background: #0a0e1a; border: 1px solid #1f2937; "
            "border-radius: 8px; }"
            "QFrame:hover { border-color: #6366f1; }"
        )
        card.setProperty("ref_uid", ref.uid)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(4, 4, 4, 4)
        vl.setSpacing(2)

        # 썸네일 이미지
        thumb_label = QLabel()
        thumb_label.setFixedSize(92, 70)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_label.setStyleSheet("border: none; background: #111827; border-radius: 4px;")

        suffix = Path(ref.path).suffix.lower()
        if suffix in _IMAGE_EXTS:
            pm = QPixmap(ref.path)
            if not pm.isNull():
                pm = pm.scaled(92, 70,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                thumb_label.setPixmap(pm)
            else:
                thumb_label.setText("IMG")
        elif suffix in _VIDEO_EXTS:
            thumb_label.setText("VIDEO")
            thumb_label.setStyleSheet(
                "border: none; background: #1a1040; border-radius: 4px; "
                "color: #a855f7; font-weight: 700; font-size: 11px;"
            )
        vl.addWidget(thumb_label)

        # 카테고리 라벨
        cat_lbl = QLabel(ref.category)
        cat_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cat_lbl.setStyleSheet(
            "color: #6b7280; font-size: 10px; border: none;"
        )
        vl.addWidget(cat_lbl)

        self._thumb_layout.addWidget(card)
        self._thumb_layout.addStretch()

    def _get_selected_reference(self) -> Optional[ReferenceItem]:
        """현재 선택된(마지막으로 추가된) 레퍼런스를 반환."""
        if self._references:
            return self._references[-1]
        return None

    def _ai_analyze_reference(self):
        ref = self._get_selected_reference()
        if not ref:
            QMessageBox.information(self, "알림", "분석할 레퍼런스가 없습니다.\n먼저 레퍼런스를 추가하세요.")
            return
        # AI 분석 시뮬레이션 (실제로는 ai_generator 호출)
        try:
            from affiliate_system.ai_generator import AIGenerator
            gen = AIGenerator()
            result = gen.analyze_image(ref.path) if hasattr(gen, 'analyze_image') else None
            if result:
                ref.analysis = result
                self._ref_analysis.setPlainText(result)
                return
        except Exception:
            pass

        # 폴백: 로컬 분석 정보
        suffix = Path(ref.path).suffix.lower()
        media_type = "이미지" if suffix in _IMAGE_EXTS else "동영상"
        ref.analysis = (
            f"[{media_type} 분석 결과]\n"
            f"파일: {Path(ref.path).name}\n"
            f"카테고리: {ref.category}\n"
            f"분석: AI 모듈 연동 대기 중. 'affiliate_system.ai_generator' 모듈의 "
            f"analyze_image 메서드를 구현하면 자동으로 연동됩니다.\n"
            f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self._ref_analysis.setPlainText(ref.analysis)

    def _promptify_reference(self):
        ref = self._get_selected_reference()
        if not ref:
            QMessageBox.information(self, "알림", "프롬프트화할 레퍼런스가 없습니다.")
            return

        if ref.analysis:
            ref.prompt = (
                f"[프롬프트 변환]\n"
                f"카테고리: {ref.category}\n"
                f"원본 분석을 기반으로 생성된 이미지 생성 프롬프트:\n\n"
                f"---\n{ref.analysis}\n---\n\n"
                f"위 분석을 참고하여 유사한 스타일의 이미지를 생성하세요."
            )
        else:
            ref.prompt = (
                f"[프롬프트 변환]\n"
                f"카테고리: {ref.category}\n"
                f"파일: {Path(ref.path).name}\n"
                f"먼저 AI 분석을 실행한 후 프롬프트화를 시도하세요."
            )
        self._ref_analysis.setPlainText(ref.prompt)

    # ── 비디오 ──

    def _load_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "영상 불러오기", "",
            "영상 파일 (*.mp4 *.mov *.avi *.webm *.mkv);;모든 파일 (*)"
        )
        if not path:
            return
        self._video_path_label.setText(Path(path).name)
        self._extract_video_frames(path)

    def _extract_video_frames(self, path: str):
        """비디오에서 프레임을 추출하여 썸네일로 표시."""
        # 기존 프레임 삭제
        while self._frame_layout.count() > 0:
            item = self._frame_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        try:
            import cv2
            cap = cv2.VideoCapture(path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total / fps if fps > 0 else 0
            self._trim_end.setValue(round(duration, 1))

            # 최대 20개 프레임 추출
            n_frames = min(20, max(1, int(duration)))
            interval = max(1, total // n_frames)

            for i in range(n_frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i * interval)
                ret, frame = cap.read()
                if not ret:
                    break
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame_rgb.shape
                qimg = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
                pm = QPixmap.fromImage(qimg).scaled(
                    80, 60,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                lbl = QLabel()
                lbl.setPixmap(pm)
                lbl.setFixedSize(84, 64)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(
                    "border: 1px solid #1f2937; border-radius: 4px; "
                    "background: #0a0e1a;"
                )
                lbl.setToolTip(f"{(i * interval / fps):.1f}초")
                self._frame_layout.addWidget(lbl)
            cap.release()
        except ImportError:
            # cv2가 없는 경우 안내
            lbl = QLabel("opencv-python 미설치\npip install opencv-python")
            lbl.setStyleSheet(
                "color: #f59e0b; font-size: 11px; border: none; padding: 10px;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._frame_layout.addWidget(lbl)
        except Exception as e:
            lbl = QLabel(f"프레임 추출 실패:\n{str(e)[:80]}")
            lbl.setStyleSheet(
                "color: #ef4444; font-size: 11px; border: none; padding: 10px;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._frame_layout.addWidget(lbl)

        self._frame_layout.addStretch()

    def _on_speed_changed(self, value: int):
        speed = value / 100.0
        self._speed_label.setText(f"{speed:.1f}x")

    # ── 장면 저장/불러오기 ──

    def _save_scene(self):
        scene = SceneData()
        scene.image_path = self._current_image_path
        scene.markers = [m.to_dict() for m in self.canvas.get_markers()]
        scene.regions = [r.to_dict() for r in self.canvas.get_regions()]
        scene.references = [r.to_dict() for r in self._references]

        scene.save()
        QMessageBox.information(
            self, "장면 저장 완료",
            f"장면 '{scene.name}' 이(가) 저장되었습니다."
        )
        self._refresh_scene_list()

    def _load_scene(self):
        item = self._scene_list.currentItem()
        if not item:
            QMessageBox.information(self, "알림", "불러올 장면을 선택하세요.")
            return
        uid = item.data(Qt.ItemDataRole.UserRole)
        scene = SceneData.load(uid)
        if not scene:
            QMessageBox.warning(self, "오류", "장면 데이터를 불러올 수 없습니다.")
            return

        # 이미지 복원
        if scene.image_path and Path(scene.image_path).exists():
            self._current_image_path = scene.image_path
            self.canvas.load_image(scene.image_path)

        # 마커/영역 복원
        markers = [MarkerData.from_dict(d) for d in scene.markers if d.get("type") == "marker"]
        regions = [RegionData.from_dict(d) for d in scene.regions if d.get("type") == "region"]
        self.canvas.set_items(markers, regions)
        self._rebuild_marker_list()

        # 레퍼런스 복원
        self._references = [ReferenceItem.from_dict(d) for d in scene.references]
        self._rebuild_reference_thumbs()

    def _delete_scene(self):
        item = self._scene_list.currentItem()
        if not item:
            QMessageBox.information(self, "알림", "삭제할 장면을 선택하세요.")
            return
        uid = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()
        reply = QMessageBox.question(
            self, "장면 삭제",
            f"'{name}' 장면을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            SceneData.delete(uid)
            self._refresh_scene_list()

    def _refresh_scene_list(self):
        self._scene_list.clear()
        for scene in SceneData.list_all():
            item = QListWidgetItem(f"{scene.name}  ({scene.created_at[:10]})")
            item.setData(Qt.ItemDataRole.UserRole, scene.uid)
            self._scene_list.addItem(item)

    def _rebuild_reference_thumbs(self):
        """레퍼런스 썸네일 목록을 새로 그린다."""
        while self._thumb_layout.count() > 0:
            item = self._thumb_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for ref in self._references:
            self._add_reference_thumb(ref)


# ══════════════════════════════════════════════════════════════
#  독립 실행 테스트
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    _TEST_STYLESHEET = """
    QWidget {
        background-color: #0a0e1a;
        color: #e2e8f0;
        font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
        font-size: 13px;
    }
    QPushButton {
        background-color: #6366f1;
        color: white;
        border: none;
        border-radius: 10px;
        padding: 11px 22px;
        font-weight: 700;
        font-size: 13px;
    }
    QPushButton:hover { background-color: #4f46e5; }
    QPushButton:pressed { background-color: #4338ca; }
    QPushButton:disabled { background-color: #1f2937; color: #4b5563; }
    QPushButton#dangerBtn { background-color: #dc2626; }
    QPushButton#dangerBtn:hover { background-color: #b91c1c; }
    QPushButton#successBtn { background-color: #16a34a; }
    QPushButton#successBtn:hover { background-color: #15803d; }
    QPushButton#secondaryBtn { background-color: #1f2937; color: #e5e7eb; }
    QPushButton#secondaryBtn:hover { background-color: #374151; }
    QPushButton#ghostBtn {
        background-color: transparent;
        color: #6366f1;
        border: 1px solid #6366f1;
    }
    QPushButton#ghostBtn:hover { background-color: rgba(99, 102, 241, 0.1); }
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        background-color: #111827;
        color: #e5e7eb;
        border: 1px solid #1f2937;
        border-radius: 8px;
        padding: 10px 12px;
        font-size: 13px;
        selection-background-color: #6366f1;
    }
    QLineEdit:focus, QTextEdit:focus { border-color: #6366f1; }
    QComboBox::drop-down { border: none; width: 30px; }
    QComboBox QAbstractItemView {
        background-color: #111827; color: #e5e7eb;
        border: 1px solid #1f2937;
        selection-background-color: #6366f1;
    }
    QListWidget {
        background: #0a0e1a; border: 1px solid #1f2937;
        border-radius: 8px; color: #e5e7eb; font-size: 13px;
    }
    QListWidget::item { padding: 8px 10px; border-bottom: 1px solid #111827; }
    QListWidget::item:selected { background: rgba(99, 102, 241, 0.2); }
    QSlider::groove:horizontal {
        border: none; height: 6px; background: #1f2937; border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: #6366f1; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }
    QScrollBar:vertical {
        background: transparent; width: 8px; margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #1f2937; border-radius: 4px; min-height: 30px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal {
        background: transparent; height: 8px; margin: 0;
    }
    QScrollBar::handle:horizontal {
        background: #1f2937; border-radius: 4px; min-width: 30px;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QToolTip {
        background-color: #111827; color: #e5e7eb;
        border: 1px solid #1f2937; border-radius: 6px; padding: 8px;
    }
    """

    app = QApplication([])
    app.setStyleSheet(_TEST_STYLESHEET)
    window = QWidget()
    window.setWindowTitle("이미지/동영상 편집 -- 테스트")
    window.resize(1280, 860)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    editor = EditorTab()
    layout.addWidget(editor)
    window.show()
    app.exec()
