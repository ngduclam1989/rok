"""State handlers — one per S enum value (plus the network mid-flow check).

Each ``handle_*`` function takes ``(device, screen)`` (handle_unknown
also takes ``stuck_count``) and returns a ``StepResult``.
"""
from __future__ import annotations

from . import search_panel as _search_panel
from .lock_screen import handle_lock_screen
from .march_plan import handle_march_plan
from .navigation import (
    handle_city,
    handle_switch_account,
    handle_switch_character,
    handle_switch_to_first_account,
    handle_world,
)
from .network import check_and_handle_network_popup, handle_network_error
from .popups import handle_build_menu, handle_exit_dialog, handle_popup, handle_gems_shop
from .search_panel import handle_search_panel
from .tile_info import handle_tile_info
from .unknown import handle_unknown


def reset_slider_state() -> None:
    """Reset the search-panel slider tracking — called by ``runtime.run``
    at the start of each new turn."""
    _search_panel.reset_slider_state()


__all__ = [
    "check_and_handle_network_popup",
    "handle_build_menu",
    "handle_city",
    "handle_exit_dialog",
    "handle_lock_screen",
    "handle_march_plan",
    "handle_network_error",
    "handle_popup",
    "handle_gems_shop",
    "handle_search_panel",
    "handle_tile_info",
    "handle_unknown",
    "handle_world",
    "handle_switch_account",
    "handle_switch_character",
    "handle_switch_to_first_account",
    "reset_slider_state",
]
