"""
YJ Partners MCN & F&B 자동화 파이프라인 — 런처
더블클릭으로 GUI 실행 (콘솔 창 없이)
"""
import sys
import os
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(str(PROJECT_DIR))

from affiliate_system.main_ui import main
main()
