# -*- coding: utf-8 -*-
"""python -m command_center 실행 지원"""
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from command_center.main import main
main()
