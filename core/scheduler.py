"""Timer parsing + jittered next-run scheduling.

Used to read 'Đang thu gom HH:MM:SS' values from the Đội Quân panel and
compute a sleep duration: shortest-remaining + random jitter so the next
gather wave doesn't land on a robotic interval.
"""
from __future__ import annotations

import logging
import random
import re

log = logging.getLogger(__name__)

_HMS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")


def parse_hms(text: str) -> int | None:
    """Parse a 'HH:MM:SS' substring from `text` -> total seconds."""
    m = _HMS.search(text)
    if not m:
        return None
    h, mm, s = (int(g) for g in m.groups())
    return h * 3600 + mm * 60 + s


def parse_all_hms(texts: list[str]) -> list[int]:
    """Parse every 'HH:MM:SS' substring across a list of OCR text lines."""
    out: list[int] = []
    for t in texts:
        v = parse_hms(t)
        if v is not None:
            out.append(v)
    return out


def min_timer_seconds(texts: list[str]) -> int | None:
    """Shortest remaining HH:MM:SS, or None if no timer matched."""
    parsed = parse_all_hms(texts)
    return min(parsed) if parsed else None


def jittered_wait(
    base_seconds: int,
    jitter_min_sec: int = 600,
    jitter_max_sec: int = 900,
    floor_sec: int = 30,
) -> int:
    """`base_seconds` + uniform random [jitter_min_sec, jitter_max_sec].

    Result is never less than `floor_sec` to protect against bogus tiny
    base values (e.g. OCR misread '00:00:00').
    """
    if jitter_min_sec > jitter_max_sec:
        jitter_min_sec, jitter_max_sec = jitter_max_sec, jitter_min_sec
    jitter = random.randint(jitter_min_sec, jitter_max_sec)
    return max(floor_sec, base_seconds + jitter)
