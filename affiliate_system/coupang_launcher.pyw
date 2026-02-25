"""
YJ MCN 쿠팡 수익 극대화 프로그램 — 런처
콘솔 창에서 대화형 파이프라인 실행
"""
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent

# 콘솔 창에서 실행 (input() 필요)
subprocess.Popen(
    [sys.executable.replace("pythonw.exe", "python.exe"), "-m", "affiliate_system.coupang_profit_maximizer"],
    cwd=str(PROJECT_DIR),
    creationflags=subprocess.CREATE_NEW_CONSOLE,
)
