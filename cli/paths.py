"""Đường dẫn project được CLI dùng chung."""
from __future__ import annotations

import sys
from pathlib import Path

# Nếu chạy dạng EXE đã build (frozen), ROOT sẽ là thư mục chứa file EXE đó
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    # cli/paths.py -> cli/ -> mini_game (project root)
    ROOT = Path(__file__).resolve().parent.parent

SCENARIOS_DIR = ROOT / "scenarios"
TEMPLATES_DIR = ROOT / "assets" / "templates"
DATA_DIR = ROOT / "data"
DEVICES_FILE = ROOT / "devices.yaml"
DEFAULT_DB = DATA_DIR / "mini_game.db"
