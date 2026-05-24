"""CLI / Presentation layer.

Tách hoàn toàn khỏi business logic (core/) — chỉ làm việc với
argparse, stdin/stdout, console output. Mọi command trong
``cli/commands/`` chỉ gọi vào core/ chứ không tự động xử lý
domain logic.

Public API:
  * ``run(argv)`` — entry point, được ``main.py`` gọi.
"""
from __future__ import annotations

from .parser import run

__all__ = ["run"]
