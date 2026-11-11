from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class DashboardModel(QObject):
    """Holds the latest known reading per monitor check kind ("battery",
    "internet", "nvidia_driver", "windows_update"), fed by
    MonitorBridge.reading_received. BackgroundMonitor's _run_loop runs each
    check immediately on start() (before its first interval wait), so all
    four kinds populate within seconds of app launch, not after a full
    interval -- callers should show a "checking..." placeholder until then.
    """

    updated = Signal(str)  # kind

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._readings: dict[str, object] = {}

    def on_reading(self, kind: str, reading: object) -> None:
        self._readings[kind] = reading
        self.updated.emit(kind)

    def latest(self, kind: str) -> object | None:
        return self._readings.get(kind)

    def all_readings(self) -> dict[str, object]:
        return dict(self._readings)
