# -*- coding: utf-8 -*-
"""
AI 검토 (AI Review) Tab -- YJ Partners MCN 자동화 시스템
========================================================
콘텐츠 컴플라이언스 검토 모듈 + 미디어 미리보기 + 구글 드라이브 연동

- 법적 검토: 저작권, 상표권, FTC 공시, 개인정보
- 플랫폼 적합성: YouTube Shorts, Instagram Reels, Naver Blog, TikTok
- 콘텐츠 품질: 문법, 가독성, SEO, 감정 분석, 독창성
- 미디어 미리보기: 영상 재생, 이미지 뷰, 텍스트/스크립트 뷰
- 구글 드라이브 총괄 폴더 바로가기
"""
from __future__ import annotations

import json
import os
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QProgressBar, QGroupBox, QFrame, QScrollArea,
    QFileDialog, QMessageBox, QSplitter, QSizePolicy, QListWidget,
    QListWidgetItem, QStackedWidget,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, pyqtSlot, QMimeData, QUrl, QSize, QProcess,
)
from PyQt6.QtGui import (
    QFont, QDragEnterEvent, QDropEvent, QColor, QPixmap, QImage,
)

from affiliate_system.utils import setup_logger

# 영상 재생 위젯 (선택적 임포트)
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except ImportError:
    _HAS_MULTIMEDIA = False

__all__ = ["AIReviewTab"]

logger = setup_logger("ai_review", "ai_review.log")

# ── 색상 상수 ──
CLR_BG = "#0a0e1a"
CLR_CARD = "#111827"
CLR_BORDER = "#1f2937"
CLR_ACCENT = "#6366f1"
CLR_TEXT = "#e2e8f0"
CLR_TEXT_DIM = "#6b7280"
CLR_GREEN = "#22c55e"
CLR_YELLOW = "#eab308"
CLR_RED = "#ef4444"
CLR_ORANGE = "#f97316"

# ── 미디어 확장자 ──
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}

# ── AI 프롬프트 템플릿 ──

LEGAL_REVIEW_PROMPT = """다음 콘텐츠를 법적 관점에서 검토해주세요.
반드시 아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트는 포함하지 마세요.
{
  "copyright": {"status": "safe|warning|danger", "score": 0~100, "issues": ["이슈 설명"], "fixes": ["수정 제안"]},
  "trademark": {"status": "safe|warning|danger", "score": 0~100, "issues": [], "fixes": []},
  "ftc_disclosure": {"status": "safe|warning|danger", "score": 0~100, "issues": [], "fixes": []},
  "privacy": {"status": "safe|warning|danger", "score": 0~100, "issues": [], "fixes": []}
}

콘텐츠:
"""

PLATFORM_REVIEW_PROMPT = """다음 콘텐츠의 각 플랫폼 적합성을 분석해주세요.
반드시 아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트는 포함하지 마세요.
{
  "youtube_shorts": {"score": 0~100, "breakdown": {"hook_quality": 0~100, "trending_alignment": 0~100, "format_fit": 0~100}, "suggestions": ["개선 제안"]},
  "instagram_reels": {"score": 0~100, "breakdown": {"hashtag_relevance": 0~100, "visual_appeal": 0~100, "engagement_prediction": 0~100}, "suggestions": []},
  "naver_blog": {"score": 0~100, "breakdown": {"keyword_density": 0~100, "title_optimization": 0~100, "content_length": 0~100, "image_count": 0~100}, "suggestions": []},
  "tiktok": {"score": 0~100, "breakdown": {"trend_alignment": 0~100, "caption_quality": 0~100, "music_fit": 0~100}, "suggestions": []}
}

콘텐츠:
"""

QUALITY_REVIEW_PROMPT = """다음 한국어 콘텐츠의 품질을 분석해주세요.
반드시 아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트는 포함하지 마세요.
{
  "grammar": {"score": 0~100, "issues": ["문법 오류 설명"], "fixes": ["수정안"]},
  "readability": {"score": 0~100, "grade": "A+|A|B+|B|C|D|F", "detail": "설명"},
  "engagement": {"level": "high|medium|low", "score": 0~100, "detail": "설명"},
  "seo": {"score": 0~100, "keywords_found": ["키워드"], "suggestions": ["SEO 개선 제안"]},
  "sentiment": {"tone": "positive|negative|neutral", "score": 0~100, "detail": "설명"},
  "originality": {"score": 0~100, "ai_detection_risk": "low|medium|high", "detail": "설명"}
}

콘텐츠:
"""


# ═══════════════════════════════════════════════════════
#  ReviewWorker -- QThread 기반 AI 분석 워커
# ═══════════════════════════════════════════════════════

class ReviewWorker(QThread):
    """비동기 AI 검토 워커. UI 프리징을 방지한다."""

    progress = pyqtSignal(str, int)        # (단계 메시지, 진행률 %)
    review_complete = pyqtSignal(dict)      # 전체 검토 결과
    error = pyqtSignal(str)                 # 에러 메시지

    def __init__(self, content: str, review_type: str = "all"):
        super().__init__()
        self.content = content
        self.review_type = review_type
        self._ai: Optional[object] = None

    def _init_ai(self):
        try:
            from affiliate_system.ai_generator import AIGenerator
            self._ai = AIGenerator()
            return True
        except Exception as e:
            logger.error(f"AIGenerator 초기화 실패: {e}")
            return False

    def _call_ai(self, prompt: str) -> str:
        return self._ai._call_gemini(
            prompt=prompt,
            max_tokens=4096,
            temperature=0.2,
        )

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = raw.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    text = part
                    break
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def run(self):
        results: dict = {
            "legal": {},
            "platform": {},
            "quality": {},
            "overall_score": 0,
            "grade": "F",
            "recommendations": [],
            "timestamp": datetime.now().isoformat(),
        }

        if not self._init_ai():
            self.error.emit("AI 엔진 미연결 — API 키를 확인하세요.")
            return

        content_snippet = self.content[:3000]
        steps = []

        if self.review_type in ("all", "legal"):
            steps.append(("legal", "법적 검토 수행 중...", LEGAL_REVIEW_PROMPT))
        if self.review_type in ("all", "platform"):
            steps.append(("platform", "플랫폼 적합성 분석 중...", PLATFORM_REVIEW_PROMPT))
        if self.review_type in ("all", "quality"):
            steps.append(("quality", "콘텐츠 품질 분석 중...", QUALITY_REVIEW_PROMPT))

        total = len(steps)
        for idx, (key, msg, prompt) in enumerate(steps):
            self.progress.emit(msg, int((idx / total) * 100))
            try:
                raw = self._call_ai(prompt + content_snippet)
                parsed = self._parse_json(raw)
                results[key] = parsed if parsed else {"_raw": raw}
            except Exception as e:
                logger.error(f"{key} 검토 실패: {e}")
                results[key] = {"_error": str(e)}

        results["overall_score"], results["grade"] = self._calc_overall(results)
        results["recommendations"] = self._build_recommendations(results)

        self.progress.emit("검토 완료!", 100)
        self.review_complete.emit(results)

    @staticmethod
    def _calc_overall(results: dict) -> tuple[int, str]:
        scores: list[int] = []
        legal = results.get("legal", {})
        for key in ("copyright", "trademark", "ftc_disclosure", "privacy"):
            item = legal.get(key, {})
            if isinstance(item, dict) and "score" in item:
                scores.append(int(item["score"]))
        platform = results.get("platform", {})
        for key in ("youtube_shorts", "instagram_reels", "naver_blog", "tiktok"):
            item = platform.get(key, {})
            if isinstance(item, dict) and "score" in item:
                scores.append(int(item["score"]))
        quality = results.get("quality", {})
        for key in ("grammar", "readability", "engagement", "seo", "sentiment", "originality"):
            item = quality.get(key, {})
            if isinstance(item, dict) and "score" in item:
                scores.append(int(item["score"]))
        if not scores:
            return 0, "F"
        avg = int(sum(scores) / len(scores))
        grade = (
            "A+" if avg >= 95 else
            "A" if avg >= 88 else
            "B+" if avg >= 82 else
            "B" if avg >= 75 else
            "C" if avg >= 65 else
            "D" if avg >= 50 else
            "F"
        )
        return avg, grade

    @staticmethod
    def _build_recommendations(results: dict) -> list[str]:
        recs: list[str] = []
        legal = results.get("legal", {})
        for key, label in [("copyright", "저작권"), ("trademark", "상표권"),
                           ("ftc_disclosure", "FTC 공시"), ("privacy", "개인정보")]:
            item = legal.get(key, {})
            if isinstance(item, dict):
                for fix in item.get("fixes", []):
                    recs.append(f"[{label}] {fix}")
        platform = results.get("platform", {})
        for key, label in [("youtube_shorts", "YouTube"), ("instagram_reels", "Instagram"),
                           ("naver_blog", "Naver"), ("tiktok", "TikTok")]:
            item = platform.get(key, {})
            if isinstance(item, dict):
                for sug in item.get("suggestions", []):
                    recs.append(f"[{label}] {sug}")
        quality = results.get("quality", {})
        grammar = quality.get("grammar", {})
        if isinstance(grammar, dict):
            for fix in grammar.get("fixes", []):
                recs.append(f"[문법] {fix}")
        seo = quality.get("seo", {})
        if isinstance(seo, dict):
            for sug in seo.get("suggestions", []):
                recs.append(f"[SEO] {sug}")
        return recs


# ═══════════════════════════════════════════════════════
#  FileDropZone -- 드래그&드롭 영역
# ═══════════════════════════════════════════════════════

class FileDropZone(QFrame):
    """파일 드래그&드롭을 지원하는 커스텀 위젯."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        self.setStyleSheet(f"""
            QFrame {{
                border: 2px dashed {CLR_BORDER};
                border-radius: 10px;
                background: {CLR_CARD};
            }}
            QFrame:hover {{
                border-color: {CLR_ACCENT};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = QLabel("이미지/영상 파일을 여기에 드래그하세요")
        self._label.setStyleSheet(f"color: {CLR_TEXT_DIM}; font-size: 12px; border: none;")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        self.dropped_files: list[str] = []

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                QFrame {{
                    border: 2px dashed {CLR_ACCENT};
                    border-radius: 10px;
                    background: rgba(99, 102, 241, 0.08);
                }}
            """)

    def dragLeaveEvent(self, event):
        self.setStyleSheet(f"""
            QFrame {{
                border: 2px dashed {CLR_BORDER};
                border-radius: 10px;
                background: {CLR_CARD};
            }}
        """)

    def dropEvent(self, event: QDropEvent):
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                paths.append(path)
        if paths:
            self.dropped_files = paths
            names = [Path(p).name for p in paths]
            display = ", ".join(names[:3])
            if len(names) > 3:
                display += f" 외 {len(names) - 3}개"
            self._label.setText(f"첨부됨: {display}")
            self._label.setStyleSheet(f"color: {CLR_GREEN}; font-size: 12px; border: none;")
            self.files_dropped.emit(paths)
        self.setStyleSheet(f"""
            QFrame {{
                border: 2px dashed {CLR_BORDER};
                border-radius: 10px;
                background: {CLR_CARD};
            }}
        """)

    def clear(self):
        self.dropped_files = []
        self._label.setText("이미지/영상 파일을 여기에 드래그하세요")
        self._label.setStyleSheet(f"color: {CLR_TEXT_DIM}; font-size: 12px; border: none;")


# ═══════════════════════════════════════════════════════
#  ScoreBar -- 점수 시각화 바
# ═══════════════════════════════════════════════════════

class ScoreBar(QWidget):
    """라벨 + 점수 + 컬러 진행바 조합 위젯."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self._label = QLabel(label)
        self._label.setFixedWidth(90)
        self._label.setStyleSheet(f"color: {CLR_TEXT}; font-size: 12px;")
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(12)
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar, 1)

        self._score_label = QLabel("--")
        self._score_label.setFixedWidth(50)
        self._score_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._score_label.setStyleSheet(f"color: {CLR_TEXT}; font-size: 13px; font-weight: 700;")
        layout.addWidget(self._score_label)

    def set_score(self, score: int):
        self._bar.setValue(score)
        self._score_label.setText(f"{score}점")
        if score >= 80:
            color = CLR_GREEN
        elif score >= 60:
            color = CLR_YELLOW
        else:
            color = CLR_RED
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                border: none; border-radius: 6px;
                background: {CLR_BORDER}; height: 12px;
            }}
            QProgressBar::chunk {{
                background: {color}; border-radius: 6px;
            }}
        """)


# ═══════════════════════════════════════════════════════
#  AIReviewTab -- 메인 탭 위젯
# ═══════════════════════════════════════════════════════

class AIReviewTab(QWidget):
    """AI 검토 탭 -- 콘텐츠 컴플라이언스 검토 + 미디어 미리보기."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[ReviewWorker] = None
        self._last_results: dict = {}
        self._preview_files: list[str] = []
        self._media_player = None
        self._init_ui()

    # ──────────────────────────────────────────
    #  UI 구성
    # ──────────────────────────────────────────

    def _init_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # ── 메인 스플리터: 좌측(검토) | 우측(미리보기+카테고리) ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)

        # ── 좌측: 기존 검토 영역 (스크롤) ──
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setSpacing(12)
        left_layout.setContentsMargins(6, 4, 6, 4)

        # 1. 입력 영역
        left_layout.addWidget(self._build_input_section())

        # 2. 분석 버튼 행
        left_layout.addWidget(self._build_action_bar())

        # 3. 진행 표시
        self._progress_frame = QFrame()
        self._progress_frame.setVisible(False)
        pfl = QVBoxLayout(self._progress_frame)
        pfl.setContentsMargins(0, 0, 0, 0)
        self._progress_label = QLabel("대기 중...")
        self._progress_label.setStyleSheet(f"color: {CLR_TEXT_DIM}; font-size: 12px;")
        pfl.addWidget(self._progress_label)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(6)
        pfl.addWidget(self._progress_bar)
        left_layout.addWidget(self._progress_frame)

        # 4. 결과 3열 패널
        left_layout.addWidget(self._build_result_panels())

        # 5. 종합 결과
        left_layout.addWidget(self._build_summary_section())

        left_layout.addStretch()
        left_scroll.setWidget(left_container)
        splitter.addWidget(left_scroll)

        # ── 우측: 미리보기 + 카테고리 패널 ──
        right_panel = self._build_right_panel()
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 360])

        root.addWidget(splitter)

    # ══════════════════════════════════════════
    #  우측 패널: 카테고리 + 미리보기
    # ══════════════════════════════════════════

    def _build_right_panel(self) -> QFrame:
        """우측: 결과 카테고리 네비게이션 + 미디어 미리보기 + Drive 바로가기"""
        frame = QFrame()
        frame.setMinimumWidth(300)
        frame.setStyleSheet(f"""
            QFrame#rightPanel {{
                background: {CLR_CARD};
                border: 1px solid {CLR_BORDER};
                border-radius: 12px;
            }}
        """)
        frame.setObjectName("rightPanel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 카테고리 헤더 ──
        cat_title = QLabel("카테고리")
        cat_title.setStyleSheet(
            f"font-size: 15px; font-weight: 800; color: #f9fafb; border: none;")
        layout.addWidget(cat_title)

        # ── 카테고리 리스트 ──
        self._cat_list = QListWidget()
        self._cat_list.setFixedHeight(200)
        self._cat_list.setStyleSheet(f"""
            QListWidget {{
                background: {CLR_BG};
                border: 1px solid {CLR_BORDER};
                border-radius: 8px;
                color: {CLR_TEXT};
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-bottom: 1px solid {CLR_CARD};
            }}
            QListWidget::item:selected {{
                background: rgba(99, 102, 241, 0.2);
                color: #f9fafb;
            }}
            QListWidget::item:hover {{
                background: rgba(99, 102, 241, 0.1);
            }}
        """)

        # 카테고리 항목 추가
        categories = [
            ("📊  법적 검토 결과", "legal"),
            ("📱  플랫폼 적합성", "platform"),
            ("✍️  콘텐츠 품질", "quality"),
            ("📋  종합 리포트", "summary"),
            ("🖼️  이미지 미리보기", "image_preview"),
            ("🎬  영상 미리보기", "video_preview"),
            ("📝  텍스트/스크립트", "text_preview"),
            ("📁  Google Drive 총괄", "drive"),
        ]
        for label, cat_id in categories:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cat_id)
            self._cat_list.addItem(item)

        self._cat_list.currentRowChanged.connect(self._on_category_selected)
        layout.addWidget(self._cat_list)

        # ── 미리보기 스택 위젯 ──
        preview_title = QLabel("미리보기")
        preview_title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: #f9fafb; "
            f"border: none; margin-top: 4px;")
        layout.addWidget(preview_title)

        self._preview_stack = QStackedWidget()
        self._preview_stack.setStyleSheet(f"""
            QStackedWidget {{
                background: {CLR_BG};
                border: 1px solid {CLR_BORDER};
                border-radius: 10px;
            }}
        """)

        # Page 0: 빈 상태 (안내 텍스트)
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_lbl = QLabel("카테고리를 선택하면\n결과가 여기에 표시됩니다\n\n파일을 첨부하면\n미리보기가 활성화됩니다")
        empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lbl.setStyleSheet(f"color: {CLR_TEXT_DIM}; font-size: 13px; border: none;")
        empty_layout.addWidget(empty_lbl)
        self._preview_stack.addWidget(empty_page)  # index 0

        # Page 1: 이미지 미리보기
        img_page = QWidget()
        img_layout = QVBoxLayout(img_page)
        img_layout.setContentsMargins(8, 8, 8, 8)
        self._preview_image = QLabel("이미지 없음")
        self._preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_image.setMinimumHeight(200)
        self._preview_image.setStyleSheet(
            f"color: {CLR_TEXT_DIM}; font-size: 12px; border: none; "
            f"background: {CLR_BG}; border-radius: 8px;")
        img_layout.addWidget(self._preview_image)
        self._img_info = QLabel("")
        self._img_info.setStyleSheet(
            f"color: {CLR_TEXT_DIM}; font-size: 11px; border: none;")
        self._img_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_layout.addWidget(self._img_info)
        self._preview_stack.addWidget(img_page)  # index 1

        # Page 2: 영상 미리보기
        video_page = QWidget()
        video_layout = QVBoxLayout(video_page)
        video_layout.setContentsMargins(8, 8, 8, 8)

        if _HAS_MULTIMEDIA:
            self._video_widget = QVideoWidget()
            self._video_widget.setMinimumHeight(180)
            self._video_widget.setStyleSheet("background: #000; border-radius: 8px;")
            video_layout.addWidget(self._video_widget)

            # 재생 컨트롤
            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(6)
            self._btn_play = QPushButton("▶ 재생")
            self._btn_play.setFixedHeight(32)
            self._btn_play.setStyleSheet(f"""
                QPushButton {{ background: {CLR_ACCENT}; color: white;
                    border: none; border-radius: 6px; font-weight: 700;
                    font-size: 12px; padding: 6px 14px; }}
                QPushButton:hover {{ background: #4f46e5; }}
            """)
            self._btn_play.clicked.connect(self._toggle_play)
            ctrl_row.addWidget(self._btn_play)

            self._btn_stop = QPushButton("⏹ 정지")
            self._btn_stop.setFixedHeight(32)
            self._btn_stop.setStyleSheet(f"""
                QPushButton {{ background: {CLR_BORDER}; color: {CLR_TEXT};
                    border: none; border-radius: 6px; font-weight: 700;
                    font-size: 12px; padding: 6px 14px; }}
                QPushButton:hover {{ background: #374151; }}
            """)
            self._btn_stop.clicked.connect(self._stop_video)
            ctrl_row.addWidget(self._btn_stop)
            ctrl_row.addStretch()
            video_layout.addLayout(ctrl_row)
        else:
            no_video = QLabel("영상 재생을 위해\npip install PyQt6-Qt6\n(Multimedia 모듈 필요)")
            no_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_video.setStyleSheet(f"color: {CLR_TEXT_DIM}; font-size: 12px; border: none;")
            no_video.setMinimumHeight(180)
            video_layout.addWidget(no_video)

        self._video_info = QLabel("")
        self._video_info.setStyleSheet(
            f"color: {CLR_TEXT_DIM}; font-size: 11px; border: none;")
        self._video_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        video_layout.addWidget(self._video_info)
        self._preview_stack.addWidget(video_page)  # index 2

        # Page 3: 텍스트/스크립트 미리보기
        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.setContentsMargins(8, 8, 8, 8)
        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setStyleSheet(f"""
            QTextEdit {{
                background: {CLR_BG};
                color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER};
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
            }}
        """)
        self._preview_text.setPlaceholderText("텍스트 콘텐츠를 입력하면 여기서 볼 수 있습니다...")
        text_layout.addWidget(self._preview_text)
        self._preview_stack.addWidget(text_page)  # index 3

        # Page 4: 검토 결과 상세 뷰
        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(8, 8, 8, 8)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(f"""
            QTextEdit {{
                background: {CLR_BG};
                color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER};
                border-radius: 8px;
                padding: 10px;
                font-size: 12px;
                font-family: 'D2Coding', 'Consolas', monospace;
            }}
        """)
        self._detail_text.setPlaceholderText("검토를 실행하면 상세 결과가 표시됩니다...")
        detail_layout.addWidget(self._detail_text)
        self._preview_stack.addWidget(detail_page)  # index 4

        layout.addWidget(self._preview_stack, 1)

        # ── 파일 열기 버튼 ──
        file_row = QHBoxLayout()
        file_row.setSpacing(6)

        btn_open_file = QPushButton("파일 열기")
        btn_open_file.setFixedHeight(34)
        btn_open_file.setStyleSheet(f"""
            QPushButton {{ background: {CLR_BORDER}; color: {CLR_TEXT};
                border: none; border-radius: 8px; font-weight: 700;
                font-size: 12px; padding: 8px 16px; }}
            QPushButton:hover {{ background: #374151; }}
        """)
        btn_open_file.clicked.connect(self._open_preview_file)
        file_row.addWidget(btn_open_file)

        btn_drive = QPushButton("📁 Google Drive")
        btn_drive.setFixedHeight(34)
        btn_drive.setStyleSheet(f"""
            QPushButton {{ background: #1a73e8; color: white;
                border: none; border-radius: 8px; font-weight: 700;
                font-size: 12px; padding: 8px 16px; }}
            QPushButton:hover {{ background: #1557b0; }}
        """)
        btn_drive.clicked.connect(self._open_drive_folder)
        file_row.addWidget(btn_drive)

        file_row.addStretch()
        layout.addLayout(file_row)

        return frame

    # ── 입력 섹션 ──

    def _build_input_section(self) -> QGroupBox:
        group = QGroupBox("검토 대상 입력")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self._text_input = QTextEdit()
        self._text_input.setPlaceholderText(
            "블로그 글, 스크립트, 캡션 등 검토할 콘텐츠를 붙여넣으세요...")
        self._text_input.setMinimumHeight(120)
        self._text_input.setMaximumHeight(200)
        layout.addWidget(self._text_input)

        row = QHBoxLayout()
        row.setSpacing(8)

        self._drop_zone = FileDropZone()
        self._drop_zone.files_dropped.connect(self._on_files_dropped)
        row.addWidget(self._drop_zone, 2)

        url_col = QVBoxLayout()
        url_col.setSpacing(4)
        url_label = QLabel("URL")
        url_label.setStyleSheet(f"color: {CLR_TEXT_DIM}; font-size: 11px;")
        url_col.addWidget(url_label)
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://...")
        url_col.addWidget(self._url_input)

        btn_file = QPushButton("파일 선택")
        btn_file.setObjectName("secondaryBtn")
        btn_file.setFixedHeight(36)
        btn_file.clicked.connect(self._on_browse_file)
        url_col.addWidget(btn_file)
        row.addLayout(url_col, 1)

        layout.addLayout(row)
        return group

    # ── 액션 바 ──

    def _build_action_bar(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._btn_full = QPushButton("  전체 검토 시작")
        self._btn_full.setMinimumHeight(42)
        self._btn_full.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {CLR_ACCENT}, stop:1 #a855f7);
                color: white; border: none; border-radius: 10px;
                padding: 11px 28px; font-weight: 800; font-size: 14px;
            }}
            QPushButton:hover {{ background: #4f46e5; }}
            QPushButton:disabled {{ background: {CLR_BORDER}; color: #4b5563; }}
        """)
        self._btn_full.clicked.connect(lambda: self._start_review("all"))
        layout.addWidget(self._btn_full, 2)

        for text, rtype in [("법적 검토만", "legal"),
                            ("플랫폼 검토만", "platform"),
                            ("품질 검토만", "quality")]:
            btn = QPushButton(text)
            btn.setObjectName("secondaryBtn")
            btn.setMinimumHeight(42)
            btn.clicked.connect(lambda checked, rt=rtype: self._start_review(rt))
            layout.addWidget(btn, 1)

        return frame

    # ── 결과 3열 패널 ──

    def _build_result_panels(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_legal_panel(), 1)
        layout.addWidget(self._build_platform_panel(), 1)
        layout.addWidget(self._build_quality_panel(), 1)

        return frame

    def _build_legal_panel(self) -> QGroupBox:
        group = QGroupBox("법적 검토")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self._legal_items: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for key, label in [("copyright", "저작권"),
                           ("trademark", "상표권"),
                           ("ftc_disclosure", "FTC 공시"),
                           ("privacy", "개인정보")]:
            row_frame = QFrame()
            row_frame.setStyleSheet(f"""
                QFrame {{
                    background: {CLR_BG};
                    border-radius: 8px;
                    padding: 4px;
                }}
            """)
            row = QHBoxLayout(row_frame)
            row.setContentsMargins(8, 6, 8, 6)
            row.setSpacing(8)

            status_lbl = QLabel("--")
            status_lbl.setFixedWidth(28)
            status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_lbl.setStyleSheet("font-size: 16px; border: none;")
            row.addWidget(status_lbl)

            name_lbl = QLabel(label)
            name_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 13px; font-weight: 600; border: none;")
            row.addWidget(name_lbl, 1)

            detail_lbl = QLabel("")
            detail_lbl.setWordWrap(True)
            detail_lbl.setStyleSheet(f"color: {CLR_TEXT_DIM}; font-size: 11px; border: none;")
            row.addWidget(detail_lbl, 2)

            self._legal_items[key] = (status_lbl, name_lbl, detail_lbl)
            layout.addWidget(row_frame)

        layout.addStretch()
        return group

    def _build_platform_panel(self) -> QGroupBox:
        group = QGroupBox("플랫폼 적합성")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self._platform_bars: dict[str, ScoreBar] = {}
        for key, label in [("youtube_shorts", "YouTube Shorts"),
                           ("instagram_reels", "Instagram Reels"),
                           ("naver_blog", "Naver Blog SEO"),
                           ("tiktok", "TikTok")]:
            bar = ScoreBar(label)
            self._platform_bars[key] = bar
            layout.addWidget(bar)

        self._platform_detail = QLabel("")
        self._platform_detail.setWordWrap(True)
        self._platform_detail.setStyleSheet(f"color: {CLR_TEXT_DIM}; font-size: 11px; margin-top: 4px;")
        layout.addWidget(self._platform_detail)

        layout.addStretch()
        return group

    def _build_quality_panel(self) -> QGroupBox:
        group = QGroupBox("콘텐츠 품질")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self._quality_items: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in [("grammar", "문법/맞춤법"),
                           ("readability", "가독성"),
                           ("engagement", "참여도 예측"),
                           ("seo", "SEO 키워드"),
                           ("sentiment", "감정 톤"),
                           ("originality", "독창성")]:
            row_frame = QFrame()
            row_frame.setStyleSheet(f"QFrame {{ background: {CLR_BG}; border-radius: 8px; }}")
            row = QHBoxLayout(row_frame)
            row.setContentsMargins(8, 6, 8, 6)

            name_lbl = QLabel(label)
            name_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 12px; border: none;")
            row.addWidget(name_lbl, 1)

            value_lbl = QLabel("--")
            value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 13px; font-weight: 700; border: none;")
            row.addWidget(value_lbl)

            self._quality_items[key] = (name_lbl, value_lbl)
            layout.addWidget(row_frame)

        layout.addStretch()
        return group

    # ── 종합 결과 섹션 ──

    def _build_summary_section(self) -> QGroupBox:
        group = QGroupBox("종합 결과")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        top_row = QHBoxLayout()

        self._grade_label = QLabel("--")
        self._grade_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._grade_label.setFixedSize(80, 80)
        self._grade_label.setStyleSheet(f"""
            QLabel {{
                font-size: 36px; font-weight: 900; color: {CLR_TEXT};
                background: {CLR_BG}; border-radius: 16px;
                border: 2px solid {CLR_BORDER};
            }}
        """)
        top_row.addWidget(self._grade_label)

        score_col = QVBoxLayout()
        self._overall_score_label = QLabel("종합 점수: --")
        self._overall_score_label.setStyleSheet(
            f"color: {CLR_TEXT}; font-size: 20px; font-weight: 800;")
        score_col.addWidget(self._overall_score_label)

        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 100)
        self._overall_bar.setFixedHeight(14)
        self._overall_bar.setTextVisible(False)
        score_col.addWidget(self._overall_bar)
        top_row.addLayout(score_col, 1)
        layout.addLayout(top_row)

        rec_label = QLabel("개선 제안")
        rec_label.setStyleSheet(f"color: {CLR_TEXT}; font-size: 13px; font-weight: 700; margin-top: 6px;")
        layout.addWidget(rec_label)

        self._recommendations_text = QTextEdit()
        self._recommendations_text.setReadOnly(True)
        self._recommendations_text.setMaximumHeight(140)
        self._recommendations_text.setPlaceholderText("검토 결과가 여기에 표시됩니다...")
        self._recommendations_text.setStyleSheet(f"""
            QTextEdit {{
                background: {CLR_BG}; color: {CLR_TEXT_DIM};
                border: 1px solid {CLR_BORDER}; border-radius: 8px;
                padding: 8px; font-size: 12px;
            }}
        """)
        layout.addWidget(self._recommendations_text)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_save = QPushButton("리포트 저장")
        self._btn_save.setObjectName("secondaryBtn")
        self._btn_save.setFixedHeight(38)
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save_report)
        btn_row.addWidget(self._btn_save)

        self._btn_autofix = QPushButton("자동 수정")
        self._btn_autofix.setObjectName("successBtn")
        self._btn_autofix.setFixedHeight(38)
        self._btn_autofix.setEnabled(False)
        self._btn_autofix.clicked.connect(self._on_auto_fix)
        btn_row.addWidget(self._btn_autofix)

        layout.addLayout(btn_row)
        return group

    # ──────────────────────────────────────────
    #  이벤트 핸들러
    # ──────────────────────────────────────────

    def _on_browse_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "파일 선택", "",
            "미디어 파일 (*.png *.jpg *.jpeg *.gif *.mp4 *.mov *.avi);;모든 파일 (*)")
        if paths:
            self._drop_zone.dropped_files = paths
            names = [Path(p).name for p in paths]
            display = ", ".join(names[:3])
            if len(names) > 3:
                display += f" 외 {len(names) - 3}개"
            self._drop_zone._label.setText(f"선택됨: {display}")
            self._drop_zone._label.setStyleSheet(
                f"color: {CLR_GREEN}; font-size: 12px; border: none;")
            self._on_files_dropped(paths)

    def _on_files_dropped(self, paths: list):
        """드롭된 파일들을 미리보기에 로드."""
        self._preview_files = paths
        if not paths:
            return

        first_file = paths[0]
        suffix = Path(first_file).suffix.lower()

        if suffix in _IMAGE_EXTS:
            self._load_image_preview(first_file)
            self._preview_stack.setCurrentIndex(1)
        elif suffix in _VIDEO_EXTS:
            self._load_video_preview(first_file)
            self._preview_stack.setCurrentIndex(2)
        else:
            # 텍스트 파일 시도
            try:
                content = Path(first_file).read_text(encoding="utf-8")[:5000]
                self._preview_text.setPlainText(content)
                self._preview_stack.setCurrentIndex(3)
            except Exception:
                pass

    def _load_image_preview(self, path: str):
        """이미지 파일을 미리보기에 로드."""
        pm = QPixmap(path)
        if not pm.isNull():
            # 미리보기 크기에 맞게 스케일
            scaled = pm.scaled(
                280, 250,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self._preview_image.setPixmap(scaled)
            self._img_info.setText(
                f"{Path(path).name}\n{pm.width()}x{pm.height()} px")
        else:
            self._preview_image.setText("이미지 로드 실패")

    def _load_video_preview(self, path: str):
        """영상 파일을 미리보기에 로드."""
        if not _HAS_MULTIMEDIA:
            self._video_info.setText(f"{Path(path).name}\n(재생 모듈 미설치)")
            return

        if not self._media_player:
            self._media_player = QMediaPlayer()
            self._audio_output = QAudioOutput()
            self._media_player.setAudioOutput(self._audio_output)
            self._media_player.setVideoOutput(self._video_widget)

        self._media_player.setSource(QUrl.fromLocalFile(path))
        self._video_info.setText(f"{Path(path).name}")

    def _toggle_play(self):
        """영상 재생/일시정지 토글."""
        if not _HAS_MULTIMEDIA or not self._media_player:
            return
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
            self._btn_play.setText("▶ 재생")
        else:
            self._media_player.play()
            self._btn_play.setText("⏸ 일시정지")

    def _stop_video(self):
        """영상 정지."""
        if not _HAS_MULTIMEDIA or not self._media_player:
            return
        self._media_player.stop()
        self._btn_play.setText("▶ 재생")

    def _open_preview_file(self):
        """파일 선택 대화상자로 미리볼 파일 선택."""
        path, _ = QFileDialog.getOpenFileName(
            self, "미리볼 파일 선택", "",
            "미디어/텍스트 (*.png *.jpg *.jpeg *.gif *.mp4 *.mov *.avi *.txt *.md *.json);;모든 파일 (*)")
        if path:
            self._on_files_dropped([path])

    def _open_drive_folder(self):
        """Google Drive 총괄 폴더를 웹 브라우저에서 열기."""
        try:
            from affiliate_system.drive_manager import DriveArchiver
            archiver = DriveArchiver()
            token_path = archiver.TOKEN_PATH
            if token_path.exists():
                # 인증 후 루트 폴더 URL 가져오기
                try:
                    if archiver.authenticate():
                        root_id = archiver._get_or_create_folder("YJ_Partners_MCN")
                        meta = archiver._service.files().get(
                            fileId=root_id, fields="webViewLink").execute()
                        url = meta.get("webViewLink", "")
                        if url:
                            webbrowser.open(url)
                            return
                except Exception as e:
                    logger.warning(f"Drive 폴더 URL 가져오기 실패: {e}")

                # 폴백: Google Drive 웹 직접 열기
                webbrowser.open("https://drive.google.com")
            else:
                QMessageBox.information(
                    self, "Google Drive",
                    "Google Drive가 연동되지 않았습니다.\n"
                    "설정 탭에서 Drive 클라이언트 ID/Secret을 입력하고 인증하세요.")
        except ImportError:
            webbrowser.open("https://drive.google.com")

    def _on_category_selected(self, row: int):
        """카테고리 선택 시 미리보기 패널 전환."""
        if row < 0:
            return

        item = self._cat_list.item(row)
        if not item:
            return

        cat_id = item.data(Qt.ItemDataRole.UserRole)

        if cat_id == "image_preview":
            # 이미지 미리보기
            if self._preview_files:
                for f in self._preview_files:
                    if Path(f).suffix.lower() in _IMAGE_EXTS:
                        self._load_image_preview(f)
                        break
            self._preview_stack.setCurrentIndex(1)

        elif cat_id == "video_preview":
            # 영상 미리보기
            if self._preview_files:
                for f in self._preview_files:
                    if Path(f).suffix.lower() in _VIDEO_EXTS:
                        self._load_video_preview(f)
                        break
            self._preview_stack.setCurrentIndex(2)

        elif cat_id == "text_preview":
            # 텍스트 미리보기 — 입력된 콘텐츠 표시
            text = self._text_input.toPlainText().strip()
            if text:
                self._preview_text.setPlainText(text)
            else:
                self._preview_text.setPlainText("검토 대상 텍스트를 입력하면 여기서 볼 수 있습니다.")
            self._preview_stack.setCurrentIndex(3)

        elif cat_id == "drive":
            self._open_drive_folder()

        elif cat_id in ("legal", "platform", "quality", "summary"):
            # 검토 결과 상세 표시
            self._show_result_detail(cat_id)
            self._preview_stack.setCurrentIndex(4)

        else:
            self._preview_stack.setCurrentIndex(0)

    def _show_result_detail(self, category: str):
        """검토 결과를 상세 텍스트로 표시."""
        if not self._last_results:
            self._detail_text.setPlainText("아직 검토를 실행하지 않았습니다.\n'전체 검토 시작' 버튼을 클릭하세요.")
            return

        lines = []

        if category == "legal":
            lines.append("═══ 법적 검토 상세 결과 ═══\n")
            data = self._last_results.get("legal", {})
            for key, label in [("copyright", "저작권"), ("trademark", "상표권"),
                               ("ftc_disclosure", "FTC 공시"), ("privacy", "개인정보")]:
                item = data.get(key, {})
                if isinstance(item, dict) and "status" in item:
                    status_icon = {"safe": "✅", "warning": "⚠️", "danger": "❌"}.get(
                        item.get("status", ""), "❓")
                    lines.append(f"{status_icon} {label}: {item.get('score', '?')}점")
                    for issue in item.get("issues", []):
                        lines.append(f"   ⚡ {issue}")
                    for fix in item.get("fixes", []):
                        lines.append(f"   💡 {fix}")
                    lines.append("")

        elif category == "platform":
            lines.append("═══ 플랫폼 적합성 상세 결과 ═══\n")
            data = self._last_results.get("platform", {})
            for key, label in [("youtube_shorts", "YouTube Shorts"),
                               ("instagram_reels", "Instagram Reels"),
                               ("naver_blog", "Naver Blog"),
                               ("tiktok", "TikTok")]:
                item = data.get(key, {})
                if isinstance(item, dict) and "score" in item:
                    score = item["score"]
                    icon = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
                    lines.append(f"{icon} {label}: {score}점")
                    bd = item.get("breakdown", {})
                    if bd:
                        for bk, bv in bd.items():
                            lines.append(f"   ├ {bk}: {bv}")
                    for sug in item.get("suggestions", []):
                        lines.append(f"   💡 {sug}")
                    lines.append("")

        elif category == "quality":
            lines.append("═══ 콘텐츠 품질 상세 결과 ═══\n")
            data = self._last_results.get("quality", {})
            for key, label in [("grammar", "문법/맞춤법"), ("readability", "가독성"),
                               ("engagement", "참여도"), ("seo", "SEO"),
                               ("sentiment", "감정 톤"), ("originality", "독창성")]:
                item = data.get(key, {})
                if isinstance(item, dict):
                    score = item.get("score", "?")
                    icon = "🟢" if isinstance(score, int) and score >= 80 else "🟡" if isinstance(score, int) and score >= 60 else "🔴"
                    lines.append(f"{icon} {label}: {score}점")
                    for k in ("grade", "level", "tone", "ai_detection_risk"):
                        if k in item:
                            lines.append(f"   ├ {k}: {item[k]}")
                    if "detail" in item:
                        lines.append(f"   └ {item['detail']}")
                    lines.append("")

        elif category == "summary":
            lines.append("═══ 종합 리포트 ═══\n")
            score = self._last_results.get("overall_score", 0)
            grade = self._last_results.get("grade", "F")
            lines.append(f"등급: {grade}  |  종합 점수: {score}점")
            lines.append(f"검토 시각: {self._last_results.get('timestamp', '')}\n")
            recs = self._last_results.get("recommendations", [])
            if recs:
                lines.append("── 개선 제안 ──")
                for i, r in enumerate(recs, 1):
                    lines.append(f"  {i}. {r}")
            else:
                lines.append("개선 사항이 없습니다. 훌륭한 콘텐츠입니다!")

        self._detail_text.setPlainText("\n".join(lines))

    def _get_content(self) -> str:
        parts: list[str] = []
        text = self._text_input.toPlainText().strip()
        if text:
            parts.append(text)
        url = self._url_input.text().strip()
        if url:
            parts.append(f"\n[URL: {url}]")
        files = self._drop_zone.dropped_files
        if files:
            file_info = ", ".join(Path(f).name for f in files)
            parts.append(f"\n[첨부 파일: {file_info}]")
        return "\n".join(parts)

    def _start_review(self, review_type: str):
        content = self._get_content()
        if not content:
            QMessageBox.warning(self, "입력 필요", "검토할 콘텐츠를 입력해주세요.")
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "진행 중", "이전 검토가 아직 진행 중입니다.")
            return

        self._set_reviewing(True)
        self._clear_results()

        self._worker = ReviewWorker(content, review_type)
        self._worker.progress.connect(self._on_progress)
        self._worker.review_complete.connect(self._on_review_complete)
        self._worker.error.connect(self._on_review_error)
        self._worker.finished.connect(lambda: self._set_reviewing(False))
        self._worker.start()

    def _set_reviewing(self, active: bool):
        self._progress_frame.setVisible(active)
        self._btn_full.setEnabled(not active)
        if active:
            self._progress_bar.setValue(0)
            self._progress_label.setText("검토 준비 중...")

    def _clear_results(self):
        for key, (status_lbl, _, detail_lbl) in self._legal_items.items():
            status_lbl.setText("--")
            detail_lbl.setText("")
        for key, bar in self._platform_bars.items():
            bar.set_score(0)
        self._platform_detail.setText("")
        for key, (_, value_lbl) in self._quality_items.items():
            value_lbl.setText("--")
            value_lbl.setStyleSheet(
                f"color: {CLR_TEXT}; font-size: 13px; font-weight: 700; border: none;")
        self._grade_label.setText("--")
        self._grade_label.setStyleSheet(f"""
            QLabel {{
                font-size: 36px; font-weight: 900; color: {CLR_TEXT};
                background: {CLR_BG}; border-radius: 16px;
                border: 2px solid {CLR_BORDER};
            }}
        """)
        self._overall_score_label.setText("종합 점수: --")
        self._overall_bar.setValue(0)
        self._recommendations_text.clear()
        self._btn_save.setEnabled(False)
        self._btn_autofix.setEnabled(False)

    # ──────────────────────────────────────────
    #  워커 시그널 핸들러
    # ──────────────────────────────────────────

    @pyqtSlot(str, int)
    def _on_progress(self, message: str, percent: int):
        self._progress_label.setText(message)
        self._progress_bar.setValue(percent)

    @pyqtSlot(dict)
    def _on_review_complete(self, results: dict):
        self._last_results = results
        self._populate_legal(results.get("legal", {}))
        self._populate_platform(results.get("platform", {}))
        self._populate_quality(results.get("quality", {}))
        self._populate_summary(results)
        self._btn_save.setEnabled(True)
        self._btn_autofix.setEnabled(True)
        logger.info(f"검토 완료: 종합 {results.get('grade', '?')} ({results.get('overall_score', 0)}점)")

    @pyqtSlot(str)
    def _on_review_error(self, error_msg: str):
        QMessageBox.critical(self, "검토 실패", error_msg)
        logger.error(f"검토 오류: {error_msg}")

    # ──────────────────────────────────────────
    #  결과 반영 헬퍼
    # ──────────────────────────────────────────

    def _populate_legal(self, data: dict):
        status_map = {
            "safe": ("안전", CLR_GREEN),
            "warning": ("주의", CLR_YELLOW),
            "danger": ("위험", CLR_RED),
        }
        emoji_map = {"safe": "\U0001f7e2", "warning": "\U0001f7e1", "danger": "\U0001f534"}

        for key, (status_lbl, name_lbl, detail_lbl) in self._legal_items.items():
            item = data.get(key, {})
            if not isinstance(item, dict) or "status" not in item:
                status_lbl.setText("\u2B55")
                detail_lbl.setText("분석 데이터 없음")
                continue
            status = item.get("status", "safe")
            emoji = emoji_map.get(status, "\u2B55")
            status_lbl.setText(emoji)
            label_text, label_color = status_map.get(status, ("--", CLR_TEXT_DIM))
            score = item.get("score", 0)
            name_lbl.setStyleSheet(
                f"color: {label_color}; font-size: 13px; font-weight: 600; border: none;")
            issues = item.get("issues", [])
            detail = f"{score}점"
            if issues:
                detail += " | " + "; ".join(issues[:2])
            detail_lbl.setText(detail)

    def _populate_platform(self, data: dict):
        suggestions_all: list[str] = []
        for key, bar in self._platform_bars.items():
            item = data.get(key, {})
            if isinstance(item, dict) and "score" in item:
                bar.set_score(int(item["score"]))
                for s in item.get("suggestions", []):
                    suggestions_all.append(s)
            else:
                bar.set_score(0)
        if suggestions_all:
            self._platform_detail.setText("\n".join(f"- {s}" for s in suggestions_all[:5]))
        else:
            self._platform_detail.setText("")

    def _populate_quality(self, data: dict):
        for key, (name_lbl, value_lbl) in self._quality_items.items():
            item = data.get(key, {})
            if not isinstance(item, dict):
                continue
            display = ""
            color = CLR_TEXT
            if key == "grammar":
                score = item.get("score", 0)
                display = f"{score}점"
                color = CLR_GREEN if score >= 80 else CLR_YELLOW if score >= 60 else CLR_RED
            elif key == "readability":
                grade = item.get("grade", "--")
                display = grade
                color = CLR_GREEN if grade in ("A+", "A") else (
                    CLR_YELLOW if grade in ("B+", "B") else CLR_RED)
            elif key == "engagement":
                level = item.get("level", "--")
                level_map = {"high": ("HIGH", CLR_GREEN), "medium": ("MID", CLR_YELLOW),
                             "low": ("LOW", CLR_RED)}
                display, color = level_map.get(level, (level.upper(), CLR_TEXT_DIM))
            elif key == "seo":
                score = item.get("score", 0)
                display = f"{score}점"
                color = CLR_GREEN if score >= 80 else CLR_YELLOW if score >= 60 else CLR_RED
            elif key == "sentiment":
                tone = item.get("tone", "--")
                tone_map = {"positive": ("긍정적", CLR_GREEN), "negative": ("부정적", CLR_RED),
                            "neutral": ("중립", CLR_YELLOW)}
                display, color = tone_map.get(tone, (tone, CLR_TEXT_DIM))
            elif key == "originality":
                risk = item.get("ai_detection_risk", "--")
                risk_map = {"low": ("안전", CLR_GREEN), "medium": ("주의", CLR_YELLOW),
                            "high": ("위험", CLR_RED)}
                display, color = risk_map.get(risk, (risk, CLR_TEXT_DIM))
            value_lbl.setText(display)
            value_lbl.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: 700; border: none;")

    def _populate_summary(self, results: dict):
        score = results.get("overall_score", 0)
        grade = results.get("grade", "F")
        self._overall_score_label.setText(f"종합 점수: {score}점")
        self._overall_bar.setValue(score)
        if score >= 85:
            grade_color = CLR_GREEN
        elif score >= 70:
            grade_color = CLR_YELLOW
        else:
            grade_color = CLR_RED
        self._grade_label.setText(grade)
        self._grade_label.setStyleSheet(f"""
            QLabel {{
                font-size: 36px; font-weight: 900; color: {grade_color};
                background: {CLR_BG}; border-radius: 16px;
                border: 2px solid {grade_color};
            }}
        """)
        self._overall_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none; border-radius: 7px;
                background: {CLR_BORDER}; height: 14px;
            }}
            QProgressBar::chunk {{
                background: {grade_color}; border-radius: 7px;
            }}
        """)
        recs = results.get("recommendations", [])
        if recs:
            numbered = [f"{i + 1}. {r}" for i, r in enumerate(recs)]
            self._recommendations_text.setPlainText("\n".join(numbered))
        else:
            self._recommendations_text.setPlainText("개선 사항이 없습니다. 훌륭한 콘텐츠입니다!")

    # ──────────────────────────────────────────
    #  리포트 저장 / 자동 수정
    # ──────────────────────────────────────────

    def _on_save_report(self):
        if not self._last_results:
            return
        default_name = f"ai_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "리포트 저장", default_name,
            "JSON 파일 (*.json);;모든 파일 (*)")
        if not path:
            return
        report = {
            "review_results": self._last_results,
            "content_reviewed": self._get_content()[:500],
            "exported_at": datetime.now().isoformat(),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "저장 완료", f"리포트가 저장되었습니다.\n{path}")
            logger.info(f"리포트 저장: {path}")
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", str(e))

    def _on_auto_fix(self):
        content = self._text_input.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "텍스트 필요", "자동 수정할 텍스트 콘텐츠가 없습니다.")
            return
        recs = self._last_results.get("recommendations", [])
        if not recs:
            QMessageBox.information(self, "수정 불필요", "개선할 사항이 없습니다.")
            return
        self._set_reviewing(True)
        self._autofix_worker = _AutoFixWorker(content, recs)
        self._autofix_worker.fix_complete.connect(self._on_autofix_complete)
        self._autofix_worker.error.connect(self._on_review_error)
        self._autofix_worker.finished.connect(lambda: self._set_reviewing(False))
        self._autofix_worker.start()

    @pyqtSlot(str)
    def _on_autofix_complete(self, fixed_text: str):
        self._text_input.setPlainText(fixed_text)
        QMessageBox.information(self, "자동 수정 완료", "콘텐츠가 수정되었습니다. 다시 검토를 실행하세요.")
        logger.info("자동 수정 완료")


# ═══════════════════════════════════════════════════════
#  _AutoFixWorker -- 자동 수정 워커
# ═══════════════════════════════════════════════════════

class _AutoFixWorker(QThread):
    """개선 제안을 바탕으로 콘텐츠를 자동 수정하는 워커."""

    fix_complete = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, content: str, recommendations: list[str]):
        super().__init__()
        self.content = content
        self.recommendations = recommendations

    def run(self):
        try:
            from affiliate_system.ai_generator import AIGenerator
            ai = AIGenerator()
        except Exception as e:
            self.error.emit(f"AI 엔진 미연결: {e}")
            return

        recs_text = "\n".join(f"- {r}" for r in self.recommendations[:10])
        prompt = f"""아래 콘텐츠를 개선 제안에 따라 수정해주세요.
수정된 콘텐츠만 출력하세요. 설명이나 주석은 포함하지 마세요.

[개선 제안]
{recs_text}

[원본 콘텐츠]
{self.content}

[수정된 콘텐츠]:"""

        try:
            fixed = ai._call_gemini(prompt=prompt, max_tokens=4096, temperature=0.3)
            self.fix_complete.emit(fixed.strip())
        except Exception as e:
            self.error.emit(f"자동 수정 실패: {e}")
