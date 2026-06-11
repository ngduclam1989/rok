"""Human-like mouse path helpers.

This module keeps the useful Bezier-path idea from the standalone mouse
prototype, but exposes it as pure Python data. The Windows-specific movement
and click code lives in ``core.bot.input_lock`` / ``core.device``.
"""
from __future__ import annotations

from math import ceil
from random import choice, randint
from typing import Iterable, Sequence

import numpy as np

Point = tuple[float, float]


def get_gaussian_click_coords(
    target_x: int | float,
    target_y: int | float,
    sigma: float = 5,
) -> tuple[int, int]:
    """Return click coordinates sampled around a target by Gaussian noise."""
    sigma = max(0.0, float(sigma))
    if sigma == 0:
        return int(round(target_x)), int(round(target_y))

    click_x = int(np.random.normal(loc=target_x, scale=sigma))
    click_y = int(np.random.normal(loc=target_y, scale=sigma))
    return click_x, click_y


def pascal_row(n: int) -> list[float]:
    """Return the nth row of Pascal's triangle."""
    result: list[float] = [1.0]
    numerator = n
    value = 1.0
    for denominator in range(1, n // 2 + 1):
        value *= numerator
        value /= denominator
        result.append(value)
        numerator -= 1
    if n & 1 == 0:
        result.extend(reversed(result[:-1]))
    else:
        result.extend(reversed(result))
    return result


def make_bezier(points: Sequence[Point]):
    """Build a function that evaluates the Bezier curve for ``points``."""
    n = len(points)
    combinations = pascal_row(n - 1)

    def bezier(ts: Iterable[float]) -> list[Point]:
        result: list[Point] = []
        for t in ts:
            tpowers = (t**i for i in range(n))
            upowers = reversed([(1 - t) ** i for i in range(n)])
            coefs = [c * a * b for c, a, b in zip(combinations, tpowers, upowers)]
            result.append(
                tuple(
                    sum(coef * p for coef, p in zip(coefs, axis_values))
                    for axis_values in zip(*points)
                )
            )
        return result

    return bezier


def mouse_bez(
    init_pos: tuple[int | float, int | float],
    fin_pos: tuple[int | float, int | float],
    deviation: int = 8,
    speed: int = 1,
) -> list[Point]:
    """Generate Bezier points between two cursor positions.

    ``deviation`` is the maximum control-point offset as a percent of travel
    distance. ``speed`` follows the original prototype: higher values return
    more points, so callers can move more slowly by sleeping between points.
    """
    speed = max(1, int(speed))
    deviation = max(0, int(deviation))
    start = (float(init_pos[0]), float(init_pos[1]))
    finish = (float(fin_pos[0]), float(fin_pos[1]))

    if start == finish:
        return [finish]
    if deviation == 0:
        return [start, finish]

    ts = [t / (speed * 100.0) for t in range(speed * 101)]
    dx = abs(ceil(finish[0]) - ceil(start[0]))
    dy = abs(ceil(finish[1]) - ceil(start[1]))

    min_dev = max(0, deviation // 2)
    control_1 = (
        start[0] + choice((-1, 1)) * dx * 0.01 * randint(min_dev, deviation),
        start[1] + choice((-1, 1)) * dy * 0.01 * randint(min_dev, deviation),
    )
    control_2 = (
        start[0] + choice((-1, 1)) * dx * 0.01 * randint(min_dev, deviation),
        start[1] + choice((-1, 1)) * dy * 0.01 * randint(min_dev, deviation),
    )

    return make_bezier([start, control_1, control_2, finish])(ts)


def connected_bez(
    coord_list: Sequence[tuple[int | float, int | float]],
    deviation: int = 8,
    speed: int = 1,
) -> list[Point]:
    """Connect multiple coordinates with Bezier path segments."""
    if not coord_list:
        return []
    points: list[Point] = []
    for index in range(1, len(coord_list)):
        segment = mouse_bez(coord_list[index - 1], coord_list[index], deviation, speed)
        if points and segment:
            segment = segment[1:]
        points.extend(segment)
    return points
