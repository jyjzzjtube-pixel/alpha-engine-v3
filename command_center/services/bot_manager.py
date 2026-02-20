# -*- coding: utf-8 -*-
"""
봇/서비스 프로세스 관리
"""
import subprocess
import threading
import time
import requests
from collections import deque
from typing import Optional, Dict

from ..config import MANAGED_BOTS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class BotProcess:
    """개별 봇 프로세스 래퍼"""

    def __init__(self, bot_config: dict):
        self.config = bot_config
        self.process: Optional[subprocess.Popen] = None
        self.log_buffer: deque = deque(maxlen=200)
        self._reader_thread: Optional[threading.Thread] = None
        self._started_at: Optional[float] = None

    @property
    def bot_id(self) -> str:
        return self.config["id"]

    @property
    def name(self) -> str:
        return self.config["name"]

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.is_running else None

    @property
    def uptime(self) -> float:
        if self._started_at and self.is_running:
            return time.time() - self._started_at
        return 0.0

    def start(self) -> bool:
        if self.is_running:
            return True
        try:
            self.process = subprocess.Popen(
                self.config["cmd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.config.get("cwd"),
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                encoding="utf-8",
                errors="replace",
            )
            self._started_at = time.time()
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()
            return True
        except Exception as e:
            self.log_buffer.append(f"[ERROR] 시작 실패: {e}")
            return False

    def stop(self) -> bool:
        if not self.is_running:
            return True
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            self._started_at = None
            self.log_buffer.append("[SYSTEM] 프로세스 중지됨")
            return True
        except Exception as e:
            self.log_buffer.append(f"[ERROR] 중지 실패: {e}")
            return False

    def restart(self) -> bool:
        self.stop()
        time.sleep(1)
        return self.start()

    def get_log(self, lines: int = 50) -> str:
        items = list(self.log_buffer)[-lines:]
        return "\n".join(items)

    def _read_output(self):
        try:
            for line in self.process.stdout:
                line = line.rstrip()
                if line:
                    self.log_buffer.append(line)
        except (ValueError, OSError):
            pass


class BotManager:
    """모든 봇/서비스 프로세스 통합 관리"""

    def __init__(self):
        self.bots: Dict[str, BotProcess] = {}
        for cfg in MANAGED_BOTS:
            self.bots[cfg["id"]] = BotProcess(cfg)

    def start(self, bot_id: str) -> bool:
        if bot_id in self.bots:
            return self.bots[bot_id].start()
        return False

    def stop(self, bot_id: str) -> bool:
        if bot_id in self.bots:
            return self.bots[bot_id].stop()
        return False

    def restart(self, bot_id: str) -> bool:
        if bot_id in self.bots:
            return self.bots[bot_id].restart()
        return False

    def is_running(self, bot_id: str) -> bool:
        if bot_id in self.bots:
            return self.bots[bot_id].is_running
        return False

    def get_status(self, bot_id: str) -> dict:
        if bot_id not in self.bots:
            return {"running": False}
        bp = self.bots[bot_id]
        return {
            "running": bp.is_running,
            "pid": bp.pid,
            "uptime": bp.uptime,
            "name": bp.name,
        }

    def get_all_status(self) -> Dict[str, dict]:
        return {bid: self.get_status(bid) for bid in self.bots}

    def get_log(self, bot_id: str, lines: int = 50) -> str:
        if bot_id in self.bots:
            return self.bots[bot_id].get_log(lines)
        return ""

    def get_running_count(self) -> int:
        return sum(1 for bp in self.bots.values() if bp.is_running)

    def stop_all(self):
        for bp in self.bots.values():
            bp.stop()

    def send_test_message(self, bot_id: str) -> bool:
        """텔레그램 봇 테스트 메시지 전송"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return False
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": f"✅ [{bot_id}] 테스트 메시지 — Command Center"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def check_health(self, bot_id: str) -> bool:
        """HTTP 헬스체크 (http 타입 봇)"""
        cfg = None
        for c in MANAGED_BOTS:
            if c["id"] == bot_id:
                cfg = c
                break
        if not cfg or cfg["type"] != "http":
            return self.is_running(bot_id)
        url = cfg.get("health_url", "")
        if not url:
            return self.is_running(bot_id)
        try:
            resp = requests.get(url, timeout=5)
            return resp.status_code < 400
        except Exception:
            return False
