"""Small utility helpers used by local mouse-path debugging."""
from __future__ import annotations

from pathlib import Path
from time import gmtime, strftime
from typing import Iterable, TypeVar

from PIL import Image

T = TypeVar("T")
CWD = Path(__file__).resolve().parent


def remove_dups(seq: Iterable[T]) -> list[T]:
    """Return items from ``seq`` while preserving the first occurrence order."""
    seen: set[T] = set()
    result: list[T] = []
    for item in seq:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def draw_points(
    points: Iterable[tuple[int, int]],
    width: int = 2000,
    height: int = 2000,
) -> Path | None:
    """Draw yellow crosses for path-debug points and save them under ``core/tmp``."""
    out_dir = CWD / "tmp"
    out_dir.mkdir(exist_ok=True)
    img = Image.new("RGB", (width, height))
    pix = img.load()

    for x, y in points:
        if not (1 <= x < width - 1 and 1 <= y < height - 1):
            continue
        pix[x, y] = (255, 255, 0)
        pix[x + 1, y + 1] = (255, 255, 0)
        pix[x + 1, y - 1] = (255, 255, 0)
        pix[x - 1, y + 1] = (255, 255, 0)
        pix[x - 1, y - 1] = (255, 255, 0)

    out_path = out_dir / f"out-{strftime('%Y%m%d-%H%M%S', gmtime())}.png"
    img.save(out_path)
    return out_path
