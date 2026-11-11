"""The "Aurora" design system for the Jarvis desktop UI: tokens, fonts, the
shared base stylesheet, crisp glyph icons, the ambient window surface and the
animated voice orb.

Imports nothing from Jarvis except icons.py (itself PySide6-only), so every UI
module can use it without an import cycle; main_window.py re-exports it.
"""
from __future__ import annotations

import math
import random
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QIcon, QImage,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QSizePolicy, QStyle, QWidget

from .icons import control_icon

AURORA: dict[str, str] = {
    "bg": "#07090D",
    "bg_raised": "#0B0F14",
    "card": "#0E1319",
    "card_hover": "#121923",
    "border": "#1B2430",
    "border_strong": "#243041",
    "input": "#111821",
    "text": "#E7EDF3",
    "text_secondary": "#A2AEBB",
    "text_tertiary": "#6C7886",
    "accent": "#22D3EE",
    "accent_light": "#67E8F9",
    "accent_2": "#8B5CF6",
    "accent_2_light": "#A78BFA",
    "success": "#5ccb9a",
    "neutral": "#5c7277",
    "warning": "#E6B86A",
    "danger": "#F28B82",
}


def _color(value: str, alpha: float = 255) -> QColor:
    color = QColor(value)
    color.setAlpha(max(0, min(255, int(alpha))))
    return color


def _noise_tile(size: int = 96) -> QPixmap:
    """A faint fixed-seed dither: dark gradients band visibly on 8-bit panels."""
    generator = random.Random(7)
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    for y in range(size):
        for x in range(size):
            value = generator.random()
            if value < 0.5:
                continue
            shade = 255 if value > 0.75 else 0
            image.setPixelColor(x, y, QColor(shade, shade, shade, 5))
    return QPixmap.fromImage(image)


# Per-role family lists (Qt 6.11 QSS accepts fallbacks). Semibold names the
# weight explicitly: "Segoe UI Variable Text" + font-weight:600 resolves to Bold.
FONT_BODY = '"Segoe UI Variable Text", "Segoe UI"'
FONT_SEMIBOLD = '"Segoe UI Variable Text Semibold", "Segoe UI Semibold", "Segoe UI"'
FONT_DISPLAY = '"Segoe UI Variable Display Semibold", "Segoe UI Semibold", "Segoe UI"'
FONT_MONO = '"Cascadia Code", "Consolas"'

_A = AURORA


def _png(width: int, height: int, rgba: bytes) -> bytes:
    rows = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


_CHEVRON_POINTS = [(2.5, 3.75), (5.0, 6.25), (7.5, 3.75)]
_CHECK_POINTS = [(2.4, 5.3), (4.3, 7.2), (7.8, 3.2)]


def _polyline_coverage(points: list[tuple[float, float]], scale: int) -> list[int]:
    """Anti-aliased alpha of a 1.5px polyline in a 10x10 box (4x4 supersampling)."""
    segments = list(zip(points, points[1:]))
    size = 10 * scale
    coverage = []
    for y in range(size):
        for x in range(size):
            hits = 0
            for sample in range(16):
                px = (x + (sample % 4 + 0.5) / 4) / scale
                py = (y + (sample // 4 + 0.5) / 4) / scale
                for (ax, ay), (bx, by) in segments:
                    dx, dy = bx - ax, by - ay
                    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
                    if (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2 <= 0.5625:  # 1.5px stroke
                        hits += 1
                        break
            coverage.append(round(255 * hits / 16))
    return coverage


def _arrow_images() -> dict[str, str]:
    """Chevron PNGs (1x/2x/3x) for combo and spin box arrows, plus a check
    mark for checkbox indicators, written once to the temp folder: only .py
    files ship, and QSS `image:` needs a file. The native arrows can't be
    relied on -- on a light-mode Windows they are drawn dark on these dark
    fields. Returns {} (native look) if writing fails."""
    up_points = [(x, 10 - y) for x, y in _CHEVRON_POINTS]
    shapes = (
        ("down", "chevron-down", _CHEVRON_POINTS, _A["text_secondary"]),
        ("down_dim", "chevron-down", _CHEVRON_POINTS, "#3E4A59"),
        ("up", "chevron-up", up_points, _A["text_secondary"]),
        ("up_dim", "chevron-up", up_points, "#3E4A59"),
        ("check", "check", _CHECK_POINTS, "#04131A"),
    )
    try:
        folder = Path(tempfile.gettempdir()) / "jarvis-ui"
        paths: dict[str, str] = {}
        for key, name, points, tint in shapes:
            base = folder / f"{name}-{tint[1:].lower()}-v1"
            paths[key] = base.with_suffix(".png").as_posix()
            if all((folder / f"{base.name}{at}.png").exists() for at in ("", "@2x", "@3x")):
                continue
            folder.mkdir(parents=True, exist_ok=True)
            red, green, blue = (int(tint[i:i + 2], 16) for i in (1, 3, 5))
            for scale, at in ((1, ""), (2, "@2x"), (3, "@3x")):
                alpha = _polyline_coverage(points, scale)
                rgba = bytes(value for a in alpha for value in (red, green, blue, a))
                (folder / f"{base.name}{at}.png").write_bytes(_png(10 * scale, 10 * scale, rgba))
        return paths
    except OSError:
        return {}


_IMAGES = _arrow_images()
# The check mark is only used by component-scoped checkbox rules (settings_page.py).
CHECK_IMAGE = _IMAGES.get("check", "")
_ARROWS = {key: path for key, path in _IMAGES.items() if key != "check"}
_ARROW_STYLE = "" if not _ARROWS else f"""
QComboBox::down-arrow {{ image: url("{_ARROWS['down']}"); width: 10px; height: 10px; }}
QComboBox::down-arrow:disabled {{ image: url("{_ARROWS['down_dim']}"); }}
QAbstractSpinBox {{ padding-top: 4px; padding-bottom: 4px; padding-right: 30px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 22px; height: 12px;
    border: none; border-radius: 4px; background: transparent; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; margin: 3px 4px 0 0; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; margin: 0 4px 3px 0; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: rgba(255, 255, 255, 16); }}
QAbstractSpinBox::up-arrow {{ image: url("{_ARROWS['up']}"); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url("{_ARROWS['down']}"); width: 9px; height: 9px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url("{_ARROWS['up_dim']}"); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url("{_ARROWS['down_dim']}"); }}
"""

# Every window parented to MainWindow inherits these rules, including Codex's
# GmailSettingsDialog and the safety QMessageBox, which style nothing
# themselves -- so this block stays neutral. Component looks are scoped by
# objectName in the module that owns the component.
BASE_STYLE = f"""
QMainWindow, QDialog, QWizard, QWizardPage {{ background: {_A['bg']}; color: {_A['text']}; }}
QWidget {{ color: {_A['text']}; font-family: {FONT_BODY}; font-size: 13px; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {_A['card_hover']}; color: {_A['text']}; border: 1px solid {_A['border_strong']};
    border-radius: 6px; padding: 6px 8px; }}
QMenu {{ background: {_A['card']}; border: 1px solid {_A['border_strong']}; border-radius: 6px; padding: 6px; }}
QMenu::item {{ padding: 8px 22px; border-radius: 4px; color: {_A['text']}; }}
QMenu::item:selected {{ background: rgba(34, 211, 238, 36); }}
QMenu::item:disabled {{ color: {_A['text_tertiary']}; }}
QMenu::separator {{ height: 1px; background: {_A['border']}; margin: 6px 8px; }}
QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {_A['border_strong']}; border-radius: 3px; min-height: 32px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: #33415A; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {_A['border_strong']}; border-radius: 3px; min-width: 32px; margin: 2px 0; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
QPushButton {{ background: {_A['card_hover']}; color: {_A['text']}; border: 1px solid {_A['border_strong']};
    border-radius: 8px; padding: 7px 16px; font-family: {FONT_SEMIBOLD}; font-weight: 600; }}
QPushButton:hover {{ background: #172130; border-color: #33415A; }}
QPushButton:pressed {{ background: {_A['card']}; }}
QPushButton:disabled {{ background: {_A['card']}; color: {_A['text_tertiary']}; border-color: {_A['border']}; }}
QPushButton[variant="primary"] {{ color: #04131A; border: none; padding: 8px 22px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
QPushButton[variant="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent_light']}, stop:1 {_A['accent_2_light']}); }}
QPushButton[variant="primary"]:pressed {{ background: {_A['accent']}; }}
QPushButton[variant="primary"]:disabled {{ background: #172130; color: {_A['text_tertiary']}; }}
QToolButton {{ background: {_A['card_hover']}; border: 1px solid {_A['border_strong']}; border-radius: 8px; }}
QToolButton:hover {{ background: #172130; border-color: #33415A; }}
QToolButton:checked {{ background: rgba(34, 211, 238, 36); border-color: rgba(34, 211, 238, 115); }}
QToolButton:disabled {{ background: {_A['card']}; border-color: {_A['border']}; }}
QLineEdit, QComboBox, QSpinBox, QAbstractSpinBox, QPlainTextEdit {{
    background: {_A['input']}; color: {_A['text']}; border: 1px solid {_A['border_strong']}; border-radius: 8px;
    padding: 6px 10px; selection-background-color: rgba(34, 211, 238, 72); selection-color: {_A['text']}; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QPlainTextEdit:hover {{ border-color: #33415A; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border-color: {_A['accent']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {_A['text_tertiary']}; border-color: {_A['border']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {_A['card']}; color: {_A['text']}; border: 1px solid {_A['border_strong']};
    padding: 4px; outline: 0; selection-background-color: rgba(34, 211, 238, 40); selection-color: {_A['text']}; }}
QListWidget, QTableWidget {{ background: {_A['bg_raised']}; color: {_A['text']}; border: 1px solid {_A['border']};
    border-radius: 10px; padding: 6px; gridline-color: {_A['border']}; outline: 0;
    selection-background-color: rgba(34, 211, 238, 40); selection-color: {_A['text']}; }}
QHeaderView::section {{ background: transparent; color: {_A['text_tertiary']}; border: none;
    border-bottom: 1px solid {_A['border']}; padding: 6px 8px; font-family: {FONT_SEMIBOLD}; font-weight: 600; font-size: 11px; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QCheckBox {{ spacing: 10px; }}
QMessageBox QLabel {{ color: {_A['text']}; }}
QComboBox:editable {{ padding-left: 4px; }}
QComboBox QLineEdit {{ background: transparent; border: none; padding: 0; }}
""" + _ARROW_STYLE
# QCheckBox indicators are deliberately left to the native rendering. Spin box
# and combo arrows are images (_arrow_images): restyling ::up-button/
# ::down-button without an arrow image suppresses Qt's glyph (verified).


def card_rules(scope: str) -> str:
    """QGroupBoxes inside `scope` render as rounded cards with the title above."""
    return f"""
{scope} QGroupBox {{ background: rgba(14, 19, 25, 235); border: 1px solid {_A['border']}; border-radius: 14px;
    margin-top: 30px; padding: 16px 18px 14px 18px; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 14px; color: {_A['text']}; }}
{scope} QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 2px;
    padding: 0 0 8px 0; color: {_A['text']}; }}
{scope} QGroupBox QWidget {{ font-family: {FONT_BODY}; font-weight: 400; font-size: 13px; }}
{scope} QGroupBox QPushButton {{ font-family: {FONT_SEMIBOLD}; font-weight: 600; }}
{scope} QGroupBox QLabel {{ color: {_A['text_secondary']}; }}
"""


# Segoe Fluent Icons (Windows 11) / MDL2 Assets (Windows 10) code points.
GLYPHS = {
    "settings": "\ue713", "mic": "\ue720", "mic_off": "\uf781", "keyboard": "\ue765",
    "history": "\ue81c", "undo": "\ue7a7", "monitor": "\ue7f4", "cast": "\uec15",
    "hang_up": "\ue778", "skip": "\ue893", "close": "\ue711", "stop": "\ue71a", "send": "\ue724",
    "sparkle": "\uf4a5", "shield": "\uea18", "globe": "\ue774", "link": "\ue71b", "apps": "\ue71d",
    "game": "\ue7fc", "volume": "\ue767", "thermometer": "\ue9ca", "power": "\ue7e8", "mail": "\ue715",
    "add": "\ue710", "delete": "\ue74d", "headphones": "\ue7f6", "checkmark": "\ue73e",
    "warning": "\ue7ba", "chevron_down": "\ue70d", "cancel": "\ue733",
    "person": "\ue77b", "puzzle": "\uea86", "books": "\ue8f1",
    "folder": "\ue8b7", "refresh": "\ue72c", "code": "\ue943", "lock": "\ue72e", "play": "\ue768",
    "chat": "\ue8bd",
}
_GLYPH_FAMILY: str | None | bool = False
_ICON_CACHE: dict[tuple, QIcon] = {}


def _glyph_family() -> str | None:
    global _GLYPH_FAMILY
    if _GLYPH_FAMILY is False:
        families = set(QFontDatabase.families())
        _GLYPH_FAMILY = next((name for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if name in families), None)
    return _GLYPH_FAMILY


def _render_glyph(family: str, glyph: str, color: str, size: int) -> QPixmap:
    dpr = 2.0  # rendered at 2x so 150-200% display scaling stays crisp
    pixmap = QPixmap(int(size * dpr), int(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont(family)
    font.setPixelSize(max(8, round(size * 0.82)))
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return pixmap


def glyph_icon(name: str, fallback: QStyle.StandardPixmap, style: QStyle, *, color: str = _A["text_secondary"],
               checked_color: str | None = None, disabled_color: str = "#3E4A59", size: int = 20) -> QIcon:
    """A Fluent/MDL2 glyph icon with normal/checked/disabled tints, falling
    back to icons.control_icon() when neither icon font has the glyph."""
    key = (name, fallback, color, checked_color, disabled_color, size)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    family = _glyph_family()
    glyph = GLYPHS.get(name, "")
    if not family or not glyph or not QFontMetrics(QFont(family)).inFontUcs4(ord(glyph)):
        icon = control_icon(style, fallback)
    else:
        icon = QIcon()
        on = checked_color or _A["text"]
        for mode, state, tint in (
            (QIcon.Mode.Normal, QIcon.State.Off, color), (QIcon.Mode.Active, QIcon.State.Off, _A["text"]),
            (QIcon.Mode.Normal, QIcon.State.On, on), (QIcon.Mode.Active, QIcon.State.On, on),
            (QIcon.Mode.Disabled, QIcon.State.Off, disabled_color), (QIcon.Mode.Disabled, QIcon.State.On, disabled_color),
        ):
            icon.addPixmap(_render_glyph(family, glyph, tint, size), mode, state)
    _ICON_CACHE[key] = icon
    return icon


class LogoMark(QWidget):
    """The brand mark: a small cyan-to-violet orb with a dark iris."""

    def __init__(self, parent: QWidget | None = None, size: int = 26) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        scale = self.width() / 26
        painter.scale(scale, scale)
        rect = QRectF(1, 1, 24, 24)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(_A["accent"]))
        gradient.setColorAt(1.0, QColor(_A["accent_2"]))
        painter.setBrush(gradient)
        painter.drawEllipse(rect)
        painter.setBrush(QColor(_A["bg"]))
        painter.drawEllipse(rect.center(), 6.4, 6.4)
        painter.setBrush(QColor(_A["accent_light"]))
        painter.drawEllipse(rect.center(), 2.4, 2.4)
        shine = QRadialGradient(QPointF(8, 7), 9)
        shine.setColorAt(0.0, QColor(255, 255, 255, 110))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(shine)
        painter.drawEllipse(rect)


def apply_window_corners(widget: QWidget, border: str = _A["border_strong"]) -> bool:
    """Ask DWM (Windows 11) for rounded corners and a hairline border on a
    frameless top-level window. Returns False where that isn't available
    (Windows 10, other platforms, offscreen) so callers can draw their own edge."""
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return False
    try:
        import ctypes

        hwnd = ctypes.c_void_p(int(widget.winId()))
        dwmapi = ctypes.windll.dwmapi
        preference = ctypes.c_int(2)  # DWMWA_WINDOW_CORNER_PREFERENCE (33) = DWMWCP_ROUND
        if dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference)) != 0:
            return False
        color = QColor(border)
        colorref = ctypes.c_uint(color.red() | color.green() << 8 | color.blue() << 16)
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(colorref), ctypes.sizeof(colorref))  # DWMWA_BORDER_COLOR
        return True
    except (AttributeError, OSError, ValueError):
        return False


class HudSurface(QFrame):
    """Window background: deep base, soft ambient glows and a faint dither.

    Rendered once per size and blitted afterwards -- the voice orb repaints
    ~30 times a second and Qt repaints this surface underneath it each time.
    """

    # (x, y as fractions of the size, radius as a fraction of the short side, color, peak alpha)
    MAIN_GLOWS = (
        (0.60, 0.44, 0.66, AURORA["accent"], 30),
        (0.94, 1.04, 0.72, AURORA["accent_2"], 30),
        (0.00, -0.06, 0.52, AURORA["accent"], 13),
    )

    def __init__(self, parent: QWidget | None = None, glows: tuple | None = None, pattern: bool = False) -> None:
        super().__init__(parent)
        self._glows = glows or self.MAIN_GLOWS
        self._pattern = pattern
        self._cache: QPixmap | None = None
        self._noise: QPixmap | None = None

    def _dot_matrix(self, width: int, height: int, dpr: float) -> QPixmap:
        """A faint holo-table dot grid fading out from the first glow's center:
        every dot in one path, then a radial alpha mask -- two fills in total."""
        layer = QPixmap(int(width * dpr), int(height * dpr))
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dots = QPainterPath()
        spacing = 22
        for y in range(spacing // 2, height, spacing):
            for x in range(spacing // 2, width, spacing):
                dots.addEllipse(QPointF(x, y), 0.9, 0.9)
        painter.fillPath(dots, _color(AURORA["accent_light"], 40))
        x, y = self._glows[0][0], self._glows[0][1]
        mask = QRadialGradient(QPointF(width * x, height * y), min(width, height) * 0.78)
        mask.setColorAt(0.0, QColor(0, 0, 0, 255))
        mask.setColorAt(0.55, QColor(0, 0, 0, 90))
        mask.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.fillRect(QRectF(0, 0, width, height), QBrush(mask))
        painter.end()
        return layer

    def resizeEvent(self, event) -> None:
        self._cache = None
        super().resizeEvent(event)

    def _render(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        width, height = max(1, self.width()), max(1, self.height())
        pixmap = QPixmap(int(width * dpr), int(height * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(QColor(AURORA["bg"]))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        span = min(width, height)
        area = QRectF(0, 0, width, height)
        for x, y, scale, color, alpha in self._glows:
            gradient = QRadialGradient(QPointF(width * x, height * y), span * scale)
            gradient.setColorAt(0.0, _color(color, alpha))
            gradient.setColorAt(0.5, _color(color, alpha * 0.35))
            gradient.setColorAt(1.0, _color(color, 0))
            painter.fillRect(area, QBrush(gradient))
        if self._pattern:
            painter.drawPixmap(0, 0, self._dot_matrix(width, height, dpr))
        if self._noise is None:
            self._noise = _noise_tile()
        painter.drawTiledPixmap(area, self._noise)
        painter.end()
        return pixmap

    def paintEvent(self, event) -> None:
        if self._cache is None or self._cache.deviceIndependentSize().toSize() != self.size():
            self._cache = self._render()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)


# state -> (highlight, core, deep, secondary, intensity)
_ORB_PALETTES: dict[str, tuple[str, str, str, str, float]] = {
    "idle": ("#A5F0FA", "#1AA3C0", "#0A3A48", AURORA["accent_2"], 0.62),
    "listening": ("#C4F8FF", AURORA["accent"], "#0A4656", AURORA["accent_light"], 1.0),
    "thinking": ("#DCD2FF", AURORA["accent_2"], "#281A5A", AURORA["accent"], 0.88),
    "speaking": ("#CFF9FF", AURORA["accent"], "#241A58", AURORA["accent_2_light"], 1.0),
    "error": ("#FFD5CF", "#DF6A5E", "#48201B", AURORA["warning"], 0.9),
    "muted": ("#BAC4CF", "#5D6978", "#1B222B", "#3A4655", 0.45),
}
_STATE_ALIASES = {
    "interrupted": "listening", "connecting": "thinking", "processing": "thinking", "unclear": "error",
}
_FAST_STATES = {"thinking", "connecting", "processing"}


class JarvisCoreWidget(QWidget):
    """The Aurora voice orb. Amplitude comes only from real audio levels
    (set_level); idle "breathing" is driven by the animation phase alone."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._state = "idle"
        self._phase = 0.0
        self._level = self._target_level = 0.0
        self._layers: dict[tuple, tuple[QPixmap, QPixmap]] = {}
        self._tick_paths: dict[int, QPainterPath] = {}
        self._booted_at: float | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._animate)
        self.setAccessibleName("Jarvis voice core")

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def set_level(self, level: float) -> None:
        self._target_level = max(0.0, min(1.0, level))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._booted_at is None:
            self._booted_at = time.monotonic()
        self._timer.start()

    def _boot_progress(self) -> float:
        """0 -> 1 over the first 1.4 s after the orb is first shown, while the
        HUD rings sweep in. The sphere itself is always drawn in full, and a
        never-shown widget (tests, renders) counts as fully booted."""
        if self._booted_at is None:
            return 1.0
        return min(1.0, (time.monotonic() - self._booted_at) / 1.4)

    def _tick_path(self, radius: float) -> QPainterPath:
        """An instrument dial: 120 ticks, every tenth one longer. Cached per radius."""
        key = round(radius)
        path = self._tick_paths.get(key)
        if path is None:
            if len(self._tick_paths) > 8:
                self._tick_paths.clear()
            path = QPainterPath()
            for index in range(120):
                angle = math.radians(index * 3)
                length = 7.0 if index % 10 == 0 else 3.0
                cos, sin = math.cos(angle), math.sin(angle)
                path.moveTo(cos * radius, sin * radius)
                path.lineTo(cos * (radius - length), sin * (radius - length))
            self._tick_paths[key] = path
        return path

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _animate(self) -> None:
        self._phase = (self._phase + (1.1 if self._state in _FAST_STATES else .25)) % 360
        self._level += (self._target_level - self._level) * .28
        self._target_level *= .9
        self.update()

    def _palette_key(self) -> str:
        key = _STATE_ALIASES.get(self._state, self._state)
        return key if key in _ORB_PALETTES else "idle"

    def _build_layers(self, width: int, height: int, radius: float, key: str) -> tuple[QPixmap, QPixmap]:
        highlight, core, deep, secondary, intensity = _ORB_PALETTES[key]
        dpr = self.devicePixelRatioF()

        halo = QPixmap(int(width * dpr), int(height * dpr))
        halo.setDevicePixelRatio(dpr)
        halo.fill(Qt.GlobalColor.transparent)
        painter = QPainter(halo)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Fades out before the widget edge, otherwise the glow clips square.
        reach = max(radius * 1.05, min(radius * 1.95, min(width, height) / 2 - 1))
        gradient = QRadialGradient(QPointF(width / 2, height / 2), reach)
        gradient.setColorAt(0.0, _color(core, 90 * intensity))
        gradient.setColorAt(min(0.99, radius / reach), _color(core, 62 * intensity))
        gradient.setColorAt(1.0, _color(core, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(width / 2, height / 2), reach, reach)
        painter.end()

        side = int(math.ceil(radius * 2))
        sphere = QPixmap(int(side * dpr), int(side * dpr))
        sphere.setDevicePixelRatio(dpr)
        sphere.fill(Qt.GlobalColor.transparent)
        painter = QPainter(sphere)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        center = QPointF(side / 2, side / 2)
        circle = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        body = QRadialGradient(center, radius, QPointF(center.x() - radius * .34, center.y() - radius * .40))
        body.setColorAt(0.0, QColor(highlight))
        body.setColorAt(0.42, QColor(core))
        body.setColorAt(0.86, QColor(deep))
        body.setColorAt(1.0, QColor(deep).darker(160))
        painter.setBrush(body)
        painter.drawEllipse(circle)
        glow = QRadialGradient(QPointF(center.x() + radius * .45, center.y() + radius * .55), radius * .95)
        glow.setColorAt(0.0, _color(secondary, 110 * intensity))
        glow.setColorAt(1.0, _color(secondary, 0))
        painter.setBrush(glow)
        painter.drawEllipse(circle)
        shine = QRadialGradient(QPointF(center.x() - radius * .36, center.y() - radius * .46), radius * .44)
        shine.setColorAt(0.0, _color("#FFFFFF", 70))
        shine.setColorAt(1.0, _color("#FFFFFF", 0))
        painter.setBrush(shine)
        painter.drawEllipse(circle)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color(highlight, 48), 1.0))
        painter.drawEllipse(circle.adjusted(0.8, 0.8, -0.8, -0.8))
        painter.end()
        return halo, sphere

    def paintEvent(self, event) -> None:
        width, height = self.width(), self.height()
        radius = min(width * 0.28, height * 0.34, 190.0)
        if radius < 8:
            return
        key = self._palette_key()
        highlight, core, _deep, secondary, intensity = _ORB_PALETTES[key]
        cache_key = (width, height, round(self.devicePixelRatioF(), 2), key)
        layers = self._layers.get(cache_key)
        if layers is None:
            if len(self._layers) > 12:
                self._layers.clear()
            layers = self._layers[cache_key] = self._build_layers(width, height, radius, key)
        halo, sphere = layers

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        breath = math.sin(math.radians(self._phase * 6))
        level = self._level
        grow = 1 - (1 - self._boot_progress()) ** 3  # ease-out sweep of the HUD rings
        fast = self._state in _FAST_STATES
        painter.setOpacity(min(1.0, 0.78 + 0.08 * breath + 0.3 * level))
        painter.drawPixmap(0, 0, halo)
        painter.setOpacity(1.0)
        painter.translate(width / 2, height / 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        extent = min(width, height) / 2 - 2

        # Instrument dial, slowly turning.
        painter.save()
        painter.rotate(self._phase * 0.4)
        painter.setPen(QPen(_color(highlight, 42 * grow), 1.0))
        painter.drawPath(self._tick_path(min(radius * 1.36, extent - 12)))
        painter.restore()

        # Arc-reactor ring: uneven segments counter-rotating, faster while thinking.
        ring = min(radius * 1.45, extent - 1)
        ring_rect = QRectF(-ring, -ring, ring * 2, ring * 2)
        spin = -self._phase * (1.8 if fast else 0.6)
        pen = QPen(_color(core, 150 * intensity * grow), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        for start, span in ((8, 62), (84, 16), (112, 94), (226, 28), (268, 58)):
            painter.drawArc(ring_rect, int((start + spin) * 16), int(span * grow * 16))
        # Reticle marks between the dial and the ring.
        painter.setPen(QPen(_color(highlight, 80 * grow), 1.2))
        for quarter in range(4):
            angle = math.radians(quarter * 90 + 45)
            painter.drawLine(QPointF(math.cos(angle) * (ring - 9), math.sin(angle) * (ring - 9)),
                             QPointF(math.cos(angle) * (ring - 4), math.sin(angle) * (ring - 4)))

        for scale, stroke, span, angle, color, clockwise in (
            (1.16, max(2.0, radius * .018), 118, self._phase * 2, core, False),
            (1.27, 1.5, 64, -self._phase, secondary, True),
        ):
            orbit = radius * scale
            # Comet-like: bright at the leading end, fading along the tail.
            head, tail = (0.0, min(1.0, span / 360)) if clockwise else (min(1.0, span / 360), 0.0)
            # The inner comet gives way to the voice spectrum while audio plays.
            peak = 235 * (1 - 0.75 * level) if scale < 1.2 else 235
            sweep = QConicalGradient(QPointF(0, 0), angle)
            sweep.setColorAt(tail, _color(color, 0))
            sweep.setColorAt(head, _color(color, peak))
            sweep.setColorAt(1.0, _color(color, 0))
            pen = QPen(QBrush(sweep), stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(QRectF(-orbit, -orbit, orbit * 2, orbit * 2), int(angle * 16), int(span * grow * 16))

        if level > 0.03:
            # Voice spectrum: radial bars whose height follows the real audio
            # level; the per-bar wave only shapes it, it never invents sound.
            base = radius * (1.07 + 0.09 * level)
            bars = QPainterPath()
            for index in range(72):
                angle = math.radians(index * 5)
                wave = abs(math.sin(math.radians(index * 15 + self._phase * 9))
                           * math.sin(math.radians(index * 25 - self._phase * 5)))
                length = radius * (0.02 + 0.2 * level * (0.3 + 0.7 * wave))
                cos, sin = math.cos(angle), math.sin(angle)
                bars.moveTo(cos * base, sin * base)
                bars.lineTo(cos * (base + length), sin * (base + length))
            pen = QPen(_color(highlight, 70 + 150 * level), max(1.5, radius * 0.012))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPath(bars)

        size = radius * (1 + 0.03 * breath + 0.09 * level)
        painter.drawPixmap(QRectF(-size, -size, size * 2, size * 2), sphere, QRectF(sphere.rect()))

        painter.setPen(Qt.PenStyle.NoPen)
        for offset, extent, angle, color, alpha in (
            (0.30, 0.60, self._phase * 3, secondary, 95),
            (0.34, 0.54, 140 - self._phase * 2, highlight, 70),
        ):
            spin = math.radians(angle)
            center = QPointF(math.cos(spin) * offset * size, math.sin(spin) * offset * size * .8)
            blob = QRadialGradient(center, extent * size)
            blob.setColorAt(0.0, _color(color, alpha * intensity))
            blob.setColorAt(1.0, _color(color, 0))
            painter.setBrush(blob)
            painter.drawEllipse(center, extent * size, extent * size)
