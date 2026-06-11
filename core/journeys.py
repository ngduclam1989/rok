"""Reusable Python journey builders for RoK bot flows.

This module intentionally contains no WebUI code. It packages common bot
routes as plain Python functions that return the same step shape consumed by
``python main.py flow --flow-file ...``.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Literal, TypedDict


BlockId = Literal[
    "main.scout.mist_explore",
    "main.scout.cave_explore",
    "chore.alliance.gifts",
    "chore.alliance.tech",
    "chore.alliance.help",
    "chore.alliance.territory",
    "flow.sleep",
]


class JourneyStep(TypedDict, total=False):
    """One executable step for the existing flow runner."""

    blockId: str
    params: dict[str, Any]


ROOT = Path(__file__).resolve().parents[1]
MAIN_SCRIPT = ROOT / "main.py"


def step(block_id: str, **params: Any) -> JourneyStep:
    """Create one flow-runner step."""
    payload: JourneyStep = {"blockId": block_id}
    if params:
        payload["params"] = params
    return payload


def scout_mist(
    *,
    count: int = 10,
    wait_minutes: int = 30,
) -> JourneyStep:
    """Scout fog/mist for ``count`` rounds.

    Each round sends 3 scouts. The existing runner waits
    ``wait_minutes`` between rounds.
    """
    return step(
        "main.scout.mist_explore",
        count=max(1, int(count)),
        wait_minutes=max(0, int(wait_minutes)),
    )


def scout_cave(
    *,
    count: int = 10,
    wait_minutes_floor: int = 30,
) -> JourneyStep:
    """Scout caves for ``count`` rounds.

    The runner tries to OCR cave timers and sleeps by the longest timer plus
    buffer. ``wait_minutes_floor`` is the fallback minimum when OCR fails.
    """
    return step(
        "main.scout.cave_explore",
        count=max(1, int(count)),
        wait_minutes_floor=max(0, int(wait_minutes_floor)),
    )


def alliance_gifts() -> JourneyStep:
    """Claim alliance gifts."""
    return step("chore.alliance.gifts")


def alliance_tech() -> JourneyStep:
    """Donate to alliance technology."""
    return step("chore.alliance.tech")


def alliance_help() -> JourneyStep:
    """Tap alliance help if the help icon is available."""
    return step("chore.alliance.help")


def alliance_territory() -> JourneyStep:
    """Claim alliance territory resources."""
    return step("chore.alliance.territory")


def sleep(
    *,
    minutes: float = 30,
    with_chores: bool = True,
) -> JourneyStep:
    """Sleep between journey parts.

    The flow runner also tries to read march timers and adds that remaining
    travel/gather time before the requested ``minutes``.
    """
    return step(
        "flow.sleep",
        minutes=max(0.0, float(minutes)),
        with_chores=bool(with_chores),
    )


def scout_mist_journey(
    *,
    count: int = 10,
    wait_minutes: int = 30,
) -> list[JourneyStep]:
    """Journey: scout fog/mist only."""
    return [scout_mist(count=count, wait_minutes=wait_minutes)]


def scout_cave_journey(
    *,
    count: int = 10,
    wait_minutes_floor: int = 30,
) -> list[JourneyStep]:
    """Journey: scout caves only."""
    return [scout_cave(count=count, wait_minutes_floor=wait_minutes_floor)]


def alliance_chores_journey(
    *,
    gifts: bool = True,
    tech: bool = True,
    help_: bool = True,
    territory: bool = True,
) -> list[JourneyStep]:
    """Journey: run selected alliance chores in a stable order."""
    steps: list[JourneyStep] = []
    if gifts:
        steps.append(alliance_gifts())
    if tech:
        steps.append(alliance_tech())
    if help_:
        steps.append(alliance_help())
    if territory:
        steps.append(alliance_territory())
    return steps


def scout_and_alliance_journey(
    *,
    mist_count: int = 10,
    mist_wait_minutes: int = 30,
    cave_count: int = 10,
    cave_wait_minutes_floor: int = 30,
    run_mist: bool = True,
    run_cave: bool = True,
    run_chores_between: bool = True,
    run_chores_after: bool = True,
) -> list[JourneyStep]:
    """Journey: scout routes plus alliance chores.

    Default route:
      1. Mist scouting.
      2. Alliance chores.
      3. Cave scouting.
      4. Alliance chores.
    """
    steps: list[JourneyStep] = []
    chores = alliance_chores_journey()

    if run_mist:
        steps.append(
            scout_mist(count=mist_count, wait_minutes=mist_wait_minutes),
        )
        if run_chores_between:
            steps.extend(chores)

    if run_cave:
        steps.append(
            scout_cave(
                count=cave_count,
                wait_minutes_floor=cave_wait_minutes_floor,
            ),
        )
        if run_chores_after:
            steps.extend(alliance_chores_journey())

    if not steps and (run_chores_between or run_chores_after):
        steps.extend(chores)
    return steps


def write_journey(path: str | Path, steps: Iterable[JourneyStep]) -> Path:
    """Write a journey to JSON for ``python main.py flow --flow-file``."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(list(steps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def load_journey(path: str | Path) -> list[JourneyStep]:
    """Load a journey JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("journey JSON must be a list")
    return data


def run_journey(
    *,
    serial: str,
    steps: Iterable[JourneyStep],
    input_method: Literal["auto", "sendevent", "input"] = "auto",
    no_humanize: bool = False,
    humanize_jitter: int = 6,
    log_file: str | Path | None = None,
) -> int:
    """Run a journey through the existing CLI flow runner.

    This helper is useful from small Python scripts. For long-running bot
    sessions, it still executes through ``main.py flow`` so behavior stays
    identical to the existing project engine.
    """
    if not serial:
        raise ValueError("serial is required")

    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".flow.json",
        delete=False,
        encoding="utf-8",
    ) as f:
        json.dump(list(steps), f, ensure_ascii=False, indent=2)
        flow_file = Path(f.name)

    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "flow",
        "--serial",
        serial,
        "--flow-file",
        str(flow_file),
        "--input-method",
        input_method,
        "--humanize-jitter",
        str(int(humanize_jitter)),
    ]
    if no_humanize:
        cmd.append("--no-humanize")
    if log_file is not None:
        cmd.extend(["--log-file", str(log_file)])

    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
        return int(proc.returncode)
    finally:
        try:
            flow_file.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "JourneyStep",
    "alliance_chores_journey",
    "alliance_gifts",
    "alliance_help",
    "alliance_tech",
    "alliance_territory",
    "load_journey",
    "run_journey",
    "scout_and_alliance_journey",
    "scout_cave",
    "scout_cave_journey",
    "scout_mist",
    "scout_mist_journey",
    "sleep",
    "step",
    "write_journey",
]
