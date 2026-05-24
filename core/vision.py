"""OpenCV multi-scale template matching with region-lock.

Faster + more accurate than full-screen single-scale matching because:
  * region crop eliminates noisy matches elsewhere on screen
  * multiple scales (0.9..1.1) absorb minor render differences
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchHit:
    cx: int          # full-image x
    cy: int          # full-image y
    score: float
    width: int
    height: int


def _to_bgr(image: Any) -> np.ndarray:
    if isinstance(image, np.ndarray):
        return image
    arr = np.array(image.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def find_template(
    image: Any,
    template_path: Path,
    region: tuple[int, int, int, int] | None = None,
    threshold: float = 0.8,
    scales: tuple[float, ...] = (1.0, 0.95, 1.05, 0.9, 1.1),
) -> MatchHit | None:
    """Locate `template_path` in `image` (optionally within `region`).

    Returns the highest-scoring match >= threshold, with coords mapped back
    into absolute screen pixels.
    """
    haystack = _to_bgr(image)
    ox, oy = 0, 0
    if region is not None:
        x1, y1, x2, y2 = region
        ox, oy = x1, y1
        haystack = haystack[y1:y2, x1:x2].copy()
    if haystack.size == 0:
        return None
    tpl = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if tpl is None:
        raise FileNotFoundError(f"Template not found: {template_path}")
    best: MatchHit | None = None
    for s in scales:
        if s == 1.0:
            t = tpl
        else:
            new_w = max(1, int(tpl.shape[1] * s))
            new_h = max(1, int(tpl.shape[0] * s))
            t = cv2.resize(tpl, (new_w, new_h), interpolation=cv2.INTER_AREA)
        if t.shape[0] > haystack.shape[0] or t.shape[1] > haystack.shape[1]:
            continue
        res = cv2.matchTemplate(haystack, t, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < threshold:
            continue
        if best is not None and max_val <= best.score:
            continue
        cx = max_loc[0] + t.shape[1] // 2 + ox
        cy = max_loc[1] + t.shape[0] // 2 + oy
        best = MatchHit(
            cx=cx,
            cy=cy,
            score=float(max_val),
            width=t.shape[1],
            height=t.shape[0],
        )
    return best
