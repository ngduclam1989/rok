"""Multi-device orchestrator — one worker thread per device.

Each worker:
  1. Connects to the device (Airtest).
  2. Upserts device info into the store.
  3. Starts a run row, attaches a DbObserver, executes the scenario.
  4. On exit/crash, updates the run row and device status.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from .device import Device
from .scenario import Scenario, ScenarioRunner
from .store import DbObserver, DeviceRepository, RunRepository

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceConfig:
    name: str
    serial: str
    scenario: str  # filename inside scenarios_dir


class FleetRunner:
    def __init__(
        self,
        devices: list[DeviceConfig],
        scenarios_dir: Path,
        templates_dir: Path,
        device_repo: DeviceRepository,
        run_repo: RunRepository,
    ) -> None:
        self.devices = devices
        self.scenarios_dir = scenarios_dir
        self.templates_dir = templates_dir
        self.device_repo = device_repo
        self.run_repo = run_repo
        self.stop_flag = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for cfg in self.devices:
            t = threading.Thread(
                target=self._worker,
                args=(cfg,),
                name=f"worker-{cfg.name}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
        log.info("Đã khởi động %d worker thiết bị", len(self._threads))

    def wait(self) -> None:
        try:
            for t in self._threads:
                while t.is_alive():
                    t.join(timeout=1)
        except KeyboardInterrupt:
            log.info("Nhận tín hiệu ngắt — đang dừng mọi worker")
            self.stop()
            for t in self._threads:
                t.join(timeout=5)

    def stop(self) -> None:
        self.stop_flag.set()

    def _worker(self, cfg: DeviceConfig) -> None:
        run_id: int | None = None
        try:
            dev = Device(cfg.serial, self.templates_dir)
            info = dev.info()
            device_row = self.device_repo.upsert(
                serial=cfg.serial,
                name=cfg.name,
                model=info.get("model"),
                screen_w=info.get("screen_w"),
                screen_h=info.get("screen_h"),
            )
            self.device_repo.set_status(cfg.serial, "running")

            scen = Scenario.load(self.scenarios_dir / cfg.scenario)
            run_id = self.run_repo.start(device_row.id, cfg.scenario)
            self.run_repo.log_event(
                run_id, "info", f"Scenario '{scen.name}' started"
            )

            observer = DbObserver(self.run_repo, run_id)
            ScenarioRunner(
                dev, scen, self.stop_flag, observer=observer
            ).run()

            self.run_repo.end(run_id, "finished")
            self.device_repo.set_status(cfg.serial, "idle")
        except Exception as e:
            log.exception("[%s] worker crash", cfg.serial)
            if run_id is not None:
                try:
                    self.run_repo.end(
                        run_id,
                        "crashed",
                        last_error=f"{type(e).__name__}: {e}",
                    )
                except Exception:
                    log.exception(
                        "Không đánh dấu được run %d là crashed", run_id,
                    )
            try:
                self.device_repo.set_status(cfg.serial, "error")
            except Exception:
                log.exception("Cập nhật trạng thái thiết bị thất bại")
