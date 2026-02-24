# -*- coding: utf-8 -*-
"""
텔레그램 ↔ Claude Code 브릿지
실시간 실행 (/cc) + 큐 시스템 (/queue)

Architecture:
  [Telegram /cc]  → subprocess claude -p → 즉시 결과 반환
  [Telegram /queue] → task_queue.json → Claude Code 세션에서 처리
"""
import json
import os
import subprocess
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("TelegramBridge")

# ── 경로 ──
_BASE = Path(__file__).resolve().parent
_PROJECT = _BASE.parent
QUEUE_FILE = _BASE / "task_queue.json"
CLAUDE_CWD = str(_PROJECT)

# Windows에서 .cmd 파일을 찾기 위해 shell=True 사용
import platform
IS_WINDOWS = platform.system() == "Windows"

# Claude Code CLI 타임아웃 (초)
CLAUDE_TIMEOUT = 300  # 5분


# ══════════════════════════════════════════════════════════
#  작업 큐 관리
# ══════════════════════════════════════════════════════════

class TaskQueue:
    """JSON 기반 작업 큐"""

    def __init__(self, path: Path = QUEUE_FILE):
        self.path = path
        self._ensure_file()

    def _ensure_file(self):
        if not self.path.exists():
            self.path.write_text(json.dumps({"tasks": [], "next_id": 1}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict):
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def add(self, message: str, source: str = "telegram") -> dict:
        """작업 추가, 생성된 task 반환"""
        data = self._load()
        task = {
            "id": data["next_id"],
            "message": message,
            "status": "pending",
            "source": source,
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
        }
        data["tasks"].append(task)
        data["next_id"] += 1
        self._save(data)
        logger.info(f"Task #{task['id']} added: {message[:50]}")
        return task

    def get_pending(self) -> list:
        """대기 중인 작업 목록"""
        data = self._load()
        return [t for t in data["tasks"] if t["status"] == "pending"]

    def get_all(self, limit: int = 10) -> list:
        """최근 작업 목록"""
        data = self._load()
        return data["tasks"][-limit:]

    def start_task(self, task_id: int) -> Optional[dict]:
        """작업 시작 표시"""
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["status"] = "in_progress"
                t["started_at"] = datetime.now().isoformat()
                self._save(data)
                return t
        return None

    def complete_task(self, task_id: int, result: str) -> Optional[dict]:
        """작업 완료 표시"""
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["status"] = "completed"
                t["completed_at"] = datetime.now().isoformat()
                t["result"] = result[:2000]  # 결과 최대 2000자
                self._save(data)
                logger.info(f"Task #{task_id} completed")
                return t
        return None

    def fail_task(self, task_id: int, error: str) -> Optional[dict]:
        """작업 실패 표시"""
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["status"] = "failed"
                t["completed_at"] = datetime.now().isoformat()
                t["error"] = error[:500]
                self._save(data)
                logger.warning(f"Task #{task_id} failed: {error[:50]}")
                return t
        return None

    def clear_completed(self) -> int:
        """완료된 작업 정리"""
        data = self._load()
        before = len(data["tasks"])
        data["tasks"] = [t for t in data["tasks"] if t["status"] in ("pending", "in_progress")]
        self._save(data)
        removed = before - len(data["tasks"])
        return removed


# ══════════════════════════════════════════════════════════
#  Claude Code 실시간 실행
# ══════════════════════════════════════════════════════════

def _build_claude_shell_cmd(task: str) -> str:
    """claude -p 명령어 문자열 생성 (shell=True용)"""
    # task 내 따옴표 이스케이프
    escaped = task.replace('"', '\\"')
    return f'claude -p "{escaped}" --output-format text'


async def run_claude_code(task: str, timeout: int = CLAUDE_TIMEOUT) -> dict:
    """
    claude -p 로 실시간 작업 실행.
    Max Plan 구독 내 처리, 추가 비용 없음.
    """
    shell_cmd = _build_claude_shell_cmd(task)

    # 중첩 세션 방지 환경변수 제거
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        process = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=CLAUDE_CWD,
            env=env,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )

        result_text = stdout.decode("utf-8", errors="replace").strip()
        error_text = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode == 0:
            return {
                "ok": True,
                "result": result_text,
                "error": None,
            }
        else:
            return {
                "ok": False,
                "result": result_text,
                "error": error_text or f"exit code {process.returncode}",
            }

    except asyncio.TimeoutError:
        try:
            process.kill()
        except Exception:
            pass
        return {
            "ok": False,
            "result": None,
            "error": f"Timeout ({timeout}s)",
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "result": None,
            "error": "claude CLI not found. Run: npm install -g @anthropic-ai/claude-code",
        }
    except Exception as e:
        return {
            "ok": False,
            "result": None,
            "error": str(e),
        }


def run_claude_code_sync(task: str, timeout: int = CLAUDE_TIMEOUT) -> dict:
    """동기 버전 (claude_helper용)"""
    shell_cmd = _build_claude_shell_cmd(task)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        proc = subprocess.run(
            shell_cmd,
            capture_output=True, text=True, timeout=timeout,
            cwd=CLAUDE_CWD,
            env=env,
            shell=True,
        )
        if proc.returncode == 0:
            return {"ok": True, "result": proc.stdout.strip(), "error": None}
        else:
            return {"ok": False, "result": proc.stdout.strip(), "error": proc.stderr.strip() or f"exit code {proc.returncode}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": None, "error": f"Timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"ok": False, "result": None, "error": "claude CLI not found"}
    except Exception as e:
        return {"ok": False, "result": None, "error": str(e)}


# ══════════════════════════════════════════════════════════
#  큐 작업 처리 (Claude Code 세션에서 호출)
# ══════════════════════════════════════════════════════════

def process_queue_tasks(send_telegram: bool = True) -> list:
    """
    대기 큐의 작업을 하나씩 처리.
    Claude Code 세션 시작 시 호출됨.
    """
    queue = TaskQueue()
    pending = queue.get_pending()

    if not pending:
        return []

    results = []
    for task in pending:
        queue.start_task(task["id"])
        logger.info(f"Processing task #{task['id']}: {task['message'][:50]}")

        outcome = run_claude_code_sync(task["message"])

        if outcome["ok"]:
            queue.complete_task(task["id"], outcome["result"])
            results.append({"id": task["id"], "status": "completed", "result": outcome["result"]})
        else:
            queue.fail_task(task["id"], outcome["error"])
            results.append({"id": task["id"], "status": "failed", "error": outcome["error"]})

        # 텔레그램 알림
        if send_telegram:
            _notify_telegram(task, outcome)

    return results


def _notify_telegram(task: dict, outcome: dict):
    """작업 결과를 텔레그램으로 알림"""
    try:
        import requests
        from command_center.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return

        if outcome["ok"]:
            msg = f"[Task #{task['id']} done]\n{task['message'][:100]}\n\n{outcome['result'][:3000]}"
        else:
            msg = f"[Task #{task['id']} FAILED]\n{task['message'][:100]}\n\nError: {outcome['error'][:500]}"

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Telegram notify failed: {e}")
