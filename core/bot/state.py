"""State enum + StepResult dataclass for the bot state machine."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class S(Enum):
    """Known game states. Detection order in ``detection.detect_state``
    matters — first match wins."""

    LOCK_SCREEN = "lock_screen"
    EXIT_DIALOG = "exit_dialog"
    POPUP = "popup"
    BUILD_MENU = "build_menu"
    SEARCH_PANEL = "search_panel"
    TILE_INFO = "tile_info"
    MARCH_PLAN = "march_plan"
    WORLD = "world"
    CITY = "city"
    NETWORK_ERROR = "network_error"  # popup "Mạng không ổn định"
    GEMS_SHOP = "gems_shop"          # cửa hàng đá quý / nạp tiền
    ALLIANCE_PANEL = "alliance_panel"# bảng màn hình liên minh
    PRE_KVK = "pre_kvk"              # sự kiện Đêm Giao Thừa Của Cuộc Thập Tự Chinh
    TROOPS_PANEL = "troops_panel"
    UNKNOWN = "unknown"




@dataclass
class StepResult:
    """Return value of every ``handle_*`` function.

    ``goal_reached`` signals a successful dispatch — the main loop
    counts it toward the queue and decides whether to enter the
    slot-poll sleep flow.
    """

    success: bool
    note: str = ""
    sleep_after: float = 1.5
    goal_reached: bool = False
    slots_full: bool = False
    slot_full_wait_sec: float | None = None
