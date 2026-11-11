from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class MonitorBridge(QObject):
    """Bridges BackgroundMonitor's plain notify()/on_reading() callbacks
    (invoked from its own daemon threads) into Qt signals delivered on the
    GUI thread. No locking needed: emitting a signal is safe from any
    thread -- Qt queues delivery based on the receiving QObject's thread
    affinity, not the caller's.
    """

    alert_received = Signal(str)
    reading_received = Signal(str, object)

    def notify(self, message: str) -> None:
        """Matches BackgroundMonitor's `notify: Callable[[str], None]`."""
        self.alert_received.emit(message)

    def on_reading(self, kind: str, reading: object) -> None:
        """Matches BackgroundMonitor's `on_reading: Callable[[str, object], None]`."""
        self.reading_received.emit(kind, reading)
