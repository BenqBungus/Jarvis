from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, Qt, QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from .voice_core import AURORA, FONT_BODY, FONT_DISPLAY, FONT_MONO, HudSurface, JarvisCoreWidget, apply_window_corners

_A = AURORA
_SPLASH_GLOWS = (
    (0.50, 0.30, 0.95, _A["accent"], 34),
    (1.00, 1.10, 0.85, _A["accent_2"], 30),
    (0.00, 1.00, 0.55, _A["accent"], 10),
)

SPLASH_STYLE = f"""
#startupSplash {{ background: {_A['border_strong']}; }}
#startupSplash QLabel {{ background: transparent; font-family: {FONT_BODY}; }}
#startupSplash QLabel[role="wordmark"] {{ color: {_A['text']}; font-family: {FONT_DISPLAY}; font-size: 26px;
    letter-spacing: 7px; }}
#startupSplash QLabel[role="tagline"] {{ color: {_A['text_tertiary']}; font-size: 10px; letter-spacing: 2px; }}
#startupSplash QLabel[role="status"] {{ color: {_A['text_secondary']}; font-size: 12px; }}
#startupSplash QLabel[role="percent"] {{ color: {_A['text_tertiary']}; font-family: {FONT_MONO}; font-size: 11px; }}
#startupSplash QProgressBar {{ background: rgba(255, 255, 255, 16); border: none; border-radius: 2px; }}
#startupSplash QProgressBar::chunk {{ border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
"""


class StartupSplash(QWidget):
    """Jarvis-style startup animation shown before the main window."""

    _STAGES = (
        "INITIALIZING",
        "LOADING MODULES",
        "CALIBRATING",
        "SYNCING VOICE",
        "READY",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self._progress = 0
        self._angle = 0
        self._status = self._STAGES[0]
        self._chrome_applied = False
        self.setObjectName("startupSplash")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(SPLASH_STYLE)
        self.resize(560, 380)

        # The 1px margin shows the window's own background as a hairline
        # edge; on Windows 11 DWM draws a rounded one instead (showEvent).
        self._frame = QVBoxLayout(self)
        self._frame.setContentsMargins(1, 1, 1, 1)
        surface = HudSurface(self, glows=_SPLASH_GLOWS)
        self._frame.addWidget(surface)

        layout = QVBoxLayout(surface)
        layout.setContentsMargins(44, 14, 44, 30)
        layout.setSpacing(0)
        self._core = JarvisCoreWidget()
        self._core.setMinimumSize(200, 190)
        self._core.setFixedHeight(200)
        self._core.set_state("thinking")
        layout.addWidget(self._core)

        wordmark = QLabel("J.A.R.V.I.S")
        wordmark.setProperty("role", "wordmark")
        wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(wordmark)
        layout.addSpacing(6)
        tagline = QLabel("JUST A RATHER VERY INTELLIGENT SYSTEM")
        tagline.setProperty("role", "tagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)
        layout.addStretch(1)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        self._status_label = QLabel()
        self._status_label.setProperty("role", "status")
        status_row.addWidget(self._status_label, 1)
        self._percent_label = QLabel()
        self._percent_label.setProperty("role", "percent")
        status_row.addWidget(self._percent_label)
        layout.addLayout(status_row)
        layout.addSpacing(8)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        layout.addWidget(self._bar)
        self._show_status()

        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._tick)

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(geometry.center().x() - self.width() // 2, geometry.center().y() - self.height() // 2)

    def start(self) -> None:
        self.center_on_screen()
        self._timer.start()
        self.show()
        self.raise_()

    def finish(self) -> None:
        self._progress = 100
        self._bar.setValue(100)
        self._status = "READY"
        self._show_status()
        self.update()
        QApplication.processEvents()
        self._timer.stop()
        self.hide()

    def set_progress(self, progress: int, status: str | None = None) -> None:
        self._progress = max(0, min(100, progress))
        self._bar.setValue(self._progress)
        if status:
            self._status = status
        else:
            stage_index = min(len(self._STAGES) - 1, int(self._progress / 25))
            self._status = self._STAGES[stage_index]
        self._show_status()
        self.update()
        QApplication.processEvents()

    def run_startup_animation(self, duration_ms: int = 1800) -> None:
        self.start()
        elapsed = QElapsedTimer()
        elapsed.start()
        while elapsed.elapsed() < duration_ms:
            progress = int((elapsed.elapsed() / max(1, duration_ms)) * 100)
            self.set_progress(progress)
            QApplication.processEvents()
        self.finish()

    def _show_status(self) -> None:
        # Stages stay upper-case identifiers; they read better in sentence case.
        self._status_label.setText(self._status.capitalize())
        self._percent_label.setText(f"{self._progress}%")
        self._core.set_state("listening" if self._progress >= 100 else "thinking")

    def _tick(self) -> None:
        self._angle = (self._angle + 7) % 360
        # A soft synthetic level keeps the orb breathing while modules load.
        self._core.set_level(0.22 + 0.14 * math.sin(math.radians(self._angle)))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_applied:
            self._chrome_applied = True
            if apply_window_corners(self):
                self._frame.setContentsMargins(0, 0, 0, 0)
