"""Mutable runtime config used by the bot.

Values here are overwritten by `main.py` (via the CLI / interactive prompt)
BEFORE `run()` is called. All other modules in the `core.bot` package
read these settings lazily via ``from . import config`` and access
``config.MAX_SLOTS`` etc. — never ``from .config import MAX_SLOTS``,
which would bind the value at import time and miss later overrides.
"""
from __future__ import annotations

MAX_SLOTS: int = 4
"""March-queue capacity. Auto-detected via the n/N badge OCR on
startup, settable via --max-slots as initial guess."""

TARGET_LEVEL: int = 5
"""Search-panel slider level the bot tries to set before each tap
TÌM KIẾM. Different accounts have different kingdom barbarian levels."""

RESOURCE_TAB: str = "wood"
"""Which resource tab to select in the search panel."""

SKIP_LEVEL_ADJUST: bool = False
"""When True, skip the OCR+slider step and trust whatever level the
panel currently shows."""

TURN_WAIT_SEC: int = 60 * 60
"""Sleep interval between queue-status checks when the queue is full
(fallback when OCR of march-panel timers fails)."""

GATHER_MIN_SEC: int = 5 * 60
"""Minimum HH:MM:SS value treated as a real gather timer (anything
shorter is travel/return time and ignored)."""

_RESOURCE_TAB_X_PCT: dict[str, float] = {
    "barb": 0.258,
    "corn": 0.378,
    "wood": 0.497,
    "stone": 0.618,
    "gold": 0.738,
    "cycle": 0.497,
}
"""Hard-coded fallback X positions (pct of width) for each resource tab.
Used when OCR of the bottom-strip labels fails. Y is always ~91%."""
