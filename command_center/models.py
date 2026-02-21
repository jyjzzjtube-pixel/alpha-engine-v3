# -*- coding: utf-8 -*-
"""
데이터 모델
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SiteStatus(Enum):
    UP = "up"
    DOWN = "down"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class AlertType(Enum):
    SITE_DOWN = "site_down"
    SITE_RECOVERED = "site_recovered"
    COST_WARN = "cost_warn"
    BOT_ERROR = "bot_error"
    BOT_STARTED = "bot_started"
    BOT_STOPPED = "bot_stopped"
    DEPLOY_OK = "deploy_ok"
    DEPLOY_FAIL = "deploy_fail"
    HEALTH_CHECK = "health_check"
    ORDER_COMPLETE = "order_complete"
    SYSTEM = "system"


class Severity(Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class SiteCheckResult:
    site_id: str
    name: str
    url: str
    status: SiteStatus
    status_code: int = 0
    response_time: float = 0.0
    error: str = ""
    checked_at: datetime = field(default_factory=datetime.now)


@dataclass
class BotStatus:
    bot_id: str
    name: str
    running: bool = False
    pid: Optional[int] = None
    uptime_seconds: float = 0.0
    last_log: str = ""
    error: str = ""


@dataclass
class Alert:
    id: Optional[int] = None
    alert_type: AlertType = AlertType.SYSTEM
    severity: Severity = Severity.INFO
    title: str = ""
    message: str = ""
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    read: bool = False


@dataclass
class OrderRecord:
    id: Optional[int] = None
    command: str = ""
    result: str = ""
    status: str = "pending"  # pending, running, success, error
    source: str = "manual"   # manual, ai, quick_action
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0


@dataclass
class SearchResult:
    source: str = ""        # code, api_usage, alert, deploy, log
    icon: str = ""
    title: str = ""
    detail: str = ""
    file_path: str = ""
    line_number: int = 0
    timestamp: str = ""
    relevance: float = 1.0


@dataclass
class DeployRecord:
    id: Optional[int] = None
    site_id: str = ""
    site_name: str = ""
    deploy_id: str = ""
    status: str = ""
    file_count: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
