"""Immutable project paths."""
from __future__ import annotations

from pathlib import Path

# core/bot/constants.py -> core/bot -> core -> mini_game (project root)
ROOT = Path(__file__).resolve().parent.parent.parent
CAPTURES_DIR = ROOT / "captures"
TEMPLATES_DIR = ROOT / "assets" / "templates"
STOP_FLAG = ROOT / "STOP.flag"
