"""Immutable project paths."""
from __future__ import annotations

from pathlib import Path

# core/bot/constants.py -> core/bot -> core -> mini_game (project root)
ROOT = Path(__file__).resolve().parent.parent.parent
CAPTURES_DIR = ROOT / "captures"
TEMPLATES_DIR = ROOT / "assets" / "templates"
STOP_FLAG = ROOT / "STOP.flag"

# Toạ độ phần trăm (%) của nút X đóng panel Liên Minh
# Dựa trên toạ độ tuyệt đối (1870, 54, 1894, 81) với tâm (1882, 67.5) trên màn 2340x1080
ALLIANCE_PANEL_CLOSE_X = (80.4, 6.25)

# Toạ độ phần trăm (%) của nút X đóng panel Pre-KVK
# Dựa trên toạ độ tuyệt đối (1861, 48, 1890, 81) với tâm (1875.5, 64.5) trên màn 2340x1080
PRE_KVK_CLOSE_X = (80.15, 5.97)


