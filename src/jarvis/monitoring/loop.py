from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from ..user_settings import JarvisSettings
from . import checks
from .thermal import read_cpu_temperature

logger = logging.getLogger(__name__)

Notifier = Callable[[str], None]
ReadingCallback = Callable[[str, object], None]

# Matches windows_actions.py's temperature_warning() default and
# settings_page.py's _TEMPERATURE_DEFAULT -- used only when no settings
# object was passed in, or the user has not saved a threshold yet.
_DEFAULT_TEMPERATURE_WARNING_C = 85


@dataclass
class MonitorIntervals:
    battery: float = 5 * 60
    internet: float = 30.0
    nvidia_driver: float = 60 * 60
    windows_update: float = 6 * 60 * 60
    cpu: float = 2.0
    memory: float = 2.0
    gpu: float = 5.0
    disk: float = 5 * 60
    cpu_temperature: float = 10.0


class BackgroundMonitor:
    """Runs periodic Windows health checks, each on its own timer and
    thread, and calls notify(message) whenever a check decides an alert is
    warranted. Each check runs independently so a slow one (Windows Update
    search can take a minute or more) never delays the others.
    Instances are single-use: repeated start calls are ignored, including
    after stop. Construct a new monitor for a new application session.
    """

    def __init__(
        self,
        notify: Notifier,
        intervals: MonitorIntervals | None = None,
        on_reading: ReadingCallback | None = None,
        settings: JarvisSettings | None = None,
    ) -> None:
        self.notify = notify
        self.on_reading = on_reading
        self.intervals = intervals or MonitorIntervals()
        # Held live (not copied), same as router.py/GuiSafetyPolicy: a
        # Settings > "Temperature warning threshold" change takes effect on
        # the very next GPU poll, no restart needed. None (cli.py's plain
        # --monitor mode may not pass one) falls back to
        # _DEFAULT_TEMPERATURE_WARNING_C.
        self._settings = settings
        self._stop_event = threading.Event()
        self._lifecycle_lock = threading.RLock()
        self._threads: list[threading.Thread] = []

        self._battery_state = checks.BatteryState()
        self._internet_state = checks.InternetState()
        self._driver_state = checks.NvidiaDriverState()
        self._update_state = checks.WindowsUpdateState()
        self._disk_state = checks.DiskState()
        self._gpu_temperature_state = checks.GpuTemperatureState()
        self._cpu_temperature_alerted = False

        # See checks.prime_cpu_reading()'s docstring: without this, the
        # dashboard's first CPU reading would flash "0%".
        checks.prime_cpu_reading()

    def start(self) -> None:
        jobs = (
            (self._check_battery, self.intervals.battery),
            (self._check_internet, self.intervals.internet),
            (self._check_nvidia_driver, self.intervals.nvidia_driver),
            (self._check_windows_update, self.intervals.windows_update),
            (self._check_cpu, self.intervals.cpu),
            (self._check_memory, self.intervals.memory),
            (self._check_gpu, self.intervals.gpu),
            (self._check_disk, self.intervals.disk),
            (self._check_cpu_temperature, self.intervals.cpu_temperature),
        )
        with self._lifecycle_lock:
            # This monitor is single-use; repeated starts must not duplicate polls.
            if self._threads or self._stop_event.is_set():
                return
            for job, interval in jobs:
                thread = threading.Thread(target=self._run_loop, args=(job, interval), daemon=True)
                thread.start()
                self._threads.append(thread)

    def stop(self) -> None:
        # Do not wait for slow Windows queries, but fence their late callbacks.
        with self._lifecycle_lock:
            self._stop_event.set()

    def _run_loop(self, job: Callable[[], None], interval: float) -> None:
        while not self._stop_event.is_set():
            try:
                job()
            except Exception:  # pragma: no cover - defensive; checks should not raise
                logger.exception("Background monitor check failed")
            self._stop_event.wait(interval)

    def _check_battery(self) -> None:
        reading = checks.read_battery()
        self._report_reading("battery", reading)
        message = checks.evaluate_battery(reading, self._battery_state)
        if message:
            self._notify(message)

    def _check_internet(self) -> None:
        reading = checks.read_internet()
        self._report_reading("internet", reading)
        message = checks.evaluate_internet(reading, self._internet_state)
        if message:
            self._notify(message)

    def _check_nvidia_driver(self) -> None:
        reading = checks.read_nvidia_driver()
        self._report_reading("nvidia_driver", reading)
        message = checks.evaluate_nvidia_driver(reading, self._driver_state)
        if message:
            self._notify(message)

    def _check_windows_update(self) -> None:
        reading = checks.read_windows_update()
        self._report_reading("windows_update", reading)
        message = checks.evaluate_windows_update(reading, self._update_state)
        if message:
            self._notify(message)

    def _check_cpu(self) -> None:
        self._report_reading("cpu", checks.read_cpu())

    def _check_memory(self) -> None:
        self._report_reading("memory", checks.read_memory())

    def _check_cpu_temperature(self) -> None:
        reading = read_cpu_temperature()
        self._report_reading("cpu_temperature", reading)
        if not reading.available:
            return
        threshold = self._temperature_threshold_c()
        if reading.temperature_c < threshold:
            self._cpu_temperature_alerted = False
        elif not self._cpu_temperature_alerted:
            self._cpu_temperature_alerted = True
            self._notify(f"CPU temperature high: {reading.temperature_c:.0f}C (threshold {threshold:.0f}C).")

    def _check_gpu(self) -> None:
        reading = checks.read_gpu()
        self._report_reading("gpu", reading)
        message = checks.evaluate_gpu_temperature(reading, self._temperature_threshold_c(), self._gpu_temperature_state)
        if message:
            self._notify(message)

    def _temperature_threshold_c(self) -> float:
        if self._settings is None:
            return _DEFAULT_TEMPERATURE_WARNING_C
        try:
            return float(self._settings.mode_preferences.get("temperature_warning_c", _DEFAULT_TEMPERATURE_WARNING_C))
        except (TypeError, ValueError):
            return _DEFAULT_TEMPERATURE_WARNING_C

    def _check_disk(self) -> None:
        reading = checks.read_disk()
        self._report_reading("disk", reading)
        message = checks.evaluate_disk_space(reading, self._disk_state)
        if message:
            self._notify(message)

    def _notify(self, message: str) -> None:
        with self._lifecycle_lock:
            if not self._stop_event.is_set():
                self.notify(message)

    def _report_reading(self, kind: str, reading: object) -> None:
        with self._lifecycle_lock:
            if self.on_reading is None or self._stop_event.is_set():
                return
            try:
                self.on_reading(kind, reading)
            except Exception:  # pragma: no cover - defensive; a UI callback must not break monitoring
                logger.exception("on_reading callback failed for %s", kind)
