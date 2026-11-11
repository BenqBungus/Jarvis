"""Profile avatars: a cropped photo, or initials on a gradient.

Owned by Claude (docs/claude/PERSONALIZATION_HANDOFF.md, C3). The profile
store (Codex, profiles.py) keeps a square 512x512 PNG that this module has
already cropped; nothing here touches the store or the disk except reading
the avatar file it is given.
"""
from __future__ import annotations

import zlib
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from .voice_core import AURORA, FONT_SEMIBOLD

AVATAR_SIZE = 512  # what the editor hands to ProfileStore.set_avatar (well under its 2 MB cap)
PHOTO_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp)"


def initials(name: str) -> str:
    """One letter for one word ("Берк" -> "Б"), two for more ("Ана Мария" -> "АМ")."""
    words = [word for word in "".join(ch if ch.isalnum() else " " for ch in name or "").split() if word]
    if not words:
        return "?"
    letters = words[0][0] + (words[-1][0] if len(words) > 1 else "")
    return letters.upper()


def hue_for(name: str) -> int:
    """A stable default hue for a name, so a new avatar is never random."""
    return zlib.crc32((name or "").strip().lower().encode("utf-8")) % 360


def profile_hue(profile: dict | None) -> int:
    profile = profile or {}
    hue = profile.get("avatar_hue")
    if isinstance(hue, int) and not isinstance(hue, bool):
        return hue % 360
    return hue_for(str(profile.get("display_name") or ""))


def _circle(size: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    return path


def generated_avatar(name: str, hue: int, size: int, dpr: float = 2.0) -> QPixmap:
    """Initials on a two-tone gradient disc."""
    pixmap = QPixmap(round(size * dpr), round(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor.fromHsl(hue % 360, 185, 132))
    gradient.setColorAt(1.0, QColor.fromHsl((hue + 38) % 360, 170, 78))
    painter.fillPath(_circle(size), gradient)
    painter.setPen(QPen(QColor(255, 255, 255, 46), max(1.0, size / 48)))
    inset = max(0.5, size / 96)
    painter.drawEllipse(QRectF(inset, inset, size - 2 * inset, size - 2 * inset))
    text = initials(name)
    font = QFont()
    font.setFamilies([family.strip().strip('"') for family in FONT_SEMIBOLD.split(",")])
    font.setPixelSize(max(6, round(size * (0.42 if len(text) == 1 else 0.36))))
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 240))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


def photo_avatar(image: QImage, size: int, dpr: float = 2.0) -> QPixmap:
    """The (already square) photo, scaled and clipped to a disc."""
    pixels = round(size * dpr)
    side = min(image.width(), image.height())
    square = image.copy((image.width() - side) // 2, (image.height() - side) // 2, side, side)
    scaled = square.scaled(pixels, pixels, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    pixmap = QPixmap(pixels, pixels)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setClipPath(_circle(size))
    painter.drawImage(QRectF(0, 0, size, size), scaled)
    painter.end()
    return pixmap


def load_image(path: str | Path | None) -> QImage | None:
    if not path:
        return None
    image = QImage(str(path))
    return None if image.isNull() else image


def avatar_pixmap(profile: dict | None, avatar_path: str | Path | None, size: int, dpr: float = 2.0) -> QPixmap:
    """The profile's photo when it loads, otherwise its generated avatar."""
    image = load_image(avatar_path)
    if image is not None:
        return photo_avatar(image, size, dpr)
    return generated_avatar(str((profile or {}).get("display_name") or ""), profile_hue(profile), size, dpr)


def square_png(image: QImage, source: QRectF | None = None, size: int = AVATAR_SIZE) -> bytes:
    """`source` (default: the centered square) as a size x size PNG."""
    if source is None:
        side = min(image.width(), image.height())
        source = QRectF((image.width() - side) / 2, (image.height() - side) / 2, side, side)
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawImage(QRectF(0, 0, size, size), image, source)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    out.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


class AvatarCropper(QWidget):
    """Pick the part of a photo that becomes the avatar: drag to move,
    wheel (or set_zoom) to zoom. The circle shows exactly what is kept."""

    changed = Signal()
    MAX_ZOOM = 4.0

    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self._zoom = 1.0
        self._center = QPointF(image.width() / 2, image.height() / 2)
        self._drag_from: QPointF | None = None
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName("Photo crop area")

    def sizeHint(self) -> QSize:
        return QSize(300, 300)

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        zoom = max(1.0, min(self.MAX_ZOOM, zoom))
        if abs(zoom - self._zoom) > 1e-6:
            self._zoom = zoom
            self._clamp()
            self.update()
            self.changed.emit()

    def crop_rect(self) -> QRectF:
        """The kept square, in image pixels."""
        side = min(self._image.width(), self._image.height()) / self._zoom
        return QRectF(self._center.x() - side / 2, self._center.y() - side / 2, side, side)

    def result_png(self, size: int = AVATAR_SIZE) -> bytes:
        return square_png(self._image, self.crop_rect(), size)

    def _clamp(self) -> None:
        half = min(self._image.width(), self._image.height()) / self._zoom / 2
        self._center = QPointF(min(max(self._center.x(), half), self._image.width() - half),
                               min(max(self._center.y(), half), self._image.height() - half))

    def _circle_rect(self) -> QRectF:
        diameter = max(40.0, min(self.width(), self.height()) - 24.0)
        return QRectF((self.width() - diameter) / 2, (self.height() - diameter) / 2, diameter, diameter)

    def _scale(self) -> float:
        """Screen pixels per image pixel."""
        return self._circle_rect().width() / self.crop_rect().width()

    def pan_by(self, screen_delta: QPointF) -> None:
        self._center -= screen_delta / self._scale()
        self._clamp()
        self.update()
        self.changed.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            position = event.position()
            self.pan_by(position - self._drag_from)
            self._drag_from = position

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120
        if steps:
            self.set_zoom(self._zoom * (1.1 ** steps))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(AURORA["bg_raised"]))
        circle = self._circle_rect()
        scale = self._scale()
        crop = self.crop_rect()
        target = QRectF(circle.x() - crop.x() * scale, circle.y() - crop.y() * scale,
                        self._image.width() * scale, self._image.height() * scale)
        painter.drawImage(target, self._image)
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        hole.addEllipse(circle)
        painter.fillPath(outside.subtracted(hole), QColor(4, 8, 12, 170))
        painter.setPen(QPen(QColor(AURORA["accent"]), 2))
        painter.drawEllipse(circle)
