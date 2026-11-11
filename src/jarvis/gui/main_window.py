from __future__ import annotations

import math
import os
import re
import time
from collections import deque
from datetime import datetime
from functools import partial

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLayout, QMainWindow, QMenu, QPushButton, QPlainTextEdit,
    QScrollArea, QSizePolicy, QStyle, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from ..privacy import redact_sensitive_text
from ..role_packs import PACKS, QuickAction, RolePack, normalize_packs
from .avatar import avatar_pixmap
from .voice_core import (  # noqa: F401 - AURORA/glyph_icon re-exported for the other UI modules
    AURORA, BASE_STYLE, FONT_DISPLAY, FONT_MONO, FONT_SEMIBOLD, HudSurface, JarvisCoreWidget, glyph_icon,
)
from .voice_core import LogoMark as _LogoMark

_DASHBOARD_LABELS = {
    "cpu": "CPU", "cpu_temperature": "CPU TEMP", "memory": "MEMORY", "gpu": "GPU", "disk": "DISK",
    "battery": "BATTERY", "internet": "NETWORK", "nvidia_driver": "NVIDIA DRIVER",
    "windows_update": "WINDOWS UPDATE",
}
_SETUP_LABELS = {
    "openai_key": "OPENAI", "realtime_deps": "REALTIME", "classic_mic": "FALLBACK MIC",
    "tts": "STARTUP VOICE",
}
_A = AURORA
_ICON_DARK = "#04131A"
_SP = QStyle.StandardPixmap
_LEADING_PERCENT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%")
_TEMPERATURE = re.compile(r"(\d+(?:\.\d+)?)\s*°?C\b")
_TONE_COLORS = {"success": _A["success"], "warning": _A["warning"], "neutral": _A["neutral"]}
# From this window width the personal column (role packs) gets its own
# column right of the orb; below it, it tops the status column instead.
_WIDE_LAYOUT = 1250
_HOT_LIMIT_C = 85  # the default temperature warning (settings "Temperature")
# Header badge and HUD banner per permission level; the rules themselves are
# enforced by permission_levels.py (Codex, X2).
_LEVEL_BADGES = {"kid": ("KID MODE", "Kid profile"), "guest": ("GUEST", "Guest profile")}
_LEVEL_BANNERS = {
    "kid": "Power, network, driver, email and file-removal actions are off. Settings need an adult profile.",
    "guest": "No memory, email or personal files, and nothing is learned. Settings need an adult profile.",
}
_MAX_HABIT_CARDS = 3

HUD_STYLE = BASE_STYLE + f"""
#hud QScrollArea {{ background: transparent; border: none; }}
#hud QScrollArea > QWidget > QWidget {{ background: transparent; }}
#hud QFrame[role="card"] {{ background: rgba(14, 19, 25, 214); border: 1px solid {_A['border']}; border-radius: 14px; }}
#hud QFrame[role="toolbar"] {{ background: rgba(14, 19, 25, 190); border: 1px solid {_A['border']}; border-radius: 12px; }}
#hud QFrame[role="dock"] {{ background: rgba(14, 19, 25, 214); border: 1px solid {_A['border']}; border-radius: 42px; }}
#hud QFrame[role="rule"] {{ background: {_A['border_strong']}; border: none; }}
#hud QLabel[role="brand"] {{ color: {_A['text']}; font-family: {FONT_DISPLAY}; font-weight: 600; font-size: 19px;
    letter-spacing: 3px; }}
#hud QLabel[role="overline"] {{ color: {_A['text_tertiary']}; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 10px; letter-spacing: 1.6px; }}
#hud QLabel[role="metricName"] {{ color: {_A['text_tertiary']}; font-size: 11px; letter-spacing: 0.6px; }}
#hud QLabel[role="metricValue"] {{ color: {_A['text']}; font-size: 13px; }}
#hud QLabel[role="detail"] {{ color: {_A['text_secondary']}; font-size: 12px; }}
#hud QLabel[role="muted"] {{ color: {_A['text_tertiary']}; font-size: 12px; }}
#hud QLabel[role="clock"] {{ color: {_A['text_secondary']}; font-size: 12px; }}
#hud QLabel[role="health"] {{ color: {_A['text_secondary']}; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 10px; letter-spacing: 1.4px; }}
#hud QLabel[role="state"] {{ color: {_A['text']}; font-family: {FONT_DISPLAY}; font-weight: 600; font-size: 15px;
    letter-spacing: 3px; }}
#hud QLabel[role="transcript"] {{ color: {_A['text_secondary']}; font-size: 14px; }}
#hud QLabel[role="transcript"][tone="error"] {{ color: {_A['danger']}; }}
#hud QLabel[role="pill"] {{ border-radius: 11px; padding: 3px 11px; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 10px; letter-spacing: 1px; }}
#hud QLabel[role="pill"][tone="off"] {{ background: {_A['card_hover']}; color: {_A['text_secondary']};
    border: 1px solid {_A['border_strong']}; }}
#hud QLabel[role="pill"][tone="live"] {{ background: rgba(34, 211, 238, 30); color: {_A['accent_light']};
    border: 1px solid rgba(34, 211, 238, 105); }}
#hud QLabel[role="pill"][tone="paused"] {{ background: rgba(230, 184, 106, 30); color: {_A['warning']};
    border: 1px solid rgba(230, 184, 106, 100); }}
#hud QLabel[role="pill"][tone="local"] {{ background: rgba(139, 92, 246, 34); color: #C4B5FD;
    border: 1px solid rgba(139, 92, 246, 105); }}
#hud QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 9px; }}
#hud QToolButton:hover {{ background: #172130; border-color: {_A['border_strong']}; }}
#hud QToolButton:pressed {{ background: {_A['card']}; }}
#hud QToolButton:checked {{ background: rgba(34, 211, 238, 36); border-color: rgba(34, 211, 238, 115); }}
#hud QToolButton:disabled {{ background: transparent; border-color: transparent; }}
#hud QToolButton[role="dockButton"] {{ background: {_A['card_hover']}; border: 1px solid {_A['border_strong']};
    border-radius: 22px; }}
#hud QToolButton[role="dockButton"]:hover {{ background: #172130; border-color: #33415A; }}
#hud QToolButton[role="dockButton"]:checked {{ background: rgba(230, 184, 106, 36); border-color: rgba(230, 184, 106, 125); }}
#hud QToolButton[role="dockButton"]:disabled {{ background: {_A['card']}; border-color: {_A['border']}; }}
#hud QToolButton#voiceCall {{ border: none; border-radius: 32px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
#hud QToolButton#voiceCall:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent_light']}, stop:1 {_A['accent_2_light']}); }}
#hud QToolButton#voiceCall:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F6A197, stop:1 #E0685C); }}
#hud QToolButton#voiceCall:checked:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F8B4AB, stop:1 #E77B70); }}
#hud QToolButton#voiceCall:disabled {{ background: #141A22; border: 1px solid {_A['border_strong']}; }}
#hud QToolButton[role="chip"] {{ background: rgba(34, 211, 238, 16); border: 1px solid rgba(34, 211, 238, 62);
    border-radius: 12px; padding: 4px 10px; color: {_A['accent_light']}; font-size: 12px; }}
#hud QToolButton[role="chip"]:hover {{ background: rgba(34, 211, 238, 38); border-color: rgba(34, 211, 238, 140);
    color: {_A['text']}; }}
#hud QToolButton[role="chip"]:pressed {{ background: rgba(34, 211, 238, 60); }}
#hud QToolButton[role="chip"]:disabled {{ background: transparent; border-color: {_A['border']};
    color: {_A['text_tertiary']}; }}
#hud QToolButton[role="ghostChip"] {{ border: 1px solid {_A['border_strong']}; border-radius: 12px; padding: 4px 10px;
    color: {_A['text_secondary']}; font-size: 12px; }}
#hud QToolButton[role="ghostChip"]:hover {{ background: #172130; color: {_A['text']}; }}
#hud QLabel[role="verdict"] {{ color: {_A['text']}; font-family: {FONT_SEMIBOLD}; font-weight: 600; font-size: 13px; }}
#hud QLabel[role="pill"][tone="kid"] {{ background: rgba(139, 92, 246, 34); color: #C4B5FD;
    border: 1px solid rgba(139, 92, 246, 105); }}
#hud QLabel[role="pill"][tone="guest"] {{ background: {_A['card_hover']}; color: {_A['text_secondary']};
    border: 1px solid {_A['border_strong']}; }}
#hud QLabel[role="transcript"][tone="blocked"] {{ color: {_A['warning']}; }}
#hud QFrame[role="card"][tone="kid"] {{ border-color: rgba(139, 92, 246, 110); }}
#hud QFrame[role="card"][tone="guest"] {{ border-color: {_A['border_strong']}; }}
#hud QFrame[role="card"][tone="noticed"] {{ border-color: rgba(34, 211, 238, 95); }}
#hud QToolButton#languageButton {{ background: {_A['card_hover']}; color: {_A['text_secondary']};
    border: 1px solid {_A['border_strong']}; border-radius: 11px; padding: 3px 11px; font-family: {FONT_SEMIBOLD};
    font-weight: 600; font-size: 10px; letter-spacing: 1px; }}
#hud QToolButton#languageButton:hover {{ color: {_A['text']}; border-color: #33415A; background: #172130; }}
#hud QToolButton#languageButton::menu-indicator {{ image: none; width: 0px; }}
#hud QToolButton#profileButton {{ border: 1px solid transparent; border-radius: 20px; padding: 0; }}
#hud QToolButton#profileButton:hover {{ background: transparent; border-color: rgba(34, 211, 238, 150); }}
#hud QToolButton#profileButton::menu-indicator {{ image: none; width: 0px; }}
#hud QLabel[role="menuName"] {{ color: {_A['text']}; font-family: {FONT_SEMIBOLD}; font-weight: 600; font-size: 13px; }}
#hud QLabel[role="menuHint"] {{ color: {_A['text_tertiary']}; font-size: 11px; }}
QMessageBox#confirmDialog QLabel#qt_msgbox_label {{ color: {_A['text']}; font-family: {FONT_SEMIBOLD};
    font-weight: 600; font-size: 15px; }}
QMessageBox#confirmDialog QLabel#qt_msgbox_informativelabel {{ color: {_A['text_secondary']}; font-size: 13px;
    min-width: 320px; }}
#settingsDialog QLabel[role="dialogTitle"], #editPreviewDialog QLabel[role="dialogTitle"] {{ color: {_A['text']};
    font-family: {FONT_DISPLAY}; font-weight: 600; font-size: 20px; }}
#settingsDialog QLabel[role="dialogSubtitle"], #editPreviewDialog QLabel[role="dialogSubtitle"] {{
    color: {_A['text_secondary']}; font-size: 12px; }}
#editPreviewDialog QPlainTextEdit {{ font-family: {FONT_MONO}; font-size: 13px; background: {_A['bg_raised']};
    border-color: {_A['border']}; padding: 10px 12px; }}
"""


def _label(text: str, role: str, parent: QWidget | None = None) -> QLabel:
    label = QLabel(text, parent)
    label.setProperty("role", role)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _frame(role: str) -> QFrame:
    frame = QFrame()
    frame.setProperty("role", role)
    return frame


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _dot_style(color: str) -> str:
    return f"background: {color}; border-radius: 4px;"


def _rgba(color: str, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(alpha)
    return value


class _LoadChart(QWidget):
    """A live HUD trace of CPU, GPU and memory load, fed by the dashboard's
    own monitor readings (update_dashboard); nothing is sampled here."""

    SERIES = (("cpu", "CPU", _A["accent"]), ("gpu", "GPU", _A["accent_2_light"]), ("memory", "RAM", "#8A96A4"))
    POINTS = 48

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(66)
        self.setAccessibleName("Live system load")
        self._history: dict[str, deque[float]] = {key: deque(maxlen=self.POINTS) for key, _name, _color in self.SERIES}

    def add(self, key: str, percent: float) -> None:
        if key in self._history:
            self._history[key].append(max(0.0, min(100.0, percent)))
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, top, bottom = self.width(), 16.0, self.height() - 2.0
        font = QFont(self.font())
        font.setPixelSize(9)
        painter.setFont(font)
        x = 0.0
        for _key, name, color in self.SERIES:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(x + 3, 5), 2.5, 2.5)
            painter.setPen(QColor(_A["text_tertiary"]))
            painter.drawText(QPointF(x + 9, 9), name)
            x += 21 + painter.fontMetrics().horizontalAdvance(name)
        grid = QPen(_rgba(_A["border_strong"], 150), 1, Qt.PenStyle.DotLine)
        painter.setPen(grid)
        for fraction in (0.0, 0.5, 1.0):
            y = bottom - (bottom - top) * fraction
            painter.drawLine(QPointF(0, y), QPointF(width, y))
        if all(len(values) < 2 for values in self._history.values()):
            painter.setPen(QColor(_A["text_tertiary"]))
            painter.drawText(self.rect().adjusted(0, 12, 0, 0), Qt.AlignmentFlag.AlignCenter, "Collecting readings…")
            return
        step = width / (self.POINTS - 1)
        for key, _name, color in reversed(self.SERIES):
            values = self._history[key]
            if len(values) < 2:
                continue
            points = [QPointF(width - (len(values) - 1 - index) * step, bottom - (bottom - top) * value / 100)
                      for index, value in enumerate(values)]
            line = QPainterPath(points[0])
            for point in points[1:]:
                line.lineTo(point)
            if key == "cpu":
                area = QPainterPath(line)
                area.lineTo(points[-1].x(), bottom)
                area.lineTo(points[0].x(), bottom)
                area.closeSubpath()
                fill = QLinearGradient(0, top, 0, bottom)
                fill.setColorAt(0.0, _rgba(color, 70))
                fill.setColorAt(1.0, _rgba(color, 0))
                painter.fillPath(area, fill)
            painter.setPen(QPen(QColor(color), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(line)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(points[-1], 2.4, 2.4)


class _MeterRow(QWidget):
    """A SYSTEM STATUS row with a thin level meter along its bottom edge."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fraction: float | None = None
        self._color = _A["accent"]

    def set_level(self, fraction: float | None, color: str = _A["accent"]) -> None:
        fraction = None if fraction is None else max(0.0, min(1.0, fraction))
        if fraction != self._fraction or color != self._color:
            self._fraction, self._color = fraction, color
            self.update()

    def paintEvent(self, event) -> None:
        if self._fraction is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() - 1.5
        track = QPen(_rgba(_A["border_strong"], 170), 2)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawLine(QPointF(1, y), QPointF(self.width() - 1, y))
        if self._fraction > 0:
            level = QPen(QColor(self._color), 2)
            level.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(level)
            painter.drawLine(QPointF(1, y), QPointF(1 + (self.width() - 2) * self._fraction, y))


def _meter_level(kind: str, text: str) -> tuple[float, str] | None:
    """(fraction, colour) for a dashboard reading, or None when it has no level."""
    percent = _LEADING_PERCENT.match(text)
    if kind == "cpu_temperature":
        match = _TEMPERATURE.search(text)
        if not match:
            return None
        celsius = float(match.group(1))
        return celsius / 100, (_A["danger"] if celsius >= 90 else _A["warning"] if celsius >= _HOT_LIMIT_C - 10
                               else _A["accent"])
    if percent is None or kind not in {"cpu", "memory", "gpu", "disk", "battery"}:
        return None
    value = float(percent.group(1)) / 100
    if kind == "disk":  # "61% free": the meter shows what is used
        value = 1 - value
    if kind == "battery":
        if "charging" in text and "not" not in text:
            return value, _A["accent"]
        return value, _A["danger"] if value < 0.2 else _A["warning"] if value < 0.35 else _A["success"]
    return value, _A["danger"] if value >= 0.9 else _A["warning"] if value >= 0.75 else _A["accent"]


class _FlowLayout(QLayout):
    """Left-to-right items that wrap onto the next line (the pack chips)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.x() + rect.width():
                x, y, line = rect.x(), y + line + self._gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y()


class _FocusRing(QWidget):
    """The focus timer's dial: remaining time inside a progress ring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self._fraction = 1.0
        self._text = ""
        self._color = _A["accent"]

    def set_progress(self, fraction: float, text: str, color: str) -> None:
        self._fraction, self._text, self._color = max(0.0, min(1.0, fraction)), text, color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        painter.setPen(QPen(QColor(_A["border_strong"]), 4))
        painter.drawEllipse(ring)
        if self._fraction > 0:
            pen = QPen(QColor(self._color), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(ring, 90 * 16, -round(360 * 16 * self._fraction))
        font = QFont(self.font())
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(_A["text"]))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class _FocusTimer(QWidget):
    """The Student pack's focus timer: 25 minutes of focus, then a 5-minute
    break. Time is measured against a monotonic deadline and the ticker only
    runs while the timer does."""

    FOCUS_MINUTES = 25
    BREAK_MINUTES = 5
    phase_finished = Signal(str)  # "focus" | "break"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._clock = time.monotonic
        self._phase = "focus"
        self._remaining = self.FOCUS_MINUTES * 60.0
        self._deadline: float | None = None
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._ring = _FocusRing()
        layout.addWidget(self._ring)
        side = QVBoxLayout()
        side.setSpacing(6)
        self._phase_label = _label("", "metricName")
        side.addWidget(self._phase_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self._start_button = QToolButton()
        self._start_button.setProperty("role", "chip")
        self._start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_button.clicked.connect(self.toggle)
        self._reset_button = QToolButton()
        self._reset_button.setText("Reset")
        self._reset_button.setProperty("role", "ghostChip")
        self._reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_button.clicked.connect(self.reset)
        buttons.addWidget(self._start_button)
        buttons.addWidget(self._reset_button)
        buttons.addStretch()
        side.addLayout(buttons)
        layout.addLayout(side, 1)
        self._render()

    @property
    def running(self) -> bool:
        return self._deadline is not None

    def toggle(self) -> None:
        if self.running:
            self._remaining = max(0.0, self._deadline - self._clock())
            self._deadline = None
            self._ticker.stop()
        else:
            self._deadline = self._clock() + self._remaining
            self._ticker.start()
        self._render()

    def reset(self) -> None:
        self._deadline = None
        self._ticker.stop()
        self._phase = "focus"
        self._remaining = self.FOCUS_MINUTES * 60.0
        self._render()

    def _tick(self) -> None:
        if self._deadline is None:
            return
        self._remaining = max(0.0, self._deadline - self._clock())
        if self._remaining <= 0:
            finished = self._phase
            if finished == "focus":  # the break starts on its own
                self._phase = "break"
                self._remaining = self.BREAK_MINUTES * 60.0
                self._deadline = self._clock() + self._remaining
            else:  # the next focus session waits for the person
                self._phase = "focus"
                self._remaining = self.FOCUS_MINUTES * 60.0
                self._deadline = None
                self._ticker.stop()
            self.phase_finished.emit(finished)
        self._render()

    def _render(self) -> None:
        total = (self.FOCUS_MINUTES if self._phase == "focus" else self.BREAK_MINUTES) * 60.0
        seconds = math.ceil(self._remaining)
        color = _A["accent"] if self._phase == "focus" else _A["accent_2_light"]
        self._ring.set_progress(self._remaining / total, f"{seconds // 60:02d}:{seconds % 60:02d}", color)
        minutes = self.FOCUS_MINUTES if self._phase == "focus" else self.BREAK_MINUTES
        self._phase_label.setText(f"{'FOCUS' if self._phase == 'focus' else 'BREAK'} · {minutes} MIN")
        fresh = not self.running and self._remaining >= total
        self._start_button.setText("Pause" if self.running else "Start" if fresh else "Resume")
        self._start_button.setAccessibleName(f"{self._start_button.text()} focus timer")


def _gamer_verdict(readings: dict[str, str], hot_limit: int = _HOT_LIMIT_C) -> tuple[str, str, str]:
    """(tone, headline, detail) for the Gamer pack card, from the same
    dashboard texts the status column shows."""
    def percent(kind: str) -> float | None:
        match = _LEADING_PERCENT.match(readings.get(kind, ""))
        return float(match.group(1)) if match else None

    cpu, gpu, memory = percent("cpu"), percent("gpu"), percent("memory")
    temperatures = [float(match.group(1)) for kind in ("cpu_temperature", "gpu")
                    if (match := _TEMPERATURE.search(readings.get(kind, "")))]
    hottest = max(temperatures) if temperatures else None
    if cpu is None and gpu is None and memory is None and hottest is None:
        return "neutral", "Waiting for readings", "Performance checks start shortly after launch."
    if hottest is not None and hottest >= hot_limit:
        return "warning", f"Running hot · {hottest:.0f}°C", "Close background apps or switch on Gaming mode."
    if "on battery" in readings.get("battery", ""):
        return "warning", "On battery power", "Plug in for full GPU performance."
    if (cpu or 0) >= 90 or (memory or 0) >= 90:
        return "warning", "Heavy background load", "Check what's slowing you before you play."
    parts = [f"CPU {cpu:.0f}%" if cpu is not None else "", f"GPU {gpu:.0f}%" if gpu is not None else "",
             f"{hottest:.0f}°C" if hottest is not None else ""]
    return "success", "Game ready", "  ·  ".join(part for part in parts if part)


class MainWindow(QMainWindow):
    command_submitted = Signal(str, str)
    push_to_talk_pressed = Signal()
    voice_conversation_requested = Signal()
    speaker_test_requested = Signal()
    voice_diagnostics_requested = Signal()
    speaker_tone_requested = Signal()
    stop_session_requested = Signal()
    realtime_start_requested = Signal()
    realtime_stop_requested = Signal()
    input_mute_requested = Signal(bool)
    interrupt_speech_requested = Signal()
    cancel_task_requested = Signal()
    overlay_requested = Signal()
    activity_requested = Signal()
    undo_center_requested = Signal()
    screen_sharing_requested = Signal()
    screen_chat_requested = Signal()
    # Profiles, permission levels and habits (docs/claude/PERSONALIZATION_HANDOFF.md).
    profile_switch_requested = Signal(str)
    profile_editor_requested = Signal(str)  # "" = a new profile
    habit_accepted = Signal(str)
    habit_dismissed = Signal(str)
    habit_snoozed = Signal(str)
    routine_run_requested = Signal(str)
    routine_skipped = Signal(str)
    language_change_requested = Signal(str)  # en | bg | auto, from the header switch
    passwords_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.setMinimumSize(900, 660)
        self.resize(1360, 850)
        self.setStyleSheet(HUD_STYLE)
        self._realtime_ready = False
        self._realtime_active = False
        self._input_muted = False
        self._speaker_guard = True
        self._keyword_interrupt_available = False
        self._session_active = False
        self._screen_sharing_active = False
        self._state = "idle"
        self._settings_dialog: QDialog | None = None
        self._feedback_text = ""
        self._feedback_error = False
        self._privacy_tone = "off"
        self._transcript_tone = "normal"
        self._readings: dict[str, str] = {}
        self._role_packs: list[str] = []
        self._pack_cards: dict[str, QFrame] = {}
        self._gamer_status: tuple[QLabel, QLabel, QLabel] | None = None
        self._focus_timer: _FocusTimer | None = None
        self._personal_wide: bool | None = None
        self._profile: dict = {}
        self._profile_avatar = None
        self._profiles: list[dict] = []
        self._avatar_paths: dict[str, object] = {}
        self._permission_level = "adult"
        self._habit_cards: dict[str, QFrame] = {}
        self._routine_cards: dict[str, QFrame] = {}
        self._settings_widget: QWidget | None = None

        surface = HudSurface(pattern=True)
        surface.setObjectName("hud")
        self.setCentralWidget(surface)
        root = QVBoxLayout(surface)
        root.setContentsMargins(24, 18, 24, 20)
        root.setSpacing(16)
        root.addLayout(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(24)
        body.addWidget(self._build_status_column())
        body.addLayout(self._build_stage(), 1)
        body.addWidget(self._build_personal_column())
        root.addLayout(body, 1)

        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._clear_feedback)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

    # ------------------------------------------------------------------ layout

    def _glyph(self, name: str, fallback: QStyle.StandardPixmap, **kwargs) -> QIcon:
        return glyph_icon(name, fallback, self.style(), **kwargs)

    def _icon_button(self, glyph: str, fallback: QStyle.StandardPixmap, title: str, size: int, *,
                     icon_size: int = 18, role: str | None = None, **icon_kwargs) -> QToolButton:
        button = QToolButton()
        button.setIcon(self._glyph(glyph, fallback, size=icon_size, **icon_kwargs))
        button.setIconSize(QSize(icon_size, icon_size))
        button.setFixedSize(size, size)
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if role:
            button.setProperty("role", role)
        return button

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_LogoMark())
        header.addWidget(_label("J.A.R.V.I.S", "brand"))
        header.addSpacing(10)
        self._privacy_label = _label("MIC OFF", "pill")
        self._privacy_label.setProperty("tone", self._privacy_tone)
        header.addWidget(self._privacy_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._level_badge = _label("", "pill")
        self._level_badge.setProperty("tone", "kid")
        self._level_badge.hide()
        header.addWidget(self._level_badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        # The conversation language, switched on the spot (set_language).
        self._language_button = QToolButton()
        self._language_button.setObjectName("languageButton")
        self._language_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._language_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._language_menu = QMenu(self._language_button)
        self._language_actions = {}
        for code, title in (("bg", "Български"), ("en", "English"), ("auto", "Auto: Bulgarian or English")):
            action = self._language_menu.addAction(title, partial(self.language_change_requested.emit, code))
            action.setCheckable(True)
            self._language_actions[code] = action
        self._language_button.setMenu(self._language_menu)
        self._language_button.hide()
        header.addWidget(self._language_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        self._health_dot = QLabel()
        self._health_dot.setFixedSize(7, 7)
        header.addWidget(self._health_dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._health_label = _label("", "health")
        header.addWidget(self._health_label)
        header.addSpacing(14)
        self._setup_ready: dict[str, bool] = {}
        self._refresh_health()
        self._clock_label = _label("", "clock")
        header.addWidget(self._clock_label)
        header.addSpacing(6)

        toolbar = _frame("toolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(4, 4, 4, 4)
        tools.setSpacing(2)
        for glyph, fallback, title, signal in (
            ("keyboard", _SP.SP_FileDialogListView, "Command overlay (Alt+Space)", self.overlay_requested),
            ("history", _SP.SP_FileDialogContentsView, "Какво направи?", self.activity_requested),
            ("undo", _SP.SP_ArrowBack, "Undo Center", self.undo_center_requested),
            ("monitor", _SP.SP_ComputerIcon, "Screen Chat | GPT-5.6 Sol", self.screen_chat_requested),
        ):
            button = self._icon_button(glyph, fallback, title, 34)
            button.clicked.connect(signal.emit)
            tools.addWidget(button)
        self._screen_share_button = self._icon_button(
            "cast", _SP.SP_MediaPlay, "Start screen sharing", 34, checked_color=_A["accent_light"])
        self._screen_share_button.setCheckable(True)
        self._screen_share_button.clicked.connect(self._toggle_screen_sharing)
        # A "live" badge on the button itself; hidden while sharing is off.
        self._screen_share_dot = QLabel(self._screen_share_button)
        self._screen_share_dot.setFixedSize(8, 8)
        self._screen_share_dot.move(22, 4)
        self._screen_share_dot.setStyleSheet(_dot_style(_A["neutral"]))
        self._screen_share_dot.hide()
        tools.addWidget(self._screen_share_button)
        self._passwords_button = self._icon_button("lock", _SP.SP_DialogSaveButton, "Passwords", 34)
        self._passwords_button.clicked.connect(self.passwords_requested.emit)
        tools.addWidget(self._passwords_button)
        rule = _frame("rule")
        rule.setFixedSize(1, 18)
        tools.addWidget(rule, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._settings_button = self._icon_button("settings", _SP.SP_FileDialogDetailedView, "Settings", 34)
        self._settings_button.clicked.connect(self._show_settings)
        tools.addWidget(self._settings_button)
        header.addWidget(toolbar)
        # Shown once a profile is set (set_profile); the menu is rebuilt on open.
        self._profile_button = QToolButton()
        self._profile_button.setObjectName("profileButton")
        self._profile_button.setFixedSize(40, 40)
        self._profile_button.setIconSize(QSize(30, 30))
        self._profile_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._profile_menu = QMenu(self._profile_button)
        self._profile_menu.aboutToShow.connect(self._build_profile_menu)
        self._profile_button.setMenu(self._profile_menu)
        self._profile_button.hide()
        header.addWidget(self._profile_button)
        return header

    def _build_status_column(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(276)
        self._status_column = QWidget()
        column = QVBoxLayout(self._status_column)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(14)
        self._status_layout = column

        system = _frame("card")
        rows = QVBoxLayout(system)
        rows.setContentsMargins(18, 16, 18, 16)
        rows.setSpacing(11)
        rows.addWidget(_label("SYSTEM STATUS", "overline"))
        rows.addSpacing(2)
        self._load_chart = _LoadChart()
        rows.addWidget(self._load_chart)
        rows.addSpacing(4)
        self._dashboard_labels: dict[str, QLabel] = {}
        self._meters: dict[str, _MeterRow] = {}
        for key, name in _DASHBOARD_LABELS.items():
            stacked = key in {"nvidia_driver", "windows_update"}
            meter = None if stacked or key == "internet" else _MeterRow()
            row = QVBoxLayout() if stacked else QHBoxLayout(meter) if meter is not None else QHBoxLayout()
            row.setSpacing(3 if stacked else 10)
            if meter is not None:
                row.setContentsMargins(0, 0, 0, 6)  # room for the meter line
                self._meters[key] = meter
            name_label = _label(name, "metricName")
            value = _label("Awaiting reading", "metricValue")
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            if not stacked:
                name_label.setFixedWidth(82)
                value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(name_label)
            row.addWidget(value, 0 if stacked else 1)
            self._dashboard_labels[key] = value
            if meter is not None:
                rows.addWidget(meter)
            else:
                rows.addLayout(row)
        column.addWidget(system)

        readiness = _frame("card")
        rows = QVBoxLayout(readiness)
        rows.setContentsMargins(18, 16, 18, 16)
        rows.setSpacing(12)
        rows.addWidget(_label("READINESS", "overline"))
        self._setup_rows: dict[str, tuple[QWidget, QLabel, QLabel]] = {}
        for key, name in _SETUP_LABELS.items():
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(_dot_style(_A["neutral"]))
            dot_box = QVBoxLayout()
            dot_box.setContentsMargins(0, 4, 0, 0)
            dot_box.addWidget(dot)
            dot_box.addStretch()
            row.addLayout(dot_box)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(_label(name, "metricName"))
            detail = _label("Not checked", "detail")
            detail.setWordWrap(True)
            detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.addWidget(detail)
            row.addLayout(text, 1)
            self._setup_rows[key] = (row_widget, dot, detail)
            rows.addWidget(row_widget)
        column.addWidget(readiness)
        column.addStretch()
        scroll.setWidget(self._status_column)
        return scroll

    def _build_personal_column(self) -> QScrollArea:
        """The person's own cards (role packs). They get a column right of the
        orb on wide windows and move to the top of the status column on
        narrow ones (_place_personal_column)."""
        self._personal_scroll = QScrollArea()
        self._personal_scroll.setWidgetResizable(True)
        self._personal_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._personal_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._personal_scroll.setFixedWidth(276)
        self._personal_scroll.hide()
        self._personal_column = QWidget()
        column = QVBoxLayout(self._personal_column)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(14)
        self._level_banner = self._build_level_banner()
        column.addWidget(self._level_banner)
        self._habits_host = QWidget()
        self._habits_layout = QVBoxLayout(self._habits_host)
        self._habits_layout.setContentsMargins(0, 0, 0, 0)
        self._habits_layout.setSpacing(14)
        column.addWidget(self._habits_host)
        self._packs_host = QWidget()
        self._packs_layout = QVBoxLayout(self._packs_host)
        self._packs_layout.setContentsMargins(0, 0, 0, 0)
        self._packs_layout.setSpacing(14)
        column.addWidget(self._packs_host)
        column.addStretch(1)  # all spare height goes below the cards
        self._personal_column.hide()
        self._status_layout.insertWidget(0, self._personal_column)
        return self._personal_scroll

    def _place_personal_column(self) -> None:
        has_content = bool(self._pack_cards or self._habit_cards or self._routine_cards
                           or self._permission_level != "adult")
        # Empty hosts would still add the column's spacing above the cards.
        self._habits_host.setVisible(bool(self._habit_cards or self._routine_cards))
        self._packs_host.setVisible(bool(self._pack_cards))
        wide = self.width() >= _WIDE_LAYOUT
        self._personal_column.setVisible(has_content)
        self._personal_scroll.setVisible(has_content and wide)
        if wide == self._personal_wide:
            return
        self._personal_wide = wide
        # The status column already leaves room for its scroll bar.
        self._personal_column.layout().setContentsMargins(0, 0, 8 if wide else 0, 0)
        if wide:
            self._status_layout.removeWidget(self._personal_column)
            self._personal_scroll.setWidget(self._personal_column)
        elif self._status_layout.indexOf(self._personal_column) < 0:
            self._personal_scroll.takeWidget()
            self._personal_column.setAutoFillBackground(False)  # QScrollArea.setWidget turned it on
            self._status_layout.insertWidget(0, self._personal_column)
        self._personal_column.setVisible(has_content)

    def _build_pack_card(self, pack: RolePack) -> QFrame:
        card = _frame("card")
        card.setAccessibleName(f"{pack.name} pack")
        rows = QVBoxLayout(card)
        rows.setContentsMargins(18, 14, 18, 16)
        rows.setSpacing(10)
        title = QHBoxLayout()
        title.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(self._glyph(pack.glyph, _SP.SP_FileDialogInfoView, size=14,
                                   color=_A["accent_light"]).pixmap(QSize(14, 14), 2.0))
        icon.setFixedSize(14, 14)
        title.addWidget(icon)
        overline = _label(f"{pack.name.upper()} PACK", "overline")
        overline.setToolTip(pack.tagline)
        title.addWidget(overline, 1)
        rows.addLayout(title)
        if pack.id == "gamer":
            rows.addLayout(self._build_gamer_status())
        elif pack.id == "student":
            self._focus_timer = _FocusTimer()
            self._focus_timer.phase_finished.connect(self._on_focus_phase_finished)
            rows.addWidget(self._focus_timer)
        chips = _FlowLayout(spacing=6)
        for action in pack.quick_actions:
            chip = QToolButton()
            chip.setText(action.label)
            chip.setProperty("role", "chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"Says “{action.command}”" if action.command else action.label)
            chip.clicked.connect(partial(self._run_quick_action, action))
            chips.addWidget(chip)
        rows.addLayout(chips)
        return card

    def _build_gamer_status(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot_box = QVBoxLayout()
        dot_box.setContentsMargins(0, 5, 0, 0)
        dot_box.addWidget(dot)
        row.addLayout(dot_box)
        row.setAlignment(dot_box, Qt.AlignmentFlag.AlignTop)  # no vertical spacer: the card must not grow
        text = QVBoxLayout()
        text.setSpacing(2)
        headline = _label("", "verdict")
        detail = _label("", "detail")
        detail.setWordWrap(True)
        detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(headline)
        text.addWidget(detail)
        row.addLayout(text, 1)
        self._gamer_status = (dot, headline, detail)
        self._refresh_gamer_status()
        return row

    def _refresh_gamer_status(self) -> None:
        if self._gamer_status is None:
            return
        dot, headline, detail = self._gamer_status
        tone, title, text = _gamer_verdict(self._readings)
        dot.setStyleSheet(_dot_style(_TONE_COLORS[tone]))
        headline.setText(title)
        detail.setText(text)

    def _run_quick_action(self, action: QuickAction) -> None:
        if action.signal:
            getattr(self, action.signal).emit()
        else:
            self.command_submitted.emit(action.command, "button")

    def _on_focus_phase_finished(self, phase: str) -> None:
        if phase == "focus":
            self.show_feedback(f"Focus session complete. Take a {_FocusTimer.BREAK_MINUTES}-minute break.")
        else:
            self.show_feedback("Break over. Start the next focus session when you're ready.")
        QApplication.alert(self)

    def _build_level_banner(self) -> QFrame:
        banner = _frame("card")
        banner.setProperty("tone", "kid")
        rows = QVBoxLayout(banner)
        rows.setContentsMargins(18, 14, 18, 16)
        rows.setSpacing(8)
        self._level_banner_title = _label("", "overline")
        rows.addWidget(self._level_banner_title)
        self._level_banner_text = _label("", "detail")
        self._level_banner_text.setWordWrap(True)
        self._level_banner_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        rows.addWidget(self._level_banner_text)
        switch = QToolButton()
        switch.setText("Switch profile")
        switch.setProperty("role", "ghostChip")
        switch.setCursor(Qt.CursorShape.PointingHandCursor)
        switch.clicked.connect(self._profile_button.showMenu)
        self._level_banner_switch = switch
        chips = QHBoxLayout()
        chips.addWidget(switch)
        chips.addStretch()
        rows.addLayout(chips)
        banner.hide()
        return banner

    def _build_notice_card(self, overline: str, item: dict, buttons: tuple, answer) -> QFrame:
        """A "Jarvis noticed" style card: sparkle overline, title, detail, evidence and answer chips."""
        item_id = str(item.get("id") or "")
        card = _frame("card")
        card.setProperty("tone", "noticed")
        card.setAccessibleName(overline.title())
        rows = QVBoxLayout(card)
        rows.setContentsMargins(18, 14, 18, 16)
        rows.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(self._glyph("sparkle", _SP.SP_MessageBoxInformation, size=14,
                                   color=_A["accent_light"]).pixmap(QSize(14, 14), 2.0))
        icon.setFixedSize(14, 14)
        title_row.addWidget(icon)
        title_row.addWidget(_label(overline, "overline"), 1)
        rows.addLayout(title_row)
        rows.addSpacing(2)
        rows.addWidget(_label(str(item.get("title") or "A routine"), "verdict"))
        for key, role in (("detail", "detail"), ("evidence", "muted")):
            if item.get(key):
                label = _label(str(item[key]), role)
                label.setWordWrap(True)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                rows.addWidget(label)
        rows.addSpacing(4)
        flow = _FlowLayout(spacing=6)
        for text, role, signal, tip in buttons:
            button = QToolButton()
            button.setText(text)
            button.setProperty("role", role)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(partial(answer, item_id, signal))
            flow.addWidget(button)
        rows.addLayout(flow)
        return card

    def _build_habit_card(self, suggestion: dict) -> QFrame:
        return self._build_notice_card("JARVIS NOTICED", suggestion, (
            ("Set it up", "chip", self.habit_accepted, "Jarvis still asks before anything protected runs."),
            ("Later", "ghostChip", self.habit_snoozed, "Ask again in a week."),
            ("Don't suggest", "ghostChip", self.habit_dismissed, "Never suggest this again.")), self._answer_habit)

    def _build_stage(self) -> QVBoxLayout:
        stage = QVBoxLayout()
        stage.setSpacing(10)
        self._core = JarvisCoreWidget()
        stage.addWidget(self._core, 1)
        self._core_status_label = _label("VOICE OFFLINE", "state")
        self._core_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._core_status_label.setFixedHeight(26)
        stage.addWidget(self._core_status_label)
        self._voice_transcript_label = _label("", "transcript")
        self._voice_transcript_label.setProperty("tone", self._transcript_tone)
        self._voice_transcript_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._voice_transcript_label.setFixedHeight(26)
        self._voice_transcript_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        # Re-elided whenever it resizes, including when the personal column
        # appears or moves without the window itself changing size.
        self._voice_transcript_label.installEventFilter(self)
        stage.addWidget(self._voice_transcript_label)
        stage.addSpacing(4)

        self._mic_icons = (
            self._glyph("mic", _SP.SP_MediaPause, size=18, checked_color=_A["warning"]),
            self._glyph("mic_off", _SP.SP_MediaPause, size=18, checked_color=_A["warning"]),
        )
        self._call_icons = (
            self._glyph("mic", _SP.SP_MediaPlay, size=26, color=_ICON_DARK, checked_color="#2B0B07"),
            self._glyph("hang_up", _SP.SP_MediaStop, size=26, color=_ICON_DARK, checked_color="#2B0B07"),
        )
        dock = _frame("dock")
        controls = QHBoxLayout(dock)
        controls.setContentsMargins(12, 10, 12, 10)
        controls.setSpacing(14)
        self._mute_button = self._icon_button("mic", _SP.SP_MediaPause, "Mute microphone", 44, role="dockButton",
                                              checked_color=_A["warning"])
        self._mute_button.setCheckable(True)
        self._mute_button.setEnabled(False)
        self._mute_button.clicked.connect(lambda checked: self.input_mute_requested.emit(checked))
        self._voice_button = self._icon_button("mic", _SP.SP_MediaPlay, "Start voice conversation", 64, icon_size=26,
                                               color=_ICON_DARK, checked_color="#2B0B07")
        self._voice_button.setObjectName("voiceCall")
        self._voice_button.setCheckable(True)
        self._voice_button.setEnabled(False)
        self._voice_button.clicked.connect(self._toggle_voice)
        self._interrupt_button = self._icon_button("skip", _SP.SP_MediaSkipForward, "Interrupt reply", 44,
                                                   role="dockButton")
        self._interrupt_button.setEnabled(False)
        self._interrupt_button.clicked.connect(self.interrupt_speech_requested.emit)
        self._cancel_task_button = self._icon_button("close", _SP.SP_BrowserStop, "Cancel current task", 44,
                                                     role="dockButton")
        self._cancel_task_button.setEnabled(False)
        self._cancel_task_button.clicked.connect(self.cancel_task_requested.emit)
        for button in (self._mute_button, self._voice_button, self._interrupt_button, self._cancel_task_button):
            controls.addWidget(button, alignment=Qt.AlignmentFlag.AlignVCenter)
        dock_row = QHBoxLayout()
        dock_row.addStretch()
        dock_row.addWidget(dock)
        dock_row.addStretch()
        stage.addLayout(dock_row)
        self._profile_label = _label("", "muted")
        self._profile_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stage.addWidget(self._profile_label)
        return stage

    def _update_clock(self) -> None:
        now = datetime.now()
        self._clock_label.setText(f"{now:%H:%M}  ·  {now:%a %d %b}")

    # --------------------------------------------------------------- dialogs

    def show_edit_preview(self, message: str) -> None:
        dialog = getattr(self, "_edit_preview_dialog", None)
        if dialog is None:
            dialog = QDialog(self)
            dialog.setObjectName("editPreviewDialog")
            dialog.setWindowTitle("Jarvis | Proposed file changes")
            dialog.resize(820, 580)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(24, 20, 24, 18)
            layout.setSpacing(12)
            layout.addWidget(_label("Proposed file changes", "dialogTitle"))
            layout.addWidget(_label("Review the diff below. Nothing is saved until you confirm the save separately.",
                                    "dialogSubtitle"))
            self._edit_preview_text = QPlainTextEdit()
            self._edit_preview_text.setReadOnly(True)
            layout.addWidget(self._edit_preview_text, 1)
            footer = QHBoxLayout()
            footer.addStretch()
            close = QPushButton("Close")
            close.clicked.connect(dialog.hide)
            footer.addWidget(close)
            layout.addLayout(footer)
            self._edit_preview_dialog = dialog
        self._edit_preview_text.setPlainText(message)
        dialog.show()
        dialog.raise_()

    def set_settings_widget(self, widget: QWidget) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("settingsDialog")
        dialog.setWindowTitle("Jarvis settings")
        width, height = 1040, 720
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            # The settings page scrolls (rail included), so the dialog can
            # shrink to fit 1366x768 at 150% (about 910x510 logical).
            width = min(width, max(720, available.width() - 60))
            height = min(height, max(440, available.height() - 60))
        dialog.resize(width, height)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(_label("Settings", "dialogTitle"))
        titles.addWidget(_label("Voice, AI, safety and app preferences. Changes apply when you press Save.",
                                "dialogSubtitle"))
        header.addLayout(titles, 1)
        audio = QPushButton("Audio tools")
        menu = QMenu(audio)
        for title, signal in (("Test voice", self.speaker_test_requested),
                              ("Test speaker tone", self.speaker_tone_requested),
                              ("Voice Doctor", self.voice_diagnostics_requested),
                              (None, None),
                              ("Push to talk", self.push_to_talk_pressed),
                              ("Classic voice fallback", self.voice_conversation_requested),
                              ("Stop classic voice", self.stop_session_requested)):
            if title is None:
                menu.addSeparator()
            else:
                menu.addAction(title, signal.emit)
        audio.setMenu(menu)
        header.addWidget(audio, alignment=Qt.AlignmentFlag.AlignTop)
        close = QPushButton("Close")
        close.clicked.connect(dialog.hide)
        header.addWidget(close, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addWidget(widget, 1)
        self._settings_dialog = dialog
        self._settings_widget = widget
        # SettingsPage (settings_page.py) reports the person's packs after Save.
        changed = getattr(widget, "personalization_changed", None)
        current = getattr(widget, "current_personalization", None)
        if changed is not None and callable(current):
            changed.connect(self._on_personalization_changed)
            self._on_personalization_changed(current())

    def _show_settings(self) -> None:
        if self._permission_level != "adult":
            self.show_permission_block("Settings need an adult profile.")
            return
        if self._settings_dialog is not None:
            self._settings_dialog.show()
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()

    # ---------------------------------------------------------------- toggles

    def _toggle_voice(self) -> None:
        # The check state represents the transport, not an optimistic button click.
        self._voice_button.setChecked(self._realtime_active)
        if self._realtime_active:
            self.realtime_stop_requested.emit()
        else:
            self.realtime_start_requested.emit()

    def _toggle_screen_sharing(self) -> None:
        # Same reasoning as _toggle_voice: the check state represents confirmed
        # state, not the click -- a failed start (e.g. AI vision unconfigured)
        # must never show "on" before set_screen_sharing_active confirms it.
        self._screen_share_button.setChecked(self._screen_sharing_active)
        self.screen_sharing_requested.emit()

    def set_screen_sharing_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._screen_sharing_active and self._screen_share_dot.isVisibleTo(self) == active:
            return  # app.py polls this twice a second
        self._screen_sharing_active = active
        self._screen_share_button.setChecked(active)
        title = "Stop screen sharing" if active else "Start screen sharing"
        self._screen_share_button.setToolTip(title)
        self._screen_share_button.setAccessibleName(title)
        self._screen_share_dot.setStyleSheet(_dot_style(_A["success"] if active else _A["neutral"]))
        self._screen_share_dot.setVisible(active)

    # ---------------------------------------------------------------- content

    def update_dashboard(self, kind: str, text: str) -> None:
        if kind in self._dashboard_labels:
            self._dashboard_labels[kind].setText(text)
            self._readings[kind] = text
            if kind in self._meters:
                level = _meter_level(kind, text)
                self._meters[kind].set_level(*(level or (None,)))
        match = _LEADING_PERCENT.match(text)
        if match:
            self._load_chart.add(kind, float(match.group(1)))
        if kind in {"cpu", "gpu", "memory", "cpu_temperature", "battery"}:
            self._refresh_gamer_status()

    def set_role_packs(self, pack_ids) -> None:
        """One card per chosen role pack (role_packs.PACKS): its quick actions,
        plus live game readiness for Gamer and a focus timer for Student.
        Cards of packs that stay chosen are kept, so a running timer survives."""
        wanted = normalize_packs(pack_ids)
        for pack_id in [pack_id for pack_id in self._pack_cards if pack_id not in wanted]:
            card = self._pack_cards.pop(pack_id)
            if pack_id == "gamer":
                self._gamer_status = None
            elif pack_id == "student" and self._focus_timer is not None:
                self._focus_timer.reset()
                self._focus_timer = None
            self._packs_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        cards = {pack_id: self._pack_cards.get(pack_id) or self._build_pack_card(PACKS[pack_id])
                 for pack_id in wanted}
        for card in cards.values():  # re-added in PACKS order
            self._packs_layout.removeWidget(card)
            self._packs_layout.addWidget(card)
        self._pack_cards = cards
        self._role_packs = wanted
        self._place_personal_column()

    def _on_personalization_changed(self, personalization: dict) -> None:
        self.set_role_packs(personalization.get("role_packs"))

    # ------------------------------------------------------------- people

    def set_profile(self, profile: dict, avatar_path=None) -> None:
        """The active profile (ProfileStore.active(), Codex X1): the header
        avatar, the permission level and the profile's role packs. Settings'
        Personality and Role packs then edit this profile."""
        self._profile = dict(profile or {})
        self._profile_avatar = avatar_path
        profile_id = str(self._profile.get("id") or "")
        if profile_id:
            self._avatar_paths[profile_id] = avatar_path
        name = str(self._profile.get("display_name") or "Profile")
        level = self._profile.get("permission_level")
        level = level if level in _LEVEL_BADGES else "adult"
        self._profile_button.setIcon(QIcon(avatar_pixmap(self._profile, avatar_path, 30)))
        title = f"{name} · {_LEVEL_BADGES.get(level, ('', 'Adult profile'))[1]}"
        self._profile_button.setToolTip(title)
        self._profile_button.setAccessibleName(f"Profile: {title}")
        self._profile_button.show()
        self.set_permission_level(level)
        self.set_role_packs(self._profile.get("role_packs"))
        setter = getattr(self._settings_widget, "set_active_profile", None)
        if callable(setter):
            setter(self._profile)

    def set_profiles(self, profiles: list[dict], avatar_paths: dict | None = None) -> None:
        """Everyone the profile menu (and the tray's) can switch to."""
        self._profiles = [dict(profile) for profile in profiles or [] if isinstance(profile, dict)]
        self._avatar_paths.update(avatar_paths or {})
        self._sync_banner_switch()

    def _sync_banner_switch(self) -> None:
        self._level_banner_switch.setVisible(not self._profile_button.isHidden() and len(self._profiles) > 1)

    def _build_profile_menu(self) -> None:
        menu = self._profile_menu
        menu.clear()
        active_id = str(self._profile.get("id") or "")
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 8, 18, 8)
        layout.setSpacing(10)
        avatar = QLabel()
        avatar.setPixmap(avatar_pixmap(self._profile, self._profile_avatar, 36))
        avatar.setFixedSize(36, 36)
        layout.addWidget(avatar)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(_label(str(self._profile.get("display_name") or "Profile"), "menuName"))
        text.addWidget(_label(_LEVEL_BADGES.get(self._permission_level, ("", "Adult profile"))[1], "menuHint"))
        layout.addLayout(text, 1)
        header_action = QWidgetAction(menu)
        header_action.setDefaultWidget(header)
        header_action.setEnabled(False)
        menu.addAction(header_action)
        others = [profile for profile in self._profiles if str(profile.get("id") or "") != active_id]
        if others:
            menu.addSection("Switch to")
            for profile in others:
                profile_id = str(profile.get("id") or "")
                icon = QIcon(avatar_pixmap(profile, self._avatar_paths.get(profile_id), 20))
                action = menu.addAction(icon, str(profile.get("display_name") or profile_id))
                action.triggered.connect(partial(self._request_profile_switch, profile_id))
        menu.addSeparator()
        menu.addAction(self._glyph("person", _SP.SP_FileDialogInfoView, size=16), "Edit profile…",
                       lambda: self.profile_editor_requested.emit(active_id))
        if self._permission_level == "adult":
            menu.addAction(self._glyph("add", _SP.SP_FileDialogNewFolder, size=16), "Add profile…",
                           lambda: self.profile_editor_requested.emit(""))

    def _request_profile_switch(self, profile_id: str) -> None:
        if profile_id and profile_id != str(self._profile.get("id") or ""):
            self.profile_switch_requested.emit(profile_id)

    def ask_adult_pin(self, profile_name: str = "", error: str = "") -> str | None:
        """Modal adult-PIN prompt for ProfileStore.switch(); None if cancelled."""
        from .profile_editor import AdultPinDialog

        return AdultPinDialog.ask(self, profile_name, error=error)

    def open_profile_editor(self, profile: dict | None = None, avatar_path=None, *, pin_set: bool = True):
        """Opens ProfileEditorDialog (gui/profile_editor.py) for `profile`, or
        for a new one, and returns it so the caller can connect saved,
        avatar_chosen, adult_pin_chosen and delete_requested to the store."""
        from .profile_editor import ProfileEditorDialog

        dialog = ProfileEditorDialog(profile, self, avatar_path=avatar_path,
                                     can_manage=self._permission_level == "adult",
                                     windows_user=os.environ.get("USERNAME", ""), pin_set=pin_set)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()
        return dialog

    def set_language(self, code: str) -> None:
        """Show the conversation language on the header switch."""
        if code not in self._language_actions:
            return
        self._language_button.setText({"bg": "БГ", "en": "EN", "auto": "BG · EN"}[code])
        name = {"bg": "Bulgarian", "en": "English", "auto": "Auto (Bulgarian or English)"}[code]
        self._language_button.setToolTip(f"Conversation language: {name}. Click to switch; it applies at once.")
        self._language_button.setAccessibleName(f"Conversation language: {name}")
        for key, action in self._language_actions.items():
            action.setChecked(key == code)
        self._language_button.show()

    def set_permission_level(self, level: str) -> None:
        """adult | kid | guest: the header badge, the HUD banner and the
        Settings lock. The tool rules are enforced by the router (Codex, X2)."""
        level = level if level in _LEVEL_BADGES else "adult"
        self._permission_level = level
        badge = _LEVEL_BADGES.get(level)
        self._level_badge.setVisible(badge is not None)
        self._level_banner.setVisible(badge is not None)
        if badge is not None:
            self._level_badge.setText(badge[0])
            self._level_badge.setToolTip(_LEVEL_BANNERS[level])
            self._level_banner_title.setText(badge[1].upper())
            self._level_banner_text.setText(_LEVEL_BANNERS[level])
            for widget in (self._level_badge, self._level_banner):
                if widget.property("tone") != level:
                    widget.setProperty("tone", level)
                    _repolish(widget)
        self._sync_banner_switch()
        self._settings_button.setEnabled(level == "adult")
        self._settings_button.setToolTip("Settings" if level == "adult" else "Settings need an adult profile")
        self._passwords_button.setEnabled(level == "adult")
        self._passwords_button.setToolTip("Passwords" if level == "adult" else "Passwords need an adult profile")
        if level != "adult" and self._settings_dialog is not None:
            self._settings_dialog.hide()
        self._place_personal_column()

    def show_permission_block(self, message: str, level: str = "") -> None:
        """A request the profile's level does not allow (a result with
        metadata["blocked_by_level"]), shown apart from errors."""
        level = level or self._permission_level
        prefix = {"kid": "Not in Kid mode", "guest": "Not in Guest mode"}.get(level, "Not allowed")
        self._show_feedback(f"{prefix}: {message}", "blocked")

    def show_habit_suggestions(self, suggestions: list[dict]) -> None:
        """HabitLearner.suggestions() (Codex, X3) as "Jarvis noticed" cards."""
        for card in self._habit_cards.values():
            self._habits_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._habit_cards = {}
        for suggestion in suggestions or []:
            habit_id = str(suggestion.get("id") or "") if isinstance(suggestion, dict) else ""
            if not habit_id or habit_id in self._habit_cards:
                continue
            card = self._build_habit_card(suggestion)
            self._habits_layout.addWidget(card)
            self._habit_cards[habit_id] = card
            if len(self._habit_cards) == _MAX_HABIT_CARDS:
                break
        self._place_personal_column()

    def _answer_habit(self, habit_id: str, signal) -> None:
        card = self._habit_cards.pop(habit_id, None)
        if card is not None:
            self._habits_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        signal.emit(habit_id)
        self._place_personal_column()

    def show_routine_due(self, routine: dict) -> None:
        """An accepted routine's time has come (habits.py). It is only offered:
        nothing runs until Run now, and then with the usual confirmations."""
        routine_id = str(routine.get("id") or "")
        if not routine_id or routine_id in self._routine_cards:
            return
        clock = str((routine.get("trigger") or {}).get("time") or "")
        card = self._build_notice_card(f"ROUTINE · {clock}" if clock else "ROUTINE", routine, (
            ("Run now", "chip", self.routine_run_requested, "Runs these steps; protected ones still ask."),
            ("Skip today", "ghostChip", self.routine_skipped, "Offer it again tomorrow.")), self._answer_routine)
        self._habits_layout.insertWidget(0, card)
        self._routine_cards[routine_id] = card
        self._place_personal_column()
        QApplication.alert(self)

    def _answer_routine(self, routine_id: str, signal) -> None:
        card = self._routine_cards.pop(routine_id, None)
        if card is not None:
            self._habits_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        signal.emit(routine_id)
        self._place_personal_column()

    def show_feedback(self, text: str, *, error: bool = False) -> None:
        self._show_feedback(text, "error" if error else "normal")

    def _show_feedback(self, text: str, tone: str) -> None:
        self._feedback_text = redact_sensitive_text(text).text[:4000]
        self._feedback_error = tone == "error"
        self._voice_transcript_label.setToolTip(self._feedback_text)
        if tone != self._transcript_tone:
            self._transcript_tone = tone
            self._voice_transcript_label.setProperty("tone", tone)
            _repolish(self._voice_transcript_label)
        self._elide_feedback()
        self._feedback_timer.stop()
        if tone != "error":
            self._feedback_timer.start(12000 if tone == "blocked" else 9000)

    def _elide_feedback(self) -> None:
        width = max(100, self._voice_transcript_label.width()-24)
        text = " ".join(self._feedback_text.split())
        self._voice_transcript_label.setText(self._voice_transcript_label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width))

    def _clear_feedback(self) -> None:
        self._feedback_text = ""
        self._voice_transcript_label.clear()
        self._voice_transcript_label.setToolTip("")

    def append_history(self, source: str, text: str, result_message: str, ok: bool) -> None:
        # Persistent command history belongs to the audit log, not this voice surface.
        self.show_feedback(result_message, error=not ok)

    def set_voice_transcript(self, text: str, speaker: str = "You") -> None:
        if text.strip():
            self.show_feedback(f"{speaker}: {text}")

    def set_assistant_message(self, text: str) -> None:
        self.set_voice_transcript(text, "Jarvis")

    def set_realtime_detail(self, detail: str) -> None:
        self.show_feedback(detail, error=self._state == "error")

    def show_tool_error(self, message: str) -> None:
        """A tool/backend failure during a live call must stay visibly
        distinct from routine transcript text and must not silently
        auto-clear after the usual 9 seconds -- see
        RealtimeVoiceWorker.tool_error_occurred."""
        self.show_feedback(message, error=True)

    # ------------------------------------------------------------------ state

    def set_realtime_status(self, ready: bool, detail: str) -> None:
        self._realtime_ready = ready
        self._voice_button.setEnabled(ready or self._realtime_active)
        self._voice_button.setToolTip("End voice conversation" if self._realtime_active else "Start voice conversation" if ready else detail)
        self.set_setup_check("realtime_deps", ready, "Ready to connect" if ready else detail)
        self._render_state()

    def set_voice_mode_profile(self, voice: str, model: str, intelligence: str = "Instant", language: str = "English") -> None:
        self._profile_label.setText(f"{voice.capitalize()}   ·   Live   ·   {language}")
        self._profile_label.setToolTip(f"AI-generated voice: {voice}\nModel: {model}\nLanguage: {language}")

    def set_realtime_active(self, active: bool, state: str = "") -> None:
        self._realtime_active = active
        self._state = state or ("listening" if active else "idle")
        self._voice_button.setChecked(active)
        self._voice_button.setEnabled(active or self._realtime_ready)
        self._voice_button.setIcon(self._call_icons[1 if active else 0])
        title = "End voice conversation" if active else "Start voice conversation"
        self._voice_button.setToolTip(title)
        self._voice_button.setAccessibleName(title)
        self._mute_button.setEnabled(active)
        self._interrupt_button.setEnabled(active and state in {"speaking", "thinking"})
        if not active:
            self._input_muted = False
            self._keyword_interrupt_available = False
            self._mute_button.setChecked(False)
            self._mute_button.setIcon(self._mic_icons[0])
            self._core.set_level(0)
        if state == "error" and self._feedback_text:
            self.show_feedback(self._feedback_text, error=True)
        self._render_state()

    def set_input_muted(self, muted: bool) -> None:
        self._input_muted = muted
        self._mute_button.setChecked(muted)
        self._mute_button.setIcon(self._mic_icons[1 if muted else 0])
        title = "Unmute microphone" if muted else "Mute microphone"
        self._mute_button.setToolTip(title)
        self._mute_button.setAccessibleName(title)
        self._render_state()

    def set_audio_level(self, level: float) -> None:
        self._core.set_level(level)

    def set_mic_status(self, state: str) -> None:
        if not self._realtime_active:
            self._state = state
            self._render_state()

    def _render_state(self) -> None:
        state = "muted" if self._input_muted and self._state != "speaking" else self._state
        captions = {"listening": "LISTENING", "speaking": "SPEAKING", "thinking": "THINKING",
                    "processing": "WORKING", "connecting": "CONNECTING", "error": "VOICE ERROR",
                    "unclear": "PLEASE REPEAT", "interrupted": "LISTENING", "muted": "MICROPHONE PAUSED"}
        caption = captions.get(state, "READY" if self._realtime_ready else "VOICE OFFLINE")
        self._core_status_label.setText(caption)
        self._core.set_state(state)
        guarded = self._speaker_guard and self._realtime_active and self._state == "speaking"
        if self._input_muted:
            text, tone = "MIC PAUSED", "paused"
        elif guarded and self._keyword_interrupt_available:
            text, tone = "LOCAL WAKE / JARVIS", "local"
        elif guarded:
            text, tone = "MIC PAUSED", "paused"
        elif self._realtime_active and self._state != "connecting":
            text, tone = "MIC LIVE / OPENAI", "live"
        elif self._state == "listening":
            text, tone = "MIC ACTIVE", "live"
        else:
            text, tone = "MIC OFF", "off"
        self._privacy_label.setText(text)
        if tone != self._privacy_tone:
            self._privacy_tone = tone
            self._privacy_label.setProperty("tone", tone)
            _repolish(self._privacy_label)

    def set_keyword_interrupt_status(self, available: bool, detail: str = "") -> None:
        self._keyword_interrupt_available = available
        self._privacy_label.setToolTip(detail or "Local Jarvis keyword detection while replies play. Mute disables it.")
        self._render_state()

    def set_speaker_guard(self, enabled: bool) -> None:
        self._speaker_guard = enabled

    def set_setup_check(self, key: str, ready: bool, detail: str) -> None:
        if key not in self._setup_rows:
            return
        _, dot, label = self._setup_rows[key]
        dot.setStyleSheet(_dot_style(_A["success"] if ready else _A["warning"]))
        label.setText(detail)
        label.setToolTip(detail)
        self._setup_ready[key] = ready
        self._refresh_health()

    def _refresh_health(self) -> None:
        """The header's one-line verdict over the readiness checks."""
        failing = [_SETUP_LABELS.get(key, key) for key, ready in self._setup_ready.items() if not ready]
        if not self._setup_ready:
            text, color, tip = "STANDING BY", _A["neutral"], "Readiness checks have not reported yet."
        elif not failing:
            text, color, tip = "ALL SYSTEMS NOMINAL", _A["success"], "Every readiness check passed."
        else:
            count = len(failing)
            text = f"{count} CHECK{'S' if count > 1 else ''} NEED{'' if count > 1 else 'S'} ATTENTION"
            color, tip = _A["warning"], "Needs attention: " + ", ".join(failing)
        self._health_label.setText(text)
        self._health_label.setToolTip(tip)
        self._health_dot.setStyleSheet(f"background: {color}; border-radius: 3px;")
        self._health_dot.setToolTip(tip)

    def set_setup_checks(self, checks: dict[str, tuple[bool, str]]) -> None:
        for key, (ready, detail) in checks.items():
            self.set_setup_check(key, ready, detail)

    def set_session_active(self, active: bool) -> None:
        self._session_active = active

    def set_task_state(self, active: bool, detail: str) -> None:
        self._cancel_task_button.setEnabled(active)
        if active and detail:
            self.show_feedback(detail)

    # ----------------------------------------------------------------- window

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize and watched is getattr(self, "_voice_transcript_label", None):
            self._elide_feedback()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_personal_column"):
            self._place_personal_column()
        if hasattr(self, "_voice_transcript_label"):
            self._elide_feedback()

    def closeEvent(self, event) -> None:
        event.ignore()
        if self._settings_dialog:
            self._settings_dialog.hide()
        self.hide()
