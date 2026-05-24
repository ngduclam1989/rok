"""Đường dẫn project được CLI dùng chung."""
from __future__ import annotations

from pathlib import Path

# cli/paths.py -> cli/ -> mini_game (project root)
ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "scenarios"
TEMPLATES_DIR = ROOT / "assets" / "templates"
DATA_DIR = ROOT / "data"
DEVICES_FILE = ROOT / "devices.yaml"
DEFAULT_DB = DATA_DIR / "mini_game.db"
