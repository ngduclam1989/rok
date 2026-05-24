"""RoK auto-gather state-machine bot.

Public API (used by ``main.py`` and CLI):
    * ``run(device, max_iterations=None)`` — main loop.
    * ``main(argv=None)`` — CLI entry.
    * ``detect_state(device, screen) -> S`` — state classifier.
    * ``read_slot_badge(screen) -> (n, max)`` — queue badge OCR.
    * Mutable settings: ``MAX_SLOTS``, ``TARGET_LEVEL``, ``RESOURCE_TAB``,
      ``SKIP_LEVEL_ADJUST``, ``TURN_WAIT_SEC``, ``GATHER_MIN_SEC``.

Backwards compat: ``main.py`` reads and writes the settings as
attributes on this module (``bot.MAX_SLOTS = 4``). A custom module
class forwards those writes to the ``config`` submodule so internal
handlers — which read ``config.MAX_SLOTS`` lazily — see the new value.

Layout:
    config       — mutable runtime config (read by everything else).
    constants    — paths (ROOT, CAPTURES_DIR, TEMPLATES_DIR, STOP_FLAG).
    state        — S enum + StepResult dataclass.
    signals      — graceful-stop handler + sleep helpers.
    geometry     — coord helpers, OCR-region helper, template-tap.
    detection    — is_lock_screen, is_network_popup, detect_state.
    readers      — read_slot_badge, read_level_in_panel, march timers.
    handlers/    — one ``handle_*`` per S enum value.
    runtime      — run(), navigation glue, _poll_until_slot_free, main.
"""
from __future__ import annotations

import sys as _sys
import types as _types

from . import config as _config
from .detection import detect_state
from .readers import read_slot_badge
from .runtime import main, run
from .state import S, StepResult

# Names that ``main.py`` may write to. Writes are forwarded to
# ``config`` so submodules that read ``config.X`` see the new value.
_CONFIG_NAMES = frozenset({
    "MAX_SLOTS", "TARGET_LEVEL", "RESOURCE_TAB",
    "SKIP_LEVEL_ADJUST", "TURN_WAIT_SEC", "GATHER_MIN_SEC",
})


class _BotPackage(_types.ModuleType):
    """Custom module type so ``bot.MAX_SLOTS = 4`` forwards to config."""

    def __setattr__(self, name: str, value: object) -> None:
        if name in _CONFIG_NAMES:
            setattr(_config, name, value)
        _types.ModuleType.__setattr__(self, name, value)

    def __getattr__(self, name: str) -> object:
        # Default __getattr__ is only invoked when the attribute is
        # NOT found via normal lookup. Use it to surface ``config``
        # values even if they were never explicitly imported here.
        if name in _CONFIG_NAMES:
            return getattr(_config, name)
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}",
        )


_sys.modules[__name__].__class__ = _BotPackage

# Seed public config attributes so ``hasattr(bot, "MAX_SLOTS")`` is
# True without triggering __getattr__. Forwarded back to ``config``
# via the custom __setattr__.
MAX_SLOTS = _config.MAX_SLOTS
TARGET_LEVEL = _config.TARGET_LEVEL
RESOURCE_TAB = _config.RESOURCE_TAB
SKIP_LEVEL_ADJUST = _config.SKIP_LEVEL_ADJUST
TURN_WAIT_SEC = _config.TURN_WAIT_SEC
GATHER_MIN_SEC = _config.GATHER_MIN_SEC

__all__ = [
    "GATHER_MIN_SEC",
    "MAX_SLOTS",
    "RESOURCE_TAB",
    "S",
    "SKIP_LEVEL_ADJUST",
    "StepResult",
    "TARGET_LEVEL",
    "TURN_WAIT_SEC",
    "detect_state",
    "main",
    "read_slot_badge",
    "run",
]


if __name__ == "__main__":
    raise SystemExit(main())
