# -*- coding: utf-8 -*-
"""
YJ Partners 통합 커맨드센터
=============================
모든 서비스를 하나의 앱에서 모니터링, 제어, 배포, 알림 수신

실행: python -m command_center.main
"""
import sys
import os
import traceback
import logging
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget,
    QVBoxLayout, QSystemTrayIcon, QMenu,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont

from command_center.styles import DARK_STYLESHEET
from command_center.config import (
    MANAGED_SITES, MANAGED_BOTS,
    HEALTH_CHECK_INTERVAL_MS, COST_REFRESH_INTERVAL_MS, BOT_STATUS_INTERVAL_MS,
)
from command_center.database import Database
from command_center.services.site_monitor import SiteMonitor
from command_center.services.bot_manager import BotManager
from command_center.services.cost_service import CostService
from command_center.services.alert_engine import AlertEngine
from command_center.models import AlertType, Severity, SiteStatus
from command_center.workers import HealthCheckWorker, CostRefreshWorker

from command_center.tabs.dashboard_tab import DashboardTab
from command_center.tabs.site_tab import SiteTab
from command_center.tabs.bot_tab import BotTab
from command_center.tabs.cost_tab import CostTab
from command_center.tabs.order_tab import OrderTab
from command_center.tabs.search_tab import SearchTab
from command_center.tabs.alert_tab import AlertTab


def _create_tray_icon() -> QIcon:
    """프로그래밍 방식 트레이 아이콘 생성 (외부 파일 불필요)"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 배경 원
    painter.setBrush(QColor("#6366f1"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    # 텍스트
    painter.setPen(QColor("white"))
    font = QFont("Segoe UI", 22, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "YJ")
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    """통합 커맨드센터 메인 윈도우"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("YJ Partners Command Center")
        self.setMinimumSize(1300, 860)
        self.resize(1500, 950)

        # ── 서비스 초기화 ──
        self.db = Database()
        self.bot_manager = BotManager()
        self.cost_service = CostService()
        self.alert_engine = AlertEngine(self.db)

        # 시스템 트레이
        self._setup_tray()

        # 알림 콜백 설정
        self.alert_engine.set_tray_callback(self._show_tray_notification)
        self.alert_engine.set_ui_callback(self._on_new_alert)

        # ── UI 구성 ──
        self._init_ui()

        # ── 타이머 ──
        self._setup_timers()

        # 이전 사이트 상태 (상태 변경 감지용)
        self._prev_site_status: dict[str, SiteStatus] = {}

        # ── 초기 데이터 로드 ──
        QTimer.singleShot(500, self._initial_load)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        # 탭 위젯
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)

        # 탭 생성
        self.dashboard_tab = DashboardTab()
        self.site_tab = SiteTab()
        self.bot_tab = BotTab(self.bot_manager)
        self.cost_tab = CostTab()
        self.order_tab = OrderTab()
        self.search_tab = SearchTab()
        self.alert_tab = AlertTab(self.db)

        self.tabs.addTab(self.dashboard_tab, "  \U0001F4CA 대시보드  ")
        self.tabs.addTab(self.site_tab, "  \U0001F310 사이트  ")
        self.tabs.addTab(self.bot_tab, "  \U0001F916 봇 관리  ")
        self.tabs.addTab(self.cost_tab, "  \U0001F4B0 API 비용  ")
        self.tabs.addTab(self.order_tab, "  \U0001F3AF 오더  ")
        self.tabs.addTab(self.search_tab, "  \U0001F50D 검색  ")
        self.tabs.addTab(self.alert_tab, "  \U0001F514 알림  ")

        layout.addWidget(self.tabs)

        # ── 시그널 연결 ──
        self.dashboard_tab.health_check_requested.connect(self._run_health_check)
        self.site_tab.health_check_requested.connect(self._run_health_check)

        # 봇 탭 시그널
        self.bot_tab.bot_action.connect(self._on_bot_action)

        # 오더 탭 시그널
        self.order_tab.order_executed.connect(self._on_order_executed)

        # 단축키
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """글로벌 키보드 단축키"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        # Ctrl+K → 오더 탭 포커스
        QShortcut(QKeySequence("Ctrl+K"), self, lambda: self._focus_tab(4))
        # Ctrl+F → 검색 탭 포커스
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self._focus_tab(5))
        # F5 → 전체 새로고침
        QShortcut(QKeySequence("F5"), self, self._initial_load)

    def _focus_tab(self, index: int):
        self.tabs.setCurrentIndex(index)

    def _setup_tray(self):
        """시스템 트레이 아이콘"""
        self.tray_icon = QSystemTrayIcon(_create_tray_icon(), self)
        tray_menu = QMenu()
        show_action = QAction("열기", self)
        show_action.triggered.connect(self.showNormal)
        quit_action = QAction("종료", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _show_tray_notification(self, title: str, message: str):
        if self.tray_icon.isSystemTrayAvailable():
            self.tray_icon.showMessage(
                f"YJ Command Center — {title}",
                message,
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.activateWindow()

    def _setup_timers(self):
        """자동 갱신 타이머"""
        # 건강검진 (30초)
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._run_health_check)
        self._health_timer.start(HEALTH_CHECK_INTERVAL_MS)

        # 비용 갱신 (15초)
        self._cost_timer = QTimer(self)
        self._cost_timer.timeout.connect(self._refresh_cost)
        self._cost_timer.start(COST_REFRESH_INTERVAL_MS)

        # 봇 상태 (5초)
        self._bot_timer = QTimer(self)
        self._bot_timer.timeout.connect(self._refresh_bot_status)
        self._bot_timer.start(BOT_STATUS_INTERVAL_MS)

    def _initial_load(self):
        """초기 데이터 로드"""
        self._run_health_check()
        self._refresh_cost()
        self._refresh_bot_status()
        self._refresh_alerts()
        self.alert_engine.emit(
            AlertType.SYSTEM, "커맨드센터 시작",
            "YJ Partners Command Center가 시작되었습니다.",
            Severity.INFO, "system",
        )

    # ── 건강검진 ──
    def _run_health_check(self):
        self._hc_worker = HealthCheckWorker()
        self._hc_worker.result_ready.connect(self._on_health_results)
        self._hc_worker.start()

    def _on_health_results(self, results: list):
        # 대시보드 업데이트
        self.dashboard_tab.update_sites(results)
        # 사이트 탭 업데이트
        self.site_tab.update_sites(results)

        # 상태 변경 시에만 알림 (UP→DOWN, DOWN→UP)
        for r in results:
            prev = self._prev_site_status.get(r.site_id)
            if prev is None:
                # 최초 실행: DOWN이면 기록만 하고 팝업 안 띄움
                self._prev_site_status[r.site_id] = r.status
                continue

            if prev == r.status:
                continue  # 상태 변경 없음 — 스킵

            self._prev_site_status[r.site_id] = r.status

            if r.status != SiteStatus.UP:
                self.alert_engine.emit(
                    AlertType.SITE_DOWN,
                    f"{r.name} 다운",
                    f"상태: {r.status.value} | {r.error}",
                    Severity.ERROR, r.site_id,
                )
            else:
                self.alert_engine.emit(
                    AlertType.SITE_RECOVERED,
                    f"{r.name} 복구됨",
                    f"응답시간: {r.response_time}s",
                    Severity.INFO, r.site_id,
                )

        # 봇 상태도 업데이트
        self._refresh_bot_status()

    # ── 비용 ──
    def _refresh_cost(self):
        self._cost_worker = CostRefreshWorker()
        self._cost_worker.result_ready.connect(self._on_cost_summary)
        self._cost_worker.start()

    def _on_cost_summary(self, summary: dict):
        self.dashboard_tab.update_cost(summary)
        self.cost_tab.update_summary(summary)

    # ── 봇 상태 ──
    def _refresh_bot_status(self):
        statuses = self.bot_manager.get_all_status()
        self.dashboard_tab.update_bots(statuses)
        self.bot_tab.update_status(statuses)

    def _on_bot_action(self, bot_id: str, action: str):
        if action == "start":
            ok = self.bot_manager.start(bot_id)
            level = "success" if ok else "error"
            self.alert_engine.emit(
                AlertType.BOT_STARTED if ok else AlertType.BOT_ERROR,
                f"{bot_id} 시작 {'완료' if ok else '실패'}",
                severity=Severity.INFO if ok else Severity.ERROR,
            )
        elif action == "stop":
            self.bot_manager.stop(bot_id)
            self.alert_engine.emit(AlertType.BOT_STOPPED, f"{bot_id} 중지됨")
        elif action == "restart":
            self.bot_manager.restart(bot_id)
            self.alert_engine.emit(AlertType.BOT_STARTED, f"{bot_id} 재시작됨")
        elif action == "test":
            ok = self.bot_manager.send_test_message(bot_id)
            self.alert_engine.emit(
                AlertType.SYSTEM,
                f"테스트 메시지 {'전송 완료' if ok else '실패'}",
                severity=Severity.INFO if ok else Severity.WARN,
            )
        self._refresh_bot_status()

    # ── 알림 ──
    def _refresh_alerts(self):
        alerts = self.alert_engine.get_history(limit=10)
        self.dashboard_tab.update_alerts(alerts)
        self.alert_tab.refresh()
        unread = self.alert_engine.get_unread_count()
        self.dashboard_tab.update_alert_count(unread)

    def _on_new_alert(self, alert):
        self._refresh_alerts()

    # ── 오더 ──
    def _on_order_executed(self, action: str, result: str):
        self.alert_engine.emit(
            AlertType.ORDER_COMPLETE,
            f"오더 완료: {action}",
            result[:200],
            Severity.INFO,
        )
        self._refresh_alerts()

    # ── 종료 ──
    def closeEvent(self, event):
        """최소화 시 트레이로 이동"""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "YJ Command Center",
            "백그라운드에서 실행 중입니다.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def _quit_app(self):
        """완전 종료"""
        self.bot_manager.stop_all()
        self.tray_icon.hide()
        QApplication.quit()


def _setup_logging():
    """크래시 로그를 파일에 기록"""
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"crash_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        filename=str(log_file),
        level=logging.ERROR,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )
    return log_file


def _exception_hook(exc_type, exc_value, exc_tb):
    """전역 예외 핸들러 — 로그 기록만 (팝업 없음)"""
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.error(f"Unhandled exception:\n{msg}")
    # 팝업 없이 로그만 기록 — 반복 팝업 방지
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _check_single_instance() -> bool:
    """중복 실행 방지 — 이미 실행 중이면 False 반환"""
    import socket
    try:
        _check_single_instance._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _check_single_instance._sock.bind(("127.0.0.1", 47391))
        _check_single_instance._sock.listen(1)
        return True
    except OSError:
        return False


def main():
    log_file = _setup_logging()
    sys.excepthook = _exception_hook

    if not _check_single_instance():
        print("YJ Command Center is already running.", file=sys.stderr)
        sys.exit(0)

    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        app.setStyleSheet(DARK_STYLESHEET)

        window = MainWindow()
        window.show()

        sys.exit(app.exec())
    except Exception as e:
        msg = traceback.format_exc()
        logging.error(f"Fatal startup error:\n{msg}")
        # 최후의 에러 표시 시도
        try:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None, "YJ Command Center 시작 실패",
                f"프로그램을 시작할 수 없습니다:\n\n{e}\n\n"
                f"로그: {log_file}",
            )
        except Exception:
            print(f"FATAL: {msg}", file=sys.stderr)


if __name__ == "__main__":
    main()
