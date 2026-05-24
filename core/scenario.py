"""YAML scenario interpreter with OCR, percent coords, and state checks.

Supported step keys (old + new):

  Positioning
    tap_xy:        [x, y]                        # absolute pixels
    tap_pct:       [x_pct, y_pct]                # percent of screen

  Find-then-tap (preferred — robust across resolutions)
    find_and_tap:
      text: "TÌM KIẾM"                # OCR Vietnamese
      # OR
      template: "btn_tim_kiem.png"
      region_pct: [40, 60, 70, 90]    # search box (optional)
      threshold: 0.7
      timeout: 5
      fallback_tap_pct: [x, y]        # fired if find fails
      on_fail: [<step>, ...]          # extra recovery steps

  State machine
    wait_for_text:
      any: ["Cấp", "TÌM KIẾM"]
      region_pct: [...]
      timeout: 5
      on_fail: [<step>, ...]

    assert_state:
      any: ["Bảng đồ"]                # synonym wait_for_text + raise
      region_pct: [...]
      timeout: 3
      on_fail: [<step>, ...]

    ensure_value:                     # loop tap until OCR shows target
      pattern: "Cấp\\s+(\\d+)"
      region_pct: [38, 50, 50, 65]
      target: 5
      decrease_tap_pct: [40.8, 57.9]
      increase_tap_pct: [55, 57.9]    # optional
      max_taps: 10
      poll_after_tap_sec: 0.4

  Scheduling
    read_timers:                      # parse all HH:MM:SS into runner state
      region_pct: [25, 25, 75, 90]
      only_if: "Dang thu gom"         # optional row filter
      save_as: army_timers

    wait_until_min:                   # sleep min(timers) + jitter
      source: army_timers
      jitter_min_sec: 600
      jitter_max_sec: 900
      log_every_sec: 60

  March-queue badge
    read_slot_count:                  # OCR "n/N" badge, save state
      region_pct: [85, 8, 100, 22]
      save_as: slots

    if_slots_full:                    # branch on slot count
      source: slots
      default_when_unknown: not_full  # if OCR fails -> treat as "not full"
      when_full: [<step>, ...]
      when_not_full: [<step>, ...]

  Misc (kept from v1)
    swipe:         [x1, y1, x2, y2, duration_ms]
    wait:          float seconds  OR  {min, max}
    key:           "BACK" | "HOME" | ...
    if_exists:     "img.png" or {template, threshold}
    log:           "message"

The engine has zero DB dependency. It emits events via the ScenarioObserver
Protocol; the store package's DbObserver persists them.
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from . import ocr, scheduler, vision
from .device import Device

log = logging.getLogger(__name__)


class ScenarioObserver(Protocol):
    def on_iteration(self) -> None: ...
    def on_error(self, message: str) -> None: ...
    def on_log(self, level: str, message: str) -> None: ...


class NullObserver:
    def on_iteration(self) -> None: ...
    def on_error(self, message: str) -> None: ...
    def on_log(self, level: str, message: str) -> None: ...


@dataclass(frozen=True)
class Scenario:
    name: str
    loop: bool
    loop_interval: float
    on_error: str  # "continue" | "stop"
    steps: list[dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            name=data.get("name", path.stem),
            loop=bool(data.get("loop", False)),
            loop_interval=float(data.get("loop_interval", 0)),
            on_error=str(data.get("on_error", "stop")),
            steps=list(data.get("steps", [])),
        )


class ScenarioRunner:
    """Executes scenario steps against a Device.

    Holds a tiny per-run state dict (`_vars`) so steps can pass values to
    later steps (e.g. read_timers -> wait_until_min).
    """

    def __init__(
        self,
        device: Device,
        scenario: Scenario,
        stop_flag: threading.Event,
        observer: ScenarioObserver | None = None,
    ) -> None:
        self.device = device
        self.scenario = scenario
        self.stop_flag = stop_flag
        self.observer: ScenarioObserver = observer or NullObserver()
        self._vars: dict[str, Any] = {}
        # When a wait_for_text with abort_on_fail=true fails, this flag is
        # set and _run_steps skips remaining steps until the next iteration.
        self._abort_iteration: bool = False
        info = device.info()
        self._screen_w = int(info.get("screen_w") or 0)
        self._screen_h = int(info.get("screen_h") or 0)
        if self._screen_w <= 0 or self._screen_h <= 0:
            raise RuntimeError(
                f"Cannot read screen size for {device.serial}: {info}"
            )
        log.info(
            "[%s] screen %dx%d",
            device.serial,
            self._screen_w,
            self._screen_h,
        )

    # --- entry point ---------------------------------------------------

    def run(self) -> None:
        log.info(
            "[%s] start scenario '%s'", self.device.serial, self.scenario.name
        )
        try:
            while not self.stop_flag.is_set():
                self._abort_iteration = False
                self._run_steps(self.scenario.steps)
                self.observer.on_iteration()
                if not self.scenario.loop:
                    break
                if self.scenario.loop_interval > 0:
                    self._interruptible_sleep(self.scenario.loop_interval)
        finally:
            log.info(
                "[%s] scenario '%s' ended",
                self.device.serial,
                self.scenario.name,
            )

    # --- coordinate helpers --------------------------------------------

    def _pct_to_px(self, p: Any) -> tuple[int, int]:
        return (
            int(round(self._screen_w * float(p[0]) / 100.0)),
            int(round(self._screen_h * float(p[1]) / 100.0)),
        )

    def _region_pct_to_px(self, r: Any) -> tuple[int, int, int, int]:
        return (
            int(round(self._screen_w * float(r[0]) / 100.0)),
            int(round(self._screen_h * float(r[1]) / 100.0)),
            int(round(self._screen_w * float(r[2]) / 100.0)),
            int(round(self._screen_h * float(r[3]) / 100.0)),
        )

    def _template_path(self, name: str) -> Path:
        return self.device.templates_dir / name

    # --- step dispatch -------------------------------------------------

    def _run_steps(self, steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if self.stop_flag.is_set():
                return
            if self._abort_iteration:
                return
            try:
                self._run_one(step)
            except Exception as e:
                log.exception(
                    "[%s] step failed: %s", self.device.serial, step
                )
                self.observer.on_error(f"{type(e).__name__}: {e}")
                if self.scenario.on_error == "stop":
                    raise

    def _run_one(self, step: dict[str, Any]) -> None:  # noqa: C901
        # Order matters only for backward-compat keys vs new keys with the
        # same conceptual meaning (e.g. tap_xy and tap_pct).
        if "tap_xy" in step:
            x, y = step["tap_xy"]
            self.device.tap(int(x), int(y))
            return

        if "tap_pct" in step:
            x, y = self._pct_to_px(step["tap_pct"])
            self.device.tap(x, y)
            return

        if "find_and_tap" in step:
            self._step_find_and_tap(step["find_and_tap"])
            return

        if "wait_for_text" in step:
            self._step_wait_for_text(
                step["wait_for_text"], raise_on_fail=False
            )
            return

        if "assert_state" in step:
            self._step_wait_for_text(step["assert_state"], raise_on_fail=True)
            return

        if "ensure_value" in step:
            self._step_ensure_value(step["ensure_value"])
            return

        if "read_timers" in step:
            self._step_read_timers(step["read_timers"])
            return

        if "wait_until_min" in step:
            self._step_wait_until_min(step["wait_until_min"])
            return

        if "read_slot_count" in step:
            self._step_read_slot_count(step["read_slot_count"])
            return

        if "if_slots_full" in step:
            self._step_if_slots_full(step["if_slots_full"])
            return

        if "tap_template" in step:
            spec = step["tap_template"]
            if isinstance(spec, str):
                name, threshold, timeout = spec, 0.8, 0.0
            else:
                name = spec["name"]
                threshold = float(spec.get("threshold", 0.8))
                timeout = float(spec.get("timeout", 0))
            result = self.device.tap_template(
                name, threshold=threshold, timeout=timeout
            )
            if not result.matched:
                raise RuntimeError(
                    f"Template '{name}' not found within {timeout}s"
                )
            return

        if "swipe" in step:
            x1, y1, x2, y2, dur = step["swipe"]
            self.device.swipe(int(x1), int(y1), int(x2), int(y2), int(dur))
            return

        if "wait" in step:
            spec = step["wait"]
            if isinstance(spec, (int, float)):
                self._interruptible_sleep(float(spec))
            else:
                lo, hi = float(spec["min"]), float(spec["max"])
                self._interruptible_sleep(random.uniform(lo, hi))
            return

        if "key" in step:
            self.device.key(str(step["key"]))
            return

        if "if_exists" in step:
            spec = step["if_exists"]
            if isinstance(spec, dict) and (
                "text" in spec or "any" in spec
            ):
                # OCR-based existence check
                queries = spec.get("any") or [spec["text"]]
                region = spec.get("region_pct")
                region_px = (
                    self._region_pct_to_px(region) if region else None
                )
                threshold = float(spec.get("threshold", 0.55))
                screen = self.device.snapshot()
                norm_qs = [
                    ocr.strip_diacritics(q).lower() for q in queries
                ]
                found = False
                for hit in ocr.find_all(screen, region=region_px):
                    if hit.confidence < threshold:
                        continue
                    t = ocr.strip_diacritics(hit.text).lower()
                    if any(q in t for q in norm_qs):
                        found = True
                        break
                branch = "then" if found else "else"
            elif isinstance(spec, dict):
                name = spec["template"]
                threshold = float(spec.get("threshold", 0.8))
                branch = (
                    "then" if self.device.exists(name, threshold)
                    else "else"
                )
            else:
                branch = (
                    "then" if self.device.exists(spec, 0.8)
                    else "else"
                )
            self._run_steps(list(step.get(branch, [])))
            return

        if "log" in step:
            msg = str(step["log"])
            log.info("[%s] %s", self.device.serial, msg)
            self.observer.on_log("info", msg)
            return

        raise ValueError(f"Unknown step: {step}")

    # --- step implementations ------------------------------------------

    def _step_find_and_tap(self, spec: dict[str, Any]) -> None:
        text = spec.get("text")
        template = spec.get("template")
        if not (text or template) or (text and template):
            raise ValueError(
                "find_and_tap requires exactly one of 'text' or 'template'"
            )
        region = spec.get("region_pct")
        region_px = self._region_pct_to_px(region) if region else None
        threshold = float(spec.get("threshold", 0.7 if text else 0.8))
        timeout = float(spec.get("timeout", 0))
        poll = float(spec.get("poll_sec", 0.5))

        deadline = time.monotonic() + timeout
        while True:
            screen = self.device.snapshot()
            if text:
                hit = ocr.find_text(
                    screen, text, region=region_px, threshold=threshold
                )
                pos = (hit.cx, hit.cy) if hit else None
            else:
                tpl_path = self._template_path(str(template))
                m = vision.find_template(
                    screen,
                    tpl_path,
                    region=region_px,
                    threshold=threshold,
                )
                pos = (m.cx, m.cy) if m else None
            if pos is not None:
                self.device.tap(*pos)
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(poll)

        # find failed -> fallback path
        fallback = spec.get("fallback_tap_pct")
        if fallback:
            x, y = self._pct_to_px(fallback)
            log.warning(
                "[%s] find_and_tap fell back to pct %s",
                self.device.serial,
                fallback,
            )
            self.device.tap(x, y)
            return

        on_fail = spec.get("on_fail")
        if on_fail:
            self._run_steps(list(on_fail))
            return

        target = text or template
        raise RuntimeError(f"find_and_tap: '{target}' not found in {timeout}s")

    def _step_wait_for_text(
        self, spec: dict[str, Any], raise_on_fail: bool
    ) -> None:
        queries = spec.get("any") or ([spec["text"]] if "text" in spec else [])
        if not queries:
            raise ValueError(
                "wait_for_text/assert_state needs 'any: [...]' or 'text: ...'"
            )
        region = spec.get("region_pct")
        region_px = self._region_pct_to_px(region) if region else None
        timeout = float(spec.get("timeout", 5))
        poll = float(spec.get("poll_sec", 0.5))
        threshold = float(spec.get("threshold", 0.6))

        deadline = time.monotonic() + timeout
        queries_norm = [
            ocr.strip_diacritics(q).lower() for q in queries
        ]
        while True:
            screen = self.device.snapshot()
            for hit in ocr.find_all(screen, region=region_px):
                if hit.confidence < threshold:
                    continue
                t = ocr.strip_diacritics(hit.text).lower()
                if any(q in t for q in queries_norm):
                    return
            if time.monotonic() >= deadline:
                break
            time.sleep(poll)

        abort = bool(spec.get("abort_on_fail", False))
        on_fail = spec.get("on_fail")
        if on_fail:
            log.warning(
                "[%s] state check failed for %s, running on_fail",
                self.device.serial,
                queries,
            )
            self._run_steps(list(on_fail))
            if abort:
                log.warning(
                    "[%s] abort_on_fail -> skip rest of iteration",
                    self.device.serial,
                )
                self._abort_iteration = True
            return

        msg = f"wait_for_text: none of {queries} appeared in {timeout}s"
        if raise_on_fail:
            raise RuntimeError(msg)
        if abort:
            log.warning(
                "[%s] %s -> abort iteration", self.device.serial, msg,
            )
            self._abort_iteration = True
            return
        log.warning("[%s] %s (continuing)", self.device.serial, msg)

    def _step_ensure_value(self, spec: dict[str, Any]) -> None:
        pattern = re.compile(str(spec["pattern"]))
        region = spec.get("region_pct")
        region_px = self._region_pct_to_px(region) if region else None
        target = int(spec["target"])
        max_taps = int(spec.get("max_taps", 10))
        poll = float(spec.get("poll_after_tap_sec", 0.4))
        dec = spec.get("decrease_tap_pct")
        inc = spec.get("increase_tap_pct")

        for attempt in range(max_taps + 1):
            screen = self.device.snapshot()
            found = ocr.find_pattern(screen, pattern, region=region_px)
            if found is None:
                # Dump what OCR actually saw to help debug bad regex / region.
                seen = [
                    h.text for h in ocr.find_all(screen, region=region_px)
                ]
                log.warning(
                    "[%s] ensure_value: pattern '%s' not visible. "
                    "OCR saw in region: %r",
                    self.device.serial,
                    pattern.pattern,
                    seen,
                )
                if attempt >= 2:
                    return
                time.sleep(poll)
                continue
            _, match = found
            try:
                value = int(match.group(1))
            except (ValueError, IndexError):
                log.warning(
                    "[%s] ensure_value: bad capture from '%s'",
                    self.device.serial,
                    match.group(0),
                )
                return
            if value == target:
                log.info(
                    "[%s] ensure_value reached target %d",
                    self.device.serial,
                    target,
                )
                return
            if value > target and dec:
                x, y = self._pct_to_px(dec)
                direction = "-"
            elif value < target and inc:
                x, y = self._pct_to_px(inc)
                direction = "+"
            else:
                log.warning(
                    "[%s] ensure_value: value=%d target=%d but no "
                    "adjuster button defined",
                    self.device.serial,
                    value,
                    target,
                )
                return
            log.info(
                "[%s] ensure_value: %d->%d tap %s at (%d,%d)",
                self.device.serial, value, target, direction, x, y,
            )
            self.device.tap(x, y)
            time.sleep(poll)

        log.warning(
            "[%s] ensure_value: gave up after %d taps",
            self.device.serial,
            max_taps,
        )

    def _step_read_timers(self, spec: dict[str, Any]) -> None:
        """Read HH:MM:SS timers, optionally filtered by `only_if` label.

        For RoK gather: only_if = "Dang thu gom" — ignore march/return timers
        and sleep only on actually-gathering troops. We use OCR cell positions
        so an HH:MM:SS hit is kept only if a label like "Đang thu gom" sits
        on roughly the same row (within ~5% of screen height).
        """
        region = spec.get("region_pct")
        region_px = self._region_pct_to_px(region) if region else None
        save_as = str(spec.get("save_as", "timers"))
        only_if = spec.get("only_if")
        screen = self.device.snapshot()
        hits = ocr.find_all(screen, region=region_px)

        all_texts = [h.text for h in hits]

        if only_if:
            needle = ocr.strip_diacritics(str(only_if)).lower()
            row_tol_px = max(20, int(self._screen_h * 0.05))
            label_rows = [
                h.cy for h in hits
                if needle in ocr.strip_diacritics(h.text).lower()
            ]
            texts: list[str] = []
            for h in hits:
                if scheduler.parse_hms(h.text) is None:
                    continue
                same_row = any(
                    abs(h.cy - ly) <= row_tol_px for ly in label_rows
                )
                if same_row:
                    texts.append(h.text)
        else:
            texts = all_texts

        seconds = scheduler.parse_all_hms(texts)
        self._vars[save_as] = {
            "texts": texts,
            "all_texts": all_texts,
            "seconds": seconds,
            "min_seconds": min(seconds) if seconds else None,
        }
        log.info(
            "[%s] read_timers '%s': %d gather rows (of %d cells), min=%s",
            self.device.serial,
            save_as,
            len(texts),
            len(all_texts),
            seconds and min(seconds),
        )

    _SLOT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")

    def _step_read_slot_count(self, spec: dict[str, Any]) -> None:
        """OCR the march-queue badge 'n/N' (e.g. 3/4) and save to _vars.

        Saved shape: {"n": int|None, "max": int|None, "full": bool}.
        full is True only when both numbers parsed AND n == max.
        """
        region = spec.get("region_pct")
        region_px = self._region_pct_to_px(region) if region else None
        save_as = str(spec.get("save_as", "slots"))
        screen = self.device.snapshot()
        hits = ocr.find_all(screen, region=region_px)
        n_val: int | None = None
        m_val: int | None = None
        for h in hits:
            match = self._SLOT_RE.search(h.text)
            if not match:
                continue
            try:
                a = int(match.group(1))
                b = int(match.group(2))
            except ValueError:
                continue
            # Sanity: march queue is small, ignore wild numbers
            if 0 <= a <= b <= 20:
                n_val, m_val = a, b
                break
        full = n_val is not None and m_val is not None and n_val == m_val
        self._vars[save_as] = {"n": n_val, "max": m_val, "full": full}
        log.info(
            "[%s] read_slot_count '%s': n=%s max=%s full=%s",
            self.device.serial, save_as, n_val, m_val, full,
        )

    def _step_if_slots_full(self, spec: dict[str, Any]) -> None:
        source = str(spec.get("source", "slots"))
        state = self._vars.get(source) or {}
        if state.get("n") is None or state.get("max") is None:
            default = str(spec.get("default_when_unknown", "not_full"))
            full = default == "full"
            log.warning(
                "[%s] if_slots_full: slot OCR unknown, default=%s",
                self.device.serial, default,
            )
        else:
            full = bool(state.get("full"))
        branch = "when_full" if full else "when_not_full"
        self._run_steps(list(spec.get(branch, [])))

    def _step_wait_until_min(self, spec: dict[str, Any]) -> None:
        source = str(spec.get("source", "timers"))
        state = self._vars.get(source)
        jitter_min = int(spec.get("jitter_min_sec", 600))
        jitter_max = int(spec.get("jitter_max_sec", 900))
        log_every = int(spec.get("log_every_sec", 60))
        floor = int(spec.get("floor_sec", 30))

        base = 0
        if state and state.get("min_seconds") is not None:
            base = int(state["min_seconds"])
        else:
            log.warning(
                "[%s] wait_until_min: no timer found in '%s', using floor",
                self.device.serial,
                source,
            )

        total = scheduler.jittered_wait(
            base, jitter_min_sec=jitter_min, jitter_max_sec=jitter_max,
            floor_sec=floor,
        )
        log.info(
            "[%s] wait_until_min: base=%ds + jitter -> %ds",
            self.device.serial,
            base,
            total,
        )
        self._interruptible_sleep(float(total), log_every=log_every)

    # --- sleep that respects stop_flag ---------------------------------

    def _interruptible_sleep(
        self, seconds: float, log_every: int = 0
    ) -> None:
        deadline = time.monotonic() + seconds
        next_log = time.monotonic() + log_every if log_every > 0 else 0.0
        while not self.stop_flag.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if log_every > 0 and time.monotonic() >= next_log:
                log.info(
                    "[%s] still waiting, %ds left",
                    self.device.serial,
                    int(remaining),
                )
                next_log = time.monotonic() + log_every
            time.sleep(min(1.0, remaining))
