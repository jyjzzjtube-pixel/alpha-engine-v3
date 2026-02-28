"""
Affiliate Marketing System — Shared Utilities
"""
import logging
import time
import hashlib
import functools
from pathlib import Path

from affiliate_system.config import UPLOAD_LOG_DIR


def setup_logger(name: str, log_file: str = "affiliate.log") -> logging.Logger:
    """Create a logger with file + console handlers (UTF-8)."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    # File handler
    fh = logging.FileHandler(
        UPLOAD_LOG_DIR / log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s'))
    logger.addHandler(ch)

    return logger


def retry(max_attempts: int = 3, delay: float = 2.0, backoff: float = 2.0):
    """Decorator for retry with exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            wait = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts:
                        time.sleep(wait)
                        wait *= backoff
            raise last_error
        return wrapper
    return decorator


def file_md5(path: str) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(path: Path) -> Path:
    """Create directory if not exists, return path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def send_telegram(message: str) -> None:
    """텔레그램 봇으로 메시지를 전송한다.

    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID가 .env에 설정되어 있어야 한다.
    실패 시 조용히 무시 (알림은 보조 기능).
    """
    try:
        import requests
        from affiliate_system.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message[:4096],  # 텔레그램 메시지 최대 4096자
            "parse_mode": "HTML",
        }
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass
