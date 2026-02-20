# -*- coding: utf-8 -*-
"""
QThread 워커들 — 모든 네트워크/비동기 작업을 UI 블로킹 없이 처리
"""
from PyQt6.QtCore import QThread, pyqtSignal
from .services.site_monitor import SiteMonitor
from .services.cost_service import CostService
from .services.netlify_deployer import NetlifyDeployer
from .services.order_engine import OrderEngine
from .services.search_engine import SearchEngine
from .models import SiteCheckResult


class HealthCheckWorker(QThread):
    """사이트 건강검진 워커"""
    progress = pyqtSignal(str)
    result_ready = pyqtSignal(list)       # List[SiteCheckResult]
    error = pyqtSignal(str)

    def __init__(self, sites=None):
        super().__init__()
        self.sites = sites

    def run(self):
        try:
            monitor = SiteMonitor()
            self.progress.emit("건강검진 시작...")
            results = monitor.check_all(self.sites)
            self.result_ready.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class CostRefreshWorker(QThread):
    """비용 데이터 갱신 워커"""
    result_ready = pyqtSignal(dict)
    models_ready = pyqtSignal(list)
    daily_ready = pyqtSignal(list)
    records_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self):
        try:
            service = CostService()
            summary = service.get_summary()
            self.result_ready.emit(summary)
            models = service.get_model_breakdown()
            self.models_ready.emit(models)
            daily = service.get_daily_trend()
            self.daily_ready.emit(daily)
            records = service.get_recent_records()
            self.records_ready.emit(records)
        except Exception as e:
            self.error.emit(str(e))


class DeployWorker(QThread):
    """Netlify 배포 워커"""
    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, site_name: str, source_dir: str):
        super().__init__()
        self.site_name = site_name
        self.source_dir = source_dir

    def run(self):
        try:
            deployer = NetlifyDeployer(on_progress=self.progress.emit)
            result = deployer.deploy(self.site_name, self.source_dir)
            if result["success"]:
                self.finished_ok.emit(result)
            else:
                self.error.emit(result.get("error", "배포 실패"))
        except Exception as e:
            self.error.emit(str(e))


class OrderWorker(QThread):
    """오더 실행 워커"""
    result_ready = pyqtSignal(str, str)   # (result_text, status)
    error = pyqtSignal(str)

    def __init__(self, command: str, action: str, target: str = None):
        super().__init__()
        self.command = command
        self.action = action
        self.target = target

    def run(self):
        try:
            engine = OrderEngine()
            if self.action == "ai_query":
                result = engine.ai_chat(self.command)
                self.result_ready.emit(result, "success")
            elif self.action == "cost_report":
                service = CostService()
                s = service.get_summary()
                result = (
                    f"💰 API 비용 리포트\n"
                    f"오늘: ₩{s['today_krw']:,} (${s['today_usd']:.4f})\n"
                    f"이번달: ₩{s['monthly_krw']:,} (${s['monthly_usd']:.4f})\n"
                    f"전체: ₩{s['alltime_krw']:,}\n"
                    f"예산: {s['budget_pct']}% (₩{s['budget_limit']:,} 한도)\n"
                    f"환율: 1 USD = ₩{s['exchange_rate']:,.0f}"
                )
                self.result_ready.emit(result, "success")
            else:
                self.result_ready.emit(f"'{self.action}' 액션이 실행되었습니다.", "success")
        except Exception as e:
            self.error.emit(str(e))


class SearchWorker(QThread):
    """검색 워커"""
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, keyword: str, sources: list = None):
        super().__init__()
        self.keyword = keyword
        self.sources = sources

    def run(self):
        try:
            engine = SearchEngine()
            results = engine.search(self.keyword, self.sources)
            self.result_ready.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class AIchatWorker(QThread):
    """AI 채팅 워커"""
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, prompt: str, context: str = ""):
        super().__init__()
        self.prompt = prompt
        self.context = context

    def run(self):
        try:
            engine = OrderEngine()
            result = engine.ai_chat(self.prompt, self.context)
            self.result_ready.emit(result)
        except Exception as e:
            self.error.emit(str(e))
