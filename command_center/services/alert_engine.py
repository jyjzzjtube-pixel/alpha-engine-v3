# -*- coding: utf-8 -*-
"""
통합 알림 엔진 — 데스크톱 + 텔레그램
"""
import requests
from typing import Optional, Callable

from ..config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ALERT_DESKTOP_ENABLED, ALERT_TELEGRAM_ENABLED,
)
from ..models import Alert, AlertType, Severity
from ..database import Database


class AlertEngine:
    """알림 발행 + 기록 + 전송"""

    def __init__(self, db: Database):
        self.db = db
        self._tray_callback: Optional[Callable] = None
        self._ui_callback: Optional[Callable] = None

    def set_tray_callback(self, cb: Callable):
        """시스템 트레이 알림 콜백 설정"""
        self._tray_callback = cb

    def set_ui_callback(self, cb: Callable):
        """UI 업데이트 콜백 설정"""
        self._ui_callback = cb

    def emit(self, alert_type: AlertType, title: str, message: str = "",
             severity: Severity = Severity.INFO, source: str = ""):
        """알림 발행"""
        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            source=source,
        )

        # DB 기록
        alert.id = self.db.add_alert(alert)

        # 데스크톱 알림
        if ALERT_DESKTOP_ENABLED and severity in (Severity.WARN, Severity.ERROR, Severity.CRITICAL):
            self._send_desktop(alert)

        # 텔레그램 알림
        if ALERT_TELEGRAM_ENABLED and severity in (Severity.ERROR, Severity.CRITICAL):
            self._send_telegram(alert)

        # UI 콜백
        if self._ui_callback:
            self._ui_callback(alert)

    def _send_desktop(self, alert: Alert):
        if self._tray_callback:
            self._tray_callback(alert.title, alert.message)

    def _send_telegram(self, alert: Alert):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return
        icons = {
            Severity.INFO: "\u2139\uFE0F",
            Severity.WARN: "\u26A0\uFE0F",
            Severity.ERROR: "\u274C",
            Severity.CRITICAL: "\U0001F6A8",
        }
        icon = icons.get(alert.severity, "")
        text = f"{icon} *{alert.title}*\n{alert.message}"
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception:
            pass

    def get_unread_count(self) -> int:
        return self.db.get_unread_count()

    def get_history(self, limit: int = 50, alert_type: str = None) -> list:
        return self.db.get_alerts(limit=limit, alert_type=alert_type)

    def mark_all_read(self):
        self.db.mark_all_read()
